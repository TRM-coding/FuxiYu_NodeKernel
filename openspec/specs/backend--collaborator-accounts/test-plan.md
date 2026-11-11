# backend--collaborator-accounts Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: AddCollaboratorConfig 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_password_contracts.py::test_add_collaborator_contract`
  - [X] `tests/test_blueprint_api.py::test_add_collaborator_invalid_role_422`
  - [X] `tests/test_anvil_accounts_procedure.py::test_add_collaborator_config_required_and_identity_fields`
- Assertion scope: 既有模型用例断言合法配置被接受、`repr()`/`model_dump()` 不出现明文、缺 `password` 与七类非法密码抛 `ValidationError`；既有端点用例断言 `role="hacker"` 经真实请求返回 422。规划用例补 `container_name`/`user_name` 缺失、错误类型及 `role` 非 Literal 的拒绝，并断言没有可依赖的缺省值。
- Coverage note: 该类型没有可依赖的缺省值；正文要求的 password 必填与非法值拒绝由既有模型行承担，请求边界与缺失身份字段由规划行承担。

#### Scenario: 新增协作者携带 Ctrl 密码

- Test/check:
  - [X] `tests/test_password_contracts.py::test_add_collaborator_contract`
  - [X] `tests/test_password_services.py::test_add_collaborator_uses_password`
- Assertion scope: 模型用例断言 admin 合法 `SecretStr` 被接受、`repr()` 与 `model_dump()` 只显掩码；服务用例对 ADMIN 与 COLLABORATOR 断言明文只写入 `exec_start` 的 stdin（`u1:Role#Password9\n`），exec argv 不含明文。
- Coverage note: 正文约束的“两种角色都由 Ctrl 提供密码、Node 只用于 stdin”由模型与服务行组合承担；密码不进入 Docker 配置由 fake Docker 的 `containers.run_calls` 为空、命令只走 exec/stdin 核对，规划行 `test_add_collaborator_role_group_matrix` 同时承担该边界。

#### Scenario: 新增协作者缺少 password

- Test/check:
  - [X] `tests/test_password_contracts.py::test_add_collaborator_contract`
  - [X] `tests/test_anvil_accounts_procedure.py::test_add_collaborator_missing_or_invalid_password_http_422`
- Assertion scope: 既有模型行断言缺 `password` 抛 `ValidationError`；规划行通过 `POST /api/add_collaborator` 断言 422、响应不含 `input`/`ctx`/明文、fake Docker 的容器查找与 exec 均未执行、不回退 `u1123`。
- Coverage note: 既有只到模型层；HTTP 边界、未创建账号和默认密码回退没有既有断言。

#### Scenario: 新增协作者密码非法

- Test/check:
  - [X] `tests/test_password_contracts.py::test_add_collaborator_contract`
  - [X] `tests/test_anvil_accounts_procedure.py::test_add_collaborator_missing_or_invalid_password_http_422`
- Assertion scope: 既有模型行对空、短、超长、全空白、含冒号/LF/NUL 的密码断言 `ValidationError`；规划行对空、超长、冒号、CR/LF/NUL 经真实端点断言 422、响应与日志无原值、fake Docker 未执行账号创建。
- Coverage note: 既有只证明模型拒绝；HTTP 状态、日志脱敏和“未执行创建”由规划行承担。

### Requirement: AddCollaboratorMessage 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_blueprint_api.py::test_add_collaborator_success`
  - [X] `tests/test_blueprint_api.py::test_add_collaborator_invalid_role_422`
  - [X] `tests/test_anvil_accounts_procedure.py::test_add_collaborator_message_requires_outer_config`
- Assertion scope: 既有成功端点用例只证明外层 `config` 被接受并走成功分支（端点调用了被替换的服务，`lambda` 未记录参数）；非法 role 用例断言嵌套非法值在请求层 422。规划用例用记录参数的 service stub 断言 `container_name`/`user_name`/`role` 原样转发，并断言缺 `config` 或 `config` 非对象被 `ValidationError`/HTTP 422 拒绝。
- Coverage note: 该模型没有声明缺省；正文“外层对象、嵌套 config、FastAPI 前置校验”由成功分支、非法 role 与规划缺 config/字段转发分支共同承担。

### Requirement: AddCollaboratorResponse 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_blueprint_api.py::test_add_collaborator_success`
  - [X] `tests/test_anvil_accounts_procedure.py::test_add_collaborator_response_default_and_required_message`
- Assertion scope: 既有成功端点断言 `success is True` 且 `decrypted_message` 为三键公开配置；规划用例断言省略 `success` 时默认 1、缺 `decrypted_message` 被 `ValidationError` 拒绝、非法类型被拒。
- Coverage note: 既有未断言默认值与必填缺失；该模型没有其它声明缺省。

#### Scenario: 新增协作者成功响应脱敏

- Test/check:
  - [X] `tests/test_blueprint_api.py::test_add_collaborator_success`
  - [X] `tests/test_password_api.py::test_add_collab_response_redacts`
  - [X] `tests/test_password_api.py::test_responses_no_credentials`
- Assertion scope: 成功端点响应 `success` 为真，`decrypted_message` 恰为 `container_name`/`user_name`/`role`，响应文本不含明文；`test_responses_no_credentials` 的 add collaborator 分支另行断言响应不出现 `credentials` 与密码。

#### Scenario: 新增协作者失败响应脱敏

- Test/check:
  - [X] `tests/test_password_api.py::test_add_collab_response_redacts`
  - [X] `tests/test_password_services.py::test_add_collaborator_uses_password`
  - [X] `tests/test_anvil_accounts_procedure.py::test_add_collaborator_failure_path_redacts_and_no_fallback`
- Assertion scope: 既有端点用例让服务抛含密码异常，断言 500/`add_failed` 且响应无明文；服务用例让 chpasswd 退出非 0，断言返回 False、stdout 无密码与默认值。规划行把真实服务失败接到端点，断言响应与 caplog 无明文、不返回 `success:1`、不回退默认。
- Coverage note: 既有未把失败服务、HTTP 响应、日志和默认回退放在同一断言链。

### Requirement: RemoveCollaboratorConfig 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_blueprint_api.py::test_remove_collaborator_success`
  - [X] `tests/test_anvil_accounts_procedure.py::test_remove_collaborator_wire_models_and_response_default`
- Assertion scope: 既有端点成功用例只断言合法 `container_name`/`user_name` 被外层 config 接受并返回 `success == 1`，其 `lambda *a: True` 没有记录服务参数；规划用例用记录参数的 service stub 断言两个字段原样转发，并断言缺字段、错误类型被 `ValidationError` 拒绝。
- Coverage note: 该模型没有声明缺省；请求边界的缺失字段没有既有断言。

### Requirement: RemoveCollaboratorMessage 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_blueprint_api.py::test_remove_collaborator_success`
  - [X] `tests/test_anvil_accounts_procedure.py::test_remove_collaborator_wire_models_and_response_default`
- Assertion scope: 既有成功端点断言外层 config 被接受；规划用例断言缺 config 或 config 非对象被 `ValidationError`/HTTP 422 拒绝。
- Coverage note: 既有未覆盖外层对象缺失/类型错误的请求边界。

### Requirement: RemoveCollaboratorResponse 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_blueprint_api.py::test_remove_collaborator_success`
  - [X] `tests/test_blueprint_api.py::test_remove_collaborator_failure_returns_500`
  - [X] `tests/test_anvil_accounts_procedure.py::test_remove_collaborator_wire_models_and_response_default`
- Assertion scope: 既有成功/失败端点断言成功 `success == 1`、失败 500/`success == 0`/`remove_failed`；规划用例断言模型省略 `success` 时默认 1，并保留同一成功信封形状。
- Coverage note: 既有未直接构造模型默认值。

### Requirement: UpdateRoleConfig 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_password_contracts.py::test_update_role_password_contract`
  - [X] `tests/test_role_adversarial.py::test_invalid_role_rejected_before_docker`
  - [X] `tests/test_anvil_accounts_procedure.py::test_update_role_config_required_fields_and_optional_defaults`
- Assertion scope: 既有模型用例断言普通 admin 的 `password`/`root_password` 均为 None、合法 root/admin 被接受并掩码；对抗用例断言多种非法 role 在请求边界 422 且不触 Docker。规划用例补 `container_name`/`user_name`/`updated_role` 缺失、错误类型和非法名字的拒绝。
- Coverage note: 该模型没有其它缺省；缺失必填字段未在既有断言中逐项覆盖。

#### Scenario: ROOT 目标携带 root_password

- Test/check:
  - [X] `tests/test_password_contracts.py::test_update_role_password_contract`
  - [X] `tests/test_role_adversarial.py::test_valid_roles_keep_secret_on_stdin`
- Assertion scope: 模型接受 `updated_role="root"` 的合法 `root_password` 并掩码；端到端用例断言 root 分支只把 `root:Root#Password9\n` 写入 stdin，exec argv 与命令文本不含明文。

#### Scenario: ROOT 目标缺少 root_password

- Test/check:
  - [X] `tests/test_password_contracts.py::test_update_role_password_contract`
  - [X] `tests/test_role_adversarial.py::test_invalid_password_contract_rejected_before_docker`
  - [X] `tests/test_role_adversarial.py::test_root_missing_password_and_root_identity_rejected_before_exec`
- Assertion scope: 模型缺 `root_password` 抛 `ValidationError`；端点用例参数化 `root_missing` 断言 422 脱敏且不触 Docker；服务用例断言直接调用在 exec 前抛 `ValueError`。

#### Scenario: 旧 ROOT 降 ADMIN 携带 password

- Test/check:
  - [X] `tests/test_password_contracts.py::test_update_role_password_contract`
  - [X] `tests/test_password_services.py::test_admin_demotion_creates_or_updates_account`
- Assertion scope: 模型接受 admin 携带合法 `password` 并掩码；服务用 stdin 设置 `old_root:Role#Password9\n`，并断言建号使用持久化目录而非默认密码。

#### Scenario: 普通 ADMIN 切换可缺省 password

- Test/check:
  - [X] `tests/test_password_contracts.py::test_update_role_password_contract`
  - [X] `tests/test_update_role.py::test_admin_existing_without_password_does_not_chpasswd`
  - [X] `tests/test_role_adversarial.py::test_valid_roles_keep_secret_on_stdin`
- Assertion scope: 模型接受无密码 admin（两个密码字段为 None）；既有服务/端点断言无密码时 `api.created == []`，不执行 `chpasswd`，只执行管理组命令。

#### Scenario: 普通角色携带 root_password 或 collaborator 携带 password

- Test/check:
  - [X] `tests/test_password_contracts.py::test_update_role_password_contract`
  - [X] `tests/test_role_adversarial.py::test_invalid_password_contract_rejected_before_docker`
  - [X] `tests/test_anvil_accounts_procedure.py::test_update_role_password_matrix_rejects_collaborator_root_password_and_admin_invalid`
- Assertion scope: 既有模型与端点参数化覆盖 admin 携带 `root_password`、collaborator 携带 `password`、root 同时携带两者；没有覆盖 `updated_role="collaborator"` 同时携带 `root_password` 的分支。规划用例补该分支的模型拒绝与 HTTP 422 脱敏，并断言不触 Docker。
- Coverage note: `collaborator + root_password` 是未披露的真实分支缺口；其余三组已由既有参数化覆盖。

#### Scenario: 密码字段非法

- Test/check:
  - [X] `tests/test_password_contracts.py::test_update_role_password_contract`
  - [X] `tests/test_role_adversarial.py::test_invalid_password_contract_rejected_before_docker`
  - [X] `tests/test_role_adversarial.py::test_validation_and_internal_errors_do_not_log_secret`
  - [X] `tests/test_anvil_accounts_procedure.py::test_update_role_password_matrix_rejects_collaborator_root_password_and_admin_invalid`
- Assertion scope: 既有模型循环对空、短、超长、全空白、冒号、CR/LF/NUL 的 `root_password` 断言 `ValidationError`；端点参数化的 admin 分支只有 `admin_short`、`admin_colon`、`admin_int`，没有空、超长、全空白、CR/LF/NUL。规划用例补 admin 的完整非法密码矩阵、collaborator+root_password 分支，均断言 HTTP 422、无原值、无 `chpasswd`。
- Coverage note: 既有只覆盖部分 admin 非法值；admin 的空、超长、全空白、CR/LF/NUL 与 `collaborator + root_password` 由规划行承担。

### Requirement: UpdateRoleMessage 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_blueprint_api.py::test_update_role_success`
  - [X] `tests/test_blueprint_api.py::test_update_role_invalid_role_422`
  - [X] `tests/test_anvil_accounts_procedure.py::test_update_role_message_requires_outer_config`
- Assertion scope: 既有端点成功/失败用例证明外层 config 被接受、嵌套非法 role 被 422 拒绝；规划用例断言缺 config 或 config 非对象被拒。
- Coverage note: 既有未覆盖外层对象缺失/类型错误。

### Requirement: UpdateRoleResponse 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_password_contracts.py::test_update_role_response_plain_shape`
  - [X] `tests/test_anvil_accounts_procedure.py::test_update_role_response_defaults_and_role_shapes`
- Assertion scope: 既有模型用例断言显式 `success == 1` 与 `decrypted_message` 容器字段；规划用例断言省略 `success` 时默认 1、缺 `decrypted_message` 被 `ValidationError` 拒绝。
- Coverage note: 默认值与必填缺失没有既有断言。

#### Scenario: 普通角色切换保持既有响应

- Test/check:
  - [X] `tests/test_role_adversarial.py::test_valid_roles_keep_secret_on_stdin`
  - [X] `tests/test_anvil_accounts_procedure.py::test_update_role_response_defaults_and_role_shapes`
- Assertion scope: 既有端点断言普通 admin/collaborator 成功时 `success` 为真且无密码 stdin；规划行断言普通切换的 `decrypted_message` 仍为 `container_name`/`user_name`/`updated_role` 三键，无凭证字段。
- Coverage note: 既有未逐字断言普通角色切换的响应形状。

#### Scenario: ROOT 与旧 ROOT 降 ADMIN 响应脱敏

- Test/check:
  - [X] `tests/test_password_api.py::test_update_role_response_redacts`
  - [X] `tests/test_password_api.py::test_responses_no_credentials`
  - [X] `tests/test_anvil_accounts_procedure.py::test_update_role_response_defaults_and_role_shapes`
- Assertion scope: 既有 ROOT 分支断言 `success is True`、`decrypted_message` 恰为三键公开配置；旧 ROOT 降 ADMIN 分支只断言 200 与响应无密码，没有断言 `success`；`test_responses_no_credentials` 只覆盖 ROOT 分支无 `credentials`。规划用例补断言旧 ROOT 降 ADMIN 的 `success is True`、公开三键形状与无 `credentials`/密码。

#### Scenario: 失败响应不回显密码

- Test/check:
  - [X] `tests/test_password_api.py::test_failure_response_no_secret`
  - [X] `tests/test_role_adversarial.py::test_validation_and_internal_errors_do_not_log_secret`
  - [X] `tests/test_role_adversarial.py::test_api_root_transport_failure_is_500_redacted`
- Assertion scope: 422/500 响应与日志无密码；root transport failure 返回 500/`internal_error`，且不执行清理命令；admin transport failure 返回 200 但 `success` 为假，不伪装成功。

### Requirement: CollaboratorRole 数据契约 [schemas/container.py]

#### Scenario: 使用声明值域

- Test/check:
  - [X] `tests/test_blueprint_api.py::test_add_collaborator_invalid_role_422`
  - [X] `tests/test_blueprint_api.py::test_add_collaborator_success`
  - [X] `tests/test_anvil_accounts_procedure.py::test_role_literal_values_and_runtime_enum_are_distinct`
- Assertion scope: 既有端点接受 admin、拒绝 hacker 并返回 422；规划用例断言 admin/collaborator 各自被模型接受，root 与其它值被拒，不把兼容别名解释成新协议。
- Coverage note: 既有未枚举完整合法/非法值域。

### Requirement: UpdatedRole 数据契约 [schemas/container.py]

#### Scenario: 使用声明值域

- Test/check:
  - [X] `tests/test_role_adversarial.py::test_invalid_role_rejected_before_docker`
  - [X] `tests/test_role_adversarial.py::test_valid_roles_keep_secret_on_stdin`
- Assertion scope: 对抗用例参数化大量非法 role 在请求边界 422；合法 admin/collaborator/root 分别进入相应密码/组分支。

### Requirement: ROLE 数据契约 [constant.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_role_literal_values_and_runtime_enum_are_distinct`
- Assertion scope: 断言 `ROLE.ADMIN.value == "admin"`、`ROLE.COLLABORATOR.value == "collaborator"`、`ROLE.ROOT.value == "root"`，三个成员互不相等；并断言字符串 `"admin"` 不是 ROLE 实例，运行层枚举与 schemas Literal 分别维护。
- Coverage note: 既有测试只把 ROLE 成员作为服务参数使用，未断言值域或类型区分。Scenario 的“运行配置只传配置值、证书数据只传文件引用”在本类型没有对应成员，分别由 `backend--runtime-configuration` 与 `backend--node-identity` 的映射承担，不把它们伪装成 ROLE 的断言。

### Requirement: 恢复重建账号时修正家目录属主 [services/container_service.py]

#### Scenario: 按恢复清单重建账号

- Test/check:
  - [X] `tests/test_blueprint_api.py::test_create_container_restore_payload_passes_mount_and_accounts`
  - [X] `tests/test_password_api.py::test_create_restore_password_failure`
  - [X] `tests/test_anvil_accounts_procedure.py::test_restore_accounts_rebuild_each_entry_and_fail_closed`
- Assertion scope: 既有用例断言恢复账号按 container_name/user_name/role/password 调用一次 `add_collaborator`，且失败时 `last_action.phase == "failed"`、`error_reason == "create_failed"`；规划用例用两条清单断言逐项按顺序调用，任一条 False 即失败且后续不再被当作成功。
- Coverage note: 既有只覆盖单条和单条失败；逐项与多条目顺序没有断言。恢复条目的 `role` 决定是否加入管理组，这一分支由 Scenario“新增 ADMIN 或 COLLABORATOR 使用下发密码”的规划行 `test_add_collaborator_role_group_matrix` 承担。

#### Scenario: 属主随账号重建被修正

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_restore_account_home_chown_targets_new_account`
- Assertion scope: fake Docker 捕获恢复账号的 exec 命令，断言建号命令使用 `/root/.collaborators/<user>` 持久化目录，随后 `chown -R <user>:<user> /root/.collaborators/<user>`；断言不使用删除前的数字 uid/gid 或默认 `<user>123`。
- Coverage note: fake Docker 只证明下发命令的目标为新建账号；真实内核 ACL/可读写不在本阶段执行，不声称真实 adduser/chpasswd 验证。

#### Scenario: 家目录数据随挂载取回

- Test/check:
  - [X] `tests/test_create_container.py::test_create_container_restore_reuses_existing_mount`
  - [X] `tests/test_anvil_accounts_procedure.py::test_restore_mount_preserves_files_and_reuses_source`
- Assertion scope: 既有用例断言恢复挂载路径存在时 `bind_mount_path` 与 `containers.run` 的 `Mount.Source` 都指向同一宿主目录；规划用例在该目录预置文件后走恢复创建，断言文件仍存在且挂载来源仍是该目录。
- Coverage note: 既有只证明挂载复用，不证明文件内容；规划行用宿主文件保留与 Mount.Source 证明数据随挂载可取回，不声称真实容器内可见性。

### Requirement: 新增协作者使用 Ctrl 下发的随机密码 [services/container_service.py]

#### Scenario: 新增 ADMIN 或 COLLABORATOR 使用下发密码

- Test/check:
  - [X] `tests/test_password_services.py::test_add_collaborator_uses_password`
  - [X] `tests/test_password_services.py::test_add_collaborator_logs_no_secret`
  - [X] `tests/test_anvil_accounts_procedure.py::test_add_collaborator_role_group_matrix`
- Assertion scope: 既有 `test_add_collaborator_uses_password` 的 `capsys` 覆盖 ADMIN/COLLABORATOR，断言 `useradd -M -d /root/.collaborators/u1`、密码只走 stdin、无 `u1:u1123`；`test_add_collaborator_logs_no_secret` 的 `caplog` 只覆盖 ADMIN。规划用例补 ADMIN 的 `usermod -aG sudo`（失败再 wheel）、COLLABORATOR 不追加管理组，并对两角色分别断言 `capsys.readouterr().out + caplog.text` 均无密码，且 add collaborator 路径不调用 `containers.run`、不把密码放进容器配置。
- Coverage note: 既有断言未区分两个角色的管理组命令，也未覆盖 COLLABORATOR 的 `caplog`。正文的“Node 不写 oplog，Ctrl 沿用 ADD_COLLABORATOR”不在 Node 测试范围；规划行只核对容器内命令与日志，不声称 Ctrl 审计已验证。

#### Scenario: 缺少 password 时不回退默认

- Test/check:
  - [X] `tests/test_password_contracts.py::test_add_collaborator_contract`
  - [X] `tests/test_anvil_accounts_procedure.py::test_add_collaborator_missing_or_invalid_password_http_422`
- Assertion scope: 既有模型行拒绝缺 `password`；规划行断言 HTTP 422、不执行账号创建、不回退默认密码。
- Coverage note: 与 Scenario“新增协作者缺少 password”/“新增协作者密码非法”共用同一规划行；既有未覆盖 HTTP 边界。

#### Scenario: 密码设置失败不伪装成功

- Test/check:
  - [X] `tests/test_password_services.py::test_add_collaborator_uses_password`
  - [X] `tests/test_anvil_accounts_procedure.py::test_add_collaborator_failure_path_redacts_and_no_fallback`
- Assertion scope: 既有用例让 chpasswd 非 0，断言服务返回 False、stdout 无密码与默认密码；规划行经真实端点断言不返回 `success:1`、响应/日志无密码、未回退默认。
- Coverage note: 既有未覆盖 HTTP 响应与 caplog 的同一失败链。

### Requirement: 旧 ROOT 降 ADMIN 时按 Ctrl 密码创建独立账号 [services/container_service.py]

#### Scenario: 旧 ROOT 降 ADMIN 创建独立账号

- Test/check:
  - [X] `tests/test_password_services.py::test_admin_demotion_creates_or_updates_account`
  - [X] `tests/test_update_role.py::test_admin_ensure_user_home_in_collaborators`
  - [X] `tests/test_anvil_accounts_procedure.py::test_admin_demotion_joins_admin_group_without_touching_root`
- Assertion scope: 既有用例断言目标账号不存在时建号、`useradd -M -d /root/.collaborators/old_root`、stdin 设置 `old_root:Role#Password9\n`；没有断言 `usermod -aG sudo old_root` 或 wheel 回退。规划用例断言建号后下发 `usermod -aG sudo old_root || usermod -aG wheel old_root`，只出现该用户 stdin、没有 `root:` 写入。
- Coverage note: 既有未断言 old_root 的管理组命令，也未显式断言 root stdin 不存在；规划行补命令层面的组断言，但不证明真实组数据库结果。

#### Scenario: 旧 ROOT 降 ADMIN 已有独立账号

- Test/check:
  - [X] `tests/test_password_services.py::test_admin_demotion_creates_or_updates_account`
  - [X] `tests/test_anvil_accounts_procedure.py::test_admin_demotion_joins_admin_group_without_touching_root`
- Assertion scope: 既有用例断言已存在账号不重复 `useradd`、仍用 stdin 更新；没有断言管理组命令。规划用例断言已存在账号仍下发 sudo/wheel 管理组命令，且不写 `root:` 密码。
- Coverage note: 既有只断言用户账号更新，未断言 old_root 的管理组或 root 不受影响；规划行补这两项命令级断言。

#### Scenario: 普通 ADMIN 切换不改密码

- Test/check:
  - [X] `tests/test_password_services.py::test_admin_demotion_creates_or_updates_account`
  - [X] `tests/test_update_role.py::test_admin_existing_without_password_does_not_chpasswd`
  - [X] `tests/test_role_adversarial.py::test_valid_roles_keep_secret_on_stdin`
- Assertion scope: 既有用例断言无 password 且账号存在时只执行 usermod、`api.created == []`，不执行 `chpasswd`；admin_no_password 分支同样无 stdin。

#### Scenario: 普通 ADMIN 切换缺少账号且无密码

- Test/check:
  - [X] `tests/test_password_services.py::test_admin_demotion_creates_or_updates_account`
- Assertion scope: 既有用例断言账号不存在且无 password 时返回 False、`api.created == []`，不创建带默认密码的账号。

### Requirement: ROOT 交接由 Ctrl 统一编排，Node 只处理单目标 [services/container_service.py]

#### Scenario: 按旧 ROOT 再目标的顺序执行

- Test/check:
  - [X] `tests/test_password_services.py::test_root_handover_orchestration`
  - [X] `tests/test_role_adversarial.py::test_repeated_handover_sequence_is_deterministic_and_redacted`
  - [X] `tests/test_anvil_accounts_procedure.py::test_root_handover_order_and_binding_isolation`
- Assertion scope: 既有用例按 old_root ADMIN 然后 target ROOT 调用，断言两次 stdin 分别为 old_root/root 密码、命令包含两目标；重复用例断言三轮响应/命令/stdin 摘要一致且无密码泄漏。既有断言只检查包含关系，没有锁定调用顺序或两次请求之间不共享绑定状态。规划用例记录精确调用顺序，并断言第一次命令不含 target、第二次命令不含 old_root（必要的 root/目标原账号除外），两次请求各自独立。
- Coverage note: Ctrl 端统一编排不由 Node 测试单独证明；规划行只证明 Node 两次单目标调用的顺序与命令隔离，不证明 Ctrl 的数据库/绑定状态。

#### Scenario: 单次 Node 请求只处理指定账号

- Test/check:
  - [X] `tests/test_password_services.py::test_root_transfer_single_target`
  - [X] `tests/test_role_adversarial.py::test_transfer_root_extra_field_is_ignored_and_no_scan`
- Assertion scope: 既有用例断言 target ROOT 只发送 root stdin、命令包含 target 不含 old_root；额外 `transfer_root`/`owner_name` 等字段被忽略，不触发其他账号命令。
- Coverage note: 单次 Node 请求不代表 Ctrl 可以省略完整交接；Node 请求体没有 `transfer_root` 字段。正文的“Node MUST NOT 更新绑定”属 Ctrl/DB 契约，Node 测试不可见，本计划不伪证。

#### Scenario: 历史多 ROOT 逐次处理

- Test/check:
  - [X] `tests/test_role_adversarial.py::test_repeated_handover_sequence_is_deterministic_and_redacted`
  - [X] `tests/test_anvil_accounts_procedure.py::test_root_handover_multiple_old_roots_single_target`
- Assertion scope: 既有重复用例覆盖同一旧 ROOT 与目标的多轮顺序；规划用例对 3 个旧 ROOT 各调用一次 ADMIN 后再调用目标 ROOT，断言每次命令/sent 只涉及该次 user_name（以及 ROOT 必然涉及的 root/目标原账号），不合并不丢失。
- Coverage note: 既有只覆盖一个旧 ROOT，不覆盖历史多 ROOT 的 N+1。

#### Scenario: 目标不在 sudo/wheel 时幂等清理

- Test/check:
  - [X] `tests/test_password_services.py::test_root_group_cleanup_idempotent`
  - [X] `tests/test_role_adversarial.py::test_root_cleanup_command_shape_is_idempotent_and_best_effort_archive`
  - [X] `tests/test_anvil_accounts_procedure.py::test_root_cleanup_records_only_with_all_state_command_doubles`
- Assertion scope: 既有用例断言 ROOT 清理命令用 `for g in sudo wheel`、`grep -qx` 条件删除并保留 archive/userdel/rm；没有证明目标不在两组时的真实控制流。规划用例从 fake Docker 捕获完整清理命令后，在临时 PATH 中执行：`id` 记录并只输出 `target`（不含 sudo/wheel），`deluser` 记录但预期不被调用，`mv`、`userdel`、`rm`、`date` 全部为记录式替身并返回受控退出码，`tr`/`grep` 用只读系统命令；断言整体退出 0，`deluser` 未因 sudo/wheel 被调用，`mv`/`userdel`/`rm` 各记录一次目标路径，伪宿主 sentinel 文件不变，且没有任何真实账号/目录变动。
- Coverage note: 该规划测试不把完整清理脚本交给宿主真实命令：所有会变更状态的命令（deluser、mv、userdel、rm）都只记录、不执行宿主变更；date 仅作确定性替身，id 只记录读取；它证明组判断、退出码与命令记录，不证明真实组数据库或真实删除结果。POSIX shell 依赖使测试只在不能提供 `/bin/sh` 的 Windows 默认套件中显式 skip，并在 WSL/Linux 运行，不用跳过结果冒充验证。

#### Scenario: 删除用户触发的 ROOT 转移同样带密码

- Test/check:
  - [X] `tests/test_role_adversarial.py::test_root_missing_password_and_root_identity_rejected_before_exec`
  - [X] `tests/test_role_adversarial.py::test_invalid_password_contract_rejected_before_docker`
- Assertion scope: 既有用例断言 ROOT 请求缺 `root_password` 在模型/端点被 422、服务在 exec 前抛 `ValueError`，不回退默认密码。
- Coverage note: Ctrl 删除用户路径必须生成密码属于 Ctrl 调用契约；Node 侧只证明缺失即拒绝，不声称 Ctrl 端已验证。

#### Scenario: Node 不扫描其他账号

- Test/check:
  - [X] `tests/test_password_services.py::test_root_transfer_single_target`
  - [X] `tests/test_role_adversarial.py::test_transfer_root_extra_field_is_ignored_and_no_scan`
- Assertion scope: 既有用例断言目标 ROOT 命令不含 old_root、只出现 target/root 相关目标；额外字段不触发扫描。
- Coverage note: 命令序列不能证明真实容器内没有未执行扫描，但能证明 Node 未下发其他账号命令。

#### Scenario: 第二步失败不回滚第一步

- Test/check:
  - [X] `tests/test_role_adversarial.py::test_second_step_failure_does_not_rollback_first_and_repeats`
  - [X] `tests/test_password_services.py::test_root_handover_orchestration`
- Assertion scope: 既有用例先成功旧 ROOT ADMIN，再让目标 ROOT `exec_start` 失败，断言第二次 500/`internal_error`、无 old_root 回滚命令、无 root stdin 或清理命令，重复轮次一致；错误/日志无密码。

#### Scenario: 普通 ADMIN/COLLABORATOR 互换仍不改密码

- Test/check:
  - [X] `tests/test_password_services.py::test_plain_role_switch_no_password`
  - [X] `tests/test_role_adversarial.py::test_valid_roles_keep_secret_on_stdin`
- Assertion scope: 既有用例断言普通 ADMIN/COLLABORATOR 互换 `api.created == []`，无 stdin，仅执行组命令；响应保持 `success` 与既有形状。
- Coverage note: 普通切换的完整响应形状由 Scenario“普通角色切换保持既有响应”的规划行补充。

### Requirement: 重置容器账号密码 [network/api.py]

#### Scenario: 重置普通账号成功

- Test/check:
  - [X] `tests/test_password_api.py::test_reset_endpoint_cases`
  - [X] `tests/test_password_exec.py::test_chpasswd_stdin_argv`
  - [X] `tests/test_password_api.py::test_no_password_lookup_endpoint`
  - [X] `tests/test_anvil_accounts_procedure.py::test_reset_password_service_binds_user_and_root_stdin`
  - [X] `tests/test_anvil_accounts_procedure.py::test_reset_password_no_persistence_and_no_retry`
  - [X] `人工核对： network/api.py @ 97aa0cb 的路由清单 + GET /openapi.json paths`
- Assertion scope: 既有端点用例断言成功返回 200/`{"success":1}`、调用参数 `("c1","u1")`；helper 用例断言普通账号 exec argv 为 `["chpasswd"]`、stdin 为 `u1:...\n`；`test_no_password_lookup_endpoint` 只证明含 `password` 的 OpenAPI 路径没有非 POST 方法，不证明不存在其他名称的查回路径。规划服务用例对普通账号与 root 走真实 `reset_container_password` + 运行中 fake container，断言前导登录名分别为 `u1`/`root` 且 argv 无密码；不持久化/不重试用例用写入守卫和 exec 计数断言无文件写入、成功与失败路径都只执行一次 chpasswd。人工路由清单核对 `network/api.py@97aa0cb` 的 `_password_post`/router 与 `GET /openapi.json` paths，预期密码相关 POST 只有 create/add/update/reset 四类，其他路由不读取或查回密码。
- Coverage note: 既有端点用例替换了服务，未证明服务层在线检查与实际 stdin 在同一路径；“不提供查回”留给 `network/api.py@97aa0cb` 路由清单与 OpenAPI 的人工核对（无 PR 也可复现），不以仅含 password 的路径断言冒充全量查回面；“不持久化/不自动重试”由规划行承担：Node reset 路径没有数据库依赖，规划用例不建立 DB，只以文件写入守卫与 exec 计数证明无文件持久化和无重试，不声称证明所有外部审计系统。

#### Scenario: 重置 root 成功

- Test/check:
  - [X] `tests/test_password_api.py::test_reset_endpoint_cases`
  - [X] `tests/test_anvil_accounts_procedure.py::test_reset_password_service_binds_user_and_root_stdin`
- Assertion scope: 既有端点用例 root 分支只证明 200/`{"success":1}` 且把字符串 `root` 传给被替换的服务，没有执行 `chpasswd`；helper 用例固定使用 `u1`，不能承担 root 前缀。规划服务用例走真实 `reset_container_password` + 运行中 fake container，断言 stdin 恰为 `root:<password>\n`、argv 为 `["chpasswd"]`、只执行一次。
- Coverage note: root 的真实服务绑定与 stdin 没有既有断言；helper 的 `u1` 断言只归普通账号 Scenario，不能挪作 root 证据。

#### Scenario: 容器不存在

- Test/check:
  - [X] `tests/test_password_api.py::test_reset_endpoint_cases`
  - [X] `tests/test_anvil_accounts_procedure.py::test_reset_password_missing_or_stopped_container_no_exec`
- Assertion scope: 既有端点用例让服务抛 `docker.NotFound`，断言 404/`not_found`/响应无密码；规划用例直接调用真实服务，断言容器缺失时在 `exec_create` 前抛 NotFound、无 chpasswd/明文。
- Coverage note: 既有未证明失败发生在 exec 前。

#### Scenario: 容器未运行

- Test/check:
  - [X] `tests/test_password_api.py::test_reset_endpoint_cases`
  - [X] `tests/test_anvil_accounts_procedure.py::test_reset_password_missing_or_stopped_container_no_exec`
- Assertion scope: 既有端点用例断言 409/`container_not_running`；规划用例让 fake container 状态为 stopped，断言在 `_set_account_password` 前抛 `ContainerNotRunning`、无 exec。
- Coverage note: 既有未覆盖服务层短路位置。

#### Scenario: 容器内账号不存在

- Test/check:
  - [X] `tests/test_password_api.py::test_reset_endpoint_cases`
  - [X] `tests/test_password_exec.py::test_chpasswd_failure_sanitized`
  - [X] `tests/test_password_api.py::test_failure_response_no_secret`
- Assertion scope: 端点用例断言服务异常映射 500/`reset_failed`、响应无密码；helper 用例断言 chpasswd 非 0 时 `_set_account_password` 抛 `RuntimeError` 且不含明文；失败响应用例断言 500 体无密码。
- Coverage note: 未在端点层断言真实容器 stderr/原始输出被完全丢弃；现有组合证明固定错误体与 sanitized exception。

#### Scenario: 非法登录名或密码

- Test/check:
  - [X] `tests/test_password_api.py::test_reset_endpoint_cases`
  - [X] `tests/test_password_api.py::test_password_route_422_redaction`
  - [X] `tests/test_anvil_accounts_procedure.py::test_reset_password_invalid_inputs_http_422`
- Assertion scope: 既有端点用例断言短密码/非法 `user_name` 422 且无密码；redaction 用例断言 short/int 422 无 `input`/`ctx`。规划用例补空、超长、全空白、冒号、CR/LF/NUL、非法 `container_name`，全部 422、无原值、fake Docker 零 exec。
- Coverage note: 既有只覆盖部分非法值，未证明所有非法输入都不执行 chpasswd。

#### Scenario: 客户端断开不取消

- Test/check:
  - [X] `tests/test_password_api.py::test_sync_disconnect_continues`
  - [X] `tests/test_anvil_accounts_procedure.py::test_reset_password_http_disconnect_does_not_cancel_chpasswd`
  - [X] `tests/test_anvil_accounts_procedure.py::test_reset_password_no_persistence_and_no_retry`
- Assertion scope: 既有用例断言端点函数非协程并同步调用服务到返回，未模拟断开。规划行直接以原始 ASGI scope 调用应用，使用自定义 `receive` 在请求体读完后注入 `http.disconnect`（不是任务取消、不是直接调用 handler），断言同步 chpasswd 仍执行到 stdin/结束、不自动重试、不伪造成功；不持久化/不重试用例另行断言无文件写入、exec 次数固定。
- Coverage note: 该规划验证的是进程内 ASGI `http.disconnect` 边界，不声称真实 TCP 半关闭或生产网络行为；既有 `test_sync_disconnect_continues` 只证明同步函数形状。
