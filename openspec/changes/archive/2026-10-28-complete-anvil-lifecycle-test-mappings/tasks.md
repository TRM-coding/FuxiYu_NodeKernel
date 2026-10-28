# Tasks

## 1. 测试文件与隔离基座

- [x] 1.1 新建唯一测试文件 `tests/test_anvil_lifecycle_contracts.py`，只提供本文件使用的 fake Docker 接线、缓存/Schema 构造 helper 与逐测试清理（worker、patch、queue、deleted 候选、后台线程），不修改 `tests/runtime_fakes.py`、`tests/conftest.py` 或既有测试。验证：`wsl -d Ubuntu -- /home/chest/miniconda3/envs/fuxi/bin/python -m pytest tests/test_anvil_lifecycle_contracts.py --collect-only -q` 能收集本文件，且收集数量与 plan 的 29 个 locator 一致。

## 2. 数据契约缺口

- [x] 2.1 实现 `test_name_config_alias_and_field_validation`、`test_container_message_models_require_config`、`test_container_response_models_default_success_and_optional_fields`、`test_pause_config_default_and_literal_rejection`、`test_container_status_literal_domain`、`test_wire_alias_models_preserve_shapes`、`test_internal_enums_and_remove_result_contracts`、`test_internal_enum_type_boundary`、`test_machine_status_type_boundary`。对应 test-plan：`backend--container-lifecycle → ContainerNameConfig/PauseContainerConfig/MachineStatus/RemoveContinaerReturn 等数据契约 → 字段校验与缺省值/使用声明值域/内部值传递`。验证：`wsl -d Ubuntu -- /home/chest/miniconda3/envs/fuxi/bin/python -m pytest tests/test_anvil_lifecycle_contracts.py -q -k "name_config or message_models or response_models or pause_config or status_literal or wire_alias or internal_enum or machine_status"`。

## 3. 状态响应、WSS 与事件

- [x] 3.1 实现 `test_status_response_hard_block_fields`、`test_last_ssh_wss_allows_none`、`test_event_positive_trace_and_unknown_diagnostic`、`test_event_inspect_failure_keeps_last_known_with_diagnostic`、`test_late_state_event_does_not_rollback_online`。对应 test-plan：`backend--container-lifecycle → Docker 状态事件兼容 / ContainerStatusResponse 数据契约 / 统一动作序号与旧写抑制 → 事件只有 Action/事件不直接写运行态/未知事件/运行态与动作诊断同响应/迟到事件不回滚新状态`。验证：`... -m pytest tests/test_anvil_lifecycle_contracts.py -q -k "status_response or last_ssh or event"`。

## 4. 动作与硬阻塞边界

- [x] 4.1 实现 `test_unpause_docker_error_uses_fresh_inspect`、`test_repeated_pause_on_paused_is_idempotent`、`test_repeated_unpause_without_ready_keeps_ready_check`、`test_hard_block_survives_action_ttl`、`test_sshd_not_installed_probe_sets_hard_block`、`test_exited_is_offline_without_hard_block`、`test_dead_hard_block_survives_event_and_stale_observation`、`test_hard_block_cleared_by_recreated_object`。对应 test-plan：`backend--container-lifecycle → pause 与 unpause 的新鲜实态确认 / 硬阻塞边界与恢复 / 运行态与动作结果分离 → 其他 Docker 错误/重复 pause/重复 unpause/动作 TTL/sshd 未安装/正常退出/dead/删除重建恢复`。验证：`... -m pytest tests/test_anvil_lifecycle_contracts.py -q -k "unpause or repeated_pause or hard_block or sshd or exited or dead"`。

## 5. 代际、采集、重启与有界记录

- [x] 5.1 实现 `test_identity_change_invalidates_old_delete_candidate`、`test_create_pending_identity_deferral_is_diagnosed`、`test_new_generation_rejects_old_ref`、`test_list_failure_keeps_last_known_and_reports_collect_error`、`test_unknown_recovers_on_next_successful_observe`、`test_restart_does_not_revive_old_failed_pending`、`test_action_records_are_bounded`。对应 test-plan：`backend--container-lifecycle → 对账观察边界/共享本地代际与同名对象更换/未知与采集错误保留最后已知/冷启动运行态重建/last_action 诊断与终结语义 → 同名 Docker ID 更换/create pending 延迟/旧代观察失效/列表失败/unknown 恢复/旧 failed pending/记录有界`。验证：`... -m pytest tests/test_anvil_lifecycle_contracts.py -q -k "identity_change or create_pending or new_generation or list_failure or unknown_recovers or restart_does_not or records_are_bounded"`。

## 6. 新文件与相关既有套件

- [x] 6.1 运行新文件完整测试，确认 29 个 locator 全部存在且本文件无 worker/patch/queue 泄漏；验证：`... -m pytest tests/test_anvil_lifecycle_contracts.py -q` 退出码为 0。
- [x] 6.2 运行本生命周期相关既有套件（不跑全基线）：`tests/test_runtime_guard.py tests/test_runtime_barriers.py tests/test_prevent_vanished.py tests/test_action_contracts.py tests/test_action_inspect_errors.py tests/test_blueprint_api.py tests/test_cache_collectors.py`；验证：同一命令退出码为 0，日志写入 `E:\AI\Fuxi_audit_artifacts\anvil-rollout-2026-10-28\node-batch-3\`。
- [x] 6.3 运行官方 `openspec-verify-change` advisory（不创建 `verify.md`），核对 change、delta、test-plan、新测试与既有套件一致性；验证：verify 输出/advisory 无 blocker，且 `get-childitem ...\verify.md` 不存在。

## Workflow follow-up

- official `openspec sync specs` 保持主规格 42/93 与 SHA 不变。
- official sync 成功后按 `anvil-test-plan` 写 `openspec/specs/backend--container-lifecycle/test-plan.md`。
- official archive 本次 change 到北京时间 2026-10-28 归档目录。
- 父代理统一 Git 验收 commit；本会话不 commit/push。
