# 容器创建

## Purpose

接收资源/镜像构建/恢复输入，后台创建 Docker 容器，受理态与最终状态分别表达。本文件是 chester-next 33672c4edd96 在 2026-10-11 的代码逆向基线，按能力组织相关类型而非每个 class 单独建文件。完整字段、继承与兼容定义保留在下列 Requirements 中；跨能力使用以公共类型及源文件为准，已知问题集中于 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)。

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

系统 SHALL 保持以下已实现的职责：dockerfile_text 为 Ctrl 生成的最终 Dockerfile，image_tag 为最终制品 tag；正文为空走既有镜像，不把用户模板和完整 Dockerfile 混同。

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

系统 SHALL 保持以下已实现的职责：仅表示创建已受理，状态为 building 或 creating；端口和挂载路径稍后由快照同步，成功受理不等同容器已 online。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例



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
- [utils/Container.py](../../../utils/Container.py)
- [tests/](../../../tests/)：Linux 安全默认套件 152 passed、11 deselected；未运行 Docker 集成测试。
