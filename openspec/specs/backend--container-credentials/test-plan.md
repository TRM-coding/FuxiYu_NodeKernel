# backend--container-credentials Test Plan

Spec: [spec.md](spec.md)

## Current Mapping


### Requirement: 密码输入使用 SecretStr 且只保持最小生命周期

#### Scenario: SecretStr 掩码

- Test/check:
  - [X] tests/test_password_contracts.py::test_secretstr_masking_across_models
  - [X] tests/test_password_contracts.py::test_create_message_root_password_contract
  - [X] tests/test_password_contracts.py::test_update_role_password_contract
- Assertion scope: 既有：创建、恢复、新增协作者、更新 ROOT、重置五个入口经 `jsonable_encoder` 与 `repr()` 后 JSON 均不含明文；`test_update_role_password_contract` 另断言更新 ADMIN 的 `password` 在 `repr()` 中同样为掩码；`root_password` 只有 `get_secret_value()` 才返回明文。
- Coverage note: `AddCollaboratorConfig`、`ResetContainerPasswordConfig` 没有独立 Scenario；由同一掩码用例覆盖，不另造场景。

#### Scenario: 创建密码不进入 Docker 运行配置

- Test/check:
  - [X] tests/test_password_services.py::test_create_password_not_in_docker_config
  - [X] tests/test_password_exec.py::test_chpasswd_stdin_argv
- Assertion scope: 既有：`containers.run` 的 args 与 kwargs（含 `environment`）整体序列化后不含明文；密码 exec 的 argv 恰为 `["chpasswd"]`，明文只出现在 exec stdin 的套接字字节流中。
- Coverage note: 正文“`restore_accounts` 的瞬时密码复用同一 helper”由 `test_add_collaborator_uses_password` 的 stdin 断言与创建编排的 `add_collaborator` 调用共同证明；没有第二条 Docker 配置注入路径。

#### Scenario: 密码不进入 WSS 或 action 缓存

- Test/check:
  - [X] tests/test_password_api.py::test_password_not_in_status_or_wss
  - [X] tests/test_anvil_creation_credentials.py::test_restore_account_password_absent_from_snapshot_wss_cache_and_logs
- Assertion scope: 既有：`CreateContainerMessage.model_dump()` 序列化不含 `root_password` 明文与 `credentials`，创建受理响应文本不含明文。补测：一次带 `restore_accounts` 的真实 `/api/create_container` 之后，`extensions.status_cache.list_states()` 与 `get_state(name)["last_action"]`、`wss.build_status_snapshot()` 全量 JSON、响应体均不含该密码、`root_password`、`password`、`credentials` 与 stdin 内容。
- Coverage note: 既有断言只到“模型 dump + 单次响应文本”，未读取 status/action 缓存投影与 WSS 快照。正文的“数据库”约束在 Node 无数据库层，本仓没有可执行断言；本行只锁 Node 缓存与 WSS。

#### Scenario: 恢复密码不进入 snapshot

- Test/check:
  - [X] tests/test_password_contracts.py::test_restore_password_not_in_snapshot
  - [X] tests/test_anvil_creation_credentials.py::test_restore_account_password_absent_from_snapshot_wss_cache_and_logs
- Assertion scope: 既有：`RestoreAccountConfig.model_dump()` 的 `password` 为掩码，`model_dump()` 与 `model_dump_json()` 均不含明文。补测：恢复成功与恢复失败（`add_collaborator` 返回 False）两条路径结束后，快照/WSS/action 缓存/响应/caplog+capsys 均无明文。
- Coverage note: “Ctrl 也不得写入持久化 snapshot”属 Ctrl 仓库，Node 侧不可断言；本行只锁 Node 侧快照、缓存、WSS、日志与响应。

#### Scenario: 不提供密码查回

- Test/check:
  - [X] tests/test_password_api.py::test_no_password_lookup_endpoint
  - [X] tests/test_anvil_creation_credentials.py::test_restore_account_password_absent_from_snapshot_wss_cache_and_logs
- Assertion scope: 既有：`/openapi.json` 中路径含 `password` 的路由方法集合只含 `post`（无查询端点）。补测：创建完成后 status 缓存与 WSS 全量载荷中检索不到该密码/`credentials`，说明 Node 没有可逆读面。
- Coverage note: “读取持久化数据取回密码”在 Node 无对应存储，只能以快照/缓存不可见间接证明。

### Requirement: 通过 stdin 安全执行 chpasswd

#### Scenario: stdin 传递密码且 argv 不含密码

- Test/check:
  - [X] tests/test_password_exec.py::test_chpasswd_stdin_argv
  - [X] tests/test_password_exec.py::test_chpasswd_stdin_real_socketio
- Assertion scope: 既有：`exec_create(container.id, ["chpasswd"], stdin=True, tty=False, user="root")`；stdin 收到 `u1:<密码>\n` 且写端 shutdown；真实 `socket.socketpair()` + `SocketIO` 场景对端收到 `b"u1:Real#Socket9\n"`，`_exec_chpasswd_stdin` 返回 0。

#### Scenario: 特殊字符按数据处理

- Test/check:
  - [X] tests/test_password_exec.py::test_chpasswd_stdin_argv
  - [X] tests/test_role_adversarial.py::test_valid_roles_keep_secret_on_stdin
- Assertion scope: 既有：`test_chpasswd_stdin_argv` 的密码含 `$`、`;`、反引号、引号、反斜杠，作为整段 stdin 字节原样送达，argv 仍为 `["chpasswd"]`；`test_valid_roles_keep_secret_on_stdin` 的 API 层合法密码含 `$`、`;`、括号，四个角色路径的所有容器命令文本均不含明文（未被 shell 拼接）。
- Coverage note: “不被任何 shell 解释”由“argv 无 shell 拼接 + stdin 字节原样”证明，未在真实容器内执行。

#### Scenario: chpasswd 非 0 时脱敏失败

- Test/check:
  - [X] tests/test_password_exec.py::test_chpasswd_failure_sanitized
  - [X] tests/test_anvil_creation_credentials.py::test_chpasswd_failure_does_not_retry
- Assertion scope: 既有：`exec_inspect` 退出码 1 时 `_exec_chpasswd_stdin` 返回 1，`_set_account_password` 抛 `RuntimeError`，异常文本不含明文。补测：失败路径 `api.exec_create` 只被调用 1 次（不自动重试），错误只含固定原因、不含 stdin 内容或原始输出。
- Coverage note: 既有断言未覆盖 THEN 中“不自动重试”这一部分。

#### Scenario: add_collaborator 日志不含初始密码

- Test/check:
  - [X] tests/test_password_services.py::test_add_collaborator_logs_no_secret
  - [X] tests/test_anvil_creation_credentials.py::test_add_collaborator_logs_no_echo_or_chpasswd_command
- Assertion scope: 既有：一次 `add_collaborator` 后 stdout+caplog 不含明文，也不含 `u1:u1123`；既有用例未断言 `echo ... | chpasswd` 或 `chpasswd` 字样。补测：同一 helper 执行后 stdout+caplog 不含 `chpasswd`、不含 `echo` 拼接密码/`u1:` 文本，密码只出现在 stdin socket 字节中。
- Coverage note: 既有只锁明文与 `u1:u1123`；`echo ... | chpasswd` 命令模式由补测覆盖，不把既有断言扩大为命令模式断言。

#### Scenario: update_role 日志不含 ROOT/旧 owner 密码

- Test/check:
  - [X] tests/test_password_services.py::test_update_role_logs_no_secret
  - [X] tests/test_role_adversarial.py::test_api_root_transport_failure_is_500_redacted
- Assertion scope: 既有：旧 ROOT 降 ADMIN 与 ROOT 目的一次调用后 stdout+caplog 不含任一明文；API 层 ROOT 传输失败时响应与日志无明文，`error_reason == "internal_error"`，且失败后不执行清理组命令。

#### Scenario: 普通角色切换不触碰密码

- Test/check:
  - [X] tests/test_password_services.py::test_plain_role_switch_no_password
  - [X] tests/test_update_role.py::test_admin_existing_without_password_does_not_chpasswd
  - [X] tests/test_role_adversarial.py::test_valid_roles_keep_secret_on_stdin
- Assertion scope: 既有：`test_plain_role_switch_no_password` 与 `test_admin_existing_without_password_does_not_chpasswd` 在 admin/collaborator 未提供密码时 `client.api.created == []`（未实际执行 chpasswd）；`test_valid_roles_keep_secret_on_stdin` 进一步断言命令仍执行 `usermod -aG sudo u1`/`deluser u1 sudo`，且没有 `chpasswd` stdin。
- Coverage note: 前两条只锁“没有密码 exec”；组操作命令与 stdin 为空由第三条用例补齐，不新增实现。

### Requirement: 密码不得进入日志、错误、WSS、缓存与响应

#### Scenario: 日志与异常无明文

- Test/check:
  - [X] tests/test_password_services.py::test_logs_and_exceptions_no_secret
  - [X] tests/test_role_adversarial.py::test_validation_and_internal_errors_do_not_log_secret
- Assertion scope: 既有：ROOT 传输失败后 stdout+caplog 无明文；含 `:` 的 `root_password` 触发 422 与一次内部失败两条路径的日志同样无明文。
- Coverage note: 正文“Node 不写浏览器 localStorage/sessionStorage”属 Web 仓库，Node 侧没有浏览器执行面；Node 也没有数据库层，数据库约束在本仓无可执行断言。本行不伪造这两类断言。

#### Scenario: 响应不返回凭据

- Test/check:
  - [X] tests/test_password_api.py::test_add_collab_response_redacts
  - [X] tests/test_password_api.py::test_update_role_response_redacts
  - [X] tests/test_password_api.py::test_responses_no_credentials
- Assertion scope: 既有：新增协作者与更新角色成功响应包含 `success` 与 `decrypted_message`（`container_name`/`user_name`/`role` 或 `updated_role`），响应文本无明文、无 `credentials`；未逐键断言没有其他非敏感字段。新增协作者失败时 500 的 `error_reason == "add_failed"` 且无明文。
- Coverage note: 更新角色失败路径由“失败响应夹带尝试不泄漏”与“日志与异常无明文”覆盖；本行不把成功响应断言扩大为失败响应全文断言。

#### Scenario: 凭据响应禁止缓存

- Test/check:
  - [X] tests/test_password_api.py::test_password_routes_no_store
  - [X] tests/test_role_adversarial.py::test_invalid_password_contract_rejected_before_docker
- Assertion scope: 既有：创建（422）、新增协作者（200）、更新角色（200）、重置（200）四条密码路由的响应头 `Cache-Control == "no-store"`；更新角色的 19 组 422 脱敏体也带 `no-store`。
- Coverage note: “Ctrl/Web 返回 `credentials` 同样 MUST `no-store`”属 Ctrl/Web 仓库，Node 侧只能证明本仓路由。

#### Scenario: ROOT 交接逐次调用、逐项凭据

- Test/check:
  - [X] tests/test_password_services.py::test_root_handover_orchestration
  - [X] tests/test_role_adversarial.py::test_repeated_handover_sequence_is_deterministic_and_redacted
- Assertion scope: 既有：先 `update_role(old_root, ADMIN, password=...)` 再 `update_role(target, ROOT, root_password=...)` 时 stdin 内容分别出现 `b"old_root:Role#Password9\n"` 与 `b"root:Root#Password9\n"`；三轮重复交接记录完全一致（三次 200 + `success=True`、`created == 3`、三条 stdin 摘要），响应与日志无明文。
- Coverage note: THEN 中“Ctrl 返回所有旧账号 + `root` 的凭据（单旧 ROOT 2 项）”属 Ctrl 仓库；Node 侧只锁“每次只出现本次目标的一个密码字段”。

#### Scenario: 单次 ROOT 请求只带本次密码字段

- Test/check:
  - [X] tests/test_password_services.py::test_root_transfer_single_target
  - [X] tests/test_role_adversarial.py::test_transfer_root_extra_field_is_ignored_and_no_scan
  - [X] tests/test_password_contracts.py::test_update_role_password_contract
- Assertion scope: 既有：`test_root_transfer_single_target` 的 ROOT 目标调用出现 `b"root:Root#Password9\n"`，命令文本不含 `old_root`、不含 `root:target123`；`test_transfer_root_extra_field_is_ignored_and_no_scan` 中请求体附加 `transfer_root`/`owner_name`/`other_user` 被忽略（只对 target 执行、`_sent` 仅 1 条）；同时带 `root_password` 与 `password` 的模型抛 `ValidationError`。
- Coverage note: “完整交接的 Ctrl 响应包含 root 与所有旧所有者凭据”属 Ctrl 仓库。

#### Scenario: 不新增重复密码审计

- Test/check:
  - [X] tests/test_password_api.py::test_no_duplicate_password_audit
  - [X] tests/test_anvil_creation_credentials.py::test_create_logs_carry_no_password_or_credential_entry
  - [X] tests/test_anvil_creation_credentials.py::test_root_handover_no_new_password_audit
- Assertion scope: 既有：新增协作者与手动重置各一次后，stdout+caplog 不含明文，也不含 `password=`（Node 未新增密码审计行）。补测：完整创建日志无新密码/凭据条目；旧 ROOT 降 ADMIN + ROOT 目标交接后 stdout+caplog 不含 `password=`、无新增密码审计行/重复条目。
- Coverage note: 既有只覆盖新增与重置两条路由；创建与 ROOT 交接的审计断言由上述补测补齐。“Ctrl 沿用 `ADD_COLLABORATOR`/`UPDATE_COLLABORATOR_ROLE`、超时不得伪装成功”属 Ctrl 仓库。

#### Scenario: 非密码路由保持默认 422

- Test/check:
  - [X] tests/test_password_api.py::test_non_password_route_default_422
- Assertion scope: 既有：`/api/container_status` 的非法请求仍返回 422 且响应含 `detail`、无 `success` 字段，响应头不是 `no-store`（未被密码路由脱敏 handler 改写）；未逐键断言默认 error 形状。

#### Scenario: 失败响应夹带尝试不泄漏

- Test/check:
  - [X] tests/test_password_api.py::test_failure_response_no_secret
  - [X] tests/test_role_adversarial.py::test_api_admin_transport_failure_reports_false
- Assertion scope: 既有：重置/更新角色的服务抛含 `secret=...` 的异常时响应 500 且无明文；ADMIN 传输失败时响应 200 + `success` 为假、无明文，并满足 `_assert_redacted`（无 `input`/`ctx`、`no-store`）；失败体使用固定的 `error`/`error_reason` 文案，未逐键断言没有其他非敏感字段，响应文本不含密码。

### Requirement: 含密码请求的校验错误必须脱敏

#### Scenario: 同层字段缺失时不回显密码

- Test/check:
  - [X] tests/test_password_api.py::test_password_route_422_redaction
  - [X] tests/test_anvil_creation_credentials.py::test_password_routes_sibling_missing_422_redacted
- Assertion scope: 既有：创建请求带合法 `root_password` 但 `config` 缺必填字段时返回 422，响应文本不含明文且无 `input`/`ctx`；重置密码 `short` 非法时 422 且无回显（不是同层字段缺失）。补测：创建、新增协作者、更新角色、重置四条路由分别携带合法密码并省略一个同层必填字段，均返回 422，`detail` 键集只含 `type`/`loc`/`msg`，无 `input`/`ctx`/`url`，响应无明文、带 `no-store`，且 fake Docker 未被调用。
- Coverage note: 既有只覆盖创建的同层字段缺失与重置的非法密码；新增/更新/重置的“同层缺字段”由补测覆盖。

#### Scenario: 密码本身非法时不回显

- Test/check:
  - [X] tests/test_role_adversarial.py::test_invalid_password_contract_rejected_before_docker
  - [X] tests/test_password_api.py::test_password_route_422_redaction
  - [X] tests/test_anvil_creation_credentials.py::test_create_root_password_invalid_422_redacted
- Assertion scope: 既有：更新角色 19 组非法/错位密码（缺失、空串、过短、超长、全空白、含 `:`、CR、LF、NUL、类型错误、双密码混用）均返回 422，响应无明文、无 `input`/`ctx`、带 `no-store`；重置密码 `short` 同样 422 且无回显。补测：创建路由的非法 `root_password`（空、超长、含 `:`、控制字符）同样 422 且不回显，并断言 `detail` 无 `url`。
- Coverage note: 创建路由缺“密码本身非法”的 HTTP 层断言，由补测覆盖。

#### Scenario: 类型错误不携带原值

- Test/check:
  - [X] tests/test_password_api.py::test_password_route_422_redaction
  - [X] tests/test_role_adversarial.py::test_invalid_password_contract_rejected_before_docker
  - [X] tests/test_anvil_creation_credentials.py::test_create_root_password_invalid_422_redacted
- Assertion scope: 既有：重置密码传数字 `123` 返回 422、响应不含 `123`、无 `input`/`ctx`；更新角色传数字/数组/对象均 422，响应无明文、无 `input`/`ctx`、带 `no-store`。补测：创建路由传对象类型 `root_password` 同样 422 且不带原值，`detail` 键集只含 `type`/`loc`/`msg`，不含 `url`。

### Requirement: 已受理的密码任务不因客户端断开而取消

#### Scenario: 创建受理后断开

- Test/check:
  - [X] tests/test_runtime_guard.py::test_api_create_visible_before_background_thread_finishes
  - [X] tests/test_anvil_creation_credentials.py::test_create_disconnect_keeps_background_password_step
- Assertion scope: 既有：真实 `TestClient` HTTP 受理先于后台完成（响应已回、缓存状态先为 `creating`、后台完成后 `last_action.phase == "confirmed"`），只证明受理与后台解耦，未模拟断开，不覆盖本 Scenario。补测：真实 `create_app` + `httpx2.ASGITransport` 发起 `POST /api/create_container`；fake Docker 的 `containers.run` 在后台 worker 中由 `threading.Event` 阻塞；等待 worker 进入 `containers.run` 后，在受理响应已返回的时点 `aclose`/取消 ASGI client，再释放 worker；断言 `containers.run` 只 1 次、root `chpasswd` stdin 只出现一次（`api.started[0]["socket"].sent == b"root:<明文>\n"`）、`last_action.phase == "confirmed"`，无第二次创建或密码步骤。明确这是 ASGI transport 生命周期断开/取消，不声称真实 TCP 断开。
- Coverage note: 既有只证明受理先于后台；ASGI 断开由补测覆盖，不能用“响应已回”代替断开断言。创建场景的断开点是 accepted 响应已返回后的 ASGI client 关闭（不是请求处理中取消），与 spec 的“受理后断开”一致；不声称服务端收到真实 TCP FIN。

#### Scenario: 新增、重置或转移执行中断开

- Test/check:
  - [X] tests/test_password_api.py::test_sync_disconnect_continues
  - [X] tests/test_anvil_creation_credentials.py::test_sync_password_routes_survive_asgi_disconnect
- Assertion scope: 既有：仅 handler 层证据——`reset_container_password_api` 是同步函数（`inspect.iscoroutinefunction(...) is False`），直接调用会调用已打桩的 `reset_container_password` 并返回 `{"success": 1}`；未执行真实 `chpasswd`，`iscoroutinefunction` 不是断开证据，不覆盖本 Scenario。补测：真实 `create_app` + `httpx2.ASGITransport` 分别发起 add/update/reset 的 `POST`，fake `exec_create` 在服务线程由 `threading.Event` 阻塞；等待进入后取消 ASGI request task（或发送 ASGI disconnect），释放 worker；断言每条路由只执行一次 `chpasswd`、stdin 字节正确、无第二次 exec；失败路径不出现 `200`/`success`。明确这是 ASGI request 生命周期取消，不是真实 TCP，不对端到端网络断开作声明。
- Coverage note: 既有只到 handler 层；新增/重置/转移的断开语义由 ASGI 补测承担，不能用 `isCoroutineFunction` 或直接调用 handler 伪证。
