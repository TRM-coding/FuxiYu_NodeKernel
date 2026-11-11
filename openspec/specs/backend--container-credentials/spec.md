# 容器账号凭据

## Purpose

定义 Node 侧容器账号密码的 SecretStr 输入、stdin `chpasswd` 安全执行、脱敏校验错误、禁止明文持久化/日志/响应，以及已受理密码任务不因客户端断开而取消的跨接口约束。

## Requirements

### Requirement: 密码输入使用 SecretStr 且只保持最小生命周期

Node SHALL 将创建 root 密码、恢复协作者瞬时密码、新增协作者密码、手动重置密码、ROOT 目标密码和旧 ROOT 降 ADMIN 密码声明为 `SecretStr`，不得使用普通字符串或可自由序列化的字段。模型 `repr`、`model_dump()`、`jsonable_encoder`、异常链与日志 MUST 只出现掩码。明文 SHALL 仅在请求校验、后台任务闭包和最终 stdin 写入的瞬间存在；MUST NOT 存入 status/action 缓存、WSS 快照、数据库、Docker environment/config/labels、文件或任何可查询结构。

#### Scenario: SecretStr 掩码

- **GIVEN** 创建/恢复、新增协作者、重置、更新角色等密码入口分别持有合法密码
- **WHEN** Node 打印模型 repr、调用 `model_dump()` 或记录异常
- **THEN** 输出只含掩码，不含明文；只有显式 `get_secret_value()` 才能取得明文

#### Scenario: 创建密码不进入 Docker 运行配置

- **GIVEN** 创建请求携带 `root_password`，或 `restore_accounts` 携带瞬时 `password`
- **WHEN** Node 调用 `containers.run` 并执行容器命令
- **THEN** Docker environment、config、labels、容器启动命令与 exec argv 均不含密码；明文只出现在 `chpasswd` 的 stdin

#### Scenario: 密码不进入 WSS 或 action 缓存

- **GIVEN** 创建、恢复协作者、新增协作者、重置、ROOT 目标或旧 ROOT 降 ADMIN 已经执行
- **WHEN** 读取 status/action 缓存投影与 WSS 快照
- **THEN** 均不含密码、`root_password`、`password`、`credentials` 或 stdin 内容

#### Scenario: 恢复密码不进入 snapshot

- **GIVEN** 创建请求的 `restore_accounts` 带瞬时 `password`
- **WHEN** Node 完成恢复并读取任何快照/缓存/响应
- **THEN** 该密码不在 snapshot、WSS、status/action 缓存、日志或响应中；Ctrl 也不得把它写入持久化 snapshot

#### Scenario: 不提供密码查回

- **GIVEN** 任一密码设置成功
- **WHEN** 调用 Node 的查询端点或读取持久化数据
- **THEN** 无法取回该密码；Node 不新增凭据查询接口或可逆存储

### Requirement: 通过 stdin 安全执行 chpasswd

Node SHALL 通过 Docker exec 的 stdin 向 `chpasswd` 写入 `login_name:password\n`。命令 argv MUST 仅为 `chpasswd` 或等价的不含密码命令；MUST NOT 使用 shell 拼接、`echo`、命令行参数、环境变量、临时文件或容器内落盘传递明文。Node SHALL 读取 `chpasswd` 退出码，仅 0 视为成功；异常与错误响应 MUST 使用固定脱敏文案，MUST NOT 包含密码、stdin 内容、拼接命令或可能回显密码的 stdout/stderr。`add_collaborator`、`update_role` 的密码设置 MUST 复用同一 helper；普通非 ROOT ADMIN/COLLABORATOR 互换且未提供密码时 MUST NOT 实际执行 `chpasswd`。

#### Scenario: stdin 传递密码且 argv 不含密码

- **GIVEN** 需要设置某账号密码
- **WHEN** Node 执行安全 helper
- **THEN** exec 的命令为 `["chpasswd"]` 一类 argv，密码仅写入 stdin；退出码 0 时返回成功

#### Scenario: 特殊字符按数据处理

- **GIVEN** 密码包含 `$`、`;`、引号或反斜杠等 shell 元字符
- **WHEN** Node 通过 stdin 写入
- **THEN** 这些字符作为密码数据被 `chpasswd` 读取，不被任何 shell 解释；命令日志中不出现密码

#### Scenario: chpasswd 非 0 时脱敏失败

- **GIVEN** `chpasswd` 返回非 0 或 exec 连接失败
- **WHEN** Node 构造错误
- **THEN** 只返回固定脱敏错误与错误原因，异常、日志、响应均不含密码、stdin 或原始输出；不自动重试

#### Scenario: add_collaborator 日志不含初始密码

- **GIVEN** 调用 `add_collaborator` 创建协作者
- **WHEN** Node 执行用户创建与密码设置并记录日志
- **THEN** 日志只含容器名与用户名等非敏感字段，不含 Ctrl 密码、`echo ... | chpasswd` 命令或密码输出

#### Scenario: update_role 日志不含 ROOT/旧 owner 密码

- **GIVEN** 调用 `update_role` 执行 ROOT 目标或旧 ROOT 降 ADMIN
- **WHEN** Node 执行密码、组清理与账号归档删除
- **THEN** 日志只含容器名、用户名、步骤与退出码等非敏感字段，不含 `root_password`、`password` 或 stdin

#### Scenario: 普通角色切换不触碰密码

- **GIVEN** `updated_role` 为 admin 或 collaborator，且请求未提供密码
- **WHEN** Node 更新角色
- **THEN** 不实际执行 `chpasswd`、不改变账号密码；命令文本与日志不含密码

### Requirement: 密码不得进入日志、错误、WSS、缓存与响应

Node MUST NOT 将任何密码或含密码的请求体写入 Docker environment/config/labels、WSS、status/action 缓存、数据库、日志、审计、错误响应或异常文本。Node 不写浏览器 localStorage/sessionStorage，响应与 WSS 不携带密码。Node 的密码相关响应 MUST NOT 返回 `credentials`/`password`/`root_password`，且 MUST 设置 `Cache-Control: no-store`；Ctrl/Web 携带 `credentials` 的响应同样 MUST `no-store`。

#### Scenario: 日志与异常无明文

- **GIVEN** 创建、恢复协作者、新增协作者、重置、ROOT 目标或旧 ROOT 降 ADMIN 成功或失败
- **WHEN** 检查 Node 日志、stdout/stderr 与异常链
- **THEN** 均不含密码明文、stdin 或完整含密码命令

#### Scenario: 响应不返回凭据

- **GIVEN** 创建、恢复协作者、新增协作者、重置、ROOT 目标或旧 ROOT 降 ADMIN 成功
- **WHEN** Node 返回响应
- **THEN** 只含既有 `success`/状态/脱敏后的 `decrypted_message` 等非敏感字段，不含 `credentials`、`password` 或 `root_password`

#### Scenario: 凭据响应禁止缓存

- **GIVEN** Node 返回含密码请求的成功或失败响应，或 Ctrl/Web 返回 `credentials`
- **WHEN** 检查响应头
- **THEN** `Cache-Control` 为 `no-store`；响应体不含可缓存的明文

#### Scenario: ROOT 交接逐次调用、逐项凭据

- **GIVEN** Ctrl 受理任一外部 ROOT 上位请求，且存在一个或多个旧 ROOT
- **WHEN** Ctrl 按既有顺序对每个旧 ROOT 调 `update_role(ADMIN)` 并携带 `password`，再对目标调 `update_role(ROOT)` 并携带 `root_password`
- **THEN** Node 每次只出现本次目标所需的一个密码字段，响应均不含密码；Ctrl 返回所有涉及旧账号 + `root` 的凭据，单旧 ROOT 为 2 项、历史多 ROOT 可大于 2，不丢人、不为凑 2 篡改角色

#### Scenario: 单次 ROOT 请求只带本次密码字段

- **GIVEN** Ctrl 已先为旧 ROOT 调用 ADMIN 并传入其独立账号密码，随后为目标调用 ROOT
- **WHEN** 检查目标的单次 Node 请求
- **THEN** 该次只出现 `root_password`，不混入旧 ROOT 的 `password`，Node 请求体无 `transfer_root`；完整交接的 Ctrl 响应仍包含 root 与所有旧所有者独立账号凭据

#### Scenario: 不新增重复密码审计

- **GIVEN** 创建、恢复、新增协作者、ROOT 交接或手动重置完成
- **WHEN** 检查 Ctrl/Node 审计
- **THEN** Node 不新增密码审计；Ctrl 沿用既有 `ADD_COLLABORATOR`/`UPDATE_COLLABORATOR_ROLE`，手动重置用 `reset_container_password`，创建不额外记录，不产生重复密码日志；超时/未知结果不得伪装成 Node 确认成功

#### Scenario: 非密码路由保持默认 422

- **GIVEN** 一个不包含密码字段的其他路由收到非法请求
- **WHEN** FastAPI/Pydantic 返回 422
- **THEN** 保持该路由既有默认错误形状，不被密码路由的脱敏 handler 改写

#### Scenario: 失败响应夹带尝试不泄漏

- **GIVEN** Docker exec 或 `chpasswd` 失败
- **WHEN** Node 生成错误响应
- **THEN** 错误体只含固定文案与 `error_reason`，不把请求体、stdin、原始输出或异常字符串拼入

### Requirement: 含密码请求的校验错误必须脱敏

Node SHALL 仅对密码相关路由（创建/恢复、新增协作者、手动重置、ROOT 目标、旧 ROOT 降 ADMIN）的校验失败返回脱敏 422，错误体仅包含 `success:0`、`error`、`error_reason` 与 `detail` 中的 `type`、`loc`、`msg`。MUST NOT 回显 Pydantic 的 `input`、`ctx`、`url` 或原始请求体；校验器消息 MUST NOT 拼接密码值，包括 `SecretStr` 自身校验失败。其他非密码路由 MUST 保留既有默认 422 形状，不借机重构全局错误处理。

#### Scenario: 同层字段缺失时不回显密码

- **GIVEN** 请求已携带合法密码，但同层另一个必填字段缺失
- **WHEN** FastAPI/Pydantic 拒绝请求
- **THEN** 422 的 `detail` 不含 `input`/`ctx`，响应与日志均不出现密码

#### Scenario: 密码本身非法时不回显

- **GIVEN** `password` 或 `root_password` 为空、超长、含冒号或控制字符
- **WHEN** 请求校验失败
- **THEN** 422 只含通用校验消息，密码原值不进入响应、日志或异常

#### Scenario: 类型错误不携带原值

- **GIVEN** 密码字段传入了对象、数组或数字
- **WHEN** 请求校验失败
- **THEN** 422 的 `detail` 只保留类型、位置与通用消息，不保留原始输入

### Requirement: 已受理的密码任务不因客户端断开而取消

Node SHALL 在创建后台任务、新增协作者同步执行、手动重置同步执行、ROOT 目标同步执行和旧 ROOT 降 ADMIN 同步执行期间，不因 HTTP 客户端断开而主动取消已受理的密码设置。Node MUST NOT 在断开时自动重试、重复执行或伪造成功；响应可以因连接关闭而无法送达。

#### Scenario: 创建受理后断开

- **GIVEN** 创建请求已返回 building/creating
- **WHEN** 客户端随后断开
- **THEN** 既有后台创建继续执行 root 密码设置，不因断开取消，也不新增密码日志

#### Scenario: 新增、重置或转移执行中断开

- **GIVEN** 新增协作者、重置、ROOT 目标或旧 ROOT 降 ADMIN 已进入同步 `chpasswd` 执行
- **WHEN** 客户端连接断开
- **THEN** Node 继续到 exec 结束再收尾；不基于断开自动重试，不把未确认结果写成成功
