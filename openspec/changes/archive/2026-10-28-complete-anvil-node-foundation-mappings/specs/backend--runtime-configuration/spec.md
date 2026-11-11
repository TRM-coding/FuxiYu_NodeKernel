# Spec Delta

## MODIFIED Requirements

### Requirement: NetConfig 数据契约 [config.py]

系统 SHALL 按此类型的字段、成员和构造约定传递内部数据；该内部类型不自动构成一个公开 HTTP 请求端点。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：Node 只知道自己的监听端口 NODE_PORT，Ctrl 主动拨入 /ws/ctrl；不要求 Node 配置 Ctrl 地址。

#### Scenario: 内部值传递

- **WHEN** 生产方构造并向消费方传递此数据类型
- **THEN** 成员名称和数据职责保持一致；运行配置只传配置值，证书数据只传文件引用



来源：[config.py](../../../config.py)。

### Requirement: PortConfig 数据契约 [config.py]

系统 SHALL 按此类型的字段、成员和构造约定传递内部数据；该内部类型不自动构成一个公开 HTTP 请求端点。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端口范围由 NODE_PORT_RANGE_START/END 控制，缺省 20000–29999；选择和显式 Docker 绑定由 port_allocator 负责。

#### Scenario: 内部值传递

- **WHEN** 生产方构造并向消费方传递此数据类型
- **THEN** 成员名称和数据职责保持一致；运行配置只传配置值，证书数据只传文件引用



来源：[config.py](../../../config.py)。

### Requirement: KeyConfig 数据契约 [config.py]

系统 SHALL 按此类型的字段、成员和构造约定传递内部数据；该内部类型不自动构成一个公开 HTTP 请求端点。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：历史 RSA 文件名配置，记录配置键及来源即可，不复制密钥；是否仍被运行入口消费在 Global 问题清单中核查。

#### Scenario: 内部值传递

- **WHEN** 生产方构造并向消费方传递此数据类型
- **THEN** 成员名称和数据职责保持一致；运行配置只传配置值，证书数据只传文件引用



来源：[config.py](../../../config.py)。

### Requirement: AppConfig 数据契约 [config.py]

系统 SHALL 按此类型的字段、成员和构造约定传递内部数据；该内部类型不自动构成一个公开 HTTP 请求端点。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：继承 KeyConfig 的运行配置，从环境变量覆写路径与 SECRET_KEY；SPEC 不记录任何实际凭据值。

#### Scenario: 内部值传递

- **WHEN** 生产方构造并向消费方传递此数据类型
- **THEN** 成员名称和数据职责保持一致；运行配置只传配置值，证书数据只传文件引用



来源：[config.py](../../../config.py)。
