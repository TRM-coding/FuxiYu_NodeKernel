# 容器创建

## Purpose

定义资源、镜像构建与恢复输入及后台容器创建行为，分别表达受理态与最终状态。按能力组织完整类型契约；构建缓存以 Ctrl 下发的准确标签为准。

## Requirements

### Requirement: ContainerConfig 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。

字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：资源单位为 GB，GPU 为具体设备 id 列表；cpu_number/memory/shared_memory 的 schema 下界为 0，port 保留在线路协议但生产端口由 Node 分配器选择；镜像 tag 由 Ctrl 指定。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例

来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: ImageBuildConfig 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。

字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：dockerfile_text 为 Ctrl 生成的最终 Dockerfile，image_tag 为最终制品 tag；未提供 image_build 时按 config.image 使用既有镜像，提供了构建段但正文或标签为空时构建失败，不把用户模板和完整 Dockerfile 混同。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例

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

来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: CreateContainerAcceptedResponse 数据契约 [schemas/container.py]

生产方和消费方 SHALL 遵守 `CreateContainerResponse` 的定义，不增加未声明的 Literal 值或将兼容别名解释为新协议。

定义：`CreateContainerResponse`。

本类型没有独立声明字段；以别名、继承或上述职责为准。

系统 SHALL 保持以下已实现的职责：线路值域或兼容类型别名，消费方保持其已声明的成员与指向类型。

#### Scenario: 使用声明值域

- **WHEN** 生产者序列化此别名所代表的数据
- **THEN** 值域或数据形状保持与上述 Literal/目标类型一致

来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: Container 数据契约 [utils/Container.py]

系统 SHALL 按此类型的字段、成员和构造约定传递内部数据；该内部类型不自动构成一个公开 HTTP 请求端点。

本类型没有独立声明字段；以别名、继承或上述职责为准。

系统 SHALL 保持以下已实现的职责：legacy 内部容器 DTO，将构造参数映射为 GPU_LIST/CPU_NUMBER/MEMORY/SHARED_MEMORY/NAME 等属性；get_config 返回配置字典。

#### Scenario: 内部值传递

- **WHEN** 生产方构造并向消费方传递此数据类型
- **THEN** 成员名称和数据职责保持一致；运行配置只传配置值，证书数据只传文件引用

来源：[utils/Container.py](../../../utils/Container.py)。

### Requirement: Container.Config_info 数据契约 [utils/Container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。

字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：legacy 配置模型仍被 network/api.py 创建入口消费，不能仅因存在新版 ContainerConfig 就删除；该类型本身没有新版 ge 边界。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例

来源：[utils/Container.py](../../../utils/Container.py)。

### Requirement: CreateContainerReturn 数据契约 [services/container_service.py]

系统 SHALL 按此类型的字段、成员和构造约定传递内部数据；该内部类型不自动构成一个公开 HTTP 请求端点。

字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：内部 NamedTuple，记录 Docker 容器 id、名称及可选端口映射、bind_mount_path；供操作服务回传已建立的事实。

#### Scenario: 内部值传递

- **WHEN** 生产方构造并向消费方传递此数据类型
- **THEN** 成员名称和数据职责保持一致；运行配置只传配置值，证书数据只传文件引用

来源：[services/container_service.py](../../../services/container_service.py)。

### Requirement: 构建段命中本机标签即跳过构建 [services/container_service.py]

Node SHALL 以 `image_build.image_tag` 作为本机 Docker 制品的缓存键：该标签在本机已存在时直接复用，不存在时才按 `image_build.dockerfile_text` 构建。正文或标签为空 SHALL 失败，MUST NOT 静默退回按运行标签直接启动。Node MUST NOT 因外部派发记录存在或同一模板的旧标签存在而跳过本次标签查验，也不自行推导 Ctrl 的资源身份或缓存版本。

#### Scenario: 命中即跳过构建
- **WHEN** 本机 Docker 已存在构建段声明的标签
- **THEN** 直接使用该标签，不执行构建

#### Scenario: 未命中则现场构建
- **WHEN** 本机 Docker 不存在该标签
- **THEN** 用构建段的 Dockerfile 文本构建出该标签后继续创建

#### Scenario: 构建段缺文本时失败而非降级
- **WHEN** 请求声明了构建段但 dockerfile_text 为空
- **THEN** 本次创建失败，不按运行标签直接启动容器

#### Scenario: 构建结果决定运行镜像
- **WHEN** 构建段存在且构建成功
- **THEN** 本次创建实际运行的镜像标签等于构建段声明的标签

#### Scenario: 平台注入换代而旧标签仍在
- **WHEN** 旧版本标签存在，但 Ctrl 因平台注入变化派发不同的新标签与新 Dockerfile
- **THEN** 按新 Dockerfile 构建新标签，保留旧制品，不因旧标签存在跳过构建

#### Scenario: 新版本再次派发
- **WHEN** 新版本标签已在本机构建完成，Ctrl 再次派发同一新版本
- **THEN** 命中新标签并复用，不再次构建，也不修改旧容器的镜像

来源：[services/container_service.py](../../../services/container_service.py)。

### Requirement: 普通新建挂载目录的本地时间戳命名与序号后缀

未携带 `restore_mount_path` 的普通新建 SHALL 在 `NODE_CONTAINERS_BASE/<owner>/containers/` 下使用 `<container_name>_<YYYYMMDD_HHMMSS>` 作为基名；基名可用时使用该基名，基名已占用时依次追加 `_1`、`_2` ... `_99` 的十进制序号。时间取 Node 本地时间并精确到秒；实际目录 SHALL 作为 Docker `/root` 的 bind Source 和 `bind_mount_path`。碰撞后缀 MUST 限于 `_1` 至 `_99` 的十进制序号，且 MUST NOT 使用无时间戳基名。

#### Scenario: 普通新建使用本地时间戳基名

- **GIVEN** Node 本地时间为 `2026-11-01 23:19:26`，普通新建容器名为 `c1`，且该基名尚未被占用
- **WHEN** Node 创建该容器的宿主挂载目录
- **THEN** 实际目录为 `<NODE_CONTAINERS_BASE>/<owner>/containers/c1_20261101_231926`，Docker `/root` 的 bind Source 和 `bind_mount_path` 均等于该目录，且不创建同级的无时间戳 `c1`，也不追加序号后缀

#### Scenario: 时间戳取本地时间而非 UTC

- **GIVEN** Node 本地时区为 UTC+08:00，本地时间为 `2026-01-01 00:30:00`，对应 UTC 为 `2025-12-31 16:30:00`
- **WHEN** Node 普通新建容器 `c1`
- **THEN** 目录时间戳为 `20260101_003000`，不采用 UTC 日期 `20251231_163000`

#### Scenario: 历史目录保留且不参与新路径

- **GIVEN** 同一 owner 的 `containers` 下已有 `c1`、`c1_12345` 和 `c1_20261001_010101` 等历史目录，目录内各有数据
- **WHEN** Node 在 `2026-11-01 23:19:26` 普通新建同名容器 `c1`
- **THEN** 新目录为 `c1_20261101_231926`，上述历史目录的名称和内容保持不变，不被改名、移动或复用

来源：[services/container_service.py](../../../services/container_service.py)。

### Requirement: 普通新建目录碰撞的原子有界避让

普通新建目录 SHALL 用 `exist_ok=False` 的独占创建取得。候选基名已存在时 MUST 视为碰撞，并立即按 `_1`、`_2` ... `_99` 的顺序尝试下一候选；基名加 `_1` 至 `_99` 共 100 个候选，全部失败后 SHALL 使本次创建失败且不启动 Docker 创建。MUST NOT 复用、接管、改名或删除既有目录，也不得跳过候选或改用无时间戳基名；候选后缀 MUST 限于 `_1` 至 `_99` 的十进制序号。

#### Scenario: 基名碰撞追加 _1

- **GIVEN** 候选目录 `c1_20261101_231926` 已存在并含有历史数据，且 `c1_20261101_231926_1` 尚未被占用
- **WHEN** Node 在同一本地秒普通新建 `c1`
- **THEN** 已有基名目录的名称和内容保持不变，Node 以独占创建取得 `c1_20261101_231926_1` 作为唯一挂载来源

#### Scenario: 连续碰撞按序递增

- **GIVEN** 基名目录 `c1_20261101_231926` 和 `c1_20261101_231926_1` 均已被占用
- **WHEN** Node 在同一本地秒再次普通新建 `c1`
- **THEN** Node 取得 `c1_20261101_231926_2`，不跳过序号、不复用前两个目录，也不改用无时间戳目录

#### Scenario: 并发创建只占用一个候选

- **GIVEN** 两个普通新建请求同时为同名容器生成相同的本地时间戳基名
- **WHEN** 两者尝试取得候选目录
- **THEN** 独占创建只允许一个请求取得该基名，另一个按序取得下一个序号，任一请求都不得与另一个共用同一目录

#### Scenario: 100 个候选耗尽不降级复用

- **GIVEN** 基名 `c1_20261101_231926` 及 `_1` 至 `_99` 共 100 个候选均已被占用
- **WHEN** Node 尝试普通新建 `c1`
- **THEN** 本次创建失败且不启动 Docker 创建，不复用任一既有目录，不改用无时间戳目录，也不尝试第 101 个候选

#### Scenario: 非碰撞错误不当作碰撞重试

- **GIVEN** 创建候选目录时发生权限不足、只读文件系统或其它非“已存在”错误
- **WHEN** Node 处理该错误
- **THEN** 本次创建失败并保留真实错误原因，不以碰撞重试或复用其它目录来掩盖

来源：[services/container_service.py](../../../services/container_service.py)。

### Requirement: 恢复挂载来源只由入参决定 [services/container_service.py]

恢复既有容器时，宿主挂载来源 SHALL 取请求携带的 `restore_mount_path`（已删除容器保留的宿主目录），MUST NOT 依据本次容器名重新推导，也 MUST NOT 因运行镜像的来源不同而改变。未携带该入参时才按普通新建目录命名与原子避让规则生成独立目录，不得复用同名历史目录。

`restore_mount_path` SHALL 经 realpath 规范化，并约束在容器挂载根目录之下且不得等于该根目录，且含 `containers` 路径段；目录不存在时 SHALL 拒绝该次创建。目标容器名已被本机占用时 SHALL 直接拒绝，MUST NOT 自行改名或改用其它挂载目录。恢复 MUST NOT 重命名、迁移或重新生成历史目录；历史目录名是否带时间戳、旧随机后缀或 `_N` 序号不影响其作为恢复源。

#### Scenario: 恢复沿用原目录

- **WHEN** 恢复请求携带原容器的宿主挂载目录
- **THEN** 挂载来源取该目录，与本次容器名和运行镜像的来源无关

#### Scenario: 改名不改变数据位置

- **WHEN** 恢复请求携带的容器名与原容器不同，而挂载入参仍指向原目录
- **THEN** 数据仍来自原目录，不按新名字推导新目录

#### Scenario: 越界或缺失的挂载入参被拒绝

- **WHEN** 挂载入参经规范化后超出容器挂载根、缺少 `containers` 段，或目录不存在
- **THEN** 本次创建被拒绝

#### Scenario: 恢复源等于当前公共根被拒绝

- **WHEN** 历史单容器目录后来成为当前容器挂载根，恢复入参经 realpath 规范化后恰好等于该根目录
- **THEN** 本次创建被拒绝，不把公共根当作该容器的历史数据目录

#### Scenario: 名字被占用即拒绝

- **WHEN** 本机已存在同名容器
- **THEN** 本次创建失败，不自行改名、不替换挂载来源

#### Scenario: 恢复不生成时间戳目录

- **GIVEN** 恢复请求携带一个已存在的历史目录，其名称不带时间戳、带旧随机后缀或带 `_N` 序号
- **WHEN** Node 按该 `restore_mount_path` 创建容器
- **THEN** Docker `/root` 的 bind Source 与返回的 `bind_mount_path` 均为该历史目录，不生成普通新建基名或带序号后缀的目录，也不重命名历史目录

#### Scenario: 恢复与当前时刻的普通新建候选同名

- **GIVEN** 恢复请求携带的历史目录名恰为 `<container_name>_<当前本地时间戳>`，或该基名加 `_N` 序号
- **WHEN** Node 处理该恢复
- **THEN** 仍以该历史目录为挂载来源，不因普通新建命名格式相同而改道或新建另一个候选

来源：[services/container_service.py](../../../services/container_service.py)、[network/api.py](../../../network/api.py)。

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

### ContainerConfig 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `gpu_list` | `list[int]` | `Field(default_factory=list, description='GPU device ids. Empty means CPU only.')` |
| `cpu_number` | `int` | `Field(..., ge=0)` |
| `memory` | `int` | `Field(..., ge=0, description='Memory limit in GB')` |
| `shared_memory` | `int` | `Field(..., ge=0, description='Shared memory size in GB')` |
| `name` | `str` | `必填` |
| `port` | `int` | `Field(..., ge=0, le=65535)` |
| `image` | `str` | `必填` |

### ImageBuildConfig 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `dockerfile_text` | `str` | `Field(default='', description='Ctrl 生成的最终 Dockerfile 文本。')` |
| `image_tag` | `str` | `Field(default='', description='最终 build 后用于 run 的镜像 tag。')` |

### RestoreAccountConfig 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `user_name` | `str` | `必填` |
| `role` | `CollaboratorRole` | `'collaborator'` |
| `password` | `SecretStr` | `必填`；瞬时值，长度 8–128，不含 `:`、CR、LF、NUL；仅用于 stdin `chpasswd`，不得持久化到 snapshot |

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

### CreateContainerResponse 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `success` | `int \| bool` | `Field(default=1)` |
| `container_status` | `Literal['building', 'creating']` | `必填` |
| `container_name` | `str` | `必填` |
| `action_ref` | `ActionRef \| None` | `None`；新 Node 成功受理时输出，旧 Node 可缺省 |

### ActionRef 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `node_epoch` | `str` | `必填` |
| `generation` | `int` | `Field(ge=0)` |
| `seq` | `int` | `Field(ge=0)` |

### Container.Config_info 数据契约 [utils/Container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `gpu_list` | `list` | `必填` |
| `cpu_number` | `int` | `必填` |
| `memory` | `int` | `必填` |
| `shared_memory` | `int` | `必填` |
| `name` | `str` | `必填` |
| `port` | `int` | `必填` |
| `image` | `str` | `必填` |

### CreateContainerReturn 数据契约 [services/container_service.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `container_id` | `str` | `必填` |
| `container_name` | `str` | `必填` |
| `port` | `int \| None` | `None` |
| `port_mappings` | `list \| None` | `None` |
| `bind_mount_path` | `str \| None` | `None` |

## Source references

- [schemas/container.py](../../../schemas/container.py)
- [services/container_service.py](../../../services/container_service.py)
- [network/api.py](../../../network/api.py)
- [utils/Container.py](../../../utils/Container.py)
- [tests/](../../../tests/)：默认套件 331 passed, 1 skipped, 16 deselected, 24 subtests passed；Docker 分项：旧用例 10 passed + 1 skipped、本变更专项 4 passed + 1 skipped；未合并重跑全量 `-m docker`。
