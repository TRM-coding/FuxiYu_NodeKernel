# Proposal

## Why

Ctrl 已持久化容器详情所需的 `containers.bind_mount_path`，Web 也已能拿到已删除容器记录的 `mount_path`；但 Node 没有安全的只读入口，按路径 `du -sb` 只能被现有内部缓存间接使用。直接把 `get_bind` 暴露给 Ctrl 会缺少路径范围校验，并可能把失败、未测量或已清理目录误报成 0。本变更只补齐 Node 的安全批量路径用量查询，供 Ctrl 为已删除容器页取遗留目录的异步统计。

Node 不负责详情字段、`deleted_id`、用户权限、清理决定或数据库写入。详情路径完全来自 Ctrl 既有列；TTL 内的旧缓存只表示真实测量时间内的历史样本，不宣称是删除后的新扫描。

## What Changes

- **新增 Node HTTP 只读端点**：`POST /api/check_mount_usage`，请求体为 `{config:{mount_paths:[绝对路径]}}`，单次 1～100 条。响应固定为 `{success:1,mounts:[{path,bytes,measured_at,pending,error}]}`；每个请求路径按原样回显，不使用容器名、Docker ID 或宿主目录内容作为线路字段。
- **路径校验与按路径缓存**：只接受 `NODE_CONTAINERS_BASE` 内、含 `containers` 路径段、绝对且非 symlink 的现存目录；`realpath` 与目录检查在测量前完成。越界/非绝对/非目录/symlink 返回 `invalid_path`，不存在或已清理返回 `not_found`，两者均不启动 `du`，也不返回旧缓存。
- **复用既有测量语义**：复用 `docker_operates/disk_usage_cache.py` 的按规范化路径缓存、后台 `du -sb`、默认 900 秒 TTL 和 600 秒超时；请求不等待慢 `du`。成功返回逻辑字节数、真实 UTC `measured_at`、`pending=false`、`error=null`；测量中返回 `pending=true` 且 `bytes=null`；错误返回 `bytes=null`、`pending=false` 和稳定原因。失败绝不补 0。
- **有界调度**：同一规范化路径 singleflight，路径缓存不因重复请求重复起 `du`；小并发上限、失败冷却，不建设通用队列框架，不改变 `clean_mount`，不调用可写库的解析/认领函数。
- **只读与兼容**：不新增 WSS topic/字段、不改变 `check_disk_usage`、`ContainerDiskUsage`、周期快照或 `clean_mount`；不新增数据库列/表/JSON 迁移，不写已删容器 `disk_*`、恢复快照或清理记录。旧 Ctrl 不调用新端点即可保持原行为；旧 Node 的 404/405 由 Ctrl 映射为 `node_unsupported`，不由 Node 伪造成功。
- **详情展示无 Node 修改**：详情 `bind_mount_path` 的追加可空字段、完整路径复制与空值“未记录”展示由 Ctrl/Web 配套变更完成，Node 不新增详情接口或字段。

配套变更：[Ctrl](../../../../../FuxiYu_CtrKernel/openspec/changes/archive/2026-10-20-show-mount-path-and-deleted-usage/proposal.md) · [Web](../../../../../FuxiYu_Web/openspec/changes/archive/2026-10-20-show-mount-path-and-deleted-usage/proposal.md)。本仓规格不依赖这些链接即可实现。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--storage-and-mounts`: 新增 Node 只读批量路径用量 HTTP 契约、受限目录校验、按路径内存缓存与后台 `du`、有界失败/清理后目录检查，以及不扩 WSS/不改既有测量契约的兼容要求。

## Impact

- 代码：`schemas/container.py`（请求/响应模型）、`network/api.py`（只读端点）、`docker_operates/disk_usage_cache.py`（复用/补齐路径校验、singleflight、并发与失败冷却）、相关测试。
- 接口：新增 `/api/check_mount_usage`；既有 `/api/check_disk_usage`、`/api/clean_mount`、WSS 快照和容器生命周期接口不变。
- 数据：无数据库或持久化变更；缓存仅在 Node 进程内，重启即丢失。
- 权限：沿用现有 Node 控制通道信任与 Ctrl 的既有 `container:manage`；Node 不新增机器角色门禁，也不接受浏览器直连路径。
- 边界：不做全盘/孤儿扫描、全局总计、清理授权、自动冻结或恢复资格变更；`du -sb` 为逻辑字节，不是物理 blocks。
