# 协作账号 测试覆盖

规格：[spec.md](spec.md)

## 当前场景映射

| Requirement | Scenario | 测试位置 | 状态 |
| --- | --- | --- | --- |
| AddCollaboratorConfig 数据契约 [schemas/container.py] | 字段校验与缺省值 | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_add_collaborator_contract | 🟢 已通过 |
| AddCollaboratorConfig 数据契约 [schemas/container.py] | 新增协作者携带 Ctrl 密码 | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_add_collaborator_contract | 🟢 已通过 |
| AddCollaboratorConfig 数据契约 [schemas/container.py] | 新增协作者缺少 password | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_add_collaborator_contract | 🟢 已通过 |
| AddCollaboratorConfig 数据契约 [schemas/container.py] | 新增协作者密码非法 | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_add_collaborator_contract | 🟢 已通过 |
| AddCollaboratorResponse 数据契约 [schemas/container.py] | 字段校验与缺省值 | [test_password_api.py](../../../tests/test_password_api.py)::test_add_collab_response_redacts | 🟢 已通过 |
| AddCollaboratorResponse 数据契约 [schemas/container.py] | 新增协作者成功响应脱敏 | [test_password_api.py](../../../tests/test_password_api.py)::test_add_collab_response_redacts | 🟢 已通过 |
| AddCollaboratorResponse 数据契约 [schemas/container.py] | 新增协作者失败响应脱敏 | [test_password_api.py](../../../tests/test_password_api.py)::test_add_collab_response_redacts | 🟢 已通过 |
| UpdateRoleConfig 数据契约 [schemas/container.py] | 字段校验与缺省值 | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_update_role_password_contract | 🟢 已通过 |
| UpdateRoleConfig 数据契约 [schemas/container.py] | ROOT 目标携带 root_password | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_update_role_password_contract | 🟢 已通过 |
| UpdateRoleConfig 数据契约 [schemas/container.py] | ROOT 目标缺少 root_password | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_update_role_password_contract | 🟢 已通过 |
| UpdateRoleConfig 数据契约 [schemas/container.py] | 旧 ROOT 降 ADMIN 携带 password | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_update_role_password_contract | 🟢 已通过 |
| UpdateRoleConfig 数据契约 [schemas/container.py] | 普通 ADMIN 切换可缺省 password | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_update_role_password_contract | 🟢 已通过 |
| UpdateRoleConfig 数据契约 [schemas/container.py] | 普通角色携带 root_password 或 collaborator 携带 password | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_update_role_password_contract | 🟢 已通过 |
| UpdateRoleConfig 数据契约 [schemas/container.py] | 密码字段非法 | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_update_role_password_contract | 🟢 已通过 |
| UpdateRoleResponse 数据契约 [schemas/container.py] | 字段校验与缺省值 | [test_password_api.py](../../../tests/test_password_api.py)::test_update_role_response_redacts | 🟢 已通过 |
| UpdateRoleResponse 数据契约 [schemas/container.py] | 普通角色切换保持既有响应 | [test_password_api.py](../../../tests/test_password_api.py)::test_update_role_response_redacts | 🟢 已通过 |
| UpdateRoleResponse 数据契约 [schemas/container.py] | ROOT 与旧 ROOT 降 ADMIN 响应脱敏 | [test_password_api.py](../../../tests/test_password_api.py)::test_update_role_response_redacts | 🟢 已通过 |
| UpdateRoleResponse 数据契约 [schemas/container.py] | 失败响应不回显密码 | [test_password_api.py](../../../tests/test_password_api.py)::test_update_role_response_redacts | 🟢 已通过 |
| 新增协作者使用 Ctrl 下发的随机密码 [services/container_service.py] | 新增 ADMIN 或 COLLABORATOR 使用下发密码 | [test_password_services.py](../../../tests/test_password_services.py)::test_add_collaborator_uses_password | 🟢 已通过 |
| 新增协作者使用 Ctrl 下发的随机密码 [services/container_service.py] | 缺少 password 时不回退默认 | [test_password_api.py](../../../tests/test_password_api.py)::test_add_collab_response_redacts | 🟢 已通过 |
| 新增协作者使用 Ctrl 下发的随机密码 [services/container_service.py] | 密码设置失败不伪装成功 | [test_password_services.py](../../../tests/test_password_services.py)::test_add_collaborator_uses_password | 🟢 已通过 |
| 旧 ROOT 降 ADMIN 时按 Ctrl 密码创建独立账号 [services/container_service.py] | 旧 ROOT 降 ADMIN 创建独立账号 | [test_password_services.py](../../../tests/test_password_services.py)::test_admin_demotion_creates_or_updates_account | 🟢 已通过 |
| 旧 ROOT 降 ADMIN 时按 Ctrl 密码创建独立账号 [services/container_service.py] | 旧 ROOT 降 ADMIN 已有独立账号 | [test_password_services.py](../../../tests/test_password_services.py)::test_admin_demotion_creates_or_updates_account | 🟢 已通过 |
| 旧 ROOT 降 ADMIN 时按 Ctrl 密码创建独立账号 [services/container_service.py] | 普通 ADMIN 切换不改密码 | [test_password_services.py](../../../tests/test_password_services.py)::test_admin_demotion_creates_or_updates_account | 🟢 已通过 |
| 旧 ROOT 降 ADMIN 时按 Ctrl 密码创建独立账号 [services/container_service.py] | 普通 ADMIN 切换缺少账号且无密码 | [test_password_services.py](../../../tests/test_password_services.py)::test_admin_demotion_creates_or_updates_account | 🟢 已通过 |
| ROOT 交接由 Ctrl 统一编排，Node 只处理单目标 [services/container_service.py] | 按旧 ROOT 再目标的顺序执行 | [test_password_services.py](../../../tests/test_password_services.py)::test_root_handover_orchestration | 🟢 已通过 |
| ROOT 交接由 Ctrl 统一编排，Node 只处理单目标 [services/container_service.py] | 单次 Node 请求只处理指定账号 | [test_password_services.py](../../../tests/test_password_services.py)::test_root_transfer_single_target | 🟢 已通过 |
| ROOT 交接由 Ctrl 统一编排，Node 只处理单目标 [services/container_service.py] | 历史多 ROOT 逐次处理 | [test_password_services.py](../../../tests/test_password_services.py)::test_root_handover_orchestration | 🟢 已通过 |
| ROOT 交接由 Ctrl 统一编排，Node 只处理单目标 [services/container_service.py] | 目标不在 sudo/wheel 时幂等清理 | [test_password_services.py](../../../tests/test_password_services.py)::test_root_group_cleanup_idempotent | 🟢 已通过 |
| ROOT 交接由 Ctrl 统一编排，Node 只处理单目标 [services/container_service.py] | 删除用户触发的 ROOT 转移同样带密码 | [test_password_services.py](../../../tests/test_password_services.py)::test_root_transfer_single_target | 🟢 已通过 |
| ROOT 交接由 Ctrl 统一编排，Node 只处理单目标 [services/container_service.py] | Node 不扫描其他账号 | [test_password_services.py](../../../tests/test_password_services.py)::test_root_transfer_single_target | 🟢 已通过 |
| ROOT 交接由 Ctrl 统一编排，Node 只处理单目标 [services/container_service.py] | 第二步失败不回滚第一步 | [test_password_services.py](../../../tests/test_password_services.py)::test_root_handover_orchestration | 🟢 已通过 |
| ROOT 交接由 Ctrl 统一编排，Node 只处理单目标 [services/container_service.py] | 普通 ADMIN/COLLABORATOR 互换仍不改密码 | [test_password_services.py](../../../tests/test_password_services.py)::test_plain_role_switch_no_password | 🟢 已通过 |
| 重置容器账号密码 [network/api.py] | 重置普通账号成功 | [test_password_api.py](../../../tests/test_password_api.py)::test_reset_endpoint_cases | 🟢 已通过 |
| 重置容器账号密码 [network/api.py] | 重置 root 成功 | [test_password_api.py](../../../tests/test_password_api.py)::test_reset_endpoint_cases | 🟢 已通过 |
| 重置容器账号密码 [network/api.py] | 容器不存在 | [test_password_api.py](../../../tests/test_password_api.py)::test_reset_endpoint_cases | 🟢 已通过 |
| 重置容器账号密码 [network/api.py] | 容器未运行 | [test_password_api.py](../../../tests/test_password_api.py)::test_reset_endpoint_cases | 🟢 已通过 |
| 重置容器账号密码 [network/api.py] | 容器内账号不存在 | [test_password_api.py](../../../tests/test_password_api.py)::test_reset_endpoint_cases | 🟢 已通过 |
| 重置容器账号密码 [network/api.py] | 非法登录名或密码 | [test_password_api.py](../../../tests/test_password_api.py)::test_reset_endpoint_cases | 🟢 已通过 |
| 重置容器账号密码 [network/api.py] | 客户端断开不取消 | [test_password_api.py](../../../tests/test_password_api.py)::test_sync_disconnect_continues | 🟢 已通过 |

## 覆盖说明

- 本台账只列本次变更新增或修改的 Scenario；未列出的旧 Scenario 仍保留在主 spec，本轮未重新逐场景映射，不据此声明新的通过结论。
- 测试位置相对本台账目录计算；测试代码保留在仓库既有 `tests/` 目录，未新增测试目录。
- 同一测试函数覆盖多个紧密相关场景时，表内按场景分别登记。

## 最近验证

- 时间：2026-10-24 17:30 +0800
- 版本：6961aee997bd155d96212776a3ff2ec66c95a6df（实现 + 工具抽取 FIX 提交；主 spec 同步前版本）
- 主 spec SHA256：F7AC5B52317EDE9EDA77E2408C00E155257BDA5F86040CFBF214DEE8FA15442F
- 命令与环境：`cd /mnt/e/AI/Fuxi/FuxiYu_NodeKernel && /home/chest/.cache/fuxi-password-tests-offline/bin/python -m pytest -q --no-header`；WSL Linux 隔离 venv，docker 7.1.0
- 结果：`444 passed, 16 deselected, 24 subtests passed`，0 skipped；SocketIO wrapper 专项 `5 passed`；密码专项 `36 passed`。
- 限制：FakeDocker/FakeExecAPI 证明 Node argv/stdin/错误边界；真实 `socket.socketpair()` + `SocketIO` 测试证明 wrapper I/O；未连接真实 Docker daemon 或远程主机，不宣称生产环境验证。

## ROOT 交接纠正复验（2026-10-24）

- 当前主 spec SHA256：061F30192386037BFAD53CC9EE706D08AF32011585100CEF5FF97E88A4ABD4AC

- 仅纠正规格边界：所有外部 ROOT 交接由 Ctrl 编排，Node 保留单账号执行方法；不改 Node 运行代码、数据结构或历史归档。
- Node 密码相关三个测试文件复验：31 passed，0 failed；日志位于外部 root-handover-2026-10-24/node-password-regression.log。
- 隔离的本地真实 Docker 复验：先为原所有者创建/重置独立 ADMIN 账号，再由目标接管永久 root；两个密码均与实际系统哈希一致，目标旧账号已删除。临时容器已清理，未使用用户容器。报告位于外部 root-handover-2026-10-24/docker-account-probe.json。
- Node 的单次执行测试不单独证明 Ctrl 最终唯一 ROOT；该断言由 Ctrl 的交接 API/数据库回归覆盖，Web 双凭据由页面与浏览器测试覆盖。

## update_role 对抗补充（2026-10-24）

- 范围：新增 [test_role_adversarial.py](../../../tests/test_role_adversarial.py) 并追加本台账；2026-10-24 修复只动 `UpdateRoleConfig` 安全标识校验、`update_role` 服务入口前置防御和 sanitizer 最小 helper，未回退/改写 4 个由父级修正 Ctrl 统一编排的主规格文件。
- 固定语料 `SEED=20261024`，测试不使用随机数；旧 ROOT→ADMIN、目标→ROOT 顺序重复 3 轮并在测试内逐轮比较 transcript（响应、命令、stdin 摘要、created 数）。
- 隔离：只替换 Docker 边界（`tests/conftest.py` 的 FakeContainers/FakeDockerClient 与 `tests/password_fakes.py` 的 PasswordFakeContainer/FakeExecAPI）；不 mock `update_role`/`_exec_chpasswd_stdin`；不连 Docker daemon、数据库、网络，不启动/停止服务，不加载仓库 `.env`。
- 环境：WSL Ubuntu；`/home/chest/miniconda3/envs/fuxi/bin/python`（Python 3.10.20）；pydantic 2.13.4；fastapi 0.141.1；docker-py 7.2.0；HEAD `d0a67e8855970b68c0ad8881738ea02aed3dc213`。
- 主 spec 追加后 SHA256：`0761ABA6C2478A1EFAE20633DF214B1F31D693D18E50D47A0B7E4C8531FF6E58`（父级原 `061F...` 记录保留为追加前基线）。
- 命令：
  `cd /mnt/e/AI/Fuxi/FuxiYu_NodeKernel && PYTHONPATH=/mnt/e/AI/Fuxi PYTHONDONTWRITEBYTECODE=1 NODE_LOG_DIR=/mnt/e/AI/Fuxi_audit_artifacts/root-handover-2026-10-24/adversarial-node/logs NODE_LOG_FILE=role-adversarial-node.log PYTHON_DOTENV_DISABLED=1 /home/chest/miniconda3/envs/fuxi/bin/python -m pytest tests/test_role_adversarial.py -q --no-header -p no:cacheprovider --junitxml=/mnt/e/AI/Fuxi_audit_artifacts/root-handover-2026-10-24/adversarial-node/junit-role-adversarial.xml`
- 结果（修复前）：`60` 个用例，**56 passed, 4 failed, 0 skipped**（exit 1）；同一命令重复第二次仍为 56/4，失败名单一致（`junit-role-adversarial-run2.xml`、`pytest-role-adversarial-run2.log`）。
- 安全收敛：`UpdateRoleConfig` 的 `container_name`/`user_name` 复用安全标识校验（字母/数字/下划线/连字符；禁止空、前导 `-`、shell 元字符、路径穿越）；非 ROOT `user_name="root"` 由模型校验拒绝；`update_role` 服务入口在 Docker lookup 前重复同一标识/root 目标约束；ROOT 指定 root 保持分支内既有拒绝。
- 修复后复验：`60 passed, 0 failed, 0 skipped`；相关 `80 passed, 1 deselected`；Node 默认安全全量 `508 passed, 16 deselected, 24 subtests passed`。
- 相关回归：`tests/test_update_role.py tests/test_password_contracts.py tests/test_password_services.py tests/test_password_api.py tests/test_password_exec.py tests/test_blueprint_api.py` → **80 passed, 1 deselected**（`pytest-role-related-fixed.log`）。
- 断言限制：FakeDocker 证明 Node argv/stdin/决策与响应边界；`--help` 的真实命令退出码另在 WSL 主机用 `id -u --help`、`usermod -aG sudo --help`、`userdel --help` 核对为 0；未创建真实账号、未连真实 Docker daemon，不宣称生产环境验证。

| Requirement | 对抗面 / Scenario | 测试位置 | 状态 |
| --- | --- | --- | --- |
| UpdateRoleConfig 数据契约 [schemas/container.py] | role 大小写、前后空格、同形字、null、数组、对象、数字、bool 均由 Pydantic 拒绝 | [test_role_adversarial.py](../../../tests/test_role_adversarial.py)::test_invalid_role_rejected_before_docker | 🟢 已通过 |
| UpdateRoleConfig 数据契约 [schemas/container.py] | root_password 缺失/null/空/短/超长/全空白/冒号/CR/LF/NUL/非字符串 | [test_role_adversarial.py](../../../tests/test_role_adversarial.py)::test_invalid_password_contract_rejected_before_docker | 🟢 已通过 |
| UpdateRoleConfig 数据契约 [schemas/container.py] | admin password 非法；collaborator 携带 password；admin 携带 root_password；root 同时携带两者 | [test_role_adversarial.py](../../../tests/test_role_adversarial.py)::test_invalid_password_contract_rejected_before_docker | 🟢 已通过 |
| 旧 ROOT 降 ADMIN / ROOT 交接 [services/container_service.py] | 合法 root/admin/collaborator 密码只走 stdin；admin 无密码不 chpasswd；响应/argv/日志无明文 | [test_role_adversarial.py](../../../tests/test_role_adversarial.py)::test_valid_roles_keep_secret_on_stdin | 🟢 已通过 |
| UpdateRoleConfig 数据契约 [schemas/container.py] | user_name 含 shell 元字符/换行/NUL/路径穿越：应在请求边界 422 且不执行命令 | [test_role_adversarial.py](../../../tests/test_role_adversarial.py)::test_shell_metacharacter_user_names_rejected_at_request_boundary | 🟢 已通过（请求边界 422，零 Docker/exec） |
| UpdateRoleConfig 数据契约 [schemas/container.py] | container_name 含同类注入串：应请求边界 422 且不先访问 Docker | [test_role_adversarial.py](../../../tests/test_role_adversarial.py)::test_shell_metacharacter_container_names_rejected_before_docker_lookup | 🟢 已通过（请求边界 422，零 Docker lookup） |
| UpdateRoleConfig 数据契约 [schemas/container.py] | 前导连字符名字（`--help`）不得被 id/usermod/userdel 当选项并假成功 | [test_role_adversarial.py](../../../tests/test_role_adversarial.py)::test_option_like_user_names_cannot_false_succeed | 🟢 已通过（请求边界 422，零命令） |
| ROOT 交接由 Ctrl 统一编排，Node 只处理单目标 [services/container_service.py] | 非 ROOT 角色以 `user_name=root` 为目标时不得写共享 root 密码/改组 | [test_role_adversarial.py](../../../tests/test_role_adversarial.py)::test_non_root_roles_must_not_touch_shared_root | 🟢 已通过（非 ROOT 目标 root 请求边界 422，零命令） |
| ROOT 交接由 Ctrl 统一编排，Node 只处理单目标 [services/container_service.py] | 旧 ROOT→ADMIN、目标→ROOT 连续多轮：transcript 完全一致、响应/日志无密码 | [test_role_adversarial.py](../../../tests/test_role_adversarial.py)::test_repeated_handover_sequence_is_deterministic_and_redacted | 🟢 已通过 |
| ROOT 交接由 Ctrl 统一编排，Node 只处理单目标 [services/container_service.py] | 第二步 ROOT exec_start 失败：不回滚第一步、不伪装成功、不发送 root stdin | [test_role_adversarial.py](../../../tests/test_role_adversarial.py)::test_second_step_failure_does_not_rollback_first_and_repeats | 🟢 已通过 |
| ROOT 交接由 Ctrl 统一编排，Node 只处理单目标 [services/container_service.py] | 旧客户端 `transfer_root` 等额外字段被忽略，不扫描/修改其他账号 | [test_role_adversarial.py](../../../tests/test_role_adversarial.py)::test_transfer_root_extra_field_is_ignored_and_no_scan | 🟢 已通过 |
| UpdateRoleResponse / 服务失败 [network/api.py, services/container_service.py] | exec_create/exec_start/exec_inspect 异常与 inspect 未知：ADMIN 返回 false，ROOT 抛错且不跑清理 | [test_role_adversarial.py](../../../tests/test_role_adversarial.py)::test_admin_password_transport_failures_never_false_success、test_root_password_transport_failures_raise_and_skip_cleanup | 🟢 已通过 |
| 旧 ROOT 降 ADMIN / ROOT 交接 [services/container_service.py] | 用户探测、建号、密码写、管理组、userdel、归档分步失败均不假成功 | [test_role_adversarial.py](../../../tests/test_role_adversarial.py)::test_admin_user_probe_exception_aborts_before_any_write、test_admin_create_failure_stops_before_password_write、test_admin_password_failure_after_create_is_false_with_partial_account、test_admin_group_failure_after_password_is_false_no_rollback、test_root_userdel_failure_is_false_after_root_password_set、test_root_archive_step_failure_is_false_after_root_password_set | 🟢 已通过 |
| ROOT 交接由 Ctrl 统一编排，Node 只处理单目标 [services/container_service.py] | ROOT 清理命令幂等摘组、归档 best-effort、userdel 失败即 false | [test_role_adversarial.py](../../../tests/test_role_adversarial.py)::test_root_cleanup_command_shape_is_idempotent_and_best_effort_archive | 🟢 已通过 |
| UpdateRoleResponse 数据契约 [schemas/container.py] | 失败响应不伪装成功、422/500 脱敏、日志无密码 | [test_role_adversarial.py](../../../tests/test_role_adversarial.py)::test_api_admin_transport_failure_reports_false、test_api_root_transport_failure_is_500_redacted、test_api_root_userdel_failure_reports_false、test_validation_and_internal_errors_do_not_log_secret | 🟢 已通过 |

### 本轮缺陷复现历史（2026-10-24，已收敛）

以下为修复前复现；2026-10-24 已按“安全收敛”修复并复验，当前 60/0。

1. **注入串未在请求边界拒绝**：`user_name`/`container_name` 含 `; && $( ) | \n \0 ../` 时，Pydantic 接受，服务层 `_sanitizer.validate_username` 抛 `ValueError`，`network/api.py` 的宽泛 `except Exception` 返回 `500 internal_error`，而数据契约要求非法值在请求校验阶段拒绝（422）。`container_name` 还在校验前调用 `containers.get`。期望：422 且不触达 Docker/exec；实际：500，Docker lookup 已发生，exec 未发生。
2. **前导连字符选项注入/假成功**：`user_name="--help"` 通过 `is_valid_name`（允许连字符）并进入 shell。真实 `id -u --help`、`usermod -aG sudo --help`、`userdel --help` 均退出 0，于是 ADMIN/ROOT 都返回 `200 success=true`；实际没有创建/删除对应账号，ROOT 分支还先改了共享 root 密码。期望：拒绝该名字，不执行命令；实际：200 假成功。
3. **非 ROOT 角色可触碰共享 root**：`user_name="root"` 时，ADMIN+password 会 `chpasswd` 写入 `root:<password>` 并 `usermod -aG sudo root`；ADMIN 无 password 也执行 root 组命令；COLLABORATOR 执行 `deluser root sudo/wheel`。这违反“旧 ROOT 降 ADMIN 不得改变共享 root 密码/其他账号”的单目标 primitive。期望：非 ROOT 角色以 root 为目标时拒绝且零命令；实际：200 success=true，密码/组命令已执行。

修复前 56/4、修复后 60/0；失败用例不使用 xfail/skip。修复后日志/JUnit：`role-adversarial-fixed.log`、`junit-role-adversarial-fixed.xml`、`node-security-default-full.log`、`junit-node-security-default-full.xml`，均位于 `E:/AI/Fuxi_audit_artifacts/root-handover-2026-10-24/adversarial-node/`。
