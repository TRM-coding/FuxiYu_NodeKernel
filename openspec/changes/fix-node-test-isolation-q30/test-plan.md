## 测试计划

| Requirement | Scenario | 测试文件 | 测试名称 | 当前状态 |
|-------------|----------|-----------|-----------|---------------|
| specs/procedure--repository-workflow/spec.md → 测试替身不得污染测试运行时 | 挂载准备使用真实临时目录 | tests/test_create_container.py | test_create_container_mount_setup_keeps_global_os_stat_real | 🟢 已通过 |
| specs/procedure--repository-workflow/spec.md → 测试替身不得污染测试运行时 | 权限模拟限制在被测模块 | tests/test_mount_usage_cache.py | test_path_gate_maps_permission_error_without_stat | 🟢 已通过 |

## 覆盖说明

- 额外覆盖：`tests/test_mount_usage_cache.py::test_invalid_not_found_and_permission_never_start_du` 也断言全局 `os.stat` 未变，防止第二个权限模拟用例重新引入全局替换。
- 旧回归对 `linecache.cache` 私有元组长度和 mtime 的断言已删除；新回归只断言全局 stat 对象身份及 `st_size`/`st_mode` 完整性。
- 历史 Q30 的 5 项 Windows 失败现状：
  - 4 个路径用例 `test_accepts_legitimate_container_mount_dir`、`test_rm_failure_raises`、`test_rm_failure_surfaces_stderr`、`test_rm_failure_truncates_huge_stderr` 使用 `tmp_path` 真实目录，服务端用 `normcase`/`os.sep` 归一化路径；Windows 默认套件通过。
  - 1 个 du 用例 `test_disk_usage_cache_bind_cache_sources` 使用假 `subprocess.run` 并轮询等待 `fresh`，不再依赖真实 du；两个真实 du 集成用例在 `du` 缺失时显式 skip。
- 本次没有新增 pytest 插件、子进程测试框架或测试目录。

## 执行证据

| 平台 | 解释器与版本 | 命令 | 结果 |
|------|--------------|------|------|
| Windows | Python 3.11.15，pytest 9.1.1，docker 7.2.0 | `E:\Miniconda3\envs\lianjue\python.exe -m pytest tests -q --no-header -rs` | `362 passed, 5 skipped, 16 deselected in 6.23s` |
| WSL Ubuntu | Python 3.10.20，pytest 9.1.1，docker 7.2.0 | `cd /mnt/e/AI/Fuxi/FuxiYu_NodeKernel && /home/chest/miniconda3/envs/fuxi/bin/python -m pytest tests -q --no-header -rs` | `367 passed, 16 deselected in 5.95s` |

Windows 的 5 个 skip：2 个 `du unavailable`（`tests/test_mount_usage_api.py:276`、`tests/test_mount_usage_cache.py:378`），3 个 `symlink not permitted`（`tests/test_clean_mount.py:80`、`tests/test_mount_usage_cache.py:174`、`tests/test_mount_usage_cache.py:807`）。WSL 完整套件无 skip。

## 审查门禁

- 独立 review 为 `VERDICT: APPROVE_WITH_CHANGES`，审查者已复核 M1-M4 并确认 `CHANGES_APPLIED: yes`。
