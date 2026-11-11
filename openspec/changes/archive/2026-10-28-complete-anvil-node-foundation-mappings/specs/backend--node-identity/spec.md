# Spec Delta

## MODIFIED Requirements

### Requirement: IssueNodeUidRequest 数据契约 [network/wss.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：Ctrl 首连确认后将 uid 作为 Node 应用身份牌写入身份文件；再次握手读取持久化身份。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[network/wss.py](../../../network/wss.py)。

### Requirement: NodeIdentity 数据契约 [network/wss.py]

系统 SHALL 按此类型的字段、成员和构造约定传递内部数据；该内部类型不自动构成一个公开 HTTP 请求端点。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：冻结 dataclass，只保存 Ctrl 颁发的 uid；身份文件路径可由 NODE_IDENTITY_FILE 覆盖；证书指纹从 TLS 层取得，不是 uid 的替代值。

#### Scenario: 内部值传递

- **WHEN** 生产方构造并向消费方传递此数据类型
- **THEN** 成员名称和数据职责保持一致；运行配置只传配置值，证书数据只传文件引用



来源：[network/wss.py](../../../network/wss.py)。

### Requirement: NodeCertificateFiles 数据契约 [network/wss.py]

系统 SHALL 按此类型的字段、成员和构造约定传递内部数据；该内部类型不自动构成一个公开 HTTP 请求端点。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：冻结 dataclass，cert_file/key_file 为文件 Path；仅记录路径契约，不在 SPEC 中保存证书私钥内容。

#### Scenario: 内部值传递

- **WHEN** 生产方构造并向消费方传递此数据类型
- **THEN** 成员名称和数据职责保持一致；运行配置只传配置值，证书数据只传文件引用



来源：[network/wss.py](../../../network/wss.py)。

### Requirement: NodeEnrollmentProfile 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：响应包含 uid（可空）、identity_initialized、snapshot_endpoint='/ws/ctrl'、hardware=静态硬件画像；该响应不包含证书指纹，Ctrl 必须从 TLS 层自行计算 SHA-256 指纹。

#### Scenario: Ctrl 查询 Node 首连资料

- **WHEN** Ctrl 查询 Node 首连资料
- **THEN** 取得应用身份状态、快照路径和硬件画像；证书指纹由 Ctrl 从 TLS 层单独计算，供信任锚注册和修复入口使用

来源：[network/wss.py](../../../network/wss.py)。
