# Design

## Context

基线 `create_container` 先尝试 `<NODE_CONTAINERS_BASE>/<owner>/containers/<name>`；仅当该目录已存在时追加一个 5 位随机后缀。目录创建发生在 Docker 同名检查之前，随后统一执行 `chown`/`chmod`，并作为 Docker `/root` 的 bind Source；函数末尾把实际目录写入 `CreateContainerReturn.bind_mount_path`。恢复分支在同一段代码中把 `restore_mount_path` realpath 后直接作为挂载来源，不创建新目录。

现有测试已覆盖恢复沿用目录、改名不改数据位置和同名拒绝（见 `tests/test_create_container.py`、`tests/test_anvil_creation_credentials.py`），但没有覆盖普通新建的时间戳基名、碰撞序号和历史目录保留。主规格 `backend--container-creation` 的 `恢复挂载来源只由入参决定` 是本次唯一需要 MODIFIED 的既有 requirement；新增命名和碰撞规则作为同一能力的 ADDED requirement。动机见 [proposal.md](proposal.md)。

## Goals / Non-Goals

**Goals:**

- 普通新建总是使用本地时间戳基名 `<container_name>_YYYYMMDD_HHMMSS`；基名碰撞时按序追加 `_1`、`_2` 等短序号。
- 用文件系统独占创建解决同秒碰撞，并按 100 个候选的固定上限快速失败；不复用、不接管、不改名、不删除既有目录。
- 让实际取得的目录成为唯一挂载来源和 `bind_mount_path`。
- 恢复到既有 `restore_mount_path` 的行为保持不变，历史目录不迁移、不改名。
- 用最小改动保留既有权限、Docker 创建、返回值和错误处理路径。

**Non-Goals:**

- 不新增 API 字段、WSS topic、数据模型、数据库列/迁移或 Ctrl/Web/Global 改动。
- 不清理、迁移、重命名历史目录，也不改变 `clean_mount` 的清理语义。
- 不改变恢复路径的 realpath、范围、`containers` 段、存在性和同名容器校验。
- 不引入额外的时钟推进或休眠机制，也不调整目录创建与 Docker 同名检查的先后顺序。
- 不把目录分配扩展成通用锁或事务框架。

## Decisions

1. **本地时间戳基名**：新增一个只负责普通新建目录的小函数，例如 `_create_timestamped_mount_dir(containers_base, owner_name, container_name)`；基名为 `os.path.join(containers_base, owner_name, "containers", f"{container_name}_{datetime.now():%Y%m%d_%H%M%S}")`。使用 `datetime.now()` 的系统本地时区，不调用 `utcnow()`，不新增时区依赖。基名在进入候选循环前计算一次；后续碰撞只追加序号，不重新读取时钟。选择本地时间是因为目录名要直接反映节点所在时区的创建时刻；UTC 方案会让运维在本地文件系统上看到错位的日期。

2. **独占创建**：每个候选目录用 `os.makedirs(candidate, exist_ok=False)` 创建。Python 的该调用对叶子目录执行 `mkdir`，已存在时抛出 `FileExistsError`；这比“先 `exists()` 再创建”可靠，因为检查和创建之间没有可被并发插入的窗口。捕获且只捕获 `FileExistsError` 作为碰撞；权限不足、只读文件系统等其它 `OSError` 直接失败并保留真实原因，不能伪装成碰撞后继续换号。替代方案 `exist_ok=True` 会复用既有目录，明确拒绝。

3. **按序追加短序号，100 个候选封顶**：第一个候选是基名本身；碰撞后依次尝试 `<基名>_1`、`<基名>_2` ... `<基名>_99`，合计 100 个候选。每次 `FileExistsError` 后立即推进下一个序号，成功即返回；全部 100 个候选都失败时抛出稳定错误，并在任何 Docker `containers.run` 之前结束。这样后缀可预测、便于审计，重试也有明确上限。替代方案中，无上限重试可能长期挂起，拒绝；直接复用同名目录或回退到无时间戳目录会造成历史数据混用，拒绝。

4. **恢复分支不经过新函数**：保留现有 `if restore_mount_path:` 分支和其全部校验；只有 `else` 分支调用新的时间戳目录函数。恢复请求无论历史目录名是无时间戳、旧随机后缀、时间戳基名还是带 `_N` 序号，都直接使用 realpath 后的既有目录，不生成新候选，也不改名。这样把“普通新建命名”和“恢复沿用路径”在代码路径上彻底分开。

5. **权限与返回路径保持一致**：新函数只负责取得唯一目录；创建后的 `os.stat`、`chown`、`chmod` 仍由现有代码执行。函数返回的路径必须用于 `Mount(target="/root", source=...)` 和最终 `CreateContainerReturn.bind_mount_path`，不得保留一份旧的候选路径再用于挂载。

6. **测试策略**：服务层测试继续通过 `create_container` 验证实际 bind Source 与返回值。测试用 `monkeypatch` 替换模块级 `datetime`，固定本地时间，确保基名计算稳定；碰撞测试预置候选目录：
   - 基名可用时的本地时间戳命名、路径拼接和无时间戳目录隔离；
   - 基名碰撞取得 `_1`，基名与 `_1` 都占用时取得 `_2`，旧目录内容不变；
   - 100 个候选全部占用时失败且不调用 Docker；
   - 恢复请求预置历史目录时不产生时间戳基名或序号目录；
   - 通过 `bind_mount_path` 与 `mounts[0]["Source"]` 的 `samefile` 断言路径一致性。

## Risks / Trade-offs

- **100 个候选仍全部碰撞** → 直接失败关闭，不无限重试、不复用旧目录；正常场景下同秒同名连续创建远少于 100 个。
- **确定性序号暴露创建顺序** → 这是可预测、可审计的代价；后缀只来自 `_1` 至 `_99` 的序号。
- **目录创建仍早于 Docker 同名检查** → 同名容器已存在时可能留下一个空的 timestamp 目录；这是既有创建顺序的延续，本次不清理、不移动，避免扩大范围。后续如需清理应作为独立变更。
- **历史目录完全不动** → 不自动整理旧的无时间戳/随机后缀目录；恢复依赖 Ctrl 已保存的 `bind_mount_path`，这与现有恢复契约一致。
- **路径长度增加** → 容器名最长 115 字符，加 16 字符基名时间戳和最多 3 字符的 `_99` 后仍低于常见 Linux `NAME_MAX` 255；不新增名称校验规则。

## Migration Plan

- 仅部署 Node 代码；旧容器继续使用原有宿主目录，新普通创建使用时间戳基名或序号后缀目录。
- 不需要 Ctrl/Web 配套改动或部署顺序协调；Ctrl 读取既有 `bind_mount_path` 并在恢复时回传，天然兼容两种目录名。
- 回滚即恢复旧代码；已经创建的时间戳目录保留，后续恢复仍可按已记录路径使用，不依赖代码重新推导。
- 上线前验证：新增命名/碰撞/恢复测试通过；既有恢复、同名拒绝和创建挂载测试不回归；`openspec validate --strict` 通过。

## Open Questions

无。碰撞采用 `_1` 至 `_99` 的确定性序号并以 100 个候选封顶，已按实现口径确定，不需要额外产品决策。
