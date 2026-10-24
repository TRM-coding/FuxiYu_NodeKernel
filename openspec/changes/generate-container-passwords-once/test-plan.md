## Test Plan

| Requirement | Scenario | Test File | Test Name | Initial State |
|-------------|----------|-----------|-----------|---------------|
| specs/backend--collaborator-accounts/spec.md → AddCollaboratorConfig 数据契约 [schemas/container.py] | 字段校验与缺省值 | tests/test_password_contracts.py | test_add_collaborator_contract | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → AddCollaboratorConfig 数据契约 [schemas/container.py] | 新增协作者携带 Ctrl 密码 | tests/test_password_contracts.py | test_add_collaborator_contract | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → AddCollaboratorConfig 数据契约 [schemas/container.py] | 新增协作者缺少 password | tests/test_password_contracts.py | test_add_collaborator_contract | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → AddCollaboratorConfig 数据契约 [schemas/container.py] | 新增协作者密码非法 | tests/test_password_contracts.py | test_add_collaborator_contract | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → AddCollaboratorResponse 数据契约 [schemas/container.py] | 字段校验与缺省值 | tests/test_password_api.py | test_add_collab_response_redacts | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → AddCollaboratorResponse 数据契约 [schemas/container.py] | 新增协作者成功响应脱敏 | tests/test_password_api.py | test_add_collab_response_redacts | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → AddCollaboratorResponse 数据契约 [schemas/container.py] | 新增协作者失败响应脱敏 | tests/test_password_api.py | test_add_collab_response_redacts | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → UpdateRoleConfig 数据契约 [schemas/container.py] | 字段校验与缺省值 | tests/test_password_contracts.py | test_update_role_password_contract | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → UpdateRoleConfig 数据契约 [schemas/container.py] | ROOT 目标携带 root_password | tests/test_password_contracts.py | test_update_role_password_contract | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → UpdateRoleConfig 数据契约 [schemas/container.py] | ROOT 目标缺少 root_password | tests/test_password_contracts.py | test_update_role_password_contract | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → UpdateRoleConfig 数据契约 [schemas/container.py] | 旧 ROOT 降 ADMIN 携带 password | tests/test_password_contracts.py | test_update_role_password_contract | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → UpdateRoleConfig 数据契约 [schemas/container.py] | 普通 ADMIN 切换可缺省 password | tests/test_password_contracts.py | test_update_role_password_contract | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → UpdateRoleConfig 数据契约 [schemas/container.py] | 普通角色携带 root_password 或 collaborator 携带 password | tests/test_password_contracts.py | test_update_role_password_contract | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → UpdateRoleConfig 数据契约 [schemas/container.py] | 密码字段非法 | tests/test_password_contracts.py | test_update_role_password_contract | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → UpdateRoleResponse 数据契约 [schemas/container.py] | 字段校验与缺省值 | tests/test_password_api.py | test_update_role_response_redacts | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → UpdateRoleResponse 数据契约 [schemas/container.py] | 普通角色切换保持既有响应 | tests/test_password_api.py | test_update_role_response_redacts | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → UpdateRoleResponse 数据契约 [schemas/container.py] | ROOT 与旧 ROOT 降 ADMIN 响应脱敏 | tests/test_password_api.py | test_update_role_response_redacts | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → UpdateRoleResponse 数据契约 [schemas/container.py] | 失败响应不回显密码 | tests/test_password_api.py | test_update_role_response_redacts | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → 新增协作者使用 Ctrl 下发的随机密码 [services/container_service.py] | 新增 ADMIN 或 COLLABORATOR 使用下发密码 | tests/test_password_services.py | test_add_collaborator_uses_password | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → 新增协作者使用 Ctrl 下发的随机密码 [services/container_service.py] | 缺少 password 时不回退默认 | tests/test_password_api.py | test_add_collab_response_redacts | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → 新增协作者使用 Ctrl 下发的随机密码 [services/container_service.py] | 密码设置失败不伪装成功 | tests/test_password_services.py | test_add_collaborator_uses_password | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → 旧 ROOT 降 ADMIN 时按 Ctrl 密码创建独立账号 [services/container_service.py] | 旧 ROOT 降 ADMIN 创建独立账号 | tests/test_password_services.py | test_admin_demotion_creates_or_updates_account | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → 旧 ROOT 降 ADMIN 时按 Ctrl 密码创建独立账号 [services/container_service.py] | 旧 ROOT 降 ADMIN 已有独立账号 | tests/test_password_services.py | test_admin_demotion_creates_or_updates_account | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → 旧 ROOT 降 ADMIN 时按 Ctrl 密码创建独立账号 [services/container_service.py] | 普通 ADMIN 切换不改密码 | tests/test_password_services.py | test_admin_demotion_creates_or_updates_account | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → 旧 ROOT 降 ADMIN 时按 Ctrl 密码创建独立账号 [services/container_service.py] | 普通 ADMIN 切换缺少账号且无密码 | tests/test_password_services.py | test_admin_demotion_creates_or_updates_account | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → ROOT 提升/交接由 Ctrl 的 transfer_root 编排，Node 只处理单目标 [services/container_service.py] | 按旧 ROOT 再目标的顺序执行 | tests/test_password_services.py | test_root_handover_orchestration | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → ROOT 提升/交接由 Ctrl 的 transfer_root 编排，Node 只处理单目标 [services/container_service.py] | transfer_root=false 只处理目标 | tests/test_password_services.py | test_root_transfer_single_target | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → ROOT 提升/交接由 Ctrl 的 transfer_root 编排，Node 只处理单目标 [services/container_service.py] | 历史多 ROOT 逐次处理 | tests/test_password_services.py | test_root_handover_orchestration | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → ROOT 提升/交接由 Ctrl 的 transfer_root 编排，Node 只处理单目标 [services/container_service.py] | 目标不在 sudo/wheel 时幂等清理 | tests/test_password_services.py | test_root_group_cleanup_idempotent | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → ROOT 提升/交接由 Ctrl 的 transfer_root 编排，Node 只处理单目标 [services/container_service.py] | 删除用户触发的 ROOT 转移同样带密码 | tests/test_password_services.py | test_root_transfer_single_target | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → ROOT 提升/交接由 Ctrl 的 transfer_root 编排，Node 只处理单目标 [services/container_service.py] | Node 不扫描其他账号 | tests/test_password_services.py | test_root_transfer_single_target | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → ROOT 提升/交接由 Ctrl 的 transfer_root 编排，Node 只处理单目标 [services/container_service.py] | 第二步失败不回滚第一步 | tests/test_password_services.py | test_root_handover_orchestration | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → ROOT 提升/交接由 Ctrl 的 transfer_root 编排，Node 只处理单目标 [services/container_service.py] | 普通 ADMIN/COLLABORATOR 互换仍不改密码 | tests/test_password_services.py | test_plain_role_switch_no_password | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → 重置容器账号密码 [network/api.py] | 重置普通账号成功 | tests/test_password_api.py | test_reset_endpoint_cases | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → 重置容器账号密码 [network/api.py] | 重置 root 成功 | tests/test_password_api.py | test_reset_endpoint_cases | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → 重置容器账号密码 [network/api.py] | 容器不存在 | tests/test_password_api.py | test_reset_endpoint_cases | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → 重置容器账号密码 [network/api.py] | 容器未运行 | tests/test_password_api.py | test_reset_endpoint_cases | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → 重置容器账号密码 [network/api.py] | 容器内账号不存在 | tests/test_password_api.py | test_reset_endpoint_cases | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → 重置容器账号密码 [network/api.py] | 非法登录名或密码 | tests/test_password_api.py | test_reset_endpoint_cases | 🔴 red |
| specs/backend--collaborator-accounts/spec.md → 重置容器账号密码 [network/api.py] | 客户端断开不取消 | tests/test_password_api.py | test_sync_disconnect_continues | 🔴 red |
| specs/backend--container-creation/spec.md → CreateContainerMessage 数据契约 [schemas/container.py] | 字段校验与缺省值 | tests/test_password_contracts.py | test_create_message_root_password_contract | 🔴 red |
| specs/backend--container-creation/spec.md → CreateContainerMessage 数据契约 [schemas/container.py] | 创建请求携带 root_password | tests/test_password_contracts.py | test_create_message_root_password_contract | 🔴 red |
| specs/backend--container-creation/spec.md → CreateContainerMessage 数据契约 [schemas/container.py] | 缺少 root_password | tests/test_password_contracts.py | test_create_message_root_password_contract | 🔴 red |
| specs/backend--container-creation/spec.md → CreateContainerMessage 数据契约 [schemas/container.py] | root_password 非法 | tests/test_password_contracts.py | test_create_message_root_password_contract | 🔴 red |
| specs/backend--container-creation/spec.md → RestoreAccountConfig 数据契约 [schemas/container.py] | 字段校验与缺省值 | tests/test_password_contracts.py | test_restore_account_password_contract | 🔴 red |
| specs/backend--container-creation/spec.md → RestoreAccountConfig 数据契约 [schemas/container.py] | 恢复协作者携带瞬时密码 | tests/test_password_contracts.py | test_restore_account_password_contract | 🔴 red |
| specs/backend--container-creation/spec.md → RestoreAccountConfig 数据契约 [schemas/container.py] | 恢复协作者缺少 password | tests/test_password_contracts.py | test_restore_account_password_contract | 🔴 red |
| specs/backend--container-creation/spec.md → RestoreAccountConfig 数据契约 [schemas/container.py] | 恢复密码设置失败 | tests/test_password_services.py | test_create_uses_root_password_and_no_fallback | 🔴 red |
| specs/backend--container-creation/spec.md → 创建时由 Ctrl 下发的密码设置 root 账号 [services/container_service.py] | 用下发密码设置 root | tests/test_password_services.py | test_create_uses_root_password_and_no_fallback | 🔴 red |
| specs/backend--container-creation/spec.md → 创建时由 Ctrl 下发的密码设置 root 账号 [services/container_service.py] | 密码设置失败时不回退 | tests/test_password_services.py | test_create_uses_root_password_and_no_fallback | 🔴 red |
| specs/backend--container-creation/spec.md → 创建时由 Ctrl 下发的密码设置 root 账号 [services/container_service.py] | 创建响应不携带凭据 | tests/test_password_api.py | test_responses_no_credentials | 🔴 red |
| specs/backend--container-creation/spec.md → 创建时由 Ctrl 下发的密码设置 root 账号 [services/container_service.py] | 既有创建日志不重复 | tests/test_password_services.py | test_create_uses_root_password_and_no_fallback | 🔴 red |
| specs/backend--container-credentials/spec.md → 密码输入使用 SecretStr 且只保持最小生命周期 | SecretStr 掩码 | tests/test_password_contracts.py | test_secretstr_masking_across_models | 🔴 red |
| specs/backend--container-credentials/spec.md → 密码输入使用 SecretStr 且只保持最小生命周期 | 创建密码不进入 Docker 运行配置 | tests/test_password_services.py | test_create_password_not_in_docker_config | 🔴 red |
| specs/backend--container-credentials/spec.md → 密码输入使用 SecretStr 且只保持最小生命周期 | 密码不进入 WSS 或 action 缓存 | tests/test_password_api.py | test_password_not_in_status_or_wss | 🔴 red |
| specs/backend--container-credentials/spec.md → 密码输入使用 SecretStr 且只保持最小生命周期 | 恢复密码不进入 snapshot | tests/test_password_contracts.py | test_restore_password_not_in_snapshot | 🔴 red |
| specs/backend--container-credentials/spec.md → 密码输入使用 SecretStr 且只保持最小生命周期 | 不提供密码查回 | tests/test_password_api.py | test_no_password_lookup_endpoint | 🔴 red |
| specs/backend--container-credentials/spec.md → 通过 stdin 安全执行 chpasswd | stdin 传递密码且 argv 不含密码 | tests/test_password_exec.py | test_chpasswd_stdin_argv | 🔴 red |
| specs/backend--container-credentials/spec.md → 通过 stdin 安全执行 chpasswd | 特殊字符按数据处理 | tests/test_password_exec.py | test_chpasswd_stdin_argv | 🔴 red |
| specs/backend--container-credentials/spec.md → 通过 stdin 安全执行 chpasswd | chpasswd 非 0 时脱敏失败 | tests/test_password_exec.py | test_chpasswd_failure_sanitized | 🔴 red |
| specs/backend--container-credentials/spec.md → 通过 stdin 安全执行 chpasswd | add_collaborator 日志不含初始密码 | tests/test_password_services.py | test_add_collaborator_logs_no_secret | 🔴 red |
| specs/backend--container-credentials/spec.md → 通过 stdin 安全执行 chpasswd | update_role 日志不含 ROOT/旧 owner 密码 | tests/test_password_services.py | test_update_role_logs_no_secret | 🔴 red |
| specs/backend--container-credentials/spec.md → 通过 stdin 安全执行 chpasswd | 普通角色切换不触碰密码 | tests/test_password_services.py | test_plain_role_switch_no_password | 🔴 red |
| specs/backend--container-credentials/spec.md → 密码不得进入日志、错误、WSS、缓存与响应 | 日志与异常无明文 | tests/test_password_services.py | test_logs_and_exceptions_no_secret | 🔴 red |
| specs/backend--container-credentials/spec.md → 密码不得进入日志、错误、WSS、缓存与响应 | 响应不返回凭据 | tests/test_password_api.py | test_responses_no_credentials | 🔴 red |
| specs/backend--container-credentials/spec.md → 密码不得进入日志、错误、WSS、缓存与响应 | 凭据响应禁止缓存 | tests/test_password_api.py | test_password_routes_no_store | 🔴 red |
| specs/backend--container-credentials/spec.md → 密码不得进入日志、错误、WSS、缓存与响应 | ROOT 交接逐次调用、逐项凭据 | tests/test_password_services.py | test_root_handover_orchestration | 🔴 red |
| specs/backend--container-credentials/spec.md → 密码不得进入日志、错误、WSS、缓存与响应 | transfer_root=false 只带单项 | tests/test_password_services.py | test_root_transfer_single_target | 🔴 red |
| specs/backend--container-credentials/spec.md → 密码不得进入日志、错误、WSS、缓存与响应 | 不新增重复密码审计 | tests/test_password_api.py | test_no_duplicate_password_audit | 🔴 red |
| specs/backend--container-credentials/spec.md → 密码不得进入日志、错误、WSS、缓存与响应 | 非密码路由保持默认 422 | tests/test_password_api.py | test_non_password_route_default_422 | 🔴 red |
| specs/backend--container-credentials/spec.md → 密码不得进入日志、错误、WSS、缓存与响应 | 失败响应夹带尝试不泄漏 | tests/test_password_api.py | test_failure_response_no_secret | 🔴 red |
| specs/backend--container-credentials/spec.md → 含密码请求的校验错误必须脱敏 | 同层字段缺失时不回显密码 | tests/test_password_api.py | test_password_route_422_redaction | 🔴 red |
| specs/backend--container-credentials/spec.md → 含密码请求的校验错误必须脱敏 | 密码本身非法时不回显 | tests/test_password_api.py | test_password_route_422_redaction | 🔴 red |
| specs/backend--container-credentials/spec.md → 含密码请求的校验错误必须脱敏 | 类型错误不携带原值 | tests/test_password_api.py | test_password_route_422_redaction | 🔴 red |
| specs/backend--container-credentials/spec.md → 已受理的密码任务不因客户端断开而取消 | 创建受理后断开 | tests/test_password_api.py | test_sync_disconnect_continues | 🔴 red |
| specs/backend--container-credentials/spec.md → 已受理的密码任务不因客户端断开而取消 | 新增、重置或转移执行中断开 | tests/test_password_api.py | test_sync_disconnect_continues | 🔴 red |

## Coverage Notes

- Every scenario above maps to a named pytest node (parameterized IDs where the same test function covers closely related contract cases).
- Service tests use the repository FakeDocker/FakeExecAPI doubles; they validate socket I/O and command shape, not a real Docker daemon.
- Cross-repo Ctrl/Web-only outcomes are asserted on the Node-side wire/response/primitive; the Ctrl/Web rendering itself is out of this repository.
- Rows are flipped to 🟢 green only after the named test passes in the recorded run.
