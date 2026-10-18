# Spec Delta

## MODIFIED Requirements

### Requirement: CreateContainerResponse 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。

字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：仅表示创建已受理，状态为 building 或 creating；端口和挂载路径稍后由快照同步，成功受理不等同容器已 online。新增可选 `action_ref: ActionRef | None`，新 Node 对成功受理的创建 MUST 在响应前分配并输出，旧 Node 可以缺失。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例

#### Scenario: 创建受理返回动作引用

- **WHEN** 创建请求已被受理并返回 building/creating
- **THEN** 响应包含本进程分配的 `action_ref`，其 generation 与本次 create 使用的对象代际一致，seq 为同代本地动作序号；旧 Node 缺字段时新 Ctrl 按缺失降级
