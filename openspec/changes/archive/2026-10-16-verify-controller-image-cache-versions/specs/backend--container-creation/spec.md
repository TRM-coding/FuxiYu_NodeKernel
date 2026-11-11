## MODIFIED Requirements

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
