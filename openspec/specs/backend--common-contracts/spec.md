# 公共协议

## Purpose

公共结果、错误形状和声明映射；类型校验、缺省和兼容行为由消费入口执行。本文件是 chester-next 33672c4edd96 在 2026-10-11 的代码逆向基线，按能力组织相关类型而非每个 class 单独建文件。完整字段、继承与兼容定义保留在下列 Requirements 中；跨能力使用以公共类型及源文件为准，已知问题集中于 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)。

## Requirements

### Requirement: EmptyConfig 数据契约 [schemas/common.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。

本类型没有独立声明字段；以别名、继承或上述职责为准。

系统 SHALL 保持以下已实现的职责：无声明字段的 Pydantic 配置对象，机器状态请求缺省构造 {}。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/common.py](../../../schemas/common.py)。

### Requirement: ApiErrorResponse 数据契约 [schemas/common.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：Node 错误字段名为 error，success 缺省 0；error_reason 为可空稳定原因码，不能按 Ctrl 的 message 字段推测响应。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/common.py](../../../schemas/common.py)。

### Requirement: SuccessResponse 数据契约 [schemas/common.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：公共 success 字段允许 int/bool；它是结果标记，不能替代 HTTP 状态和端点状态字段。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/common.py](../../../schemas/common.py)。

### Requirement: ErrorResponses 数据契约 [schemas/common.py]

系统 SHALL 按此类型的字段、成员和构造约定传递内部数据；该内部类型不自动构成一个公开 HTTP 请求端点。

本类型没有独立声明字段；以别名、继承或上述职责为准。

系统 SHALL 保持以下已实现的职责：公共错误响应声明映射，400 INVALID_JSON 和 500 INTERNAL_ERROR 使用 ApiErrorResponse；这是 OpenAPI 声明容器而不是请求 payload。

#### Scenario: 内部值传递

- **WHEN** 生产方构造并向消费方传递此数据类型
- **THEN** 成员名称和数据职责保持一致；运行配置只传配置值，证书数据只传文件引用



来源：[schemas/common.py](../../../schemas/common.py)。

## Data model appendix

### ApiErrorResponse 数据契约 [schemas/common.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `success` | `int \| bool` | `Field(default=0)` |
| `error` | `str` | `必填` |
| `error_reason` | `str \| None` | `None` |

### SuccessResponse 数据契约 [schemas/common.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `success` | `int \| bool` | `Field(default=1)` |

## Source references

- [schemas/common.py](../../../schemas/common.py)
- [tests/](../../../tests/)：默认套件 331 passed, 1 skipped, 16 deselected, 24 subtests passed；Docker 分项：旧用例 10 passed + 1 skipped、本变更专项 4 passed + 1 skipped；未合并重跑全量 `-m docker`。
