# 容器创建 测试覆盖

规格：[spec.md](spec.md)

## 当前场景映射

| Requirement | Scenario | 测试位置 | 状态 |
| --- | --- | --- | --- |
| CreateContainerMessage 数据契约 [schemas/container.py] | 字段校验与缺省值 | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_create_message_root_password_contract | 🟢 已通过 |
| CreateContainerMessage 数据契约 [schemas/container.py] | 创建请求携带 root_password | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_create_message_root_password_contract | 🟢 已通过 |
| CreateContainerMessage 数据契约 [schemas/container.py] | 缺少 root_password | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_create_message_root_password_contract | 🟢 已通过 |
| CreateContainerMessage 数据契约 [schemas/container.py] | root_password 非法 | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_create_message_root_password_contract | 🟢 已通过 |
| RestoreAccountConfig 数据契约 [schemas/container.py] | 字段校验与缺省值 | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_restore_account_password_contract | 🟢 已通过 |
| RestoreAccountConfig 数据契约 [schemas/container.py] | 恢复协作者携带瞬时密码 | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_restore_account_password_contract | 🟢 已通过 |
| RestoreAccountConfig 数据契约 [schemas/container.py] | 恢复协作者缺少 password | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_restore_account_password_contract | 🟢 已通过 |
| RestoreAccountConfig 数据契约 [schemas/container.py] | 恢复密码设置失败 | [test_password_api.py](../../../tests/test_password_api.py)::test_create_restore_password_failure | 🟢 已通过 |
| 创建时由 Ctrl 下发的密码设置 root 账号 [services/container_service.py] | 用下发密码设置 root | [test_password_services.py](../../../tests/test_password_services.py)::test_create_uses_root_password_and_no_fallback | 🟢 已通过 |
| 创建时由 Ctrl 下发的密码设置 root 账号 [services/container_service.py] | 密码设置失败时不回退 | [test_password_services.py](../../../tests/test_password_services.py)::test_create_uses_root_password_and_no_fallback | 🟢 已通过 |
| 创建时由 Ctrl 下发的密码设置 root 账号 [services/container_service.py] | 创建响应不携带凭据 | [test_password_api.py](../../../tests/test_password_api.py)::test_responses_no_credentials | 🟢 已通过 |
| 创建时由 Ctrl 下发的密码设置 root 账号 [services/container_service.py] | 既有创建日志不重复 | [test_password_services.py](../../../tests/test_password_services.py)::test_create_uses_root_password_and_no_fallback | 🟢 已通过 |

## 覆盖说明

- 本台账只列本次变更新增或修改的 Scenario；未列出的旧 Scenario 仍保留在主 spec，本轮未重新逐场景映射，不据此声明新的通过结论。
- 测试位置相对本台账目录计算；测试代码保留在仓库既有 `tests/` 目录，未新增测试目录。
- 同一测试函数覆盖多个紧密相关场景时，表内按场景分别登记。

## 最近验证

- 时间：2026-10-24 17:30 +0800
- 版本：6961aee997bd155d96212776a3ff2ec66c95a6df（实现 + 工具抽取 FIX 提交；主 spec 同步前版本）
- 主 spec SHA256：32C1002617D8A6CBF11486130DAF93F3755185AE87C483A9F63AF27A9B29662D
- 命令与环境：`cd /mnt/e/AI/Fuxi/FuxiYu_NodeKernel && /home/chest/.cache/fuxi-password-tests-offline/bin/python -m pytest -q --no-header`；WSL Linux 隔离 venv，docker 7.1.0
- 结果：`444 passed, 16 deselected, 24 subtests passed`，0 skipped；SocketIO wrapper 专项 `5 passed`；密码专项 `36 passed`。
- 限制：FakeDocker/FakeExecAPI 证明 Node argv/stdin/错误边界；真实 `socket.socketpair()` + `SocketIO` 测试证明 wrapper I/O；未连接真实 Docker daemon 或远程主机，不宣称生产环境验证。
