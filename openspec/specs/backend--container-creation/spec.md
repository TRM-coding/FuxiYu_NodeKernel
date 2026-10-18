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

系统 SHALL 保持以下已实现的职责：恢复协作者账号只接受 admin/collaborator，ROOT 由 owner_name 单独恢复；公开 SSH 公钥只用于安装，不记录私钥。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例

来源：[schemas/container.py](../../../schemas/container.py)。

### Requirement: CreateContainerMessage 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。

字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：创建请求携带 owner_name、config、可选镜像构建内容和恢复挂载/账号；入口登记 building/creating 后立即受理，Docker 工作在后台线程执行。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例

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

### Requirement: 恢复挂载来源只由入参决定 [services/container_service.py]

恢复既有容器时，宿主挂载来源 SHALL 取请求携带的 `restore_mount_path`（已删除容器保留的宿主目录），MUST NOT 依据本次容器名重新推导，也 MUST NOT 因运行镜像的来源不同而改变。未携带该入参时才按 `NODE_CONTAINERS_BASE` / owner / 容器名推导新建目录。

`restore_mount_path` SHALL 经 realpath 规范化，并约束在容器挂载根目录之下且含 `containers` 路径段；目录不存在时 SHALL 拒绝该次创建。目标容器名已被本机占用时 SHALL 直接拒绝，MUST NOT 自行改名或改用其它挂载目录。

#### Scenario: 恢复沿用原目录

- **WHEN** 恢复请求携带原容器的宿主挂载目录
- **THEN** 挂载来源取该目录，与本次容器名和运行镜像的来源无关

#### Scenario: 改名不改变数据位置

- **WHEN** 恢复请求携带的容器名与原容器不同，而挂载入参仍指向原目录
- **THEN** 数据仍来自原目录，不按新名字推导新目录

#### Scenario: 越界或缺失的挂载入参被拒绝

- **WHEN** 挂载入参经规范化后超出容器挂载根、缺少 `containers` 段，或目录不存在
- **THEN** 本次创建被拒绝

#### Scenario: 名字被占用即拒绝

- **WHEN** 本机已存在同名容器
- **THEN** 本次创建失败，不自行改名、不替换挂载来源

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

### CreateContainerMessage 数据契约 [schemas/container.py]

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `owner_name` | `str` | `必填` |
| `config` | `ContainerConfig` | `必填` |
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
