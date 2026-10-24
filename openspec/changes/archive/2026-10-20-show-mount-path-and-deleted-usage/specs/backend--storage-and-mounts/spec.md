# Spec Delta

## ADDED Requirements

### Requirement: Node 批量路径用量请求契约

Node SHALL 在既有 Ctrl→Node HTTP 控制通道新增只读 `POST /api/check_mount_usage`，请求体为 `{"config":{"mount_paths":[...]}}`。`mount_paths` MUST 为 1～100 个字符串，每项语义为宿主绝对路径，并保持请求顺序；单条路径非法 MUST NOT 使整批失败。空数组、超过 100、缺 `config`/`mount_paths` 或非字符串数组 MUST 在启动测量前整体拒绝（HTTP 422 请求校验错误），不得截断、补齐或部分执行。请求 MUST NOT 携带 `deleted_id`、`machine_id`、`container_name`、角色或浏览器任意路径。

#### Scenario: 合法批量请求

- **WHEN** Ctrl 发送 1～100 个字符串路径，且 `config` 结构正确
- **THEN** Node 接受整批并为每个请求项返回一项结果，响应中的 `path` 与对应请求字符串完全一致、顺序相同

#### Scenario: 超过上限或空批次

- **WHEN** `mount_paths` 为空、超过 100 条或不是字符串数组
- **THEN** Node 在启动任何 `du` 前以 HTTP 422 拒绝整批，不返回 `success=1`，不截取前 100 条

#### Scenario: 单条路径非法不拖垮同批

- **WHEN** 同批中一项是相对路径或越界路径，其余项合法
- **THEN** Node 只为该非法项返回 `invalid_path`，其余合法项仍按各自状态返回，整批 `success=1`

#### Scenario: 不携带删除记录身份

- **WHEN** 请求只含 `config.mount_paths`
- **THEN** Node 不要求也不解释 `deleted_id`、`machine_id`、容器名或用户角色；身份映射与授权由 Ctrl 负责

### Requirement: 逐路径结果状态与真实字节

Node SHALL 为每个请求项返回 `{path,bytes,measured_at,pending,error}`，且仅允许成功、测量中、错误三种状态。成功时 `bytes` MUST 为 `du -sb` 得到的非负逻辑字节数，`measured_at` 为真实 UTC 完成时间，`pending=false`、`error=null`；测量中 MUST 为 `bytes=null`、`measured_at=null`、`pending=true`、`error=null`；错误 MUST 为 `bytes=null`、`measured_at=null`、`pending=false`、`error` 为非空稳定原因。缺失、未测量、失败或已清理 MUST NOT 用 0 冒充成功。

#### Scenario: 成功返回逻辑字节

- **WHEN** `du -sb` 对允许目录成功完成
- **THEN** 该项返回 `bytes>=0`、真实 `measured_at`、`pending=false`、`error=null`；0 只在目录确实为空时合法，且不表示物理 blocks

#### Scenario: 测量中

- **WHEN** 该路径没有可用成功样本，Node 已启动后台 `du` 但尚未完成
- **THEN** 该项立即返回 `bytes=null`、`measured_at=null`、`pending=true`、`error=null`，不等待 `du` 完成

#### Scenario: 测量失败

- **WHEN** `du` 非零退出、超时、权限失败或输出不可解析
- **THEN** 该项返回 `bytes=null`、`measured_at=null`、`pending=false`、稳定 `error`，即使 stdout 含数字也不采纳

#### Scenario: 批次含逐项错误

- **WHEN** 一批中部分路径成功、部分 pending、部分错误
- **THEN** 顶层仍为 `success=1`、`mounts` 仍与请求等长同序；`success=1` 只表示批次已受理，不表示每一项都成功

#### Scenario: 重复路径保持映射

- **WHEN** 同一路径或规范化后相同的路径在一次请求中出现多次
- **THEN** 每个请求项仍各有一项结果并原样回显 `path`，可共享同一次后台测量，但不得少返回项

### Requirement: 受限路径与不扫描边界

Node SHALL 在读取缓存或启动测量前逐项校验：请求值 MUST 为绝对路径；其 `realpath` MUST 位于 `NODE_CONTAINERS_BASE` 内且不等于 base，并包含大小写不敏感的 `containers` 路径段；最终对象 MUST 存在、为目录且不是 symlink。不存在或已清理返回 `not_found`；非绝对、越界、缺 `containers` 段、普通文件或 symlink 等返回 `invalid_path`；无法 stat 的权限错误返回 `permission_denied`。上述结果均 MUST NOT 执行 `du`、枚举父目录、调用 Docker/proc 或返回旧成功值。

#### Scenario: 允许目录

- **WHEN** 绝对路径 realpath 位于 `NODE_CONTAINERS_BASE` 内、含 `containers` 段，且最终对象是现存非 symlink 目录
- **THEN** 该路径可进入缓存/后台测量流程

#### Scenario: 越界或非绝对路径

- **WHEN** 路径为相对路径、等于 base、位于 base 外或缺少 `containers` 段
- **THEN** 该项返回 `invalid_path`，不启动 `du`，不扫描相邻目录

#### Scenario: symlink 或普通文件

- **WHEN** 请求的最终对象是 symlink 或普通文件
- **THEN** 该项返回 `invalid_path`，不跟随该对象执行 `du`

#### Scenario: 已清理或不存在

- **WHEN** 允许范围内的目录已被删除、从未存在或已被清理
- **THEN** 该项返回 `not_found`，返回前不扫描父目录、不启动 `du`

#### Scenario: 不做全盘或全局统计

- **WHEN** 一次查询只带有若干明确路径
- **THEN** Node 只处理这些路径，不枚举孤儿目录、不扫描全盘、不计算全局总计，也不读取容器或目录身份

### Requirement: 按路径内存缓存与后台测量

Node SHALL 复用既有按业务路径的内存缓存与后台 `du` 语义。缓存键 MUST 为通过校验的规范化路径；成功样本在 900 秒内可直接复用且不重启 `du`，无样本或年龄达到 900 秒时 MUST 启动后台测量并立即返回 `pending`，不得同步等待最长 600 秒的超时。`measured_at` MUST 是该次 `du` 的真实完成时间，不得用请求、缓存读取或 WSS 推送时间刷新；失败 MUST NOT 覆盖最后成功字节与时间。Node 重启后缓存 MUST 为空。

#### Scenario: TTL 内命中

- **WHEN** 同一路径存在年龄小于 900 秒的成功样本
- **THEN** Node 返回该样本的真实字节与 `measured_at`，不重新执行 `du`；测量时间早于请求时间时仍如实展示

#### Scenario: 无样本或 TTL 到期

- **WHEN** 路径没有成功样本，或成功样本年龄已达到 900 秒
- **THEN** Node 启动一次后台测量并立即返回 `pending=true`，不阻塞 HTTP 响应

#### Scenario: 慢 du

- **WHEN** `du -sb` 持续运行且接近 600 秒超时
- **THEN** 查询仍可返回 `pending`，Node 不等待进程结束，也不把超时前的空结果当 0

#### Scenario: 最后成功值不被失败覆盖

- **WHEN** 一个已有成功样本的路径后续测量失败
- **THEN** 失败不更新成功字节/`measured_at`；查询按当前可用状态返回 pending/error，不把旧值伪装成新测量

#### Scenario: 进程重启

- **WHEN** Node 进程重启后首次查询某路径
- **THEN** 进程内缓存为空，Node 重新校验并返回 `pending` 或对应错误，不恢复重启前的样本

### Requirement: 有界去重、并发与失败冷却

Node SHALL 对同一规范化路径执行 singleflight，同一时刻最多一个 `du`；同批重复路径和并发请求 MUST NOT 重复启动测量。本端点触发的 `du` 同时运行数 MUST 不超过 4，排队范围只限当前去重后的请求路径。失败后 MUST 进入固定 60 秒冷却，冷却内重复查询返回上次稳定错误，不得反复启动 `du`；MUST NOT 为此建设通用队列框架或修改 `clean_mount`。

#### Scenario: 并发 singleflight

- **WHEN** 两个并发请求包含同一规范化路径，且该路径尚无成功样本
- **THEN** 只启动一个后台 `du`，两个响应都返回该路径的 `pending`（或同一已完成结果），不重复测量

#### Scenario: 大批量有界并发

- **WHEN** 一次请求包含 100 个不同且合法的路径
- **THEN** Node 可接受整批，但同时运行的 `du` 不超过 4 个；其余路径保持 `pending`，不阻塞 HTTP 响应

#### Scenario: 失败冷却

- **WHEN** 某路径刚发生测量失败且仍在 60 秒冷却内
- **THEN** 后续查询返回该路径的稳定错误与 `pending=false`，不启动新的 `du`；冷却结束后才允许再次尝试

#### Scenario: 冷却不伪造成功

- **WHEN** 失败后的冷却期内重复查询
- **THEN** `bytes` 仍为 `null`，不得因缓存存在或请求重复而返回 0 或最后成功值冒充当前结果

### Requirement: 清理后目录检查与旧缓存失效

Node SHALL 在每次读取缓存或返回结果前检查路径当前是否存在。路径已不存在时 MUST 立即丢弃该规范化路径的缓存并返回 `not_found`，不得返回旧成功样本、启动扫描或执行 `du`。清理完成后无需 Node 收到清理通知；Node MUST NOT 修改 `clean_mount` 或为其新增回调。若目录在测量期间被清理，在途结果 MUST NOT 被发布为当前成功值，后续查询 MUST 得到 `not_found`。

#### Scenario: 缓存命中后目录被清理

- **WHEN** 某路径曾成功测量并留有 TTL 内缓存，随后目录被 `clean_mount` 删除
- **THEN** 下一次查询在返回缓存前发现目录不存在，丢弃缓存并返回 `not_found`

#### Scenario: 测量期间目录被清理

- **WHEN** 后台 `du` 启动后目录被删除，`du` 随后返回失败或空输出
- **THEN** Node 不发布成功字节/时间，返回稳定错误；下一次查询返回 `not_found`

#### Scenario: 已清理路径不扫描

- **WHEN** 请求路径已清理或不存在
- **THEN** Node 不枚举其父目录、不尝试查找替代目录、不扫描全盘，也不返回旧缓存

#### Scenario: clean_mount 行为不变

- **WHEN** 本端点上线后执行既有清理
- **THEN** `clean_mount` 的入口校验、超时、错误和删除语义保持不变，本变更不向其注入缓存逻辑

### Requirement: 只读、无周期 WSS 扩展与权限边界

本端点 SHALL 只读：MUST NOT 写数据库、已删容器 `disk_*`、恢复快照、清理记录或任何持久化状态，MUST NOT 实现或调用 `resolve_mount_cleanup_request` 等 ensure/adopt/insert/update/delete 写路径，MUST NOT 调用清理函数或修改 Docker/宿主目录。Node MUST NOT 新增或扩展周期 WSS 的 topic、字段、频率或按需推送，也不新增 Node→Ctrl 推送；既有磁盘快照若按原语义读取共享缓存，不属于新协议。Node MUST NOT 新增机器角色门禁；授权仍由 Ctrl 的既有 `container:manage` 负责，Node 只复用既有 mTLS 控制通道。

#### Scenario: 查询不产生持久化

- **WHEN** Ctrl 调用该端点并得到成功、pending 或错误
- **THEN** Node 不写数据库/快照/清理记录，不修改目录或容器，仅在进程内更新路径测量缓存

#### Scenario: 不扩 WSS

- **WHEN** 查询进行中或完成后
- **THEN** Node 不因该端点建立新 WSS topic、增加载荷字段、提高推送频率或主动向 Ctrl 推送；既有 WSS 契约保持不变

#### Scenario: 权限不另设门禁

- **WHEN** 请求从既有 Ctrl→Node mTLS 通道到达
- **THEN** Node 不要求新增 machine 角色/用户角色字段，也不以 `deleted_id` 做授权；用户权限由 Ctrl 的既有 `container:manage` 判定

#### Scenario: 不向浏览器开放路径参数

- **WHEN** 浏览器或其他非 Ctrl 客户端尝试直接调用该端点
- **THEN** 该端点不属于浏览器 API，Node 不新增 CORS 或公网路径入口；仍受既有控制通道认证约束，且路径白名单拒绝任意宿主路径

### Requirement: 详情与既有行为兼容

本变更 SHALL 只增加 Node 端点，MUST NOT 修改 `check_disk_usage`、`ContainerDiskUsage`、WSS 磁盘字段、容器详情接口或 `clean_mount`。详情路径展示完全由 Ctrl 从既有 `containers.bind_mount_path` 提供，Node 不需要也不得新增详情字段。旧 Ctrl 不调用新端点时行为不变；旧 Node 没有该端点时由 Ctrl 映射为 `node_unsupported`，Node 不伪造成功。缺少详情字段、新统计不可用、旧缓存丢失或端点缺失 MUST NOT 改变既有列表、恢复、清理资格或流程。

#### Scenario: 旧 Ctrl 不调用

- **WHEN** 旧 Ctrl 只使用既有详情、列表、恢复和清理接口
- **THEN** Node 的既有接口、WSS 快照和磁盘模型保持原行为，不因本端点存在而要求新字段

#### Scenario: 旧 Node 无端点

- **WHEN** Ctrl 向没有 `/api/check_mount_usage` 的旧 Node 发起请求
- **THEN** Node 返回既有 404/405；Ctrl 以 `node_unsupported` 降级，Node 不返回伪造的 0 或成功

#### Scenario: 详情无 Node 参与

- **WHEN** Ctrl 在详情响应中加入或缺失 `bind_mount_path`
- **THEN** Node 不调用详情接口、不新增详情字段、不因详情展示执行测量；缺失仍由 Ctrl/Web 显示“未记录”

#### Scenario: 不改变恢复/清理/冻结资格

- **WHEN** 本端点返回成功、pending、错误或 `not_found`
- **THEN** 该结果只用于展示统计，不参与冻结、恢复、长期资格、删除或清理判定；既有资格与流程不变

#### Scenario: 无数据库迁移

- **WHEN** 升级或回滚本变更
- **THEN** 不存在新增列/表/JSON 迁移，也不回写已删容器磁盘字段或恢复快照；回滚只失去按需统计能力

## Data model appendix

本附录给出 Node 实现所需的完整 HTTP 形状；实现本变更不依赖 Ctrl/Web 文档。

### 端点

| 项 | 值 |
| --- | --- |
| Method | `POST` |
| Path | `/api/check_mount_usage` |
| Content-Type | `application/json` |
| 调用方向 | Ctrl → Node，既有 mTLS 控制通道 |
| 权限 | 不新增 Node 角色门禁；Ctrl 负责既有 `container:manage` |
| 幂等性 | 只读查询；可安全重试，测量由进程内 singleflight 去重 |

### 请求

```json
{
  "config": {
    "mount_paths": [
      "/home/alice/containers/c1",
      "/home/alice/containers/c2"
    ]
  }
}
```

| 字段 | 类型 | 必填 | 约束与语义 |
| --- | --- | --- | --- |
| `config` | object | 是 | 唯一请求外层容器 |
| `config.mount_paths` | array[string] | 是 | 1～100 项；每项语义为宿主绝对路径；顺序保留；不得为空、截断或补项 |
| `config.mount_paths[]` | string | 是 | 单条非法只影响该项；路径回显必须与请求文本一致 |

请求 MUST NOT 需要或解释以下字段：`deleted_id`、`machine_id`、`container_name`、`mount_path`（单数）、用户/机器角色、inode、dev、PID、Docker ID 或浏览器提供的任意路径。

### 成功响应

合法批次即使含逐项错误，HTTP 仍为 200，顶层 `success` 为 `1`：

```json
{
  "success": 1,
  "mounts": [
    {
      "path": "/home/alice/containers/c1",
      "bytes": 123456789,
      "measured_at": "2026-10-20T08:00:00Z",
      "pending": false,
      "error": null
    },
    {
      "path": "/home/alice/containers/c2",
      "bytes": null,
      "measured_at": null,
      "pending": true,
      "error": null
    },
    {
      "path": "/home/alice/containers/c3",
      "bytes": null,
      "measured_at": null,
      "pending": false,
      "error": "permission_denied"
    }
  ]
}
```

| 字段 | 类型 | 可空 | 语义 |
| --- | --- | --- | --- |
| `success` | integer | 否 | 合法批次固定为 `1`；只表示批次已处理，不表示每项成功 |
| `mounts` | array[object] | 否 | 与请求 `mount_paths` 等长同序，每项一个结果 |
| `mounts[].path` | string | 否 | 请求路径原样回显，供 Ctrl 按路径映射；不做规范化改写 |
| `mounts[].bytes` | integer | 是 | `du -sb` 逻辑字节，`>=0`；只在成功时为整数；不是物理 blocks、不是分配大小 |
| `mounts[].measured_at` | string | 是 | 真实测量完成时间的 UTC ISO 8601，形如 `YYYY-MM-DDTHH:MM:SSZ`；不是请求/读取/推送时间 |
| `mounts[].pending` | boolean | 否 | `true` 表示后台测量尚未完成；此时字节与时间均为 null |
| `mounts[].error` | string | 是 | 稳定失败原因；成功与 pending 时为 null；错误时非空 |

响应 MUST NOT 增加 `container_name`、`deleted_id`、`machine_id`、`source`、`mount_path_status`、`inode`、`dev`、`pid`、`docker_id`、stderr 或目录内容。

### 状态矩阵

| 状态 | `bytes` | `measured_at` | `pending` | `error` |
| --- | --- | --- | --- | --- |
| 成功（含真实 0 字节空目录） | `integer >= 0` | 非空 UTC 字符串 | `false` | `null` |
| 测量中 | `null` | `null` | `true` | `null` |
| 错误 | `null` | `null` | `false` | 稳定非空原因 |

其他组合均为非法。失败、未测量和已清理一律不得填 `0`。如果成功样本仍在 900 秒 TTL 内，允许返回删除前产生的样本，但必须如实返回其原始 `measured_at`；不得把旧样本称为刚完成或“瞬时”。

### 稳定错误原因

| `error` | 触发条件 | 是否执行 `du` |
| --- | --- | --- |
| `invalid_path` | 非绝对、realpath 越界/等于 base、缺 `containers` 段、普通文件、最终对象为 symlink 或其它路径非法 | 否 |
| `not_found` | 允许范围内路径不存在、已清理或已被删除 | 否 |
| `permission_denied` | 路径 stat 或 `du` 权限不足 | stat 失败时否；测量期间失败时是 |
| `timeout` | `du` 超过 600 秒 | 是，已超时终止 |
| `non_zero_exit` | `du` 非零退出（即使 stdout 有数字） | 是 |
| `empty_output` | `du` 成功退出但输出为空 | 是 |
| `parse_error` | `du` 输出不可解析 | 是 |
| `du_unavailable` | 宿主没有可执行的 `du` | 否（启动失败） |
| `du_failed` | 其它稳定测量异常，作为兜底 | 可能是 |

错误响应 MUST NOT 包含 stderr、绝对目录内容、进程输出或内部异常文本。未知异常归一为 `du_failed`，不得将其当作成功。

### 批次级错误

空数组、超过 100、缺 `config.mount_paths`、非字符串数组或整体结构非法时，由 FastAPI/Pydantic 在进入业务处理前返回 HTTP 422，且不启动任何测量。该响应是请求校验错误，不包含本端点的成功体；调用方只按非 2xx 处理：

```json
{
  "detail": [
    {
      "loc": ["body", "config", "mount_paths"],
      "msg": "List should have between 1 and 100 items",
      "type": "value_error"
    }
  ]
}
```

未预期内部错误为 HTTP 500、`success=0`，不得返回部分伪造结果。逐项路径错误不触发批次级错误，也不使用 422。

### 路径校验

| 步骤 | 规则 | 失败原因 |
| --- | --- | --- |
| 1 | 请求值必须为绝对路径 | `invalid_path` |
| 2 | 请求的最终对象不是 symlink（含悬空链接） | `invalid_path` |
| 3 | `realpath` 必须位于 `NODE_CONTAINERS_BASE` 下，且不得等于 base | `invalid_path` |
| 4 | realpath 的路径段必须包含大小写不敏感的 `containers` | `invalid_path` |
| 5 | 最终对象存在；不存在/已清理 | `not_found` |
| 6 | 最终对象是目录 | `invalid_path` |
| 7 | 当前进程可 stat/读取该目录 | `permission_denied` |

`NODE_CONTAINERS_BASE` 使用既有配置，缺省 `/home`。校验只针对请求给出的路径，不递归、不枚举父目录、不调用 Docker inspect 或 `/proc`，不使用 inode/dev/PID/Docker ID 授权。

### 缓存、调度与时间

| 参数 | 值 | 语义 |
| --- | --- | --- |
| 缓存键 | 通过校验的规范化路径 | 同路径共享；不按容器名、inode、PID 或 Docker ID |
| 成功 TTL | 900 秒 | 年龄小于 900 秒可复用；达到 900 秒触发后台测量并返回 pending |
| `du` 超时 | 600 秒 | 超时终止并返回 `timeout`，不阻塞 HTTP |
| 本端点并发上限 | 4 | 同时运行的 `du` 不超过 4 个 |
| 失败冷却 | 60 秒 | 冷却内不重启 `du`，返回上次稳定错误 |
| singleflight | 每规范化路径最多 1 个 | 并发请求/同批重复路径不重复测量 |
| 持久化 | 无 | 缓存仅在 Node 进程内；重启清空 |

请求处理 MUST 在触发后台测量后立即返回，不允许等待 `du` 完成。`measured_at` 必须在 `du` 真正完成时生成，缓存读取、请求到达和 WSS 推送都不得刷新它。
