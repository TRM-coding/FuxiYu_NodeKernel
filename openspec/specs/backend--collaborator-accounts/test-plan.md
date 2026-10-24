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
| ROOT 提升/交接由 Ctrl 的 transfer_root 编排，Node 只处理单目标 [services/container_service.py] | 按旧 ROOT 再目标的顺序执行 | [test_password_services.py](../../../tests/test_password_services.py)::test_root_handover_orchestration | 🟢 已通过 |
| ROOT 提升/交接由 Ctrl 的 transfer_root 编排，Node 只处理单目标 [services/container_service.py] | transfer_root=false 只处理目标 | [test_password_services.py](../../../tests/test_password_services.py)::test_root_transfer_single_target | 🟢 已通过 |
| ROOT 提升/交接由 Ctrl 的 transfer_root 编排，Node 只处理单目标 [services/container_service.py] | 历史多 ROOT 逐次处理 | [test_password_services.py](../../../tests/test_password_services.py)::test_root_handover_orchestration | 🟢 已通过 |
| ROOT 提升/交接由 Ctrl 的 transfer_root 编排，Node 只处理单目标 [services/container_service.py] | 目标不在 sudo/wheel 时幂等清理 | [test_password_services.py](../../../tests/test_password_services.py)::test_root_group_cleanup_idempotent | 🟢 已通过 |
| ROOT 提升/交接由 Ctrl 的 transfer_root 编排，Node 只处理单目标 [services/container_service.py] | 删除用户触发的 ROOT 转移同样带密码 | [test_password_services.py](../../../tests/test_password_services.py)::test_root_transfer_single_target | 🟢 已通过 |
| ROOT 提升/交接由 Ctrl 的 transfer_root 编排，Node 只处理单目标 [services/container_service.py] | Node 不扫描其他账号 | [test_password_services.py](../../../tests/test_password_services.py)::test_root_transfer_single_target | 🟢 已通过 |
| ROOT 提升/交接由 Ctrl 的 transfer_root 编排，Node 只处理单目标 [services/container_service.py] | 第二步失败不回滚第一步 | [test_password_services.py](../../../tests/test_password_services.py)::test_root_handover_orchestration | 🟢 已通过 |
| ROOT 提升/交接由 Ctrl 的 transfer_root 编排，Node 只处理单目标 [services/container_service.py] | 普通 ADMIN/COLLABORATOR 互换仍不改密码 | [test_password_services.py](../../../tests/test_password_services.py)::test_plain_role_switch_no_password | 🟢 已通过 |
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
