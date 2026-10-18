# Design

## Context

动机见 [proposal.md](proposal.md)，可验收行为见 [backend--storage-and-mounts delta](specs/backend--storage-and-mounts/spec.md)。配套变更：[Ctrl](../../../../FuxiYu_CtrKernel/openspec/changes/show-mount-path-and-deleted-usage/proposal.md) · [Web](../../../../FuxiYu_Web/openspec/changes/show-mount-path-and-deleted-usage/proposal.md)；本文件与 delta 自足描述 Node 契约，不依赖跳转阅读。Node 当前只有一个按容器名读取的 `/api/check_disk_usage`，内部 `DiskUsageCache.get_bind()` 能按任意路径触发后台 `du`，但该方法不是安全外部入口：没有路径范围、存在性和 symlink 校验，也没有按批次的 singleflight、并发和失败冷却。WSS 的 `disk_usage` 是周期全量快照，不适合按已删除记录按需查询，也不应因此扩周期负载。

现有可复用的基础：

- `docker_operates/disk_usage_cache.py` 已按规范化路径维护内存缓存，成功 TTL 900 秒，`du -sb` 超时 600 秒，失败不写 0；读取侧当前不等待 du。
- `services/container_service.py` 已有 `list_disk_usage()` 桥接缓存；`clean_mount()` 已有 `NODE_CONTAINERS_BASE` + `containers` 段校验，本变更不修改它。
- `run.py` 的 HTTP/HTTPS 入口已有 Ctrl 客户端证书信任；本端点沿用既有 mTLS 控制通道，不创建新端口、证书或浏览器 API。
- Node 没有数据库；本变更所需的“已删除”身份、`deleted_id` 与路径来源全部在 Ctrl，Node 只接收路径。

## Goals / Non-Goals

**Goals:**

- 为 Ctrl 提供一个安全、只读、按路径批量查询的 Node HTTP 契约，慢测量不阻塞 HTTP。
- 复用既有按路径内存缓存与后台 `du`，以真实的测量时间和 pending/error 区分未完成与失败。
- 将路径暴露面限制在 `NODE_CONTAINERS_BASE/.../containers/...` 的非 symlink 现存目录。
- 用 singleflight、小并发和短失败冷却限制重复测量；不引入持久化或通用任务框架。
- 查询时检查目录是否已清理，避免返回已删除目录的旧成功样本。

**Non-Goals:**

- 不实现 Ctrl 的 `deleted_ids` 请求、只读记录解析、`container:manage` 校验或 Web 轮询；这些属于配套变更。
- 不新增 Node 详情字段、Docker 调用、容器目录扫描、全局总计、清理/恢复/冻结判定。
- 不新增数据库列/表/JSON 迁移，不写已删容器 `disk_*`、恢复快照或清理记录。
- 不新增/扩展周期 WSS、Node→Ctrl 推送或 `ContainerDiskUsage` 字段。
- 不使用 inode/dev/PID/Docker ID 作为授权、缓存身份或结果字段，不扫描全盘。

## Decisions

### 1. 端点、模型与分层

新增一个与既有 `/api/check_disk_usage` 并列的只读路由：

| 层 | 变更 | 职责 |
| --- | --- | --- |
| `schemas/container.py` | `CheckMountUsageConfig`、`CheckMountUsageMessage`、`MountUsageItem`、`CheckMountUsageResponse` | 请求/响应的线路形状与 Pydantic 校验 |
| `network/api.py` | `check_mount_usage_api` | 接收批次、调用服务桥、捕获未预期异常；不直接跑 du |
| `services/container_service.py` | `check_mount_usage(mount_paths)` | 桥接 `extensions.disk_usage_cache`，与 `list_disk_usage()` 同层 |
| `docker_operates/disk_usage_cache.py` | `read_mount_usage(paths)` 与固定 4 worker 的路径测量调度 | 路径校验、缓存读取、singleflight、后台 du、失败冷却 |

建议模型（字段名是线路契约，必须与 spec 数据附录一致）：

```python
class CheckMountUsageConfig(BaseModel):
    mount_paths: list[str] = Field(min_length=1, max_length=100)


class CheckMountUsageMessage(BaseModel):
    config: CheckMountUsageConfig


class MountUsageItem(BaseModel):
    path: str
    bytes: int | None = Field(default=None, ge=0)
    measured_at: str | None = None
    pending: bool = False
    error: str | None = None


class CheckMountUsageResponse(SuccessResponse):
    mounts: list[MountUsageItem]
```

路由固定返回：

```json
{"success": 1, "mounts": [{"path": "...", "bytes": null, "measured_at": null, "pending": true, "error": null}]}
```

合法批次只要通过请求校验就是 HTTP 200、`success=1`，逐项失败不下沉为批次失败。空数组、超过 100、缺 `config`/`mount_paths`、非字符串数组交给 FastAPI/Pydantic 返回 422，不进入缓存和 du。选 422 而不是自定义异常处理器，是为了复用现有 FastAPI 校验边界；该错误体不是 Ctrl 的成功响应，Ctrl 只需按非 2xx 处理。路由捕获未预期异常时返回 HTTP 500、`success=0`、`error_reason="internal_error"`，不返回部分结果或伪造 0。

响应模型只声明 `path/bytes/measured_at/pending/error`，不增加 `container_name`、`deleted_id`、`machine_id`、`mount_path_status`、inode、dev、PID、Docker ID 或 stderr 字段。`path` 在服务/路由层按请求顺序回填为原始字符串；缓存内部使用规范化键，但不改写线路回显。

### 2. 路径校验作为读侧门禁

在读取缓存或触发测量前，对每个请求项独立执行以下检查；单条失败只产生该项错误：

| 步骤 | 检查 | 失败结果 |
| --- | --- | --- |
| 1 | `os.path.isabs(path)` 为真 | `invalid_path` |
| 2 | 请求的最终对象不是 symlink（先检查 `islink`，包括悬空链接） | `invalid_path` |
| 3 | `realpath(path)` 不等于 base，且位于 `NODE_CONTAINERS_BASE` 下 | `invalid_path` |
| 4 | realpath 的路径段含大小写不敏感的 `containers` | `invalid_path` |
| 5 | 对路径 `stat`：不存在/已清理 | `not_found` |
| 6 | `stat` 为目录，而不是普通文件/其它对象 | `invalid_path` |
| 7 | stat/读取权限不足 | `permission_denied` |

实现沿用 `clean_mount` 已有的 base/`containers` 判定习惯（realpath、`normcase`、路径段比较），但新增独立校验方法，避免改变 `clean_mount` 的既有行为。`NODE_CONTAINERS_BASE` 仍取既有环境变量，缺省 `/home`。

关键选择：

- **先做存在性检查再读缓存**：`not_found` 必须优先于任何 TTL 内缓存。命中不存在路径时，在锁内移除该规范化键的缓存条目并返回 `not_found`，不启动 du，不枚举父目录。
- **不调用 `verify_mount_path`、`_dir_identity`、Docker inspect 或 `/proc`**：该端点只有明确路径，不做挂载身份核对，不读取 inode/dev/PID/Docker ID，也不把路径诊断带入授权。
- **只查请求路径**：不遍历父目录、不搜索同名前缀、不扫描全盘、不计算全局总计。

### 3. 状态投影与真实测量时间

`read_mount_usage` 在锁内读取既有 `_bind_cache` 条目，并按以下顺序投影：

| 内部状态 | 公共结果 |
| --- | --- |
| 路径校验失败 | `bytes=null`、`measured_at=null`、`pending=false`、`error=invalid_path/not_found/permission_denied` |
| 同一规范化路径正在测量/排队 | `bytes=null`、`measured_at=null`、`pending=true`、`error=null` |
| 最近一次测量失败且在 60 秒冷却内 | `bytes=null`、`measured_at=null`、`pending=false`、上次稳定 `error` |
| 成功样本年龄 < 900 秒 | `bytes=已存字节`、`measured_at=原测量时间`、`pending=false`、`error=null` |
| 无样本、成功样本达到 900 秒或失败已过冷却 | 启动/排队后台测量，返回 `pending=true`，不返回旧成功字节 |

投影规则：

- 成功字节只从 `du -sb` 成功结果更新；失败不覆盖最后成功 `bytes/measured_at`，但错误状态下 MUST NOT 把最后成功值投影成当前成功。最后成功值只留在内部作诊断。
- `measured_at` 由 `du` 进程完成时生成，沿用 UTC `YYYY-MM-DDTHH:MM:SSZ`。缓存命中时原样返回，不因 HTTP 请求、WSS 读取或轮询刷新。
- `empty_output`、`parse_error`、`non_zero_exit`、`timeout`、`permission_denied`、`du_unavailable`、`du_failed` 均原样映射为稳定 error；不把 stdout 数字、进程返回值或内部异常文本拼成“成功”或对外错误。
- 900 秒 TTL 内的成功样本可能是删除前采集的，这是允许的旧样本；线路必须带原始 `measured_at`，不增加“刚测量”语义。

### 4. 复用测量核心，补 singleflight、并发与失败冷却

不直接把 `get_bind()` 挂到路由上，因为它的读取路径会立即触发后台测量、没有请求级 singleflight/冷却，也不做路径安全校验。新方法复用同一 `_bind_cache`、`collect_bind()` 和 `du -sb` 核心，只增加读侧调度：

1. **规范化键**：通过校验的 `realpath` 经既有路径规范化函数生成缓存键；同批重复路径和并发同路径共享同一键。路由仍按原请求逐项回显，不因去重少返回。
2. **singleflight**：在锁内检查条目的 `running`；已有任务则只返回 pending，不重复启动。设置 `running`、分配进程内单调递增的 request id、将规范化路径投递到专用执行器都在同一临界区完成。
3. **固定并发**：专用执行器固定 4 个 worker；只投递去重后的合法路径，最多 100 条/请求，不启动无界的线程，不做后台孤儿扫描。专用执行器只服务该端点，避免与 live 容器的周期采集互相占用；这不是持久化队列、重试框架或跨进程任务系统。
4. **失败冷却**：`collect_bind` 失败时记录内部 `failed_at`；60 秒内查询直接返回上次稳定 error，不再投递 du。成功后清除失败时间。冷却用于防止 Web 每 5 秒轮询把持续失败放大成 du 风暴，不是把错误改成成功。
5. **清理竞态**：路径不存在时移除缓存键；同时使用进程内单调 request id，旧 du 结果即使晚到也因 request id 不匹配而丢弃。这样不修改 `clean_mount`、不借助 inode/dev，也不向清理流程注入回调。
6. **不阻塞 HTTP**：路由只做 100 条以内的路径 stat/realpath 和锁内状态投影，随后立即返回；du 由 4 个 worker 后台执行，单次最长 600 秒。

选择“复用同一缓存”的理由：Ctrl 已明确要按 path 复用 Node 的口径，900 秒 TTL、失败不写 0、真实 measured_at 都已有实现；另建缓存会形成第二套测量事实，并与既有 `disk_usage` 快照不一致。共享缓存可能让既有 WSS 在下一次正常快照中读到同一路径样本，但本变更不新增 WSS 帧、topic、字段或推送节奏。

### 5. 清理后目录检查

清理后的正确性由查询时的路径存在性检查保证，而不是修改 `clean_mount`：

- 每次请求先 stat 请求路径；不存在立即移除缓存并返回 `not_found`。
- 目录在 du 期间被清理时，du 的非零退出/空输出会按稳定错误返回；即使旧任务晚到，request id 与移除后的条目不匹配，结果被丢弃。
- 下一次查询重新检查，仍不存在则继续 `not_found`，不会返回已清理前的成功缓存。
- 不扫描父目录寻找“替代目录”，不把同名重新出现的目录自动关联为旧目录；路径本身是唯一业务键，不使用 inode/dev 做身份授权。

### 6. 路由、服务与缓存职责

`network/api.py` 不直接读 `extensions.disk_usage_cache`；沿用现有 `list_disk_usage` 的分层，通过 `services/container_service.py` 的薄桥接调用缓存。这样路由只负责 HTTP 契约和 500 兜底，缓存负责路径、并发与时间语义，避免把清理、Docker 或数据库逻辑误放进端点。

新增模型需从 `schemas/__init__.py` 导出，加入 `__all__`；新增路由加入 `network/api.py` 的 import 列表。既有 `ContainerDiskUsage`、`CheckDiskUsage*`、`CleanMount*`、WSS 构建函数和 `clean_mount` 不改语义。

### 7. 只读、权限与兼容

- 端点不写数据库（Node 没有数据库）、不写已删容器 `disk_*`/恢复快照/清理记录、不实现或调用 `resolve_mount_cleanup_request` 等 ensure/adopt 写路径、不修改目录、不调用 `clean_mount`、不触发 Docker 动作。所有新增状态仅为 Node 进程内缓存与执行器。
- 不新增 machine 角色或用户角色字段/门禁；授权由 Ctrl 既有 `container:manage` 负责。Node 只复用既有 mTLS 控制通道，不新增 CORS/公网入口。
- 旧 Ctrl 不调用新端点时，既有详情/列表/恢复/清理不变；旧 Node 没有端点时返回 404/405，Ctrl 映射为 `node_unsupported`，Web 显示不可用，不造 0。
- 详情 `bind_mount_path` 由 Ctrl 从既有 `containers.bind_mount_path` 提供，Node 不新增详情接口/字段，也不调用 Node 核对详情。
- 不改变冻结、恢复、长期资格、删除/清理资格；本端点结果只用于展示统计。

### 8. 备选方案与取舍

| 方案 | 不采用的原因 |
| --- | --- |
| 直接把 `get_bind` 暴露为 HTTP | 无路径 allowlist/存在性/symlink 校验，可能测量任意宿主目录；错误/过期语义也不符合批量接口 |
| 新增周期 WSS 字段承载删除目录统计 | 会扩大周期快照、需要跨端状态编排，且删除目录不是活跃容器；本需求只需按需 HTTP |
| 建持久化任务队列/缓存 | Node 无数据库，且重启丢失是可接受语义；持久化会引入迁移、清理和任务生命周期 |
| HTTP 同步等待 `du` 完成 | 慢目录可达 600 秒，会阻塞 Ctrl/Web；必须 pending + 后台测量 |
| 每次请求直接起独立线程 | 100 条批量会放大线程/du 并发；需 singleflight 和小并发 |

## Risks / Trade-offs

- [900 秒内返回删除前样本] → 这是明确的 TTL 语义；始终返回原始 `measured_at`，Web 展示为最近测量而非实时。
- [路径已清理但旧任务晚到] → 查询时存在性检查、移除缓存和进程内单调 request id 丢弃晚到结果；不修改 `clean_mount`。
- [路径重新创建为不同目录] → 不使用 inode，仍以路径为业务键；这是不引入目录身份授权的代价，至少要求真实 `measured_at` 和存在性检查。
- [100 条路径 + 慢 du 导致长时间 pending] → 固定 4 worker、singleflight、pending 立即返回；不阻塞 HTTP，Web 有界轮询，超时预算由消费方处理。
- [失败冷却让短暂故障显示 60 秒] → 冷却只防止 du 风暴；错误明确显示，消费方可手动重试，冷却不伪造成功。
- [批量形状错误使用 422] → Ctrl 应在调用前限制 1～100；Node 不截断，不把 422 当成功或 0。
- [共享缓存可能被既有 WSS 读取] → 不新增 WSS 协议；若路径也是活跃容器业务路径，既有快照按原语义读取是预期行为。

## Migration Plan

1. 先合入 Node 的模型、缓存读方法和路由；端点纯新增，不要求数据库或配置迁移。
2. Ctrl 可在旧 Node 上先上线兼容分支：404/405 映射 `node_unsupported`，不阻断列表/恢复/清理；新 Node 上线后自动可用。
3. 回滚 Node 只移除新端点；无持久化状态需要清理，旧 Ctrl 不受影响。Ctrl 对旧 Node 的降级路径仍保留。
4. 无需迁移已删容器记录、不需要回写 `disk_*`/恢复快照；不触碰正式 specs/archive。

## Verification Strategy

实现阶段用受控单测/端点测试覆盖，不依赖真实 Docker 或真实大型目录：

- **契约**：1～100 项成功体、逐项 mixed 状态、`path` 原样同序、重复路径不少项、422 批次拒绝、500 不返回部分结果。
- **路径**：base 内合法、base 外/相对/缺 `containers`/文件/symlink/不存在/权限失败；断言非法项不触发 du。
- **缓存与时间**：TTL 命中、过期 pending、慢 du 不阻塞、真实 `measured_at` 不被读取刷新、失败不覆盖最后成功、重启式新缓存为空。
- **并发与冷却**：同路径并发 singleflight、100 条时 du 并发不超过 4、失败 60 秒内不重启、冷却后允许重试。
- **清理**：缓存命中后删除目录返回 `not_found`、在途 du 晚到不发布成功、`clean_mount` 行为不变。
- **边界**：不产生 WSS 帧/topic/字段，不写数据库/快照/清理记录，不调用 Docker/`clean_mount`，不新增角色门禁；旧 Ctrl 不调用时既有接口回归不变。

## Open Questions

无。

## Source references

- [network/api.py](../../../network/api.py)：既有 `/check_disk_usage` 434-463、`/clean_mount` 486-498。
- [schemas/container.py](../../../schemas/container.py)：`CheckDiskUsageMessage` 272-304、`CleanMount*` 329-339。
- [schemas/__init__.py](../../../schemas/__init__.py)：模型导出 7-59、`__all__` 61-117。
- [docker_operates/disk_usage_cache.py](../../../docker_operates/disk_usage_cache.py)：base/allowlist 94-110、缓存条目 454-497、`collect_bind` 499-588、`_measurement_for_path` 590-661、`get_bind` 959-968。
- [services/container_service.py](../../../services/container_service.py)：`clean_mount` 872-901、`list_disk_usage` 1340-1347。
- [run.py](../../../run.py)：Ctrl 客户端证书/mTLS 25-30。
- [tests/test_clean_mount.py](../../../tests/test_clean_mount.py)、[tests/test_cache_collectors.py](../../../tests/test_cache_collectors.py)、[tests/test_blueprint_api.py](../../../tests/test_blueprint_api.py)：既有清理、缓存与端点测试基线。
