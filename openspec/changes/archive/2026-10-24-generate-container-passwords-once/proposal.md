## Why

容器创建、新增协作者、恢复协作者、手动重置和 ROOT 交接目前都没有安全的“一次性随机密码”链路：Node 仍用 `<owner_name>123` / `<user_name>123` 一类固定密码，`add_collaborator`/`update_role`/`_run` 还会打印含密码的整条命令；Web 的 ROOT 交接是浏览器里先对旧 ROOT 调 `updateRole(ADMIN)`、再对目标调 `updateRole(ROOT)` 的多步编排，既无法一次返回全部凭据，也可能在中途失去权限。需要把密码生成留在 Ctrl、把系统账号设置留在 Node，并把既有角色结果与内部恢复/删除路径原样保留。

## What Changes

- **创建**：`POST /api/create_container` 新增顶层必填 `root_password: SecretStr`；Node 只用该值设置 root 密码，MUST NOT 回退 `<owner_name>123`。创建仍按现有 building/creating 受理并在后台执行；响应保持既有 `success`/`container_status`/`container_name`/`action_ref`，不返回密码。旧 Ctrl 不携带该字段时创建失败（fail closed）。
- **新增协作者**：`POST /api/add_collaborator` 的 `config` 新增必填 `password: SecretStr`，ADMIN 与 COLLABORATOR 一视同仁；Node 用该值设置新账号密码，MUST NOT 回退 `<user_name>123`。响应 `decrypted_message` 不得回显密码。Ctrl 受理后立即返回一条凭据并在后台执行；沿用既有 `ADD_COLLABORATOR` 审计，不新增密码 oplog 或重复日志。Node 端点仍按单次同步执行返回。
- **内部恢复/删除兼容**：`restore_accounts` 恢复协作者与删除用户触发的 ROOT 转移也由 Ctrl 生成随机密码并在 Node wire 中传入，不得回退弱密码；不改变既有恢复/删除业务规则和页面。`RestoreAccountConfig` 增加瞬时 `password`，MUST NOT 持久化到 snapshot/WSS/缓存/日志/响应。
- **手动重置**：新增 `POST /api/reset_container_password`，请求体 `{config:{container_name,user_name,password}}`；Node 同步用 stdin 执行 `chpasswd`，成功返回 `{"success":1}`，失败按现有 `error_reason` 词表映射 404/409/500 并返回脱敏错误，不返回、不记录密码。Ctrl 侧对应 `POST /api/containers/reset_container_password {container_id,user_id}`，登录名取绑定 username（ROOT 固定 `root`），操作码 `reset_container_password`；Ctrl 不拼原始错误体。
- **ROOT 交接/提升**：保留两个 Web 入口差异。Ctrl `update_role` 请求增加纯布尔 `transfer_root:false`（默认）；Home/EditUserModal 显式传 `true`，Ctrl 仅在 true 时按原 Home 顺序后台把每个旧 ROOT -> ADMIN，再目标 -> ROOT，返回所有涉及账号凭据（普通单旧 ROOT 2 项、历史多旧 ROOT 可 >2 项，不丢人、不为凑 2 项篡改角色）；ContainerDetailPage 默认 false，只把目标提升/重置 root 并返回 1 项，不偷偷降旧 ROOT。Node 无 `transfer_root` 字段，仍只处理单目标 primitive；内部删除用户触发的 ROOT 移交保持原单目标同步 primitive，不使用 Web 交接编排，避免副作用。ROOT 各步沿用 `UPDATE_COLLABORATOR_ROLE` 审计；某一步失败时如实保留已完成步骤，不伪报完整成功，不新增持久回滚工作流。
- **恢复入口**：Ctrl 实际恢复成功返回共享创建必需 root credential；Web DeletedContainers 最小复用 CredentialModal，`requires_choice` 不展示，不得出现恢复成功但密码丢失。恢复协作者的瞬时密码由 Ctrl 生成、Node 只消费，不写入 snapshot，不新增恢复队列/日志，不改恢复其他业务或页面布局。
- **普通角色切换**：非 ROOT 的 ADMIN/COLLABORATOR 互换保持既有成功响应，不生成、不改变密码，`credentials` 可为空；Node `update_role` 不得执行 `chpasswd`。ROOT 目标本不在 sudo/wheel 时按既有预期最终组状态做最小幂等判断，组不存在不算失败；角色最终结果、归档规则与普通角色行为不变。
- **安全执行面**：所有密码以 `SecretStr` 进入模型，通过 Docker exec 的 stdin 交给 `chpasswd`；命令 argv 仅含 `chpasswd`，不得用 shell `echo`、命令行参数、环境变量、临时文件传递明文。`add_collaborator` 与 `update_role` 的密码设置复用同一 helper，整条命令/输出不再打印密码。
- **响应与错误**：Node 不新增凭据响应或查回接口。422 脱敏仅作用于密码相关路由，其他路由保留既有默认形状，不重构全局错误处理；密码字段错误 `input` 不得回显。Web 凭据 API 去掉 secret 字段与 unsafe 原始 body，但保留安全 message（如资源超限数值），不能为脱敏丢失原有具体错误信息；DOM 只清除组件状态与引用、关闭后不可回看，不承诺 JS 字符串物理零化。异常、日志、WSS、status/action 缓存、Docker env/config/labels 均不得出现明文。所有凭据响应 MUST `Cache-Control: no-store`，Node 对含密码请求的响应同样设置。Node 不写 oplog；创建不额外记录，新增/ROOT 沿用既有审计码，手动重置用 `reset_container_password`；超时/未知结果不得伪装成 Node 确认成功。
- **明确不做**：不改表结构、模型持久化或迁移；不新增全局角色唯一约束、repo 原子双绑定函数、多步 ROOT 的 Node 自动扫描或持久回滚；不扩大到 ManageUser 平台用户密码重置；不新增持久队列、租约、自动重试或密码查回；本阶段只写 proposal/specs/design，不实现、不提交、不自审。

## Capabilities

### New Capabilities

- `backend--container-credentials`：Node 侧密码 `SecretStr`、stdin `chpasswd`、脱敏 422、`Cache-Control: no-store`、禁止明文进入 Docker/日志/WSS/缓存/错误响应，以及已受理任务不因客户端断开而取消的跨接口约束。

### Modified Capabilities

- `backend--container-creation`：`CreateContainerMessage` 增加顶层 `root_password`，`RestoreAccountConfig` 增加瞬时 `password`；定义创建/恢复时设置密码、禁止默认回退的行为。
- `backend--collaborator-accounts`：`AddCollaboratorConfig` 增加 `password`；`UpdateRoleConfig` 增加 ROOT 用 `root_password` 与旧 ROOT 降 ADMIN 建号用 `password`；新增重置密码接口；保留既有 ROOT 多步角色结果与单目标语义；响应不回显密码。

## Impact

- 拟改代码：`schemas/container.py`、`schemas/__init__.py`、`network/api.py`（仅密码路由 422 脱敏）、`services/container_service.py`，以及共享 stdin `chpasswd` helper；不重构全局错误处理，测试后续另行规划。
- 固定跨仓合同（已对齐，供 review 使用）：
  - 创建：Ctrl -> Node 顶层 `root_password`，`restore_accounts[].password` 瞬时；Ctrl -> Web `accepted:true` + 一条 `credentials`。
  - 新增协作者：Ctrl -> Node `config.password`；Ctrl -> Web `accepted:true` + 一条 `credentials`。
  - 手动重置：Ctrl API `{container_id,user_id}`；Ctrl -> Node `config.password`；oplog `reset_container_password`；Ctrl -> Web 一条 `credentials`；404/409/500 沿用现有 `error_reason`；资源/方法/机器三层守卫 UI 与后端一致。
  - ROOT 交接/提升：Ctrl API 增加纯布尔 `transfer_root:false`；Home/EditUserModal 显式 true，Ctrl 才按原 Home 顺序逐次调用 Node（旧 ROOT -> ADMIN 用 `config.password`，目标 -> ROOT 用 `config.root_password`），返回所有涉及账号凭据（正常 2、历史多旧 ROOT >2，不丢人、不篡改角色）；ContainerDetailPage 默认 false，只提升目标/重置 root 并返回 1 条，不降旧 ROOT。Node 无 `transfer_root` 字段，只处理单目标；内部删除用户 ROOT 移交保持原单目标同步 primitive。
  - 恢复：Ctrl 实际恢复成功返回 root credential（共享创建必需）；Web DeletedContainers 最小复用 CredentialModal，`requires_choice` 不展示；恢复协作者瞬时密码由 Ctrl 生成、Node 消费，不存 snapshot，不新增恢复队列/日志。
  - 权限快照：Ctrl 新增派生非持久 `container_resource_unrestricted = has_resource_wildcard(uid,"container")`；Web 不得把方法通配当资源通配。此字段不落库。
  - 审计：创建只原 CREATE 日志，不额外记录；新增只沿用 `ADD_COLLABORATOR`；ROOT 各步沿用 `UPDATE_COLLABORATOR_ROLE`；手动重置用 `reset_container_password`；不得增加重复密码日志；超时/未知结果不得伪装成 Node 确认成功。
  - Guards：主机/容器状态 guard 在受理前完成；后台只做最小既有 guard 二次核对；不新增 DTO 或持久状态；受理表示进程内任务已启动，不承诺跨重启持久完成。
  - UI/Web：只详情页有手动重置入口；新增/角色密码弹窗覆盖 Home、EditUserModal、详情等现有入口；Web 只渲染凭据数组；凭据 API 去掉 secret 字段与 unsafe 原始 body 但保留安全 message（资源超限数值等）；DOM 清状态/引用、关闭不可回看，不承诺 JS 字符串物理零化。
  - 所有凭据响应 `Cache-Control: no-store`。
- 兼容性：旧 Ctrl 的创建/恢复/新增/ROOT/ADMIN 请求缺少新密码字段会收到 422/400 并 fail closed；Ctrl 内部 `restore_accounts` 与删除用户 ROOT 转移必须在同一变更内生成并传入密码。
- 已知风险：Node 的 socket helper 主要由本地 FakeDocker 验证，不宣称真实生产验证；多步 ROOT 交接后续步骤失败或超时时只保留实际完成状态，不新增持久回滚。
- 不涉及：数据库、持久化队列、邮件、RBAC 规则本身；不新增全局角色唯一约束、repo 原子双绑定函数、持久队列/租约/迁移；Ctrl 权限守卫、后台编排与 Web 弹窗由各自仓库处理。
