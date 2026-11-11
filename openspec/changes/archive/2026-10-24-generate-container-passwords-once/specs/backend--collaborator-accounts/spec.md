## MODIFIED Requirements

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

### Requirement: UpdateRoleConfig 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。

字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：本类型按源码字段、继承和调用方约束传递数据。新增两个可选 `SecretStr` 字段：

- `root_password`：仅当 `updated_role="root"` 时 MUST 必填并通过密码校验，用于设置共享 root 密码；admin/collaborator 携带时请求被拒绝。
- `password`：仅当 `updated_role="admin"` 时可携带，用于旧 ROOT 降 ADMIN 时为该 owner 创建/设置独立账号密码；root/collaborator 携带时请求被拒绝。

两者都 MUST NOT 引入旧 owner 角色、唯一所有者、自动扫描其他账号或修改请求目标之外的账号；Node 每次只处理请求指定的目标。Node 不解析绑定，调用方 MUST 保证 `password` 只在旧 ROOT 降 ADMIN 时携带，普通 ADMIN/COLLABORATOR 互换不得携带。

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

## ADDED Requirements

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

### Requirement: ROOT 提升/交接由 Ctrl 的 transfer_root 编排，Node 只处理单目标 [services/container_service.py]

ROOT 提升/交接的既有角色规则 SHALL 由 Ctrl API 的纯布尔 `transfer_root:false` 选择，Node 无该字段，仍只处理单目标 primitive。`transfer_root=false`（ContainerDetailPage 默认）只把目标提升/重置 root，返回 1 条凭据，MUST NOT 降旧 ROOT；`transfer_root=true`（Home/EditUserModal）Ctrl 才按原 Home 顺序对每个旧 ROOT 调 ADMIN、再目标调 ROOT，Node 逐次执行单目标。内部删除用户 ROOT 移交保持原单目标同步 primitive，不使用该编排。Node `update_role` MUST NOT 自动扫描、批量修改或推断其他账号；旧 ROOT ADMIN 用 `password` 建/设独立账号，目标 ROOT 用 `root_password` 设共享 root、按既有预期最终组状态清理、归档/删除目标原账号。Node MUST NOT 更新绑定；某步失败只返回该步失败，不回滚、不伪装完整成功。

#### Scenario: 按旧 ROOT 再目标的顺序执行

- **GIVEN** Ctrl 的 `transfer_root=true`，先调用旧 ROOT 的 ADMIN 请求，再调用目标的 ROOT 请求
- **WHEN** Node 分别处理两次请求
- **THEN** ADMIN 请求只创建/设置旧 owner 独立账号，ROOT 请求只设置共享 root 密码并处理目标原独立账号；两次调用不共享绑定状态

#### Scenario: transfer_root=false 只处理目标

- **GIVEN** ContainerDetailPage 默认 `transfer_root=false`，只请求目标 ROOT
- **WHEN** Node 处理该单目标请求
- **THEN** 只重置共享 root 密码并处理目标原独立账号，不降任何旧 ROOT；Ctrl/Web 只得到 1 条凭据；Node 请求体中没有 `transfer_root` 字段

#### Scenario: 历史多 ROOT 逐次处理

- **GIVEN** `transfer_root=true` 且容器历史上有多个 ROOT，Ctrl 按既有遍历对每个旧 ROOT 各调用一次 ADMIN，再调用目标 ROOT
- **WHEN** Node 分别处理 N+1 次请求
- **THEN** Node 每次只处理该次指定的旧 owner 或目标，不丢人、不合并、不篡改角色；Ctrl 返回所有涉及旧账号 + root 的凭据，数量可大于 2

#### Scenario: 目标不在 sudo/wheel 时幂等清理

- **GIVEN** 目标账号是 COLLABORATOR，不属于 sudo 或 wheel
- **WHEN** Node 执行 ROOT 分支的组清理
- **THEN** 两个组都不存在不视为失败，继续按既有规则归档/删除目标原独立账号并成功完成 ROOT 分支；最终组状态与角色结果不变

#### Scenario: 删除用户触发的 ROOT 转移同样带密码

- **GIVEN** Ctrl 的删除用户路径选择新 ROOT 并调用 Node，且不使用 `transfer_root` 编排
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

### AddCollaboratorResponse 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `success` | `int \| bool` | `Field(default=1)` |
| `decrypted_message` | `dict[str, Any]` | `必填`；不得含 `password` 或原始 `config` |

### UpdateRoleConfig 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `container_name` | `str` | `必填` |
| `user_name` | `str` | `必填` |
| `updated_role` | `UpdatedRole` | `必填` |
| `root_password` | `SecretStr \| None` | `None`；仅 `updated_role="root"` 时必填，其他角色必须缺省 |
| `password` | `SecretStr \| None` | `None`；仅 `updated_role="admin"` 时可携带，root/collaborator 必须缺省 |

### UpdateRoleResponse 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `success` | `int \| bool` | `Field(default=1)` |
| `decrypted_message` | `dict[str, Any]` | `必填`；不得含 `root_password`、`password` 或原始 `config` |
