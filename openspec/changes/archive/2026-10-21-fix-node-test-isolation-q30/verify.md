# 实施验证

## 任务与审查

- [x] 10 项任务完成，两个场景均有具名测试映射并通过。
- [x] 测试要求归入既有 `procedure--repository-workflow`，没有第九个业务能力。
- [x] 独立审查 `VERDICT: APPROVE_WITH_CHANGES`，M1-M4 由审查者复核后置 `CHANGES_APPLIED: yes`（DSH `f7cab2c4-637c-4427-91fa-5d27a5c4af94`）。
- [x] proposal/design/specs 在此次复核后没有改变。
- [x] 没有削弱业务断言；新加回归去掉私有 linecache 缓存假设，按已复审规格准确验证全局 stat 的对象与完整字段不变量。

## 真实测试证据

由 DSH `dc2c1ec0-0bad-4795-a4da-e6217daa2de9` 在修订后执行，父任务已核对测试与证据。父任务在前次实现也独立复跑过同一完整套件。

| 环境 | 命令 | 结果 |
| --- | --- | --- |
| Windows Python 3.11.15 / pytest 9.1.1 | `E:\Miniconda3\envs\lianjue\python.exe -m pytest tests -q --no-header -rs` | 362 通过、5 跳过、16 排除 |
| WSL Ubuntu Python 3.10.20 / pytest 9.1.1 | `cd /mnt/e/AI/Fuxi/FuxiYu_NodeKernel && /home/chest/miniconda3/envs/fuxi/bin/python -m pytest tests -q --no-header -rs` | 367 通过、0 跳过、16 排除 |
| 定向回归 | `pytest tests/test_create_container.py::test_create_container_mount_setup_keeps_global_os_stat_real tests/test_mount_usage_cache.py::test_path_gate_maps_permission_error_without_stat tests/test_mount_usage_cache.py::test_invalid_not_found_and_permission_never_start_du -q --no-header -rs` | 3 通过 |

Windows 的 5 项环境性跳过为 2 个真实 du 用例与 3 个符号链接用例，已由 WSL 默认完整套件全部执行。16 项真实 Docker/GPU 测试由原 pytest 默认策略排除，没有执行生产验证，不宣称 Docker/GPU 验收。无生产代码、数据库、协议或目录结构改动。

## 交付

初次实现提交 `ed5c1ba`；本次复审修订由父任务按用户要求提交。保留各平台测试限制，不把任务勾选或 OpenSpec 格式校验当作运行证明。

DECISION: PASS_WITH_WARNINGS
