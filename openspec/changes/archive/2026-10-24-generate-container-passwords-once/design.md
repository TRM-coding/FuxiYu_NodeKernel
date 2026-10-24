## Context

Node 当前在 `services/container_service.py` 的创建流程里执行 `echo 'root:{owner_name}123' | chpasswd`，`add_collaborator`/`update_role` 也把 `<user_name>123` 拼进 shell 命令并 `print` 整条命令；`_run` 同样打印完整命令与输出。Docker exec 目前使用高层 `container.exec_run(...)`，而 docker-py 的 `exec_run` 虽然接受 `stdin=True`，却没有写入 stdin 的参数，不能靠它安全传递密码。

Web 现有 ROOT 交接是 `src/components/EditUserModal.jsx:126-145` 的两步编排：先对旧 ROOT 调用 `updateRole(ADMIN)`，再对目标调用 `updateRole(ROOT)`。本变更沿用这一既有角色结果，只把编排从浏览器移入 Ctrl 后台，保留“旧 ROOT -> ADMIN、目标 -> ROOT”的顺序和最终角色；Node 的 `update_role` 仍只处理请求指定的目标，不自动扫描、不批量改其他账号。旧 ROOT 降 ADMIN 时要为其系统用户名创建独立账号并给 Ctrl 随机密码；目标升 ROOT 时重置永远存在的共享 root 账号为另一个 Ctrl 随机密码。

本次是 Node 侧合同与安全边界定义，不实现、不提交、不自审，不写 review/test-plan/tasks。Ctrl 负责随机密码、权限守卫、两步编排、绑定更新与 oplog；Web 负责一次性弹窗；Node 只接收并执行密码，不返回凭据。

## Goals / Non-Goals

**Goals:**

- 创建接收 Ctrl 生成的顶层 `root_password`，只用它设置 root 密码，绝不回退 `<owner_name>123`。
- 新增协作者（ADMIN 与 COLLABORATOR）接收 Ctrl 生成的 `config.password`，只用它设置新账号密码，绝不回退 `<user_name>123`。
- 手动重置新增同步接口，按绑定登录名设置密码，成功只回 `{"success":1}`。
- ROOT 交接保留既有两步角色结果：旧 ROOT 的 ADMIN 调用可带 `password` 创建/设置其独立账号；目标的 ROOT 调用带 `root_password` 设置共享 root 密码并归档/删除目标原独立账号；Node 每次只处理指定目标。
- 密码以 `SecretStr` 进入，通过 stdin `chpasswd` 执行；日志、异常、WSS、action 缓存、Docker env/config/labels 与响应均不留明文。
- 含密码请求的 422 不回显 `input`/`ctx`/原始请求体。
- 已受理任务不因客户端断开被主动取消。

**Non-Goals:**

- 不实现、不提交、不跑生产测试；不写 review/test-plan/tasks。
- 不改变既有 ROOT/ADMIN/COLLABORATOR 角色结果，不新增唯一所有者规则，不把 Node 改成自动扫描/批量交接。
- 不新增持久回滚工作流；某一步失败时只如实返回该步结果，已完成步骤保留，Ctrl 以 oplog 记录实际状态。
- 不扩大到 ManageUser 平台用户密码重置，不顺手重构协作者新增/角色业务规则。
- 不新增持久队列、租约、自动重试、密码查回、数据库字段或迁移。

## Decisions

### D1：保留 Web 既有两步 ROOT 角色结果，编排移入 Ctrl 后台

两个 Web 入口的既有差异必须保留：Home/EditUserModal 是“旧 ROOT -> ADMIN，再目标 -> ROOT”的交接；ContainerDetailPage 原本只提升目标，不降旧 ROOT。Ctrl API 增加纯布尔 `transfer_root:false`：Home/EditUserModal 显式传 `true`，Ctrl 才在后台按原 Home 顺序对每个旧 ROOT 调用 ADMIN、再对目标调用 ROOT；ContainerDetailPage 默认 `false`，只把目标提升/重置 root 并返回 1 条凭据，不偷偷降旧 ROOT。Node 无 `transfer_root` 字段，仍只执行单目标 primitive；内部删除用户触发的 ROOT 移交保持原单目标同步 primitive，不使用 Web 交接编排。

`transfer_root=true` 时，普通单个旧 ROOT 返回 2 项凭据；历史多 ROOT 沿用 `EditUserModal` 既有遍历，对每个旧 ROOT 各调用一次 ADMIN，再调用目标 ROOT，返回所有涉及账号 + `root` 的凭据，可大于 2 项，不丢人、不为凑 2 项篡改角色。身份字段可只含 `login_name`，不强制 `user_id`。Ctrl 在每一步成功后更新对应绑定；Node 不感知交接或 ROOT 数量，不扫描其他账号，不更新绑定。两步/多步都按受理时的权限执行，避免浏览器先降旧 ROOT 后失去权限导致后续 403；这不是新增持久状态，只是把既有 Home 编排移入后台任务。

**Alternatives considered:** 让 Node 的 ROOT 请求自动把其他 ROOT 降 ADMIN 并创建旧 owner 账号。**Rejected**：Node 不应扫描/修改其他账号，跨账号事务也不属于 Node 现有职责。

### D2：新增协作者由 Ctrl 下发密码

`AddCollaboratorConfig` 增加必填 `password: SecretStr`，ADMIN 与 COLLABORATOR 同样处理。Node 创建账号后通过 stdin 设置该密码，不再使用 `<user_name>123`。`AddCollaboratorResponse.decrypted_message` 去掉 `password` 与原始 `config`，只保留容器名、用户名、角色等公开字段。Ctrl 受理后立即返回一条凭据并在后台执行 Node 请求；沿用既有 `ADD_COLLABORATOR` 审计，不为密码新增独立 oplog 或重复日志。Node 端点保持单次同步执行。

恢复入口同样消费共享创建的必填密码：Ctrl 实际恢复成功返回 root credential，Web DeletedContainers 最小复用 CredentialModal；`requires_choice` 不展示，不得出现恢复成功但密码丢失。恢复协作者的瞬时密码由 Ctrl 生成、Node 只消费，不写 snapshot，不新增恢复队列/日志，不改恢复其他业务或页面布局。

**Alternatives considered:** 让 Node 自己生成随机密码并返回。**Rejected**：密码生成和一次性展示属于 Ctrl/Web，Node 返回密码会扩大泄露面并破坏“Node 不返回凭据”的边界。

### D3：`update_role` 增加两个有条件密码字段，Node 只处理单目标

`UpdateRoleConfig` 增加：

- `root_password: SecretStr | None`：仅 `updated_role="root"` 时必填。Node 用该值设置共享 root 密码，然后按既有 ROOT 分支清理目标账号 sudo/wheel 组、归档并删除目标原独立账号。目标本不在 sudo/wheel 时，两个组都不存在不算失败；用最小幂等判断保留“目标最终不属于 sudo/wheel”的既有预期结果，归档/删除规则不变。
- `password: SecretStr | None`：仅 `updated_role="admin"` 时可携带。Node 用该值确保旧 owner 的系统用户名独立账号存在并设置密码：账号不存在则按既有持久化目录模式创建，存在则复用；随后确保加入管理组。该调用不改共享 root 密码。
- `updated_role="collaborator"` 或普通 ADMIN/COLLABORATOR 互换不得携带密码，Node 不执行 `chpasswd`，不改变密码。

未携带 `password` 的 ADMIN 请求不得用默认密码创建缺失账号；账号已存在时只做既有管理组调整，账号缺失时返回失败。Node 不写绑定，绑定更新由 Ctrl 在每步成功后完成。

**Alternatives considered:** 用单一 `password` 字段同时承担 root 与旧 owner。**Rejected**：两者语义、校验和失败条件不同，分开字段可避免把 root 密码误发给 ADMIN 分支。

### D4：用 Docker 低层 exec + socket 写 stdin 执行 `chpasswd`

已核对本机 docker-py 源码：`Container.exec_run(..., stdin=True)` 只设置 `AttachStdin`，没有输入参数；`exec_run(..., socket=True)` 虽返回原始 socket，却不返回 exec id。因此实现应走低层 API：

1. `api.exec_create(container.id, ["chpasswd"], stdin=True, stdout=True, stderr=True, tty=False, user="root")` 取 `Id`；
2. `api.exec_start(exec_id, socket=True)` 取原始 socket；
3. 写入 `login_name:password\n`，半关闭写端（`shutdown(SHUT_WR)`），读取/丢弃输出直到 EOF；
4. `api.exec_inspect(exec_id)["ExitCode"]` 判定成功，仅 0 成功；
5. 关闭 socket，异常统一转固定脱敏错误。

密码不进 argv、不进 shell、不落容器文件、不进环境变量。若当前 Docker transport 不支持可写/半关闭 socket（例如某些 Windows named pipe），helper MUST fail closed 并返回脱敏错误，MUST NOT 退化为 `echo ... | chpasswd` 或命令行密码。

**Alternatives considered:** `echo 'user:pass' | chpasswd`（会进日志/命令/进程列表）；`docker exec -i` CLI（新增 CLI 依赖且与 SDK 连接配置可能不一致）；临时密码文件（落盘、清理竞态）。均拒绝。

### D5：SecretStr + 统一密码校验 + 脱敏 422

创建/恢复、新增协作者、重置、更新角色等密码入口使用 `SecretStr`；服务层可继续传 `SecretStr`，只在 stdin helper 内调用 `get_secret_value()`。密码约束为 8–128 字符，不含 `:`、CR、LF、NUL；校验消息只描述规则，不拼接密码。FastAPI 默认 422 会把 Pydantic 的 `input`（同层缺失时可能含密码）回显，因此只对密码相关路由做路由级脱敏（例如密码 router 自定义 `APIRoute`），只输出 `success:0`、`error`、`error_reason` 与 `detail[{type,loc,msg}]`，丢弃 `input`/`ctx`/`url`；该脱敏必须覆盖 `SecretStr` 自身校验失败。其他非密码路由 MUST 保留既有默认 422 形状，不注册替换所有路由的全局 handler。

**Alternatives considered:** 只用 `SecretStr` 不加 handler。**Rejected**：实测同层字段缺失时 `input` 会带出密码原值。

### D6：创建后台、新增/重置/角色同步，均不引入新持久化

创建仍由既有 `status_cache.submit_action` 后台执行；`root_password` 只存在请求模型和 `_bg_create` 闭包，action 缓存只存 ref/phase，不序列化闭包。新增协作者、手动重置、ROOT 目标与旧 ROOT 降 ADMIN 由同步端点直接执行并等待 `chpasswd`，不登记容器状态动作、不写 action 缓存。Node 不新增创建审计/日志条目；既有创建日志保留且不含密码。客户端断开不触发取消；同步端点在 threadpool 中执行到结束，响应可能无法送达。Node 不写 oplog；Ctrl 负责受理、后台执行与结果记录。

### D7：`add_collaborator`/`update_role` 只做密码执行方式替换

为避免把密码拼进命令并打印，`add_collaborator` 与 `update_role` 的密码步骤改调同一 stdin helper。普通非 ROOT ADMIN/COLLABORATOR 互换且未携带密码时 MUST NOT 实际执行 `chpasswd`；`update_role(ADMIN)` 的旧 ROOT 降级分支使用请求 `password`，普通 ADMIN 分支未带密码时只在账号已存在的情况下做组调整。若 shell 未读取 stdin，helper 忽略写端关闭/EPIPE，不把它误判为密码失败。该调整只替换执行方式，不改变角色最终结果、默认目录/归档规则或成功响应形状。

**内部调用兼容：** 创建容器的 `restore_accounts` 内部路径由 Ctrl 为每个恢复协作者生成随机密码，并在 `RestoreAccountConfig.password` 中瞬时传入；Node 用该密码重建账号，不得回退弱密码，也不得把密码写入 snapshot/WSS/status/action/日志/响应。删除用户触发的 ROOT 转移同样由 Ctrl 生成 `root_password` 并传入；Node 不区分调用来源。两条内部路径都沿用既有恢复/删除业务规则和页面，不新增展示入口或重复审计。

### D8：Node 响应不承担一次性凭据

Node 创建响应保持 `success`/`container_status`/`container_name`/`action_ref`；新增协作者与重置成功只返回既有 `success`（新增协作者可保留脱敏 `decrypted_message`）；ROOT/ADMIN 更新沿用 `UpdateRoleResponse`，`decrypted_message` 去除 `password`/`root_password`。`accepted:true` 与 `credentials:[{login_name,password}]` 属于 Ctrl/Web 合同，Node 不返回、不查回；所有凭据响应 MUST `Cache-Control: no-store`。ROOT 交接由 Ctrl 合并凭据：普通单个旧 ROOT 为旧 owner 系统用户名 + 其 ADMIN 密码、`root` + root 密码共 2 项；历史多 ROOT 为所有涉及旧账号 + `root`，可大于 2 项，不丢人、不为凑 2 项篡改角色。身份字段可只含 `login_name`，Web 只渲染数组。

### D9：目标/状态校验在 Ctrl，Node 做结构性与运行态兜底

Ctrl 负责 `container:operation` + `container:root` 资源权限、目标绑定、机器/online 守卫与 `transfer_root` 编排；资源/方法/机器三层守卫 UI 与后端一致。主机/容器状态 guard 必须在受理之前完成，后台只做最小既有 guard 的二次核对；受理表示进程内任务已启动，不承诺跨重启或持久完成，不新增 DTO 或持久状态。Node 仍校验容器存在、running、登录名格式、目标账号存在（由 `chpasswd`/`id` 失败体现）和密码格式；Node 不解析平台绑定、不判断资源通配、不扫描其他账号、不从 `owner_name` 推导登录名。

## 固定跨仓合同（已对齐，供 review；不在本仓单方面改）

| 方向 | 端点/字段 | 合同 |
| --- | --- | --- |
| Ctrl -> Node | `POST /api/create_container` | 顶层 `root_password: SecretStr`，必填；`restore_accounts[].password: SecretStr`，瞬时必填 |
| Ctrl -> Node | `POST /api/add_collaborator` | `config.password: SecretStr`，ADMIN/COLLABORATOR 均必填 |
| Ctrl -> Node | `POST /api/reset_container_password` | `{config:{container_name,user_name,password}}` |
| Ctrl -> Node | `POST /api/update_role` | `config.root_password`：仅 ROOT 必填；`config.password`：仅旧 ROOT 降 ADMIN 时携带；Node 无 `transfer_root` |
| Ctrl API | `POST /api/containers/update_role` | 新增纯布尔 `transfer_root:false`；Home/EditUserModal 传 true，ContainerDetailPage 默认 false；Node 不接收该字段 |
| Ctrl API | `POST /api/containers/reset_container_password` | body `{container_id,user_id}`；目标 username 取绑定（ROOT 固定 `root`）；oplog `reset_container_password`；仅 online 且主机可用时执行；404/409/500 沿用现有 error_reason 映射，Ctrl 不拼原始错误体；资源/方法/机器三层守卫 UI 与后端一致 |
| Ctrl 权限快照 | `container_resource_unrestricted` | 派生非持久 `has_resource_wildcard(uid,"container")`；Web 不得用方法通配推断 |
| Ctrl -> Web | 创建/新增/重置/恢复 | `accepted:true` + 一条 `credentials:[{login_name,password}]`；恢复成功返回 root credential，`requires_choice` 不展示；`Cache-Control: no-store` |
| Ctrl -> Web | ROOT 提升/交接 | `transfer_root=false` 只返回 1 条 root 凭据、不降旧 ROOT；`true` 返回所有涉及账号凭据：普通单旧 ROOT 2 条、历史多 ROOT 可 >2 条，不丢人、不篡改角色；身份可只含 `login_name`；`Cache-Control: no-store` |
| Node -> Ctrl | 上述 Node 响应 | 无 `credentials`/`password`/`root_password`；只回 success/状态/脱敏错误；Node 对含密码请求的响应也设 `Cache-Control: no-store` |
| Ctrl 审计 | 各动作 | 创建只原 CREATE 日志；新增只沿用 `ADD_COLLABORATOR`；ROOT 各步沿用 `UPDATE_COLLABORATOR_ROLE`；手动重置用 `reset_container_password`；不得新增重复密码日志；超时/未知结果不得伪装 Node 确认成功 |
| Ctrl 内部路径 | `restore_accounts` / 删除用户 ROOT 转移 | 同样由 Ctrl 生成随机密码并在 Node wire 传入；不回退弱密码；不改变既有恢复/删除业务规则和页面；恢复密码不持久化到 snapshot；删除用户 ROOT 不用 Web `transfer_root` 编排 |
| Guards | 受理前 / 后台 | 主机/容器状态 guard 在受理前完成；后台仅二次核对最小既有 guard；不新增 DTO 或持久状态；受理表示进程内任务已启动，不承诺跨重启持久完成 |
| Web | UI/错误 | 只详情页有手动重置按钮；新增/角色密码弹窗覆盖 Home、EditUserModal、详情等既有入口；凭据组件只渲染数组；凭据 API 去 secret/raw body 但保留安全 message（资源超限数值等）；DOM 清状态/引用、关闭不可回看，不承诺 JS 字符串物理零化 |

## Risks / Trade-offs

- [Docker SDK socket 传输在 Windows named pipe/特殊 transport 不保证可写或可半关闭] → 实现后用本地 FakeDocker 覆盖 socket I/O；不支持时 fail closed，绝不回退命令行密码；本阶段不宣称真实生产验证。
- [创建先受理、后设置密码，设置失败时用户已看到密码] → 保持既有“受理不等于完成”；Ctrl 只写失败 oplog，不伪造成功；Node 不回退弱密码。
- [ROOT 分支目标不属于 sudo/wheel 时旧命令会失败] → 采用最小幂等判断：两个组都不存在不算失败，最终组状态仍为“不在 sudo/wheel”，归档/删除与角色结果不变；普通角色行为不扩张。
- [Ctrl 内部恢复/删除路径缺少密码会 fail closed] → Ctrl 必须在同一变更内为 `restore_accounts` 和删除用户 ROOT 转移生成随机密码并传入；Node 不回退弱密码，不改既有业务规则/页面。
- [恢复密码可能被写入 snapshot] → `RestoreAccountConfig.password` 定义为瞬时字段；Node 不落 snapshot/WSS/缓存/日志/响应，Ctrl 也不得持久化。
- [旧 Ctrl 不发送新密码字段会创建/恢复/新增/ROOT/ADMIN 失败] → 这是刻意的 fail closed；部署顺序需 Node 先行或协调停机，避免旧 Node 静默继续默认密码。
- [密码会短暂存在于 Node 进程内存与 Docker daemon 内存] → 无法完全避免；通过最小生命周期、不落盘、不日志、不响应降低暴露面。
- [两步/多步 ROOT 交接后续步骤失败或超时] → Node 不回滚前一步，Ctrl 不伪报完整成功；oplog 记录实际完成步骤或未知结果，失败/未知记录不含 secret。
- [历史多 ROOT 凭据数量大于 2] → Ctrl/Web 只渲染数组，不丢涉及人、不为凑 2 项篡改角色；普通单旧 ROOT 的正常断言仍为 2。
- [受理只代表进程内任务已启动] → 不承诺跨重启或持久完成；超时/未知结果不得伪装 Node 确认成功，UI 以后续 oplog 为准。

## Migration Plan

1. 先在 Node 落地新请求字段、reset 接口、安全 helper 与脱敏 422；不修改数据库。
2. Node 部署后旧 Ctrl 的创建/恢复/新增/ROOT/ADMIN 请求会因缺字段失败（fail closed），不会退回默认密码；随后部署 Ctrl。
3. Ctrl 在 `transfer_root=true` 时将现有 Home 多步 ROOT 编排移入后台，生成旧 owner 与 root 随机密码，按既有顺序调用 Node，并在每步成功后更新绑定、按既有审计码写 oplog；`transfer_root=false` 的详情页只单目标提升/重置 root，返回 1 条。
4. Ctrl 同步覆盖内部路径：`restore_accounts` 为每个恢复协作者生成瞬时密码并在创建 wire 传入，不写入 snapshot；删除用户触发的 ROOT 转移生成 `root_password` 并传入，保持单目标同步 primitive。
5. Ctrl 在受理前完成资源/方法/机器三层守卫与主机/容器状态 guard，后台只做最小既有 guard 二次核对；受理表示进程内任务已启动，不承诺跨重启持久完成；不新增 DTO 或持久状态。
6. 实现后测试优先使用 WSL Linux 环境（完整套件、`du` 可用）与已备 Windows 环境；socket I/O 先由本地 FakeDocker 覆盖验证，不宣称真实生产验证。
7. 回滚 Node 会恢复旧行为（默认密码/命令含密码），仅作为紧急回退；回滚后应同时回滚 Ctrl，避免 Web 展示与实际密码不一致。

## Resolved Constraints / Implementation Notes

- 合同字段已对齐：创建 `root_password` 顶层；新增/重置 `config.password`；ROOT 目标 `config.root_password`；旧 ROOT 降 ADMIN `config.password`。
- `transfer_root` 为 Ctrl API 纯布尔：Home/EditUserModal true，返回 2/N+1 项；ContainerDetailPage 默认 false，返回 1 条且不降旧 ROOT；Node 无该字段，只处理单目标。
- 凭据响应统一 `accepted:true` + `credentials:[{login_name,password}]`；单旧 ROOT 正常 2 项，历史多 ROOT 可 >2；Web 只渲染数组；身份字段可只含 `login_name`；恢复成功返回 root credential 并最小复用 CredentialModal，`requires_choice` 不展示。
- 所有凭据响应 `Cache-Control: no-store`；Node 对含密码请求的响应同样设置。
- 审计码固定：创建只原 CREATE 日志；新增协作者 `ADD_COLLABORATOR`；ROOT 各步 `UPDATE_COLLABORATOR_ROLE`；手动重置 `reset_container_password`；不得新增重复密码日志；超时/未知结果不伪装成功。
- 恢复/删除内部路径必须生成并传入随机密码；恢复密码不持久化到 snapshot。
- ROOT 组清理采用最小幂等判断，不改变角色最终结果与归档规则。
- 422 脱敏仅密码路由，其他路由保留默认形状；Web 去 secret/raw body 但保留安全 message；DOM 清状态/引用，不承诺 JS 字符串物理零化。
- 不新增全局角色唯一约束、repo 原子双绑定函数、持久队列/租约/迁移。
- 本阶段仅 proposal/specs/design；在 review/test-plan/tasks 依赖闭包完成前不得实现。
