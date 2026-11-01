# Proposal

## Why

普通新建容器当前先尝试 `<NODE_CONTAINERS_BASE>/<owner>/containers/<name>`，仅在目录已存在时才追加 5 位随机后缀；目录名不能稳定表达创建时间，随机后缀也不便于审计。同名容器重建时，历史目录与新建目录的边界也不够明确。

需要把普通新建的宿主目录固定为带本地时间戳的基名，并在基名碰撞时按确定性的 `_1`、`_2` 等短序号原子避让；已有目录不重命名，恢复继续使用既有路径，避免把历史数据误当作新实例目录。

## What Changes

- 普通新建（未携带 `restore_mount_path`）的宿主挂载目录 SHALL 使用基名 `<NODE_CONTAINERS_BASE>/<owner>/containers/<container_name>_YYYYMMDD_HHMMSS`，时间取 Node 本地时间，精确到秒；基名可用时直接使用基名，基名碰撞时依次追加 `_1` 至 `_99` 的十进制短序号。
- 目录 SHALL 以 `exist_ok=False` 的独占创建取得；碰撞后立即按序尝试下一个候选，最多 100 个候选（基名加 `_1` 至 `_99`）。MUST NOT 复用、接管、重命名或删除既有目录，也不得跳过候选或回退到无时间戳目录；碰撞后缀 MUST 限于 `_1` 至 `_99` 的十进制序号。
- 创建成功后的实际目录 SHALL 作为 Docker `/root` 的 bind Source，并作为 `bind_mount_path` 的事实返回；不新增或修改 HTTP/WSS 字段。
- 恢复（携带 `restore_mount_path`）SHALL 继续使用请求给出的既有目录，MUST NOT 按本次容器名重新推导时间戳目录，也 MUST NOT 重命名历史目录；既有 realpath、范围、`containers` 段、目录存在和同名容器拒绝规则保持不变。
- 补充回归场景，覆盖命名格式与本地时间、同秒碰撞的 `_1`/`_2` 序号避让、100 个候选的原子有界上限、历史无时间戳/旧随机后缀/时间戳目录不被改名，以及恢复仍使用原路径。
- 不修改主规格、归档目录或历史 change；不改变创建接口、数据模型、Docker 运行参数形状、Ctrl/Web 消费方式或数据库。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--container-creation`: 明确普通新建目录的本地时间戳基名、`_1` 至 `_99` 序号避让和 100 个候选的原子有界重试，并保持恢复按既有路径继续。

## Impact

仅影响 Node 的 `services/container_service.py` 普通新建挂载目录生成/创建逻辑及对应服务层回归测试；`CreateContainerReturn.bind_mount_path` 与既有 WSS 路径字段继续承载实际目录。无新增依赖、API 字段、数据库迁移或跨仓库改动。
