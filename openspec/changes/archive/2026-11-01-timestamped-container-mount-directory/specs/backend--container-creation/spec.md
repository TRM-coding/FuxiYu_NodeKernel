# Spec Delta

## MODIFIED Requirements

### Requirement: 恢复挂载来源只由入参决定 [services/container_service.py]

恢复既有容器时，宿主挂载来源 SHALL 取请求携带的 `restore_mount_path`（已删除容器保留的宿主目录），MUST NOT 依据本次容器名重新推导，也 MUST NOT 因运行镜像的来源不同而改变。未携带该入参时才按本变更新增的普通新建目录命名与原子避让规则生成独立目录，不得复用同名历史目录。

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

来源：[services/container_service.py](../../../../../services/container_service.py)、[network/api.py](../../../../../network/api.py)。

## ADDED Requirements

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

来源：[services/container_service.py](../../../../../services/container_service.py)。

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

来源：[services/container_service.py](../../../../../services/container_service.py)。
