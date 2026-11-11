# Spec Delta

## MODIFIED Requirements

### Requirement: 有界去重、并发与失败冷却

Node SHALL 对同一规范化路径执行 singleflight，同一时刻最多一个 `du`；同批重复路径和并发请求 MUST NOT 重复启动测量。本端点触发的 `du` 同时运行数 MUST 不超过 4，排队范围只限当前去重后的请求路径。失败后 MUST 进入固定 60 秒冷却，冷却内重复查询返回上次稳定错误，不得反复启动 `du`；本统计能力 MUST NOT 为此建设通用队列框架，也 MUST NOT 借测量去重或冷却修改 `clean_mount` 的路径校验、30 秒超时、错误和删除语义。`clean_mount` 的进程内路径互斥与异步/同步子进程生命周期由 `async-mount-cleanup` 单独授权，不属于本统计能力。

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

Node SHALL 在每次读取缓存或返回结果前检查路径当前是否存在。路径已不存在时 MUST 立即丢弃该规范化路径的缓存并返回 `not_found`，不得返回旧成功样本、启动扫描或执行 `du`。清理完成后无需 Node 收到清理通知；本统计能力 MUST NOT 为 `clean_mount` 注入测量缓存逻辑、清理回调或目录存在性回写，也 MUST NOT 借缓存失效修改其路径入口、30 秒超时、错误和删除语义。`clean_mount` 的路径互斥与异步/同步子进程生命周期由 `async-mount-cleanup` 单独授权。若目录在测量期间被清理，在途结果 MUST NOT 被发布为当前成功值，后续查询 MUST 得到 `not_found`。

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

- **WHEN** 本统计能力上线后执行既有清理
- **THEN** 本能力不向 `clean_mount` 注入缓存逻辑或回调，测量缓存仍按目录存在性失效；`clean_mount` 的路径互斥和子进程生命周期只由 `async-mount-cleanup` 的授权要求变更，统计能力不改变其 30 秒超时、错误和删除语义

### Requirement: 详情与既有行为兼容

本变更 SHALL 只增加 Node 端点，MUST NOT 修改 `check_disk_usage`、`ContainerDiskUsage`、WSS 磁盘字段或容器详情接口；`clean_mount` 的异步协议、路径互斥、子进程生命周期和旧同步兼容由 `async-mount-cleanup` 单独授权，本统计能力 MUST NOT 借详情/统计修改 `clean_mount`。详情路径展示完全由 Ctrl 从既有 `containers.bind_mount_path` 提供，Node 不需要也不得新增详情字段。旧 Ctrl 不调用新端点时行为不变；旧 Node 没有该端点时由 Ctrl 映射为 `node_unsupported`，Node 不伪造成功。缺少详情字段、新统计不可用、旧缓存丢失或端点缺失 MUST NOT 改变既有列表、恢复、清理资格或流程。

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

## ADDED Requirements

### Requirement: 异步清理启动与状态线路契约

Node SHALL 提供 `POST /api/start_clean_mount`，请求体为 `{"config":{"mount_path":str}}`，在登记进程内任务后返回 HTTP 200 `{"success":1,"task_id":str}`；该成功只表示已受理，不表示目录已删除。`POST /api/get_clean_mount_status` 接收 `{"config":{"task_id":str}}`，返回 `{"success":1,"task_id":str,"state":"running|succeeded|failed","error_reason":str|null}`；查到失败任务仍是查询成功。线路 MUST NOT 增加 `machine_id`、`mount_path`、目录内容或子进程输出。

#### Scenario: 启动清理只返回受理和任务标识

- **WHEN** Ctrl 用合法 `mount_path` 调用 `POST /api/start_clean_mount` 且没有同路径活动任务
- **THEN** Node 返回 HTTP 200、`success=1` 和唯一 `task_id`，响应不包含 `state`、`succeeded`、目录内容或删除输出

#### Scenario: 查询运行中的任务

- **WHEN** Ctrl 用已受理的 `task_id` 查询且删除尚未结束
- **THEN** Node 返回 `success=1`、同一 `task_id`、`state="running"`、`error_reason=null`

#### Scenario: 查询成功的任务

- **WHEN** 对应 `rm` 已以退出码 0 结束
- **THEN** Node 返回 `success=1`、同一 `task_id`、`state="succeeded"`、`error_reason=null`

#### Scenario: 查询失败的任务

- **WHEN** 对应删除已明确失败
- **THEN** Node 返回 HTTP 200、`success=1`、同一 `task_id`、`state="failed"` 和非空稳定 `error_reason`；查询本身不改成 `success=0`

### Requirement: 异步清理错误与未知任务语义

非法或越界路径 SHALL 返回 HTTP 400、`success=0`、`error="invalid mount_path"`、`error_reason="invalid_path"`。同一规范化路径发生活动占用时 SHALL 返回 HTTP 409：重复清理为 `cleanup_in_progress`，恢复预登记为 `restore_in_progress`。未知、已淘汰或 Node 重启前的任务 SHALL 返回 HTTP 404、`success=0`、`error_reason="not_found"`。未预期异常 SHALL 返回 HTTP 500、`success=0`、`error_reason="internal_error"`。错误体 MUST 保持既有 `success`/`error`/`error_reason` 风格，MUST NOT 返回 `succeeded` 或目录内容。

#### Scenario: 非法路径不建立任务

- **WHEN** 请求路径经 Node 校验越出 `NODE_CONTAINERS_BASE`、缺少 `containers` 段或其它白名单失败
- **THEN** Node 返回 400 和 `invalid_path`，不创建 `task_id`，不启动删除子进程

#### Scenario: 重复清理返回冲突

- **WHEN** 同一规范化路径已有运行中的异步清理
- **THEN** Node 返回 409 和 `cleanup_in_progress`，不返回第二个 `task_id`，不启动第二个删除子进程

#### Scenario: 清理遇到恢复预登记返回冲突

- **WHEN** 同一规范化路径正被恢复创建预登记占用
- **THEN** Node 返回 409 和 `restore_in_progress`，不登记清理任务

#### Scenario: 未知或过期任务不可伪造结果

- **WHEN** 查询的 `task_id` 不存在、已被有界淘汰或属于重启前的进程
- **THEN** Node 返回 404 和 `not_found`，不得返回 Running、成功或任何伪造终态

#### Scenario: 未预期异常不伪装成任务结果

- **WHEN** 登记或查询过程中发生未预期内部异常
- **THEN** Node 返回 500 和 `internal_error`，不返回成功任务或成功清理

### Requirement: Node 权威路径规范化与原子互斥

启动清理和旧同步清理 SHALL 共用 Node 路径规范化：`realpath` 后必须位于 `NODE_CONTAINERS_BASE` 之下且不等于根，并含大小写不敏感的 `containers` 路径段；越界、symlink 逃逸和其它白名单失败均拒绝。Node SHALL 在同一进程锁内完成规范化、活动占用检查和任务或恢复预留登记，MUST NOT 存在先检查后登记的窗口。互斥键是当前 Node 机器内的规范化路径；同一路径的活动清理或恢复占用 MUST 使新清理返回 409，旧同步、异步和恢复创建共享此锁。

#### Scenario: 同一真实目录的路径别名共享一把锁

- **WHEN** 同一目录先后以含 `.`/`..` 的等价路径、symlink 路径和真实路径请求清理，且第一次任务仍在运行
- **THEN** 后续请求都归一到同一键并返回 409，不启动第二个删除

#### Scenario: 并发启动只有一个登记成功

- **WHEN** 两个请求同时为同一路径启动异步清理
- **THEN** 锁内的校验与登记只允许一个任务存在，另一个得到 409，删除子进程最多一个

#### Scenario: 校验失败不占用路径

- **WHEN** 一次清理因路径非法被拒绝，随后以合法路径请求同一目录
- **THEN** 前一次拒绝没有留下任务或锁，合法请求可正常受理

#### Scenario: 终态释放路径后允许重试

- **WHEN** 某路径的前一个清理已进入 `succeeded` 或 `failed` 终态
- **THEN** 新请求可为该路径建立新 `task_id`，旧终态不再阻塞

#### Scenario: 互斥只作用于本 Node 机器

- **WHEN** 两个不同 Node 各自收到相同的规范化路径
- **THEN** 两个 Node 的进程内任务互不影响；Ctrl 以机器标识区分两条清理状态

### Requirement: 进程内有界任务状态与重启语义

任务记录 SHALL 仅存在于当前 Node 进程内，状态只从 `running` 单向进入 `succeeded` 或 `failed`，终态 MUST NOT 被晚到结果覆盖。活动任务 MUST NOT 被淘汰；终态任务 SHALL 受固定数量和保留时间上限约束，并按最旧终态优先淘汰。任务被淘汰或 Node 重启后，旧 `task_id` 查询 MUST 返回 404 `not_found`；Node MUST NOT 根据目录是否存在推断或补写成功。任务标识 MUST 在进程重启后不可复用，Node MUST NOT 为任务状态写数据库、恢复快照、清理记录、WSS 或持久工作流。

#### Scenario: 终态任务有界淘汰

- **WHEN** 终态任务数量或保留时间超过固定上限
- **THEN** Node 按最旧终态优先淘汰，淘汰后的查询返回 404 `not_found`

#### Scenario: 活动任务不被淘汰

- **WHEN** 终态记录达到上限而仍有任务处于 `running`
- **THEN** 淘汰只作用于终态记录，运行任务及其路径占用保留

#### Scenario: 终态不被晚到结果改写

- **WHEN** 任务已写入 `succeeded` 或 `failed` 后后台又产生结果
- **THEN** 原终态保持不变，不得从成功改成失败或从失败改成成功

#### Scenario: Node 重启丢失任务

- **WHEN** Node 进程重启后用重启前的 `task_id` 查询
- **THEN** Node 返回 404 `not_found`，不重建任务、不返回旧成功，也不把目录缺失当成成功

#### Scenario: 重启后任务标识不复用

- **WHEN** Node 进程重启后为新清理生成 `task_id`
- **THEN** 新标识带新的进程纪元，和重启前任一旧标识都不相等

#### Scenario: 目录不存在不等于成功

- **WHEN** 查询一个从未登记或已淘汰的 `task_id`，而对应目录当前不存在
- **THEN** Node 返回 404 `not_found`，不生成成功任务，不写成功 oplog，也不据此补记已清理

#### Scenario: 不持久化任务状态

- **WHEN** 启动、查询、淘汰或重启清理任务
- **THEN** 不新增数据库表/列/JSON、不写持久队列、不新增 WSS topic/字段或推送

### Requirement: 异步删除子进程与关闭生命周期

清理后台 SHALL 直接以参数数组执行 `rm -rf`，不得经 shell，且 MUST NOT 设置固定删除超时；慢删除 SHALL 保持 `running` 直到子进程结束或 Node 关闭。成功只在退出码为 0 时成立；非零退出落 `failed`/`rm_failed`，启动或执行异常落 `failed`/`internal_error`。Linux 下 Node MUST 通过父死亡信号使删除子进程在 Node 被 `SIGKILL` 或异常终止后结束，并以父进程身份校验关闭启动竞态；正常关闭 MUST 拒绝新任务、终止并等待在跑子进程。中断与关闭 MUST NOT 写成成功，且可能留下部分删除目录。

#### Scenario: 退出码 0 才算成功

- **WHEN** 删除子进程以退出码 0 结束
- **THEN** 任务进入 `succeeded`，`error_reason=null`；这是异步清理唯一的成功路径

#### Scenario: 非零退出为失败

- **WHEN** 删除子进程以非零退出码结束
- **THEN** 任务进入 `failed`、`error_reason="rm_failed"`，不得返回成功，也不得把 stderr 放进状态响应

#### Scenario: 慢删除不被固定超时截断

- **WHEN** 异步删除运行超过 30 秒而 Node 仍存活
- **THEN** 任务保持 `running`，Node 不按固定超时终止子进程、不写 `failed`/`timeout`，状态查询仍返回正在运行

#### Scenario: 启动或执行异常落为失败

- **WHEN** 删除子进程无法启动，或后台执行发生未预期异常
- **THEN** 任务进入 `failed`、`error_reason="internal_error"`，不返回成功，也不留下永远 `running` 的记录

#### Scenario: Linux 强杀 Node 不遗留删除子进程

- **WHEN** Linux 上 Node 在异步删除运行中被 `SIGKILL` 或异常终止
- **THEN** 删除子进程由父死亡信号终止，不继续存活；任务结果随进程丢失为未知，绝不成为成功

#### Scenario: 父死亡信号启动竞态不启动 rm

- **WHEN** Node 在删除子进程完成父死亡信号设置前消失
- **THEN** 子进程核对父进程身份不符并直接退出，不执行 `rm`，也不遗留可继续删除的进程

#### Scenario: Node 关闭终止子进程

- **WHEN** Node 在异步删除运行中执行正常关闭
- **THEN** Node 终止并等待在跑子进程结束，不把该任务留成成功

#### Scenario: 关闭期间拒绝新任务

- **WHEN** Node 已进入正常关闭流程后又收到新的清理或恢复登记请求
- **THEN** Node 拒绝登记，不启动新的删除子进程，也不返回成功任务

#### Scenario: 部分删除不伪装成功

- **WHEN** 删除失败、Node 被强杀或关闭发生在目录已删除一部分之后
- **THEN** 任务仍为失败或丢失，Node 不检查“目录是否还存在”来改写成成功

### Requirement: 旧同步清理与旧客户端兼容

`POST /api/clean_mount` SHALL 保留既有请求体、同步语义、HTTP 200 成功体、30 秒超时和 400/500 错误形状；只有删除子进程退出码为 0 才返回 `success=1`。该端点 SHALL 接入同一路径规范化和互斥：同一规范化路径有活动清理或恢复占用时返回 409 且不执行删除，与异步任务不得并发删除同一路径。旧端点只用于旧客户端/旧调用方兼容；当前 Ctrl 的手动清理、定时清理和磁盘升级清理 SHALL 走新异步协议。Node MUST NOT 新增强制旧客户端迁移、定时器或持久队列。

#### Scenario: 旧同步成功保持原形状

- **WHEN** 旧客户端用合法路径调用 `/api/clean_mount` 且删除成功
- **THEN** Node 在删除完成后返回 HTTP 200 和 `{"success":1}`，不返回 `task_id` 或改变既有字段

#### Scenario: 旧同步错误保持可辨识

- **WHEN** 旧端点收到非法路径、删除超时或删除非零退出
- **THEN** 分别保持 400 `invalid_path`、500 `timeout`、500 `internal_error` 等既有失败语义，不返回成功

#### Scenario: 旧同步遇到活动任务返回冲突

- **WHEN** 同一路径已有异步清理或恢复预登记
- **THEN** 旧端点返回 409 和对应 `cleanup_in_progress` 或 `restore_in_progress`，不执行删除

#### Scenario: 两个旧同步请求不并发删除

- **WHEN** 两个旧客户端同时清理同一规范化路径
- **THEN** 只有第一个执行删除，另一个返回 409，不得两个 `rm` 同时运行

#### Scenario: 旧客户端继续使用同步端点

- **WHEN** 旧客户端或旧调用方继续同步调用旧端点且没有同路径活动占用
- **THEN** 请求仍按原成功/失败语义完成，不需要改用异步端点或新增持久状态

#### Scenario: 当前 Ctrl 三类清理走异步

- **WHEN** 当前 Ctrl 执行手动清理、定时清理或磁盘升级清理
- **THEN** Ctrl 使用 `start_clean_mount` 受理并按 `task_id` 轮询终态，不以旧同步端点作为这三类流程的实现路径；旧端点只为旧客户端保留

### Requirement: Ctrl/Web 受理、后台轮询与入口互斥

Web SHALL 在 Ctrl 接受清理请求后立即结束等待并展示清理中，不得同步等待删除完成。Ctrl SHALL 先建立进程内活动状态，在 Node 受理成功后向调用方返回已受理，不得等待终态；并以机器与路径为键在后台按有界间隔轮询 Node 状态。活动状态存在期间，Ctrl MUST 阻止同一机器同一路径的重复清理和恢复请求。Ctrl 的本地状态只用于入口互斥和展示，最终结果仍以 Node 任务结果为准；此协作 MUST NOT 新增数据库结构或持久工作流。本 Requirement 是跨仓协作契约；Ctrl/Web 行为不在本仓实现，Node 验收只覆盖任务事实与 409。

#### Scenario: Web 只等待受理

- **WHEN** 用户触发清理且 Ctrl 已受理
- **THEN** Web 收到受理结果并展示清理中，不等待 `rm` 结束或 Node 终态

#### Scenario: Ctrl 后台轮询

- **WHEN** Node 返回清理 `task_id`
- **THEN** Ctrl 在后台查询该任务状态，并据进程内状态在列表展示清理中

#### Scenario: Ctrl 阻止同路径重复操作

- **WHEN** Ctrl 的活动清理尚未终结，用户再次清理或恢复同一机器同一路径
- **THEN** Ctrl 在入口拒绝并保持原状态，不发起第二条 Node 清理或恢复请求

#### Scenario: Node 是规范化路径的最终门禁

- **WHEN** Ctrl 的路径键与 Node 的规范化结果不同而实际指向同一目录
- **THEN** Node 返回 409，Ctrl 不得把该冲突解释为成功或另起任务

#### Scenario: 不新增数据库或持久工作流

- **WHEN** 清理被受理、轮询或进入终态
- **THEN** Ctrl/Web 不新增表、列或 JSON 结构，不建立可跨重启恢复的持久任务

### Requirement: 清理成功、失败与未知落账边界

仅当同一 `task_id` 返回 `state="succeeded"` 时，Ctrl SHALL 在既有结构中标记已清理并写成功 oplog。`state="failed"` SHALL 写失败 oplog，MUST NOT 标记已清理。轮询超时、Node 重启、任务 404/失联或无法取得终态时，Ctrl SHALL 判为未知，MUST NOT 标记已清理或写成功 oplog；未知不改变目录可能已部分删除的事实。本 Requirement 的落账由 Ctrl/Web 实现，本仓验收只覆盖 Node 的 `succeeded`/`failed`/404 事实。

#### Scenario: 明确成功才标记已清理

- **WHEN** Ctrl 轮询到同一 `task_id` 的 `state="succeeded"`
- **THEN** Ctrl 标记已清理并写成功 oplog；受理成功、`running` 和目录缺失都不能触发这两项

#### Scenario: 明确失败只写失败 oplog

- **WHEN** Ctrl 轮询到同一 `task_id` 的 `state="failed"` 和非空原因
- **THEN** Ctrl 写失败 oplog，不标记已清理，不写成功 oplog

#### Scenario: 轮询超时为未知

- **WHEN** Ctrl 在自身有界轮询预算内没有取得终态
- **THEN** 状态变为未知，不标记已清理、不写成功 oplog，也不伪造成功任务

#### Scenario: Node 重启丢结果为未知

- **WHEN** 已受理任务在 Node 重启后查询返回 404 或连接不可用
- **THEN** Ctrl 判为未知，不根据目录是否存在补写成功，不写成功 oplog

#### Scenario: 失败可能部分删除

- **WHEN** Node 明确返回失败或结果未知
- **THEN** Ctrl/Web 将该目录视为可能部分删除，不得展示为已成功清理

### Requirement: Ctrl 重启与目录缺失的展示边界

Ctrl 重启 SHALL 允许丢失进程内轮询与活动状态，MUST NOT 从目录缺失、日志或旧记录补写成功或已清理时间。列表遇到目录不存在时 SHALL 正常返回和展示，不得把请求变成错误，也不得仅凭不存在推断清理成功。未知、失败或 Ctrl 重启后恢复入口 SHALL 重新开放；若 Node 仍持有活动锁，则以其 409 为最终判决。本 Requirement 的 Ctrl/Web 重启与展示行为不在本仓实现，Node 验收只覆盖 404/目录缺失不产生成功事实。

#### Scenario: Ctrl 重启不补成功

- **WHEN** Ctrl 在清理进行中重启
- **THEN** 旧轮询丢失，Ctrl 不恢复旧任务、不补写成功 oplog，也不把未确认目录标记为已清理

#### Scenario: 目录不存在正常显示

- **WHEN** 列表中的已删除容器目录当前不存在
- **THEN** 列表正常返回并展示该状态，不返回目录错误，也不自动写成功记录

#### Scenario: 恢复入口重新开放

- **WHEN** 清理为未知、失败或 Ctrl 已重启且没有本地活动状态
- **THEN** 恢复按钮重新可用，不因旧清理状态永久禁用

#### Scenario: Node 活动锁覆盖 Ctrl 丢失的状态

- **WHEN** Ctrl 已丢失本地清理状态但 Node 同路径任务仍在运行，用户发起恢复
- **THEN** Node 返回 409，Ctrl 保持未成功并提示操作仍在进行
