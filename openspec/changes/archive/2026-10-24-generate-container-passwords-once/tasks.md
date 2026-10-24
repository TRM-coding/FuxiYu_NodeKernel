## 1. 契约与输入校验

- [x] 1.1 编写失败测试： `tests/test_password_contracts.py` 覆盖 test-plan 中 CreateContainerMessage、RestoreAccountConfig、AddCollaboratorConfig、UpdateRoleConfig、UpdateRoleResponse、Reset 模型及 SecretStr 掩码/非法密码场景（确认因字段/模型缺失而红）
- [x] 1.2 实现： 在 `schemas/container.py` 增加 `SecretStr` 字段、密码约束、ROOT/ADMIN 条件校验与 reset 模型，并在 `schemas/__init__.py` 导出
- [x] 1.3 重构： 契约测试转绿，未改动已批准 spec

## 2. stdin chpasswd 与日志脱敏

- [x] 2.1 编写失败测试： `tests/test_password_exec.py` 覆盖 stdin/argv、特殊字符、非 0 错误、add/update 日志无 secret（确认 helper 不存在或行为不符而红）
- [x] 2.2 实现： 在 `services/container_service.py` 增加低层 exec_create/exec_start(socket) stdin helper；密码不进 argv/shell/临时文件，错误固定脱敏
- [x] 2.3 重构： exec/日志测试转绿，普通角色不触发 `chpasswd`

## 3. 新增协作者与旧 ROOT 降 ADMIN

- [x] 3.1 编写失败测试： `tests/test_password_services.py` 覆盖 add_collaborator 使用 password、失败不回退、旧 ROOT 降 ADMIN 创建/更新独立账号、普通 ADMIN 不改密码/缺账号 fail closed
- [x] 3.2 实现： `add_collaborator` 接收/消费 `SecretStr`；`update_role(ADMIN)` 有 password 时建号并设置，无 password 时只调整既有账号组
- [x] 3.3 重构： 新服务测试转绿，既有目录/归档/角色结果不变

## 4. ROOT 单目标 primitive 与幂等组清理

- [x] 4.1 编写失败测试： `tests/test_password_services.py` 覆盖 ROOT `root_password`、不扫描其他账号、删除用户来源、目标不在 sudo/wheel 幂等、两步顺序/历史多 ROOT/第二步失败不回滚、transfer_root=false 单目标
- [x] 4.2 实现： `update_role(ROOT)` 使用 root_password 设置共享 root、最小幂等组清理、归档/删除目标原账号；不创建旧 owner 账号，不更新绑定
- [x] 4.3 重构： ROOT primitive 测试转绿，transfer_root 仍只在 Ctrl 层

## 5. 创建/恢复密码流

- [x] 5.1 编写失败测试： `tests/test_password_services.py` 与既有 create 测试覆盖 create 使用顶层 root_password、失败不回退、restore_accounts 瞬时 password、恢复失败连带创建失败、创建日志不重复
- [x] 5.2 实现： `create_container` 接收 root_password；create API 后台透传；restore_accounts 内部调用 add_collaborator 时传瞬时 password
- [x] 5.3 重构： 创建/恢复测试转绿，既有创建受理/状态/日志语义不变

## 6. API reset、422 脱敏与 no-store

- [x] 6.1 编写失败测试： `tests/test_password_api.py` 覆盖 reset 成功/root/404/409/500/非法输入/断连、密码路由 422 脱敏、非密码路由默认 422、成功/错误响应 no-store
- [x] 6.2 实现： 新增 `/api/reset_container_password`；为密码路由使用自定义 `APIRoute` 做路由级 422 脱敏与 `Cache-Control: no-store`，不替换全局错误处理
- [x] 6.3 重构： API 测试转绿，其他路由 422 形状不变

## 7. 响应脱敏、审计与既有回归

- [x] 7.1 编写失败测试： `tests/test_password_api.py`/`tests/test_password_services.py` 覆盖 add/update 响应不含 secret、失败异常不含 secret、无凭据查回、无重复密码审计、WSS/action/snapshot 不含密码
- [x] 7.2 实现： 响应只回公开字段；Node 不写 oplog/不新增密码日志；确认 status/WSS/snapshot 不持有 secret
- [x] 7.3 重构： 旧有 add/update/create 测试更新到新密码参数并通过；`pytest` 默认套件保持全绿

## 8. 完整验证与证据

- [x] 8.1 运行 WSL 完整安全套件与针对性回归，记录命令、pass/skip 到 test-plan/verify
- [x] 8.2 运行 `openspec instructions verify`，写 `verify.md` 的 Evidence 与唯一 `DECISION` 行
- [x] 8.3 `git diff --check`，全部 tasks 勾选后提交实现与测试

## 9. 底层账号密码工具抽取

- [x] 9.1 将 `_container_user_exists`、`_docker_exec_api`、`_exec_socket_target`、`_exec_chpasswd_stdin`、`_set_account_password` 最小抽取到 `docker_operates/account_passwords.py`；service 仅导入调用，业务函数位置与语义不变
- [x] 9.2 测试优先直接测工具模块；补充真实 `socket.socketpair()` + `socket.SocketIO` 的写入/EOF/读取/关闭测试
- [x] 9.3 使用默认完整仓库命令 `python -m pytest -q --no-header` 验证，更新 test-plan/verify 的真实计数，并提交单独 FIX commit
