# Tasks

## 1. 数据契约与构造器

- [x] 1.1 实现 `test_container_config_defaults_and_ge_bounds`，验证 creation / ContainerConfig 数据契约 / 字段校验与缺省值；运行 `pytest -q tests/test_anvil_creation_credentials.py::test_container_config_defaults_and_ge_bounds`。
- [x] 1.2 实现 `test_image_build_config_defaults_and_empty_build_rejected`，验证 creation / ImageBuildConfig 数据契约 / 字段校验与缺省值 与 creation / 构建段缺文本时失败而非降级；运行同名测试。
- [x] 1.3 实现 `test_restore_account_defaults_and_password_retention`，验证 creation / RestoreAccountConfig 数据契约 / 字段校验与缺省值；运行同名测试。
- [x] 1.4 实现 `test_create_message_optional_field_defaults`，验证 creation / CreateContainerMessage 数据契约 / 字段校验与缺省值；运行同名测试。
- [x] 1.5 实现 `test_create_response_defaults_and_accepted_alias_wire_shape`，验证 creation / CreateContainerResponse 字段校验与缺省值 与 CreateContainerAcceptedResponse 使用声明值域；运行同名测试。
- [x] 1.6 实现 `test_legacy_container_dto_maps_config_values` 与 `test_legacy_config_info_accepts_values_new_schema_rejects`，验证 creation / Container 内部值传递 与 Container.Config_info 字段校验与缺省值；运行这两个测试。

## 2. 构建、创建与恢复服务

- [x] 2.1 实现 `test_create_response_action_ref_matches_create_generation_and_seq`，验证 creation / CreateContainerResponse 数据契约 / 创建受理返回动作引用；运行同名测试。
- [x] 2.2 实现 `test_create_container_return_fields_from_docker_facts`，验证 creation / CreateContainerReturn 数据契约 / 内部值传递；运行同名测试。
- [x] 2.3 实现 `test_build_image_uses_exact_dockerfile_text_and_new_tag`，验证 creation / 构建段未命中则现场构建 与 平台注入换代而旧标签仍在；运行同名测试。
- [x] 2.4 实现 `test_restore_mount_source_independent_of_image_and_name`，验证 creation / 恢复挂载来源只由入参决定 / 恢复沿用原目录；运行同名测试。
- [x] 2.5 实现 `test_restore_mount_path_requires_containers_segment_and_existing_dir`，验证 creation / 恢复挂载来源只由入参决定 / 越界或缺失的挂载入参被拒绝（不含暂缓的 base 自身定位）；运行同名测试。
- [x] 2.6 实现 `test_occupied_name_rejected_without_run_or_mount_change`，验证 creation / 恢复挂载来源只由入参决定 / 名字被占用即拒绝；运行同名测试。
- [x] 2.7 实现 `test_root_password_set_before_sshd_gate`，验证 creation / 创建时由 Ctrl 下发的密码设置 root 账号 / 用下发密码设置 root；运行同名测试。
- [x] 2.8 实现 `test_create_password_failure_logs_redacted_without_fallback`，验证 creation / 创建时由 Ctrl 下发的密码设置 root 账号 / 密码设置失败时不回退；运行同名测试。
- [x] 2.9 实现 `test_public_key_installed_without_private_key_material`，验证 creation / CreateContainerMessage 数据契约 / 字段校验与缺省值的正文约束；运行同名测试。
- [x] 2.10 实现 `test_restore_account_password_absent_from_snapshot_wss_cache_and_logs`，验证 creation / RestoreAccountConfig 恢复协作者携带瞬时密码、恢复密码设置失败，以及 credentials / 密码不进入 WSS 或 action 缓存、恢复密码不进入 snapshot、不提供密码查回；运行同名测试。

## 3. 创建响应、日志与审计

- [x] 3.1 实现 `test_missing_root_password_422_not_accepted`，验证 creation / CreateContainerMessage 数据契约 / 缺少 root_password；运行同名测试。
- [x] 3.2 实现 `test_create_root_password_invalid_422_redacted`，验证 creation / CreateContainerMessage 数据契约 / root_password 非法 与 credentials / 密码本身非法时不回显、类型错误不携带原值；运行同名测试。
- [x] 3.3 实现 `test_restore_account_missing_password_422_not_accepted`，验证 creation / RestoreAccountConfig 数据契约 / 恢复协作者缺少 password；运行同名测试。
- [x] 3.4 实现 `test_create_response_exact_fields_no_credentials`，验证 creation / 创建时由 Ctrl 下发的密码设置 root 账号 / 创建响应不携带凭据；运行同名测试。
- [x] 3.5 实现 `test_create_logs_carry_no_password_or_credential_entry`，验证 creation / 创建时由 Ctrl 下发的密码设置 root 账号 / 既有创建日志不重复 与 credentials / 不新增重复密码审计；运行同名测试。
- [x] 3.6 实现 `test_add_collaborator_logs_no_echo_or_chpasswd_command`，验证 credentials / 通过 stdin 安全执行 chpasswd / add_collaborator 日志不含初始密码；运行同名测试。
- [x] 3.7 实现 `test_root_handover_no_new_password_audit`，验证 credentials / 密码不得进入日志、错误、WSS、缓存与响应 / 不新增重复密码审计；运行同名测试。
- [x] 3.8 实现 `test_password_routes_sibling_missing_422_redacted`，验证 credentials / 含密码请求的校验错误必须脱敏 / 同层字段缺失时不回显密码；运行同名测试。
- [x] 3.9 实现 `test_chpasswd_failure_does_not_retry`，验证 credentials / 通过 stdin 安全执行 chpasswd / chpasswd 非 0 时脱敏失败与不自动重试；运行同名测试。

## 4. ASGI 生命周期断开

- [x] 4.1 实现 `test_create_disconnect_keeps_background_password_step`，用真实 `create_app` + ASGI 请求、受控 Event 和 client close 验证 credentials / 已受理的密码任务不因客户端断开而取消 / 创建受理后断开；运行同名测试。
- [x] 4.2 实现 `test_sync_password_routes_survive_asgi_disconnect`，用真实 ASGI request task 取消验证 credentials / 已受理的密码任务不因客户端断开而取消 / 新增、重置或转移执行中断开；运行同名测试（含 reset 失败 500 路径，不把既有 200+success:false 误判为非法）。

## 5. 验证、同步与主线台账

- [x] 5.1 运行新文件全部测试、相关 creation/password/API 既有 suites（默认排除真实 Docker），把命令、退出码与日志写入外部 `anvil-rollout-2026-10-28/node-batch-2/`；运行 `openspec validate --strict`。
- [x] 5.2 执行官方 verify advisory（不创建 verify.md），确认 28 个已实现测试与 test-plan 的映射无未审改动。
- [x] 5.3 精确 sync 两个 no-op delta 到主 spec，核对主 spec SHA 不变；若 sync 失败或改变文本，停止并报告。
- [x] 5.4 sync 成功后按 `anvil-test-plan` 生成 `openspec/specs/backend--container-creation/test-plan.md` 与 `openspec/specs/backend--container-credentials/test-plan.md`；保留 base 暂缓定位与 Coverage note，诚实标记未覆盖。

## Workflow follow-up

- 官方 archive：在 5.1-5.4 完成且 verify 无阻塞后，按 `openspec-archive-change` 归档本 change（北京时间 2026-10-28）。
- base 自身缺陷保持暂缓：不创建/执行/跳过/标记 `test_restore_mount_base_itself_is_rejected`，不应用 `proposed-existing-spec-fixes.diff`，不宣称已修复。
- 归档后向父报告准确测试数、命令/退出码、修改路径、gap 保留位置与 archive 状态；由父统一验收 Git commit。
