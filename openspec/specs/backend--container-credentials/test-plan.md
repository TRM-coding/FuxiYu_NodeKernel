# 容器账号凭据 测试覆盖

规格：[spec.md](spec.md)

## 当前场景映射

| Requirement | Scenario | 测试位置 | 状态 |
| --- | --- | --- | --- |
| 密码输入使用 SecretStr 且只保持最小生命周期 | SecretStr 掩码 | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_secretstr_masking_across_models | 🟢 已通过 |
| 密码输入使用 SecretStr 且只保持最小生命周期 | 创建密码不进入 Docker 运行配置 | [test_password_services.py](../../../tests/test_password_services.py)::test_create_password_not_in_docker_config | 🟢 已通过 |
| 密码输入使用 SecretStr 且只保持最小生命周期 | 密码不进入 WSS 或 action 缓存 | [test_password_api.py](../../../tests/test_password_api.py)::test_password_not_in_status_or_wss | 🟢 已通过 |
| 密码输入使用 SecretStr 且只保持最小生命周期 | 恢复密码不进入 snapshot | [test_password_contracts.py](../../../tests/test_password_contracts.py)::test_restore_password_not_in_snapshot | 🟢 已通过 |
| 密码输入使用 SecretStr 且只保持最小生命周期 | 不提供密码查回 | [test_password_api.py](../../../tests/test_password_api.py)::test_no_password_lookup_endpoint | 🟢 已通过 |
| 通过 stdin 安全执行 chpasswd | stdin 传递密码且 argv 不含密码 | [test_password_exec.py](../../../tests/test_password_exec.py)::test_chpasswd_stdin_argv | 🟢 已通过 |
| 通过 stdin 安全执行 chpasswd | 特殊字符按数据处理 | [test_password_exec.py](../../../tests/test_password_exec.py)::test_chpasswd_stdin_argv | 🟢 已通过 |
| 通过 stdin 安全执行 chpasswd | chpasswd 非 0 时脱敏失败 | [test_password_exec.py](../../../tests/test_password_exec.py)::test_chpasswd_failure_sanitized | 🟢 已通过 |
| 通过 stdin 安全执行 chpasswd | add_collaborator 日志不含初始密码 | [test_password_services.py](../../../tests/test_password_services.py)::test_add_collaborator_logs_no_secret | 🟢 已通过 |
| 通过 stdin 安全执行 chpasswd | update_role 日志不含 ROOT/旧 owner 密码 | [test_password_services.py](../../../tests/test_password_services.py)::test_update_role_logs_no_secret | 🟢 已通过 |
| 通过 stdin 安全执行 chpasswd | 普通角色切换不触碰密码 | [test_password_services.py](../../../tests/test_password_services.py)::test_plain_role_switch_no_password | 🟢 已通过 |
| 密码不得进入日志、错误、WSS、缓存与响应 | 日志与异常无明文 | [test_password_services.py](../../../tests/test_password_services.py)::test_logs_and_exceptions_no_secret | 🟢 已通过 |
| 密码不得进入日志、错误、WSS、缓存与响应 | 响应不返回凭据 | [test_password_api.py](../../../tests/test_password_api.py)::test_responses_no_credentials | 🟢 已通过 |
| 密码不得进入日志、错误、WSS、缓存与响应 | 凭据响应禁止缓存 | [test_password_api.py](../../../tests/test_password_api.py)::test_password_routes_no_store | 🟢 已通过 |
| 密码不得进入日志、错误、WSS、缓存与响应 | ROOT 交接逐次调用、逐项凭据 | [test_password_services.py](../../../tests/test_password_services.py)::test_root_handover_orchestration | 🟢 已通过 |
| 密码不得进入日志、错误、WSS、缓存与响应 | transfer_root=false 只带单项 | [test_password_services.py](../../../tests/test_password_services.py)::test_root_transfer_single_target | 🟢 已通过 |
| 密码不得进入日志、错误、WSS、缓存与响应 | 不新增重复密码审计 | [test_password_api.py](../../../tests/test_password_api.py)::test_no_duplicate_password_audit | 🟢 已通过 |
| 密码不得进入日志、错误、WSS、缓存与响应 | 非密码路由保持默认 422 | [test_password_api.py](../../../tests/test_password_api.py)::test_non_password_route_default_422 | 🟢 已通过 |
| 密码不得进入日志、错误、WSS、缓存与响应 | 失败响应夹带尝试不泄漏 | [test_password_api.py](../../../tests/test_password_api.py)::test_failure_response_no_secret | 🟢 已通过 |
| 含密码请求的校验错误必须脱敏 | 同层字段缺失时不回显密码 | [test_password_api.py](../../../tests/test_password_api.py)::test_password_route_422_redaction | 🟢 已通过 |
| 含密码请求的校验错误必须脱敏 | 密码本身非法时不回显 | [test_password_api.py](../../../tests/test_password_api.py)::test_password_route_422_redaction | 🟢 已通过 |
| 含密码请求的校验错误必须脱敏 | 类型错误不携带原值 | [test_password_api.py](../../../tests/test_password_api.py)::test_password_route_422_redaction | 🟢 已通过 |
| 已受理的密码任务不因客户端断开而取消 | 创建受理后断开 | [test_password_api.py](../../../tests/test_password_api.py)::test_sync_disconnect_continues | 🟢 已通过 |
| 已受理的密码任务不因客户端断开而取消 | 新增、重置或转移执行中断开 | [test_password_api.py](../../../tests/test_password_api.py)::test_sync_disconnect_continues | 🟢 已通过 |

## 覆盖说明

- 本能力由本次变更新建，表中覆盖其全部 Requirement/Scenario。
- 测试位置相对本台账目录计算；测试代码保留在仓库既有 `tests/` 目录，未新增测试目录。
- 同一测试函数覆盖多个紧密相关场景时，表内按场景分别登记。

## 最近验证

- 时间：2026-10-24 17:30 +0800
- 版本：6961aee997bd155d96212776a3ff2ec66c95a6df（实现 + 工具抽取 FIX 提交；主 spec 同步前版本）
- 主 spec SHA256：14ED05D02CF84E228462146C02800430F84FA493BE460E0EBA18D1E6142B875B
- 命令与环境：`cd /mnt/e/AI/Fuxi/FuxiYu_NodeKernel && /home/chest/.cache/fuxi-password-tests-offline/bin/python -m pytest -q --no-header`；WSL Linux 隔离 venv，docker 7.1.0
- 结果：`444 passed, 16 deselected, 24 subtests passed`，0 skipped；SocketIO wrapper 专项 `5 passed`；密码专项 `36 passed`。
- 限制：FakeDocker/FakeExecAPI 证明 Node argv/stdin/错误边界；真实 `socket.socketpair()` + `SocketIO` 测试证明 wrapper I/O；未连接真实 Docker daemon 或远程主机，不宣称生产环境验证。
