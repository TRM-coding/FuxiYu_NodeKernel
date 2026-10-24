## 1. 测试隔离实现

- [x] 1.1 删除 `tests/test_create_container.py` 对进程全局 `os.makedirs`、`os.stat`、`chmod`、`chown`、`getuid`、`getgid` 和 `os.path.isdir` 的替换，改用 autouse `tmp_path` 挂载根。
- [x] 1.2 恢复挂载用例使用 `tmp_path` 真实目录和 `os.path.samefile`，移除 `/tmp/...` 字面路径预期。
- [x] 1.3 将 `tests/test_mount_usage_cache.py` 的 stat 替身限制为被测模块 `du_module.os` 视图，并断言全局 `os.stat` 不变。

## 2. Q30 回归与证据

- [x] 2.1 将回归收窄为“挂载准备后全局 `os.stat` 仍是真实且完整实现”；删除 `linecache.cache` 私有元组断言。
- [x] 2.2 运行 Windows 完整安全套件：`362 passed, 5 skipped, 16 deselected`；记录 Python 3.11.15 / pytest 9.1.1。
- [x] 2.3 运行 WSL Ubuntu 完整安全套件：`367 passed, 16 deselected`；记录 Python 3.10.20 / pytest 9.1.1。
- [x] 2.4 在 proposal/design/test-plan 记录历史 4 个路径失败、1 个 du 失败及当前 `tmp_path`/假 du/真实 du skip 状态。

## 3. Change 结构与复核

- [x] 3.1 将测试运行时要求 delta 从 `backend--test-runtime` 移入 `procedure--repository-workflow`，删除旧 backend delta，不新增第 9 个 `backend--` 能力。
- [x] 3.2 更新 proposal、design、test-plan，并生成 verify 的真实测试证据。
- [x] 3.3 独立 reviewer 复核 M1-M4 并确认 Required Changes，review 已由审查者置 `CHANGES_APPLIED: yes`。
