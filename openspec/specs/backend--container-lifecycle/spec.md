# 容器生命周期

## Purpose

容器名称查询、启停、重启、暂停解冻、删除及状态查询；统一异步受理与最终观测。本文件是 chester-next 33672c4edd96 在 2026-10-11 的代码逆向基线，按能力组织相关类型而非每个 class 单独建文件。完整字段、继承与兼容定义保留在下列 Requirements 中；跨能力使用以公共类型及源文件为准，已知问题集中于 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)。

## Requirements

### Requirement: ContainerNameConfig 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：优先使用 container_name，name 为历史兼容别名；两个字段可空，由端点检查空名称并返回 missing_container_name。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: ContainerOperationAcceptedResponse 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：success、container_name 和过渡 container_status 描述已受理操作，最终结果由状态快照确认。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: ContainerStatusMessage 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点请求外层对象，嵌套 config 使用对应配置类型；FastAPI 在进入操作服务前执行 Pydantic 请求校验。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: ContainerStatusResponse 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：读 pending/build/cache 状态及运行指标；失败保留 error_reason/failed_reason/failed_detail，cache_updated_at 为缓存时间。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: ContainerLastSshTimeMessage 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点请求外层对象，嵌套 config 使用对应配置类型；FastAPI 在进入操作服务前执行 Pydantic 请求校验。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: ContainerLastSshTimeResponse 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：单容器 SSH 时间返回字符串；全量 WSS last_ssh 快照允许 None，Ctrl 没有新观察时保留旧值。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: MachineStatusMessage 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点请求外层对象，嵌套 config 使用对应配置类型；FastAPI 在进入操作服务前执行 Pydantic 请求校验。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: MachineStatusResponse 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点响应继承公共 success 或操作受理字段，response_model 输出该类型声明的数据。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: RemoveContainerMessage 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点请求外层对象，嵌套 config 使用对应配置类型；FastAPI 在进入操作服务前执行 Pydantic 请求校验。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: RemoveContainerResponse 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点响应继承公共 success 或操作受理字段，response_model 输出该类型声明的数据。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: StartContainerMessage 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点请求外层对象，嵌套 config 使用对应配置类型；FastAPI 在进入操作服务前执行 Pydantic 请求校验。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: StartContainerResponse 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点响应继承公共 success 或操作受理字段，response_model 输出该类型声明的数据。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: StopContainerMessage 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点请求外层对象，嵌套 config 使用对应配置类型；FastAPI 在进入操作服务前执行 Pydantic 请求校验。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: StopContainerResponse 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点响应继承公共 success 或操作受理字段，response_model 输出该类型声明的数据。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: RestartContainerMessage 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点请求外层对象，嵌套 config 使用对应配置类型；FastAPI 在进入操作服务前执行 Pydantic 请求校验。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: RestartContainerResponse 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点响应继承公共 success 或操作受理字段，response_model 输出该类型声明的数据。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: PauseContainerConfig 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：action 仅 pause/unpause，缺省 pause；对外对应 pausing/unpausing 受理态，再由 Docker 状态收敛为 paused/online。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: PauseContainerMessage 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点请求外层对象，嵌套 config 使用对应配置类型；FastAPI 在进入操作服务前执行 Pydantic 请求校验。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: PauseContainerResponse 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点响应继承公共 success 或操作受理字段，response_model 输出该类型声明的数据。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: ContainerStatus 数据契约 [schemas/container.py]

生产方和消费方 SHALL 遵守 `Literal['building', 'creating', 'starting', 'stopping', 'restarting', 'pausing', 'unpausing', 'ready_check', 'online', 'offline', 'paused', 'failed', 'unknown']` 的定义，不增加未声明的 Literal 值或将兼容别名解释为新协议。

定义：`Literal['building', 'creating', 'starting', 'stopping', 'restarting', 'pausing', 'unpausing', 'ready_check', 'online', 'offline', 'paused', 'failed', 'unknown']`。

本类型没有独立声明字段；以别名、继承或上述职责为准。

系统 SHALL 保持以下已实现的职责：线路值域或兼容类型别名，消费方保持其已声明的成员与指向类型。

#### Scenario: 使用声明值域

- **WHEN** 生产者序列化此别名所代表的数据
- **THEN** 值域或数据形状保持与上述 Literal/目标类型一致



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: PauseAction 数据契约 [schemas/container.py]

生产方和消费方 SHALL 遵守 `Literal['pause', 'unpause']` 的定义，不增加未声明的 Literal 值或将兼容别名解释为新协议。

定义：`Literal['pause', 'unpause']`。

本类型没有独立声明字段；以别名、继承或上述职责为准。

系统 SHALL 保持以下已实现的职责：线路值域或兼容类型别名，消费方保持其已声明的成员与指向类型。

#### Scenario: 使用声明值域

- **WHEN** 生产者序列化此别名所代表的数据
- **THEN** 值域或数据形状保持与上述 Literal/目标类型一致



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: ContainerNameMessage 数据契约 [schemas/container.py]

生产方和消费方 SHALL 遵守 `ContainerStatusMessage` 的定义，不增加未声明的 Literal 值或将兼容别名解释为新协议。

定义：`ContainerStatusMessage`。

本类型没有独立声明字段；以别名、继承或上述职责为准。

系统 SHALL 保持以下已实现的职责：线路值域或兼容类型别名，消费方保持其已声明的成员与指向类型。

#### Scenario: 使用声明值域

- **WHEN** 生产者序列化此别名所代表的数据
- **THEN** 值域或数据形状保持与上述 Literal/目标类型一致



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: LastSshTimeResponse 数据契约 [schemas/container.py]

生产方和消费方 SHALL 遵守 `ContainerLastSshTimeResponse` 的定义，不增加未声明的 Literal 值或将兼容别名解释为新协议。

定义：`ContainerLastSshTimeResponse`。

本类型没有独立声明字段；以别名、继承或上述职责为准。

系统 SHALL 保持以下已实现的职责：线路值域或兼容类型别名，消费方保持其已声明的成员与指向类型。

#### Scenario: 使用声明值域

- **WHEN** 生产者序列化此别名所代表的数据
- **THEN** 值域或数据形状保持与上述 Literal/目标类型一致



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: MachineStatus 数据契约 [constant.py]

系统 SHALL 按此类型的字段、成员和构造约定传递内部数据；该内部类型不自动构成一个公开 HTTP 请求端点。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：运行层枚举，与 schemas 中的 Literal 线路状态集分别维护；不能因名称相同把两者当作同一类型。

#### Scenario: 内部值传递

- **WHEN** 生产方构造并向消费方传递此数据类型
- **THEN** 成员名称和数据职责保持一致；运行配置只传配置值，证书数据只传文件引用



来源：[constant.py](../../../constant.py)。

### Requirement: MachineTypes 数据契约 [constant.py]

系统 SHALL 按此类型的字段、成员和构造约定传递内部数据；该内部类型不自动构成一个公开 HTTP 请求端点。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：运行层枚举，与 schemas 中的 Literal 线路状态集分别维护；不能因名称相同把两者当作同一类型。

#### Scenario: 内部值传递

- **WHEN** 生产方构造并向消费方传递此数据类型
- **THEN** 成员名称和数据职责保持一致；运行配置只传配置值，证书数据只传文件引用



来源：[constant.py](../../../constant.py)。

### Requirement: ContainerStatus 数据契约 [constant.py]

系统 SHALL 按此类型的字段、成员和构造约定传递内部数据；该内部类型不自动构成一个公开 HTTP 请求端点。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：运行层枚举，与 schemas 中的 Literal 线路状态集分别维护；不能因名称相同把两者当作同一类型。

#### Scenario: 内部值传递

- **WHEN** 生产方构造并向消费方传递此数据类型
- **THEN** 成员名称和数据职责保持一致；运行配置只传配置值，证书数据只传文件引用



来源：[constant.py](../../../constant.py)。

### Requirement: RemoveContinaerReturn 数据契约 [services/container_service.py]

系统 SHALL 按此类型的字段、成员和构造约定传递内部数据；该内部类型不自动构成一个公开 HTTP 请求端点。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：历史结果码容器，SUCCESS=0、NOTFOUND=1、FAILED=2；拼写保留为既有类型名，是否存在消费需以调用搜索核对。

#### Scenario: 内部值传递

- **WHEN** 生产方构造并向消费方传递此数据类型
- **THEN** 成员名称和数据职责保持一致；运行配置只传配置值，证书数据只传文件引用



来源：[services/container_service.py](../../../services/container_service.py)。

## Data model appendix

### ContainerNameConfig 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `container_name` | `str \| None` | `None` |
| `name` | `str \| None` | `Field(default=None, description='Backward-compatible alias for container_name')` |

### ContainerOperationAcceptedResponse 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `success` | `int \| bool` | `Field(default=1)` |
| `container_status` | `ContainerStatus` | `必填` |
| `container_name` | `str` | `必填` |

### ContainerStatusMessage 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `config` | `ContainerNameConfig` | `必填` |

### ContainerStatusResponse 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `success` | `int \| bool` | `Field(default=1)` |
| `container_status` | `ContainerStatus` | `必填` |
| `container_name` | `str` | `必填` |
| `cache_updated_at` | `str \| None` | `None` |
| `error` | `str \| None` | `None` |
| `error_reason` | `str \| None` | `None` |
| `failed_reason` | `str \| None` | `None` |
| `failed_detail` | `str \| None` | `None` |
| `runtime_metrics` | `dict[str, Any] \| None` | `None` |

### ContainerLastSshTimeMessage 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `config` | `ContainerNameConfig` | `必填` |

### ContainerLastSshTimeResponse 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `success` | `int \| bool` | `Field(default=1)` |
| `container_name` | `str` | `必填` |
| `last_ssh_connect_time` | `str` | `必填` |

### MachineStatusMessage 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `config` | `EmptyConfig` | `Field(default_factory=EmptyConfig)` |

### MachineStatusResponse 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `success` | `int \| bool` | `Field(default=1)` |
| `machine_status` | `Literal['online']` | `必填` |

### RemoveContainerMessage 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `config` | `ContainerNameConfig` | `必填` |

### RemoveContainerResponse 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `success` | `int \| bool` | `Field(default=1)` |

### StartContainerMessage 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `config` | `ContainerNameConfig` | `必填` |

### StartContainerResponse 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `success` | `int \| bool` | `Field(default=1)` |
| `container_status` | `ContainerStatus` | `必填` |
| `container_name` | `str` | `必填` |

### StopContainerMessage 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `config` | `ContainerNameConfig` | `必填` |

### StopContainerResponse 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `success` | `int \| bool` | `Field(default=1)` |
| `container_status` | `ContainerStatus` | `必填` |
| `container_name` | `str` | `必填` |

### RestartContainerMessage 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `config` | `ContainerNameConfig` | `必填` |

### RestartContainerResponse 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `success` | `int \| bool` | `Field(default=1)` |
| `container_status` | `ContainerStatus` | `必填` |
| `container_name` | `str` | `必填` |

### PauseContainerConfig 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `container_name` | `str` | `必填` |
| `action` | `PauseAction` | `'pause'` |

### PauseContainerMessage 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `config` | `PauseContainerConfig` | `必填` |

### PauseContainerResponse 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `success` | `int \| bool` | `Field(default=1)` |
| `container_status` | `ContainerStatus` | `必填` |
| `container_name` | `str` | `必填` |

### MachineStatus 数据契约 [constant.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `ONLINE` | `'online'` | `类成员` |
| `OFFLINE` | `'offline'` | `类成员` |
| `MAINTENANCE` | `'maintenance'` | `类成员` |

### MachineTypes 数据契约 [constant.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `GPU` | `'GPU'` | `类成员` |
| `CPU` | `'CPU'` | `类成员` |

### ContainerStatus 数据契约 [constant.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `ONLINE` | `'online'` | `类成员` |
| `OFFLINE` | `'offline'` | `类成员` |
| `BUILDING` | `'building'` | `类成员` |
| `CREATING` | `'creating'` | `类成员` |
| `STARTING` | `'starting'` | `类成员` |
| `RESTARTING` | `'restarting'` | `类成员` |
| `STOPPING` | `'stopping'` | `类成员` |
| `FAILED` | `'failed'` | `类成员` |
| `PAUSED` | `'paused'` | `类成员` |
| `UNKNOWN` | `'unknown'` | `类成员` |

### RemoveContinaerReturn 数据契约 [services/container_service.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `SUCCESS` | `0` | `类成员` |
| `NOTFOUND` | `1` | `类成员` |
| `FAILED` | `2` | `类成员` |

## Source references

- [constant.py](../../../constant.py)
- [schemas/container.py](../../../schemas/container.py)
- [services/container_service.py](../../../services/container_service.py)
- [tests/](../../../tests/)：Linux 安全默认套件 152 passed、11 deselected；未运行 Docker 集成测试。
