## Context

Q30 是在 Windows 默认安全套件上复现的测试基础设施问题，不是 Node 生产行为缺陷。旧版 `tests/test_create_container.py` 通过 `_patch_fs()` 替换进程全局 `os.makedirs`、`os.stat`、`chmod`、`chown`、`getuid`、`getgid`，其中假 stat 只有 `st_uid`/`st_gid`。测试失败后，pytest 的 linecache/traceback 会读取 `st_size`/`st_mtime`，cacheprovider 会读取 `st_mode`，于是真实断言被 `AttributeError` 内部错误替代。恢复挂载用例还全局替换 `os.path.isdir`，并依赖 `/tmp/...` 这样的 POSIX 字面路径。

Q30 基线在排除该文件后还有 5 项 Windows 失败：4 个 `test_clean_mount` 路径用例和 1 个依赖真实 `du` 的磁盘用量用例。当前代码已分别用 `tmp_path` 和假 `subprocess.run` 关闭这些失败；真实 `du` 集成用例在工具缺失时显式 skip。本 change 需要同时记录这 5 项现状，避免把“任务已勾选”误当成 Q30 全文验收。

## Goals / Non-Goals

**Goals:**

- 移除创建容器测试对进程全局 `os.*` 的不完整替换，改用每个用例独立的真实 `tmp_path` 挂载根。
- 恢复挂载用例使用真实目录和 `samefile`，同时覆盖 Windows 与 WSL/Linux 路径语义。
- 挂载用量测试只替换被测模块看到的 `os` 视图，进程全局 `os.stat` 保持不变。
- 用最小、可观察的回归锁住“挂载准备后全局 `os.stat` 仍是真实且完整的实现”，不依赖 `linecache` 私有缓存结构。
- 把测试运行时要求放入既有 `procedure--repository-workflow` capability，维持 Node 8 个 `backend--` 业务能力边界。
- 记录 Windows 与 WSL 的真实套件结果，以及历史 4 路径和 du 用例的当前状态。

**Non-Goals:**

- 不修改生产代码、协议、数据结构或部署行为。
- 不重构测试目录，不新增测试框架或 pytest 插件。
- 不运行或改造真实 Docker/GPU 集成测试。
- 不新增第 9 个 `backend--` capability。
- 不在本 change 内修改主规格、QUESTIONS 或独立 review.md；归档时再按 OpenSpec 流程同步 delta。

## Decisions

### Decision: 使用真实 `tmp_path`，不维持“完整 stat 假对象”

创建容器测试通过 autouse fixture 把 `NODE_CONTAINERS_BASE` 指向 `tmp_path / "home"`，让挂载准备真实执行 `makedirs`、`stat`、`chmod` 等调用。这样 stat 字段天然完整，也不会让 pytest 自身看到替身。

备选方案是给假 stat 补齐 `st_size`/`st_mtime`/`st_mode`。它能避免当前崩溃，但仍会把进程全局 `os.stat` 换成测试对象，继续影响 pytest 和其它并行代码；因此拒绝。另一个备选是只把假 stat 挂到 `container_service` 模块视图；因为生产模块直接引用全局 `os`，需要额外代理层，且真实临时目录已经能隔离副作用，所以不采用。

### Decision: 权限错误模拟只替换被测模块视图

`tests/test_mount_usage_cache.py` 需要让特定路径的 `stat` 抛 `PermissionError`。这里使用 `_ModuleOsView` 替换 `du_module.os`，只覆盖 `stat`，其余属性委托真实 `os`；进程全局 `os.stat` 不变，并在用例内断言 `os.stat is real_stat`。

备选方案是继续 `monkeypatch.setattr(du_module.os, "stat", ...)`。`du_module.os` 就是全局 `os` 模块，作用域没有真正缩小；因此拒绝。

### Decision: 回归收窄为全局 stat 不变量

本 change 的修复是“删除全局替身”，不是“让替身支持失败报告”。因此回归测试直接断言：执行一次真实挂载准备后，`os.stat` 仍是原对象，且对测试源文件返回 `st_size > 0`、`S_ISREG(st_mode)` 的完整结果。这比手动制造 traceback 更贴近修复，也避免依赖 CPython `linecache` 内部实现。

备选方案是使用 `pytester` 或子进程 pytest 生成一个失败报告。它能验证框架行为，但需要额外插件/子进程编排，且当全局 stat 被重新替换时会先被本不变量断言捕获；对本 Q30 修复属于过度框架，因此不采用。旧测试对 `linecache.cache` 长度为 4、第二项非空的断言已删除。

### Decision: 要求归入 `procedure--repository-workflow`

Node 业务规格固定为 8 个 `backend--` 能力单元；测试运行时隔离属于仓库测试流程，不是服务端业务能力。delta 放在 `specs/procedure--repository-workflow/spec.md`，原 `specs/backend--test-runtime/spec.md` 删除。这样不会在归档时生成第 9 个 `backend--` 主规格。

### Decision: 历史 4 路径与 1 du 失败按现状记录

- 4 个路径失败：`test_accepts_legitimate_container_mount_dir`、`test_rm_failure_raises`、`test_rm_failure_surfaces_stderr`、`test_rm_failure_truncates_huge_stderr`。测试侧已使用 `tmp_path` 真实目录，服务端路径校验已使用 `normcase`/`os.sep`；Windows 默认套件通过。
- 1 个 du 失败：`test_disk_usage_cache_bind_cache_sources`。测试改为假 `subprocess.run` 并轮询等待 `fresh`；两个真实 du 集成用例在 `shutil.which("du") is None` 时 skip，不再失败。

这些是存量测试已关闭的事实，本 change 只记录证据，不为它们新增生产兼容层。

## Risks / Trade-offs

- [真实文件系统在 Windows 与 Linux 的权限语义不同] → Windows 无 `chown`/`getuid` 时走生产已有的安全兜底；WSL 真实执行 `chown(self)`/`chmod`。两端完整套件均通过。
- [真实 du 集成用例在 Windows 上 skip] → 假 `subprocess.run` 用例覆盖测量、缓存、并发和错误映射；真实 du 覆盖保留在具备工具的 WSL/Linux 环境，skip 数在 test-plan/verify 明确记录。
- [仍有其它委托式全局 monkeypatch] → `tests/test_verify_bind_mount.py` 的 `os.scandir` 等测试包装器仍委托真实实现，不属于 Q30 的不完整 stat 替身；本 change 按最小范围不扩展处理。
- [review 结论会因 proposal/design/specs 修改而失效] → 不自行写 `CHANGES_APPLIED: yes`；等待独立 reviewer 复核本 change 的 Required Changes 后再更新 verify 结论。

## Migration Plan

1. 应用测试与 delta 规格修改。
2. 在 Windows 与 WSL 分别运行默认安全套件并记录命令、版本、pass/skip/deselect。
3. 更新 tasks/test-plan；独立 reviewer 复核 M1-M4。
4. reviewer 将 `CHANGES_APPLIED` 置为 `yes` 后，再重新生成 verify 的最终结论；本 change 不涉及部署或回滚。

## Open Questions

无实现层未决问题。唯一外部门禁是独立复核；在复核完成前 verify 不得标记 PASS。
