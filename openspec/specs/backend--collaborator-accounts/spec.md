# 协作账号

## Purpose

添加移除平台协作者、修改角色和恢复账户；线路角色映射到运行层 ROLE。本文件是 chester-next 33672c4edd96 在 2026-10-11 的代码逆向基线，按能力组织相关类型而非每个 class 单独建文件。完整字段、继承与兼容定义保留在下列 Requirements 中；跨能力使用以公共类型及源文件为准，已知问题集中于 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)。

## Requirements

### Requirement: AddCollaboratorConfig 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。

字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：本类型按源码字段、继承和调用方约束传递数据。新增必填 `password: SecretStr`：对 ADMIN 与 COLLABORATOR 都 MUST 由 Ctrl 生成并在请求中提供，Node 只用于设置新账号密码，MUST NOT 回退 `<user_name>123`。该字段 MUST NOT 进入响应、日志、异常或 Docker 配置。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例

#### Scenario: 新增协作者携带 Ctrl 密码

- **GIVEN** `role` 为 admin 或 collaborator，且 `password` 为合法 `SecretStr`
- **WHEN** Node 解析 `AddCollaboratorConfig`
- **THEN** 模型接受请求，repr 与 `model_dump()` 只出现掩码；服务层可读取明文用于 stdin

#### Scenario: 新增协作者缺少 password

- **GIVEN** 请求未提供 `config.password`
- **WHEN** Node 校验请求
- **THEN** 返回脱敏 422，不创建账号，不回退到 `<user_name>123`

#### Scenario: 新增协作者密码非法

- **GIVEN** `password` 为空、超长、含冒号或控制字符
- **WHEN** Node 校验请求
- **THEN** 返回 422，响应、日志与异常均不出现密码原值，不执行账号创建

来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: AddCollaboratorMessage 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点请求外层对象，嵌套 config 使用对应配置类型；FastAPI 在进入操作服务前执行 Pydantic 请求校验。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: AddCollaboratorResponse 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。

字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点响应继承公共 success 或操作受理字段，response_model 输出该类型声明的数据。成功响应中的 `decrypted_message` MUST NOT 包含 `password`、掩码密码字段或原始 `config`；只保留 `container_name`、`user_name`、`role` 等可公开字段。失败响应 MUST NOT 回显密码。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例

#### Scenario: 新增协作者成功响应脱敏

- **GIVEN** 一次成功的新增协作者请求携带 `password`
- **WHEN** Node 返回 `AddCollaboratorResponse`
- **THEN** `success` 为真，`decrypted_message` 只含容器名、用户名与角色，不含密码或掩码密码字段

#### Scenario: 新增协作者失败响应脱敏

- **GIVEN** 账号创建或 `chpasswd` 失败
- **WHEN** Node 返回错误响应
- **THEN** 错误体、日志与异常均不含 `password` 或 stdin 内容

来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: RemoveCollaboratorConfig 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：本类型按源码字段、继承和调用方约束传递数据。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: RemoveCollaboratorMessage 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点请求外层对象，嵌套 config 使用对应配置类型；FastAPI 在进入操作服务前执行 Pydantic 请求校验。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: RemoveCollaboratorResponse 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点响应继承公共 success 或操作受理字段，response_model 输出该类型声明的数据。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: UpdateRoleConfig 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。

字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：本类型按源码字段、继承和调用方约束传递数据。新增两个可选 `SecretStr` 字段：`root_password` 仅在 `updated_role="root"` 时必填并通过密码校验，用于设置共享 root 密码，admin/collaborator 携带时拒绝；`password` 仅在 `updated_role="admin"` 时可携带，用于旧 ROOT 降 ADMIN 时建/设独立账号密码，root/collaborator 携带时拒绝。两者 MUST NOT 引入旧 owner 角色、唯一所有者、自动扫描其他账号或修改目标之外账号；Node 每次只处理指定目标，不解析绑定；`password` 只在旧 ROOT 降 ADMIN 时携带，普通 ADMIN/COLLABORATOR 互换不得携带。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例

#### Scenario: ROOT 目标携带 root_password

- **GIVEN** `updated_role="root"` 且 `root_password` 为合法 `SecretStr`
- **WHEN** Node 解析 `UpdateRoleConfig`
- **THEN** 模型接受请求，repr 与 `model_dump()` 只出现掩码；服务层可读取明文用于 stdin

#### Scenario: ROOT 目标缺少 root_password

- **GIVEN** `updated_role="root"` 但未提供 `root_password`
- **WHEN** Node 校验请求
- **THEN** 返回脱敏 422，不调用更新角色服务，不回退到 `<user_name>123`

#### Scenario: 旧 ROOT 降 ADMIN 携带 password

- **GIVEN** `updated_role="admin"` 且 `password` 为合法 `SecretStr`
- **WHEN** Node 解析 `UpdateRoleConfig`
- **THEN** 模型接受请求，repr 与 `model_dump()` 只出现掩码；服务层可读取明文用于该 owner 独立账号的创建/设置

#### Scenario: 普通 ADMIN 切换可缺省 password

- **GIVEN** `updated_role="admin"` 且未提供 `password`
- **WHEN** Node 解析 `UpdateRoleConfig`
- **THEN** 模型接受请求；服务层不得据此创建带默认密码的账号，也不得改变既有账号密码

#### Scenario: 普通角色携带 root_password 或 collaborator 携带 password

- **GIVEN** `updated_role` 为 admin/collaborator 但请求含 `root_password`，或 `updated_role="collaborator"` 但请求含 `password`
- **WHEN** Node 校验请求
- **THEN** 返回脱敏 422；普通 ADMIN/COLLABORATOR 互换不得携带或改变密码

#### Scenario: 密码字段非法

- **GIVEN** `root_password` 或 `password` 为空、超长、含冒号或控制字符
- **WHEN** Node 校验请求
- **THEN** 返回 422，响应、日志与异常均不出现密码原值，也不调用更新角色服务

来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: UpdateRoleMessage 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点请求外层对象，嵌套 config 使用对应配置类型；FastAPI 在进入操作服务前执行 Pydantic 请求校验。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: UpdateRoleResponse 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。

字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：端点响应继承公共 success 或操作受理字段，response_model 输出该类型声明的数据。ROOT 或旧 ROOT 降 ADMIN 的成功响应中，`decrypted_message` MUST NOT 包含 `root_password`、`password`、掩码密码或原始 `config`；普通 ADMIN/COLLABORATOR 切换保持既有 `decrypted_message` 形状。失败响应 MUST NOT 回显密码。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例

#### Scenario: 普通角色切换保持既有响应

- **GIVEN** 一次成功的非 ROOT ADMIN/COLLABORATOR 切换且未携带密码
- **WHEN** Node 返回 `UpdateRoleResponse`
- **THEN** 仍返回 `success` 与既有 `decrypted_message`，不新增密码字段或 `credentials`

#### Scenario: ROOT 与旧 ROOT 降 ADMIN 响应脱敏

- **GIVEN** 一次成功的 ROOT 目标请求携带 `root_password`，或一次成功的旧 ROOT 降 ADMIN 请求携带 `password`
- **WHEN** Node 返回 `UpdateRoleResponse`
- **THEN** `success` 为真，`decrypted_message` 只含可公开的容器名、目标用户名和角色，不含密码或掩码密码字段

#### Scenario: 失败响应不回显密码

- **GIVEN** ROOT 或 ADMIN 请求因命令失败或校验失败被拒绝
- **WHEN** Node 返回错误响应
- **THEN** 错误体、日志与异常均不含密码或 stdin 内容

来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: CollaboratorRole 数据契约 [schemas/container.py]

生产方和消费方 SHALL 遵守 `Literal['admin', 'collaborator']` 的定义，不增加未声明的 Literal 值或将兼容别名解释为新协议。

定义：`Literal['admin', 'collaborator']`。

本类型没有独立声明字段；以别名、继承或上述职责为准。

系统 SHALL 保持以下已实现的职责：线路值域或兼容类型别名，消费方保持其已声明的成员与指向类型。

#### Scenario: 使用声明值域

- **WHEN** 生产者序列化此别名所代表的数据
- **THEN** 值域或数据形状保持与上述 Literal/目标类型一致



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: UpdatedRole 数据契约 [schemas/container.py]

生产方和消费方 SHALL 遵守 `Literal['admin', 'collaborator', 'root']` 的定义，不增加未声明的 Literal 值或将兼容别名解释为新协议。

定义：`Literal['admin', 'collaborator', 'root']`。

本类型没有独立声明字段；以别名、继承或上述职责为准。

系统 SHALL 保持以下已实现的职责：线路值域或兼容类型别名，消费方保持其已声明的成员与指向类型。

#### Scenario: 使用声明值域

- **WHEN** 生产者序列化此别名所代表的数据
- **THEN** 值域或数据形状保持与上述 Literal/目标类型一致



来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: ROLE 数据契约 [constant.py]

系统 SHALL 按此类型的字段、成员和构造约定传递内部数据；该内部类型不自动构成一个公开 HTTP 请求端点。


字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：运行层枚举，与 schemas 中的 Literal 线路状态集分别维护；不能因名称相同把两者当作同一类型。

#### Scenario: 内部值传递

- **WHEN** 生产方构造并向消费方传递此数据类型
- **THEN** 成员名称和数据职责保持一致；运行配置只传配置值，证书数据只传文件引用



来源：[constant.py](../../../constant.py)。

### Requirement: 恢复重建账号时修正家目录属主 [services/container_service.py]

创建/恢复请求携带 `restore_accounts` 时，Node SHALL 在容器建立后逐个重建账号，并按 `role` 决定是否附加管理员组；任一条目重建失败 SHALL 使本次创建按失败处理。

账号的家目录 SHALL 位于持久化挂载之内，从而随挂载数据一并取回；重建时 SHALL 把家目录属主修正为新建账号，MUST NOT 假定镜像为该账号分配的标识与删除前一致。

#### Scenario: 按恢复清单重建账号

- **WHEN** 创建/恢复请求携带 `restore_accounts` 清单
- **THEN** Node 对每个条目重建账号，条目重建失败则本次创建判为失败

#### Scenario: 属主随账号重建被修正

- **WHEN** 账号被重建，且镜像分配的标识与删除前不同
- **THEN** 该账号对其家目录可读写

#### Scenario: 家目录数据随挂载取回

- **WHEN** 恢复一个协作者家目录已位于持久化挂载之内、且该目录留有文件的容器
- **THEN** 这些文件在恢复后的容器中可见

来源：[services/container_service.py](../../../services/container_service.py)、[network/api.py](../../../network/api.py)。

### Requirement: 新增协作者使用 Ctrl 下发的随机密码 [services/container_service.py]

Node SHALL 在 `/api/add_collaborator` 流程中使用 `AddCollaboratorConfig.password` 设置新账号密码；ADMIN 与 COLLABORATOR 同样处理，MUST NOT 使用 `<user_name>123` 或任何缺省密码。账号家目录 MUST 保持在 `/root/.collaborators` 持久化挂载模式，ADMIN 继续加入 sudo/wheel 之一。密码设置失败 SHALL 使本次新增失败；成功响应不得回显密码。Node 不写 oplog；Ctrl 沿用既有 `ADD_COLLABORATOR` 审计，不为密码新增独立 oplog 或重复日志。

#### Scenario: 新增 ADMIN 或 COLLABORATOR 使用下发密码

- **GIVEN** 请求携带合法 `password`，目标账号尚不存在
- **WHEN** Node 执行新增协作者
- **THEN** 账号按既有目录模式创建，密码通过 stdin `chpasswd` 设置，ADMIN 加入管理组、COLLABORATOR 不加；命令与日志不含密码

#### Scenario: 缺少 password 时不回退默认

- **GIVEN** 新增协作者请求没有 `password`
- **WHEN** Node 校验或执行
- **THEN** 请求被 422 拒绝，不创建账号，不回退到 `<user_name>123`

#### Scenario: 密码设置失败不伪装成功

- **GIVEN** `chpasswd` 非 0 或 exec 失败
- **WHEN** Node 执行新增协作者
- **THEN** 返回失败，不返回 `success:1`，错误、日志与响应不含密码，也不回退默认密码

来源：[services/container_service.py](../../../services/container_service.py)、[network/api.py](../../../network/api.py)。

### Requirement: 旧 ROOT 降 ADMIN 时按 Ctrl 密码创建独立账号 [services/container_service.py]

当 `updated_role="admin"` 且请求携带 `password` 时，Node SHALL 确保 `user_name` 对应的独立账号存在：不存在时按既有持久化目录模式创建，存在时不重复建号；随后用 stdin `chpasswd` 设置该密码，并确保其加入 sudo/wheel 之一。该调用 MUST NOT 改变共享 root 密码、MUST NOT 创建或修改其他账号。未携带 `password` 时，Node MUST NOT 用默认密码创建缺失账号，也 MUST NOT 改变既有账号密码；账号已存在时只执行既有 ADMIN 组调整，账号不存在时返回失败。

#### Scenario: 旧 ROOT 降 ADMIN 创建独立账号

- **GIVEN** `updated_role="admin"`、`password` 合法，且该 owner 的系统用户名账号不存在
- **WHEN** Node 执行 ADMIN 分支
- **THEN** Node 创建该账号、通过 stdin 设置该密码、加入管理组，共享 root 密码保持不变

#### Scenario: 旧 ROOT 降 ADMIN 已有独立账号

- **GIVEN** 该 owner 的独立账号已存在且请求携带 `password`
- **WHEN** Node 执行 ADMIN 分支
- **THEN** Node 用 stdin 更新该账号密码并确保管理组，不重复建号，不修改 root 密码

#### Scenario: 普通 ADMIN 切换不改密码

- **GIVEN** `updated_role="admin"`、账号已存在且未携带 `password`
- **WHEN** Node 执行 ADMIN 分支
- **THEN** 只执行既有管理组调整，不执行 `chpasswd`，不改密码

#### Scenario: 普通 ADMIN 切换缺少账号且无密码

- **GIVEN** `updated_role="admin"`、账号不存在且未携带 `password`
- **WHEN** Node 执行 ADMIN 分支
- **THEN** 返回失败，不创建带默认密码的账号，不回退 `<user_name>123`

来源：[services/container_service.py](../../../services/container_service.py)。

### Requirement: ROOT 交接由 Ctrl 统一编排，Node 只处理单目标 [services/container_service.py]

外部 ROOT 上位 SHALL 由 Ctrl 统一编排：先对该容器其他旧 ROOT 逐个调用 ADMIN，全部成功后再对目标调用 ROOT，使目标成为唯一 ROOT。Web 不选择单目标旁路；Ctrl 对旧客户端的 `transfer_root` 兼容输入 SHALL 忽略其值，Node 无该字段。Node 每次只处理单目标账号操作。内部删除用户 ROOT 移交保持既有同步步骤。Node MUST NOT 自动扫描或修改其他账号；旧 ROOT ADMIN 用 `password` 建/设独立账号，目标 ROOT 用 `root_password` 设共享 root、按既有预期组状态清理、归档/删除目标原账号。Node MUST NOT 更新绑定；失败不回滚、不伪装成功。正常交接由 Ctrl 返回 root 与原所有者独立账号的两项凭据，Node 响应不回传密码。

#### Scenario: 按旧 ROOT 再目标的顺序执行

- **GIVEN** Ctrl 统一交接先调用旧 ROOT 的 ADMIN 请求，成功后再调用目标的 ROOT 请求
- **WHEN** Node 分别处理两次请求
- **THEN** ADMIN 请求只创建/设置旧 owner 独立账号，ROOT 请求只设置共享 root 密码并处理目标原独立账号；两次调用不共享绑定状态

#### Scenario: 单次 Node 请求只处理指定账号

- **GIVEN** Ctrl 已完成旧 ROOT 降级，发出目标 ROOT 请求
- **WHEN** Node 处理该次请求
- **THEN** 只重置共享 root 密码并处理目标原独立账号，不再次扫描或修改旧 ROOT；Node 请求体中没有 `transfer_root` 字段，此单次执行不代表 Ctrl 可以省略完整交接

#### Scenario: 历史多 ROOT 逐次处理

- **GIVEN** 容器历史上有多个 ROOT，Ctrl 按既有遍历对每个旧 ROOT 各调用一次 ADMIN，全部成功后再调用目标 ROOT
- **WHEN** Node 分别处理 N+1 次请求
- **THEN** Node 每次只处理该次指定的旧 owner 或目标，不丢人、不合并、不篡改角色；Ctrl 返回所有涉及旧账号 + root 的凭据，数量可大于 2

#### Scenario: 目标不在 sudo/wheel 时幂等清理

- **GIVEN** 目标账号是 COLLABORATOR，不属于 sudo 或 wheel
- **WHEN** Node 执行 ROOT 分支的组清理
- **THEN** 两个组都不存在不视为失败，继续按既有规则归档/删除目标原独立账号并成功完成 ROOT 分支；最终组状态与角色结果不变

#### Scenario: 删除用户触发的 ROOT 转移同样带密码

- **GIVEN** Ctrl 的删除用户路径按既有同步步骤选择新 ROOT 并调用 Node
- **WHEN** 请求未携带 `root_password`
- **THEN** Node 返回脱敏 422，不执行 ROOT 分支，不回退 `<user_name>123`；Ctrl 必须为该内部单目标同步 primitive 生成并传入密码

#### Scenario: Node 不扫描其他账号

- **GIVEN** 容器里存在多个 ROOT/ADMIN/COLLABORATOR 账号
- **WHEN** Node 处理一次 `update_role` 请求
- **THEN** 只对请求的 `user_name`（以及 ROOT 分支必然涉及的 root 和目标原账号）执行命令，不列出、不修改其他账号

#### Scenario: 第二步失败不回滚第一步

- **GIVEN** 旧 ROOT 的 ADMIN 调用已成功，目标的 ROOT 调用随后失败
- **WHEN** Node 返回第二次调用的失败结果
- **THEN** Node 不回滚已创建的旧 owner 独立账号，不返回完整成功；错误与日志不含密码，Ctrl 以实际完成步骤写 oplog

#### Scenario: 普通 ADMIN/COLLABORATOR 互换仍不改密码

- **GIVEN** 一次非 ROOT 的 ADMIN/COLLABORATOR 互换请求，未携带密码
- **WHEN** Node 执行更新角色
- **THEN** 沿用既有成功响应与角色命令，不调用 `chpasswd`，不改变任何账号密码

来源：[services/container_service.py](../../../services/container_service.py)、[network/api.py](../../../network/api.py)。

### Requirement: 重置容器账号密码 [network/api.py]

Node SHALL 提供 `POST /api/reset_container_password`，请求体为 `{config:{container_name,user_name,password}}`，其中 `password` 为 `SecretStr`；Node SHALL 在返回前同步通过 stdin `chpasswd` 设置该账号密码，成功响应仅 `{"success":1}`。Node MUST 直接使用请求给出的绑定登录名（ROOT 为 `root`），MUST NOT 从展示名或 `owner_name` 推导。失败 SHALL 使用现有 `error_reason` 词表中的 404/409/500 映射与固定脱敏错误体，MUST NOT 含密码、stdin、原始输出或拼接命令；Ctrl 不得把原始错误体拼进用户文案。Node MUST NOT 持久化密码、提供查回、自动重试或因客户端断开取消已开始的 `chpasswd`。

#### Scenario: 重置普通账号成功

- **GIVEN** 容器在线且目标绑定登录名存在
- **WHEN** Ctrl 请求重置该账号密码
- **THEN** Node 通过 stdin 向 `chpasswd` 写入 `login_name:password`，命令 argv 不含密码，退出码 0 后返回 `{"success":1}`

#### Scenario: 重置 root 成功

- **GIVEN** 目标登录名为 `root`
- **WHEN** Ctrl 请求重置 root 密码
- **THEN** Node 用同一 stdin 路径设置共享 root 密码并只返回 `{"success":1}`

#### Scenario: 容器不存在

- **GIVEN** `container_name` 在本机不存在
- **WHEN** 请求重置密码
- **THEN** 返回 404、`error_reason="not_found"`，不执行 `chpasswd`，不记录密码

#### Scenario: 容器未运行

- **GIVEN** 容器存在但状态不是 running
- **WHEN** 请求重置密码
- **THEN** 返回 409、`error_reason="container_not_running"`，不执行 `chpasswd`，不记录密码

#### Scenario: 容器内账号不存在

- **GIVEN** 容器在线但 `user_name` 在容器内不存在
- **WHEN** `chpasswd` 返回非 0
- **THEN** 返回 500、`error_reason="reset_failed"`，错误体与日志不含密码或原始输出

#### Scenario: 非法登录名或密码

- **GIVEN** `user_name` 含非法字符，或 `password` 为空、超长、含冒号或控制字符
- **WHEN** Node 校验请求
- **THEN** 返回脱敏 422，不执行 `chpasswd`，响应与日志不含密码原值

#### Scenario: 客户端断开不取消

- **GIVEN** 请求已进入同步 `chpasswd` 执行
- **WHEN** 客户端连接断开
- **THEN** Node 继续执行到 `chpasswd` 结束，不基于断开取消、不自动重试、不伪造成功；响应可无法送达

来源：[network/api.py](../../../network/api.py)、[services/container_service.py](../../../services/container_service.py)。

## Data model appendix

### AddCollaboratorConfig 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `container_name` | `str` | `必填` |
| `user_name` | `str` | `必填` |
| `role` | `CollaboratorRole` | `必填` |
| `password` | `SecretStr` | `必填`；长度 8–128，不含 `:`、CR、LF、NUL；仅用于 stdin `chpasswd` |

### AddCollaboratorMessage 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `config` | `AddCollaboratorConfig` | `必填` |

### AddCollaboratorResponse 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `success` | `int \| bool` | `Field(default=1)` |
| `decrypted_message` | `dict[str, Any]` | `必填`；不得含 `password` 或原始 `config` |

### RemoveCollaboratorConfig 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `container_name` | `str` | `必填` |
| `user_name` | `str` | `必填` |

### RemoveCollaboratorMessage 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `config` | `RemoveCollaboratorConfig` | `必填` |

### RemoveCollaboratorResponse 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `success` | `int \| bool` | `Field(default=1)` |

### UpdateRoleConfig 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `container_name` | `str` | `必填` |
| `user_name` | `str` | `必填` |
| `updated_role` | `UpdatedRole` | `必填` |
| `root_password` | `SecretStr \| None` | `None`；仅 `updated_role="root"` 时必填，其他角色必须缺省 |
| `password` | `SecretStr \| None` | `None`；仅 `updated_role="admin"` 时可携带，root/collaborator 必须缺省 |

### UpdateRoleMessage 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `config` | `UpdateRoleConfig` | `必填` |

### UpdateRoleResponse 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `success` | `int \| bool` | `Field(default=1)` |
| `decrypted_message` | `dict[str, Any]` | `必填`；不得含 `root_password`、`password` 或原始 `config` |

### ROLE 数据契约 [constant.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `ADMIN` | `'admin'` | `类成员` |
| `COLLABORATOR` | `'collaborator'` | `类成员` |
| `ROOT` | `'root'` | `类成员` |

## Source references

- [constant.py](../../../constant.py)
- [schemas/container.py](../../../schemas/container.py)
- [services/container_service.py](../../../services/container_service.py)
- [network/api.py](../../../network/api.py)
- [tests/](../../../tests/)：默认套件 331 passed, 1 skipped, 16 deselected, 24 subtests passed；Docker 分项：旧用例 10 passed + 1 skipped、本变更专项 4 passed + 1 skipped；未合并重跑全量 `-m docker`。

## 安全标识收敛记录（2026-10-24）

- `UpdateRoleConfig` 的 `container_name`/`user_name` 复用安全标识校验：仅允许 ASCII 字母、数字、下划线、连字符，禁止空值、前导 `-`、shell 元字符与路径穿越；非法值在请求校验阶段返回脱敏 422，不触发 Docker lookup 或容器命令。
- 非 ROOT `updated_role` 且 `user_name="root"` 在请求校验阶段拒绝；`updated_role="root"` 指定 `user_name="root"` 仍由服务层既有校验拒绝。`update_role` 服务入口在 Docker lookup 前重复同一标识/root 目标约束，直接调用亦不留 Docker 副作用。
- 不改变角色业务、单账号 primitive、密码字段规则或其他账号扫描范围。2026-10-24 复验：对抗 60 passed；相关 80 passed；Node 默认安全全量 508 passed, 16 deselected, 24 subtests passed。