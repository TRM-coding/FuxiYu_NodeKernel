# Spec Delta

## MODIFIED Requirements

### Requirement: snapshot-disk-usage 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：type='snapshot'；topic='disk_usage'；payload 为 {machine_disk, containers:{name:usage}}；容器用量包含既有字节/路径/来源字段，以及业务路径控制字段 `mount_path_status` 与真实测量时间 `measured_at`。MUST NOT 携带目录对象/PID/identity 门禁字段，MUST NOT 新增 `disk_protocol_version`、`collector_epoch`、`observation_seq`、`measurement_status`、`measurement_mount_path`、`measurement_reason`、`configured_mount_path` 或 `mount_path_observed_at`。`mount_path_status` 是路径修正/保留/清空的控制信号，不得作为 total 有效性或 Ctrl 业务门禁；已存在有效业务路径且同路径测量成功时，unresolved 不使测量变错误。旧 Node 缺 measured_at 时由消费方按既有接收时间兼容或未验证处理；重复推送/读取时间不得刷新真实 measured_at；total 无效时不得用 bind_mount_bytes 冒充当前值。HTTP 与 WSS 共用同一模型和校验。

#### Scenario: 读取磁盘快照

- **WHEN** 读取磁盘快照
- **THEN** 返回缓存、业务路径、路径控制状态和真实测量时间，不把缓存缺失、正在测量和实际零用量混为一谈

#### Scenario: 路径 unresolved 但同路径测量有效

- **WHEN** mount_path_status=unresolved，而既有业务 bind_mount_path 未变、测量成功且 measured_at 为真实测量时间
- **THEN** total_bytes 保持有效；路径诊断不阻断业务，也不改写为测量失败

#### Scenario: 路径变更后的旧样本

- **WHEN** 业务 bind_mount_path 已从 A 改为 B，而缓存中用量的 bind 字节仍来自 A
- **THEN** 该旧样本不得作为 B 的 total，必须按 B 重新测量；快照可显示旧值仅作诊断

#### Scenario: 旧协议缺少真实测量时间

- **WHEN** 旧 Node 的 usage 缺少 measured_at
- **THEN** 消费方按既有接收时间兼容或未验证处理，不能推断缺少目录身份，也不能把接收时间补齐为真实测量时间

#### Scenario: 无 bind 与 overlay-only

- **WHEN** Docker 成功确认无 `/root` bind，且 overlay 测量有效
- **THEN** bind_mount_path=null、mount_path_status=no_bind，total 可按明确 no_bind 的 overlay 规则有效；Ctrl 接收端清空当前活跃业务 bind 路径，不能保留旧路径再判同路径；异常不得被当成 no_bind

#### Scenario: unresolved 不清空路径

- **WHEN** 路径核对为 unresolved/not_running，或 Docker inspect/Source 诊断不可读
- **THEN** 保留已有 bind_mount_path；只有明确 no_bind 才置空

#### Scenario: 相同样本被多次推送

- **WHEN** WSS 在一个测量周期内多次推送同一结果
- **THEN** 保持该结果真实的 measured_at，新的发送/接收时间不能把它变成新测量

## ADDED Requirements

### Requirement: 路径控制与测量字段作用域

`bind_mount_path` SHALL 表示业务路径并由 Node 在确认后返回修正值；`mount_path_status` 为 resolved/unresolved/not_running/no_bind（缺省 unresolved），只用于消费方决定更新/保留/清空，不是业务门禁；`measured_at` 为合计真实测量时间，取 overlay/bind 完成时间中较早者。目录 dev/inode/PID MUST NOT 作为 HTTP/WSS 字段、长期资格/冻结/删除/清理门禁或测量有效性前置。HTTP 与 WSS 复用同一字段语义，`null` 字段不得被 response model/JSON 静默丢弃。`configured_mount_path`、`mount_path_observed_at` 只留在 Node 内部日志/调试，不进入线路。

#### Scenario: 路径控制字段缺失

- **WHEN** 旧 Node 缺 mount_path_status
- **THEN** 按 unresolved 处理；已有业务 bind_mount_path 仍可使用，不推断新的目录身份，也不改写已校正路径

#### Scenario: 测量字段缺失

- **WHEN** 旧 Node 缺 measured_at
- **THEN** 消费方按既有接收时间兼容或未验证处理；不推断目录身份，不把接收时间冒充真实测量时间

#### Scenario: HTTP 与 WSS 一致

- **WHEN** 同一用量分别经 HTTP 手动查询和 WSS 快照返回
- **THEN** bind_mount_path、mount_path_status、measured_at 和字节字段保持一致

#### Scenario: 路径纠正只体现为业务路径

- **WHEN** 消费方检查 WSS/HTTP usage 中的路径信息
- **THEN** 业务路径由 bind_mount_path 表达，路径修正/保留/清空由 mount_path_status 表达；不依赖目录对象编号、PID、configured_mount_path 或 observed_at
