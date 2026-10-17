# Spec Delta

## MODIFIED Requirements

### Requirement: snapshot-disk-usage 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：type='snapshot'；topic='disk_usage'；payload 为 {machine_disk, containers:{name:usage}}；容器用量分别包含 overlay_rw_bytes/bind_mount_bytes/total_bytes、挂载路径和来源；读共享缓存，可能处于 measuring 或 cache 状态。usage SHALL 另含协议版本、Docker 对象与观测代际、双方目录身份、挂载验证状态、测量状态、真实测量时间、身份观测时间及原因；字段名和嵌套形状以 [design.md](../../design.md) 的 version 1 总表为准。重复推送 MUST NOT 刷新测量时间；无效测量 MUST 显式给出状态且不发布可供自动处置的 total_bytes；mismatch、unknown 或过期时 MUST NOT 用 bind_mount_bytes 冒充当前总量。HTTP 与 WSS SHALL 共用同一模型和校验。

#### Scenario: 读取磁盘快照

- **WHEN** 读取磁盘快照
- **THEN** 返回缓存和来源信息，不把缓存缺失、正在测量和实际零用量混为一谈

#### Scenario: 相同样本被多次推送

- **WHEN** WSS 在一个用量采集周期内多次推送同一测量结果
- **THEN** 保持该结果真实的测量时间，新的接收或发送时间不能把它变成新测量

#### Scenario: 先前有效但现在发生挂载错位

- **WHEN** 身份观测已经发现错位而上一次正常字节数仍保存在缓存中
- **THEN** 快照显式报告错位并令 total_bytes 无效，不能省略该条目而让消费方继续沿用正常结论

#### Scenario: 身份观测新鲜但测量过期

- **WHEN** `bind_identity.checked_at` 仍新鲜，但 `measured_at` 已超过测量最大年龄
- **THEN** `total_bytes` 为空且测量状态为 `stale`/`error`，身份观测时间不能延长测量有效期

#### Scenario: overlay 与 bind 完成时间不同

- **WHEN** overlay 与 bind 各自的完成时间不同
- **THEN** 合计样本的 `measured_at` 取较早者，不能用较晚完成时间或发送时间延长测量有效期

#### Scenario: 旧协议缺少身份字段

- **WHEN** 快照中的 usage 只有旧字段，没有协议版本、身份或真实测量时间
- **THEN** 消费方将其视为未验证并暂停自动磁盘处置，不能推断为 match，也不能用接收时间补齐测量时间

#### Scenario: 时间偏差过大或位于未来

- **WHEN** `measured_at` 或 `checked_at` 与 Ctrl 时钟偏差超过允许值，或时间位于未来
- **THEN** 样本标为 `clock_skew`/未验证并暂停自动处置，Ctrl 的接收时间不能替代真实测量时间

来源：[network/wss.py](../../../../../network/wss.py)。

## ADDED Requirements

### Requirement: 磁盘身份字段的精度与作用域

目录设备号、inode 及可能超出通用 JSON 精确整数范围的进程计数 SHALL 使用无损表示；身份必须关联链路机器、Node 观测会话、Docker 对象和进程代际。字段名和嵌套形状 SHALL 与 [design.md](../../design.md) 的 version 1 总表一致，MUST NOT 随意改名；Ctrl 的持久化列名可以不同，但必须无损保存线路字段。挂载 ID 只作命名空间内诊断，MUST NOT 作为永久目录或跨机身份。HTTP 磁盘用量查询与 WSS SHALL 复用相同的验证及时间语义。

#### Scenario: 大 inode 经通用 JSON 消费方转发

- **WHEN** inode 大于 2^53 且磁盘条目经过 JSON 编解码
- **THEN** 消费方仍得到完全相同的身份值，不能因数值舍入误判匹配

#### Scenario: 旧协议消费方逐步升级

- **WHEN** HTTP 响应模型或 WSS 消费方接收到新增身份字段
- **THEN** 新字段能被完整保留，新消费方将缺少协议版本的旧样本识别为未验证，不推断其已经匹配

#### Scenario: 未知协议版本

- **WHEN** 收到无法识别的 `disk_protocol_version`
- **THEN** 标记为未验证并保留原因，不用旧字节数恢复可信状态，也不把未知版本当作 version 1

#### Scenario: HTTP 与 WSS 返回同一测量

- **WHEN** 同一用量分别经 HTTP 手动查询和 WSS 快照返回
- **THEN** 身份、状态和 `measured_at` 保持一致，两处都不能用接收时间伪造新的测量时间

### Requirement: WSS 连接代际与磁盘观测排序

Node SHALL 为每个已认证 WSS 连接维护发布代际，并在新连接上先发送完整 version 1 观测；消费方在收到该观测前 MUST NOT 恢复可信状态。退役连接的待处理或晚到帧 MUST NOT 覆盖新连接；同一 collector epoch 内 observation_seq 较小的观测 MUST 被拒绝，相同序号的重复样本可作心跳但 MUST NOT 刷新 measured_at。连接代际只解决本连接的发布排序，不构成 Q70 的跨进程操作代际。

#### Scenario: 新连接尚未收到完整观测

- **WHEN** Ctrl 建立新连接，但尚未收到首个完整 version 1 磁盘观测
- **THEN** 该连接不恢复可信磁盘状态，旧连接的待处理数据也不能被当作新连接的证据

#### Scenario: 退役连接晚到帧

- **WHEN** 旧连接关闭后仍有其排队帧到达
- **THEN** 该帧被丢弃，不能覆盖新连接已接受的状态或测量时间

#### Scenario: 同 epoch 倒序与重复序号

- **WHEN** 同一 collector epoch 内先收到较大 observation_seq，随后收到较小或相同序号
- **THEN** 较小序号被拒绝；相同序号只作心跳，既不回退状态也不刷新 `measured_at`

#### Scenario: Node 重启后的新 epoch

- **WHEN** Node 重启产生新的 collector epoch
- **THEN** 新 epoch 必须提供完整有效测量，旧 epoch 的字节数不能被复用为当前值
