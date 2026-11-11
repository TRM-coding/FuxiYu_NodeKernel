# Spec Delta

## MODIFIED Requirements

### Requirement: 恢复挂载来源只由入参决定 [services/container_service.py]

恢复既有容器时，宿主挂载来源 SHALL 取请求携带的 `restore_mount_path`（已删除容器保留的宿主目录），MUST NOT 依据本次容器名重新推导，也 MUST NOT 因运行镜像的来源不同而改变。未携带该入参时才按 `NODE_CONTAINERS_BASE` / owner / 容器名推导新建目录。

`restore_mount_path` SHALL 经 realpath 规范化，并约束在容器挂载根目录之下且不得等于该根目录，且含 `containers` 路径段；目录不存在时 SHALL 拒绝该次创建。目标容器名已被本机占用时 SHALL 直接拒绝，MUST NOT 自行改名或改用其它挂载目录。

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

来源：[services/container_service.py](../../../services/container_service.py)、[network/api.py](../../../network/api.py)。
