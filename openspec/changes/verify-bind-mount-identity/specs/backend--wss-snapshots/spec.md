# Spec Delta

## MODIFIED Requirements

### Requirement: snapshot-disk-usage 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：type='snapshot'；topic='disk_usage'；payload 为 {machine_disk, containers:{name:usage}}；容器用量包含既有字节/路径/来源字段，以及 path 诊断和测量会话字段：version 1、collector_epoch、observation_seq、configured_mount_path、bind_mount_path（业务路径）、mount_path_status、mount_path_observed_at、measurement_status、measured_at、measurement_mount_path、measurement_reason。MUST NOT 携带目录对象/PID/identity 门禁字段。mount_path_status 是诊断，不得作为 total 有效性或 Ctrl 业务门禁；已存在有效业务路径且同路径测量成功时，unresolved 不使测量变 error。旧 Node 缺 measured_at/measurement_mount_path 或采样排序时按测量未验证；重复推送/接收时间不得刷新真实 measured_at；total 无效时不得用 bind_mount_bytes 冒充当前值。HTTP 与 WSS 共用同一模型和校验。

#### Scenario: 读取磁盘快照

- **WHEN** 读取磁盘快照
- **THEN** 返回缓存、业务路径、路径诊断、真实测量时间和测量状态，不把缓存缺失、正在测量和实际零用量混为一谈

#### Scenario: 路径 unresolved 但同路径测量有效

- **WHEN** mount_path_status=unresolved，而既有业务 bind_mount_path 未变、measurement_mount_path 与之一致、measurement_status=ok 且 measured_at 未过期
- **THEN** total_bytes 保持有效；路径诊断不阻断业务，也不改写为 measurement_error

#### Scenario: 路径变更后的旧样本

- **WHEN** 业务 bind_mount_path 已从 A 改为 B，而缓存中用量的 measurement_mount_path 仍为 A
- **THEN** 该旧样本不得作为 B 的 total，必须按 B 重新测量；快照可显示旧值仅作诊断

#### Scenario: 旧协议缺少真实测量时间

- **WHEN** 旧 Node 的 usage 缺少 measured_at 或 measurement_mount_path
- **THEN** 消费方按测量未验证处理，不能推断缺少目录身份，也不能用接收时间补齐测量时间

#### Scenario: 无 bind 与 overlay-only

- **WHEN** Docker 成功确认无 `/root` bind，且 overlay 测量有效
- **THEN** bind_mount_path=null、measurement_mount_path=null、mount_path_status=no_bind，total 可按明确 no_bind 的 overlay 规则有效；Ctrl 接收端清空当前活跃业务 bind 路径，不能保留旧路径再判同路径；异常不得被当成 no_bind

#### Scenario: unresolved 不清空路径

- **WHEN** 路径核对为 unresolved/not_running，或 Docker inspect/Source 诊断不可读
- **THEN** 保留已有 bind_mount_path 与 measurement_mount_path；只有明确 no_bind 才置空

#### Scenario: 相同样本被多次推送

- **WHEN** WSS 在一个测量周期内多次推送同一结果
- **THEN** 保持该结果真实的 measured_at，新的发送/接收时间不能把它变成新测量

来源：[network/wss.py](../../../../../network/wss.py)。

## ADDED Requirements

### Requirement: 路径诊断与测量字段作用域

`configured_mount_path` SHALL 只表示 Docker Source 诊断；`bind_mount_path` 表示业务路径并由 Node 在确认后返回修正值；`mount_path_status` 为 resolved/unresolved/not_running/no_bind（缺省 unresolved）；`mount_path_observed_at` 为真实路径核对时间；`measurement_mount_path` 为实际测量使用的业务路径；`measured_at` 为合计真实测量时间。目录 dev/inode/PID MUST NOT 作为 HTTP/WSS 字段、长期资格/冻结/删除/清理门禁或测量有效性前置。HTTP 与 WSS 复用同一字段语义，`null` 字段不得被 response model/JSON 静默丢弃。

#### Scenario: 路径诊断字段缺失

- **WHEN** 旧 Node 缺 configured_mount_path/mount_path_status/mount_path_observed_at
- **THEN** 按 configured_mount_path=null、mount_path_status=unresolved、observed_at=null 处理；已有业务 bind_mount_path 仍可使用，不推断新的目录身份

#### Scenario: 测量字段缺失

- **WHEN** 旧 Node 缺 measured_at、measurement_mount_path 或 collector_epoch/observation_seq 采样排序
- **THEN** measurement_status 按未验证；不推断目录身份，不用接收时间补齐

#### Scenario: HTTP 与 WSS 一致

- **WHEN** 同一用量分别经 HTTP 手动查询和 WSS 快照返回
- **THEN** bind_mount_path、configured_mount_path、mount_path_status、measured_at、measurement_mount_path 和 measurement_status 保持一致

#### Scenario: 路径纠正只体现为业务路径

- **WHEN** 消费方检查 WSS/HTTP usage 中的路径信息
- **THEN** 业务路径由 bind_mount_path 表达，Source 诊断由 configured_mount_path 表达，路径核对结果由 mount_path_status/mount_path_observed_at 表达；不依赖目录对象编号或 PID 身份

### Requirement: WSS 连接代际与磁盘观测排序

Node SHALL 为每个已认证 WSS 连接维护发布代际，并在新连接上先发送完整 version 1 观测；消费方在收到该观测前 MUST NOT 恢复可信测量。退役连接的待处理或晚到帧 MUST NOT 覆盖新连接；同一 collector_epoch 内 observation_seq 较小的观测 MUST 被拒绝，相同序号的重复样本可作心跳但 MUST NOT 刷新 measured_at。连接代际与采样会话只解决发布/采样排序，不是目录身份或 Q70 跨进程操作代际。

#### Scenario: 新连接尚未收到完整观测

- **WHEN** Ctrl 建立新连接，但尚未收到首个完整 version 1 磁盘观测
- **THEN** 该连接不恢复可信磁盘状态，旧连接的待处理数据也不能被当作新连接的证据

#### Scenario: 退役连接晚到帧

- **WHEN** 旧连接关闭后仍有其排队帧到达
- **THEN** 该帧被丢弃，不能覆盖新连接已接受的状态或测量时间

#### Scenario: 同 epoch 倒序与重复序号

- **WHEN** 同一 collector_epoch 内先收到较大 observation_seq，随后收到较小或相同序号
- **THEN** 较小序号被拒绝；相同序号只作心跳，既不回退状态也不刷新 measured_at

#### Scenario: Node 重启后的新 epoch

- **WHEN** Node 重启产生新的 collector_epoch
- **THEN** 新 epoch 必须提供完整有效测量，旧 epoch 的字节数不能复用为当前值
