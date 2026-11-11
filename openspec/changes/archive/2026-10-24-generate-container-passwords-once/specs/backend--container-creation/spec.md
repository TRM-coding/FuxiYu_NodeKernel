## MODIFIED Requirements

### Requirement: CreateContainerMessage 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。

字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：创建请求携带 owner_name、config、可选镜像构建内容和恢复挂载/账号；入口登记 building/creating 后立即受理，Docker 工作在后台线程执行。新增顶层必填 `root_password: SecretStr`：Node SHALL 只用该值设置 root 密码，MUST NOT 以 `<owner_name>123` 或任何缺省值替代；该字段 MUST NOT 放入 `config`、Docker environment/config/labels、WSS/action 缓存、日志或异常。缺失或非法时请求在进入后台前被拒绝，并返回不含明文与原始请求体的脱敏 422。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例

#### Scenario: 创建请求携带 root_password

- **GIVEN** 请求带顶层 `root_password` 为合法 `SecretStr`
- **WHEN** Node 解析 `CreateContainerMessage`
- **THEN** 模型保存该 `SecretStr`，其 repr、`model_dump()` 与 JSON 序列化只出现掩码，后台任务可读取明文用于 stdin

#### Scenario: 缺少 root_password

- **GIVEN** 请求没有顶层 `root_password`
- **WHEN** Node 校验创建请求
- **THEN** 返回脱敏 422，未登记 building/creating，不执行 Docker 创建，也不回退到 `<owner_name>123`

#### Scenario: root_password 非法

- **GIVEN** `root_password` 为空、超长、含冒号或控制字符
- **WHEN** Node 校验创建请求
- **THEN** 返回 422，响应、日志与异常均不出现该密码原值，创建未被受理

来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: RestoreAccountConfig 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。

字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：恢复协作者账号只接受 admin/collaborator，ROOT 由 owner_name 单独恢复；公开 SSH 公钥只用于安装，不记录私钥。新增必填瞬时 `password: SecretStr`：Ctrl 为每个恢复协作者生成随机密码并在创建请求中传入，Node 只用于重建账号时通过 stdin 设置密码，MUST NOT 回退 `<user_name>123`。该密码 MUST NOT 写入 snapshot、WSS、status/action 缓存、日志、异常或响应；恢复/删除用户的既有业务规则和页面不因本字段改变。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例

#### Scenario: 恢复协作者携带瞬时密码

- **GIVEN** `restore_accounts` 中某项带合法 `password: SecretStr`
- **WHEN** Node 解析创建请求并重建该协作者
- **THEN** 账号按既有恢复规则重建，密码通过 stdin `chpasswd` 设置；密码不进入 snapshot/WSS/action 缓存/日志/响应

#### Scenario: 恢复协作者缺少 password

- **GIVEN** `restore_accounts` 中某项没有 `password`
- **WHEN** Node 校验创建请求
- **THEN** 返回脱敏 422，创建未被受理，不执行恢复，不回退 `<user_name>123`

#### Scenario: 恢复密码设置失败

- **GIVEN** 恢复协作者账号创建或 `chpasswd` 失败
- **WHEN** 后台创建处理该错误
- **THEN** 本次创建按既有恢复失败规则处理，错误与日志不含密码，不写入 snapshot

来源：[schemas/container.py](../../../schemas/container.py)。

## ADDED Requirements

### Requirement: 创建时由 Ctrl 下发的密码设置 root 账号 [services/container_service.py]

Node SHALL 在既有创建后台任务中，用请求携带的 `root_password` 通过 stdin `chpasswd` 设置 root 密码；MUST NOT 使用 `<owner_name>123`、空密码或任何缺省值。设置失败 SHALL 使本次创建按失败处理，不伪装成功。Node MUST NOT 为密码设置新增第二条创建审计或日志；既有创建受理日志保留且不得包含密码。创建响应 MUST NOT 携带密码或 `credentials`。

#### Scenario: 用下发密码设置 root

- **GIVEN** 创建请求携带合法 `root_password`
- **WHEN** 后台创建执行到 root 密码步骤
- **THEN** `chpasswd` 通过 stdin 收到 `root:<root_password>`，命令 argv 不含密码；设置成功后才继续既有 sshd 守门

#### Scenario: 密码设置失败时不回退

- **GIVEN** `chpasswd` 退出码非 0 或 exec 失败
- **WHEN** 后台创建处理该错误
- **THEN** 本次创建判为失败，不尝试 `<owner_name>123`，错误与日志不含密码

#### Scenario: 创建响应不携带凭据

- **GIVEN** 创建请求已受理
- **WHEN** Node 返回 building/creating 响应
- **THEN** 响应仍只有 `success`、`container_status`、`container_name`、`action_ref`，不含 `root_password` 或 `credentials`

#### Scenario: 既有创建日志不重复

- **GIVEN** 一次使用新密码字段的创建完成
- **WHEN** 检查 Node 日志
- **THEN** 仍只有既有受理/后台/服务完成日志，没有新增的密码或凭据日志条目，也没有明文

来源：[services/container_service.py](../../../services/container_service.py)、[network/api.py](../../../network/api.py)。

## Data model appendix

### CreateContainerMessage 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `owner_name` | `str` | `必填` |
| `config` | `ContainerConfig` | `必填` |
| `root_password` | `SecretStr` | `必填`；长度 8–128，不含 `:`、CR、LF、NUL；仅用于 stdin `chpasswd` |
| `public_key` | `str \| None` | `Field(default=None, description='Optional SSH public key installed into root authorized_keys')` |
| `image_build` | `ImageBuildConfig \| None` | `None` |
| `restore_mount_path` | `str \| None` | `Field(default=None, description='Existing host mount path reused during container resurrection')` |
| `restore_accounts` | `list[RestoreAccountConfig]` | `Field(default_factory=list)` |

### RestoreAccountConfig 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `user_name` | `str` | `必填` |
| `role` | `CollaboratorRole` | `'collaborator'` |
| `password` | `SecretStr` | `必填`；瞬时值，长度 8–128，不含 `:`、CR、LF、NUL；仅用于 stdin `chpasswd`，不得持久化到 snapshot |
