## Why

Q30 的 Windows 基线包含两段问题：`tests/test_create_container.py` 用只有 `st_uid`/`st_gid` 的对象替换进程全局 `os.stat`，用例失败后 pytest 读取源码时缺 `st_size`/`st_mode`，真实断言被内部错误掩盖；排除该文件后还有 5 项失败——4 个 `test_clean_mount` 路径用例依赖字面 `/containers/`，1 个磁盘用量用例依赖真实 `du`。

当前状态已分开：4 个路径用例改用 pytest `tmp_path` 构造真实目录，服务端路径校验用 `normcase`/`os.sep` 归一化，Windows 默认套件通过；依赖真实 `du` 的基线用例改用假 `subprocess.run` 并轮询等待结果，独立的真实 `du` 集成用例在 `du` 不存在时安全 skip，不再制造失败。仍需要关闭的是全局 `os.stat` 替身及其对失败报告路径的副作用。

## What Changes

- `tests/test_create_container.py` 删除对进程全局 `os.makedirs`、`os.stat`、`chmod`、`chown`、`getuid`、`getgid` 和 `os.path.isdir` 的替换；每个用例通过 autouse fixture 使用 `tmp_path / "home"` 作为 `NODE_CONTAINERS_BASE`。
- 恢复挂载用例改用 `tmp_path` 下真实目录，并用 `os.path.samefile` 比较，不再依赖 `/tmp/...` 字面路径或全局 `isdir` 谓词。
- `tests/test_mount_usage_cache.py` 只替换被测模块看到的 `du_module.os` 视图；权限错误模拟不再触碰进程全局 `os.stat`，并在用例内断言全局实现未变。
- 回归断言收窄为可观察的全局 stat 不变量：挂载准备后 `os.stat` 仍是原实现，且对测试源文件返回含 `st_size`/`st_mode` 的完整结果；不读取 `linecache.cache` 私有元组，不引入 pytest 子进程框架。
- 测试运行时隔离要求放入既有 `procedure--repository-workflow` capability 的 delta；删除新建 `backend--test-runtime` delta，不新增第 9 个 Node `backend--` 业务能力。

历史 4 个路径失败为 `test_accepts_legitimate_container_mount_dir`、`test_rm_failure_raises`、`test_rm_failure_surfaces_stderr`、`test_rm_failure_truncates_huge_stderr`；历史 1 个 du 失败为 `test_disk_usage_cache_bind_cache_sources`。它们当前均已在 Windows 默认套件通过，剩余两个真实 du 用例按环境 skip。

## Capabilities

### New Capabilities

- 无。本 change 不新增 capability。

### Modified Capabilities

- `procedure--repository-workflow`: 新增“测试替身不得污染测试运行时”的要求，覆盖真实临时目录挂载准备和模块局部权限模拟两个场景。

## Impact

- 仅测试与 change 文档：`tests/test_create_container.py`、`tests/test_mount_usage_cache.py`。
- 不改变生产行为、协议、数据结构、测试目录结构或 Docker/GPU 集成范围。
- 已验证 Windows `362 passed, 5 skipped, 16 deselected`；WSL `367 passed, 16 deselected`。详见 test-plan 与 verify。
