# Tasks

## 1. 账号模型、响应与服务映射

- [x] 1.1 在 `tests/test_anvil_accounts_procedure.py` 实现账号 wire/response 规划测试：`test_add_collaborator_config_required_and_identity_fields`、`test_add_collaborator_message_requires_outer_config`、`test_add_collaborator_response_default_and_required_message`、`test_remove_collaborator_wire_models_and_response_default`、`test_update_role_config_required_fields_and_optional_defaults`、`test_update_role_message_requires_outer_config`、`test_update_role_response_defaults_and_role_shapes`、`test_role_literal_values_and_runtime_enum_are_distinct`；验证：对应 pytest 节点通过。
- [x] 1.2 实现新增协作者密码、失败脱敏、角色组、旧 ROOT 降级与 ROOT 交接规划测试：`test_add_collaborator_missing_or_invalid_password_http_422`、`test_add_collaborator_failure_path_redacts_and_no_fallback`、`test_add_collaborator_role_group_matrix`、`test_update_role_password_matrix_rejects_collaborator_root_password_and_admin_invalid`、`test_admin_demotion_joins_admin_group_without_touching_root`、`test_root_handover_order_and_binding_isolation`、`test_root_handover_multiple_old_roots_single_target`；验证：对应 pytest 节点通过，fake Docker 记录 argv/stdin，不执行真实 adduser/chpasswd。
- [x] 1.3 实现恢复账号、家目录 chown、恢复挂载与 ROOT 清理记录式替身测试：`test_restore_accounts_rebuild_each_entry_and_fail_closed`、`test_restore_account_home_chown_targets_new_account`、`test_restore_mount_preserves_files_and_reuses_source`、`test_root_cleanup_records_only_with_all_state_command_doubles`；验证：对应 pytest 节点通过；完整清理命令仅在临时 PATH 的记录式 `id/deluser/mv/userdel/rm/date` 替身下执行，宿主 sentinel 不变。
- [x] 1.4 实现 reset 服务/API/断开规划测试：`test_reset_password_service_binds_user_and_root_stdin`、`test_reset_password_no_persistence_and_no_retry`、`test_reset_password_missing_or_stopped_container_no_exec`、`test_reset_password_invalid_inputs_http_422`、`test_reset_password_http_disconnect_does_not_cancel_chpasswd`；验证：对应 pytest 节点通过；ASGI `http.disconnect` 为进程内注入，服务完成后清理 worker/task/client。

## 2. procedure 与 PR 正文映射

- [x] 2.1 实现 commit-msg、pre-commit、PR 标题与 canary 规划测试：`test_commit_msg_hook_entry_grammar`、`test_commit_msg_hook_attribution_and_last_line`、`test_commit_msg_hook_merge_exemption_uses_git_state`、`test_pre_commit_capability_prefix_matrix`、`test_pr_title_is_ignored_by_checker`、`test_pr_body_canary_command_does_not_execute`；验证：对应 pytest 节点通过；临时 Git 目录/克隆不创建真实提交，canary 标记文件不存在。

## 3. 集中验证与映射实施状态

- [x] 3.1 在 WSL Ubuntu `/home/chest/miniconda3/envs/fuxi/bin/python` 运行新文件全部 30 个测试，默认排除真实 Docker 与网络；验证：退出码 0，结果写入外部 `node-batch-5` 日志。
- [x] 3.2 运行相关 accounts/roles/password/API/CI-checker 审定映射 suite 与默认安全套件；验证：退出码 0，结果写入外部 `node-batch-5` 日志。
- [x] 3.3 将 `test-plan.md` 中已实际实现并核对的新测试 locator 从 `[ ]` 更新为 `[X]`，保留人工检查 `[ ]`、Q78 暂缓与 ASGI/TCP 边界说明；验证：30 个唯一测试均存在且映射计数一致。

## Workflow follow-up

- 运行 official `openspec-verify-change` advisory，不创建 `verify.md`；记录结果。
- 官方 no-op sync 两个能力，核对 10 个 main spec SHA 不变。
- 使用 `anvil-test-plan` 维护 `backend--collaborator-accounts` 与 `procedure--repository-workflow` 两个 sidecar，使实施状态与归档 test-plan 一致。
- 官方 archive 到 `2026-10-28-complete-anvil-accounts-procedure-mappings`，报告 changed paths 与 archive 状态。
