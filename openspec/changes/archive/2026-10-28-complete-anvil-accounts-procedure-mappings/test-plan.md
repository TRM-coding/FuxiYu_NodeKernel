# Test Plan

映射范围：`backend--collaborator-accounts`（17 个 Requirement / 51 个 Scenario）与 `procedure--repository-workflow`（18 个 Requirement / 40 个 Scenario），共 35 个 Requirement、91 个 Scenario。本文件只记录 Scenario 到 Test/check 的映射与断言范围，不记录执行结果、通过率、时间戳或完成状态。

`[X]` 表示该 locator 是已存在的测试/检查且其断言已按测试源码或实际命令核对；`[ ]` 表示真实缺口，账号行为缺口与 procedure 中可自动化的钩子/检查器规则规划到专属 `tests/test_anvil_accounts_procedure.py` 的具体测试名。procedure 的非自动化规则使用可复现的人工检查或 Git/文件命令，不进入自动测试文件，也不以源码字串、反射或测试名冒充行为证明。每个 checkbox 只表示该行映射是否已核对，不是执行、通过或全 Scenario 覆盖声明。

平台边界：依赖 bash 或 `/bin/sh` 的 `commit-msg`、`pre-commit`、shell 清理、钩子测试只在 Linux/WSL 执行；Windows 默认套件无 bash 时显式 skip 并记录，不用 Windows 跳过或替代结果冒充验证。

## backend--collaborator-accounts

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


## procedure--repository-workflow

### Requirement: 提交信息采用真实变更条目 [githooks/commit-msg]

#### Scenario: 多项变更

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_commit_msg_hook_entry_grammar`
- Assertion scope: 在临时消息文件中写入 NEW、AMEND、FIX 各一条及可独立理解的短句，调用真实 `githooks/commit-msg`，断言退出 0；同一用例对空行与 `#` 注释行断言不计入条目。
- Coverage note: 正文约束“钩子只判断文本结构，条目是否真实与中文是否通顺由人工评审”不由该测试证明；该部分保持人工评审，不用静态断言冒充。

#### Scenario: 自造关键字或缺空格被拒绝

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_commit_msg_hook_entry_grammar`
- Assertion scope: 同一临时钩子用例分别写入 `- DOCS ...`、`- SPEC ...`、`- DEBUG ...` 与 `-NEW ...`，断言 `commit-msg` 退出非 0，并输出允许的 NEW/AMEND/FIX 与“连字符后有空格”的提示。
- Coverage note: 该行是规划 locator；自动检查以临时消息文件驱动真实 `commit-msg`，不执行真实 Git 提交。

#### Scenario: 没有真实条目被拒绝

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_commit_msg_hook_entry_grammar`
- Assertion scope: 同一用例写入只含空行与 Git 注释的消息文件，断言 `commit-msg` 退出非 0，并说明至少需要一条实际变更。
- Coverage note: 规划 locator；不执行真实 Git 提交。

### Requirement: 禁止工具署名与生成标记 [githooks/commit-msg]

#### Scenario: 署名尾注被拒绝

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_commit_msg_hook_attribution_and_last_line`
- Assertion scope: 临时消息分别包含 `Co-Authored-By`、`Generated with` 与生成图标，断言 `commit-msg` 退出非 0，并输出命中行。
- Coverage note: 正文约束“工具参与不改变作者归属”；该测试只证明钩子拒绝文本，不判断真实作者归属。

#### Scenario: 末行不合法仍受检

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_commit_msg_hook_attribution_and_last_line`
- Assertion scope: 同一用例写入没有终止换行、且最后一行不合法的消息，断言仍被拒绝；另写 CRLF 消息，断言行尾 `\r` 被容忍而文件末尾非法条目仍受检。
- Coverage note: 规划 locator；覆盖正文的“末行检查 + CRLF 兼容”，不代表真实提交。

### Requirement: 真实合并提交豁免 [githooks/commit-msg]

#### Scenario: 真实合并

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_commit_msg_hook_merge_exemption_uses_git_state`
- Assertion scope: 在临时 Git 目录写入 `MERGE_HEAD` 后，用由 Git 自动生成的合并信息调用 `commit-msg`，断言退出 0；不创建真实提交。
- Coverage note: 正文约束“豁免由 Git merge 状态而非文本判断”；临时 `MERGE_HEAD` 只模拟该状态。

#### Scenario: 标题写 Merge 不获豁免

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_commit_msg_hook_merge_exemption_uses_git_state`
- Assertion scope: 同一用例在没有 `MERGE_HEAD` 时写入标题含 `Merge` 的消息且无变更条目，断言仍退出非 0。
- Coverage note: 规划 locator；证明标题文字本身不触发豁免。

### Requirement: 钩子随仓库交付并显式启用 [githooks/pre-commit]

#### Scenario: 新克隆启用

- Test/check:
  - [X] `git config --local --get core.hooksPath`
  - [X] `git ls-files githooks/commit-msg githooks/pre-commit`
- Assertion scope: 本仓库克隆的 `core.hooksPath` 为 `githooks`，两个钩子文件已被 Git 跟踪并由仓库交付。
- Coverage note: 只核对本仓库克隆；新克隆仍需执行一次 `git config --local core.hooksPath githooks`。本检查不创建真实 commit，不证明 Git 实际调用钩子。

#### Scenario: 安装前核对既有钩子

- Test/check:
  - [X] `Get-ChildItem .git/hooks -File | Select-Object -ExpandProperty Name`
- Assertion scope: 本仓库 `.git/hooks` 只有 `*.sample`，没有需要保留的自定义钩子；切换 `core.hooksPath` 不会覆盖或合并这些 sample，是否为该克隆保留由配置者判断。
- Coverage note: 人工核对本仓库克隆；正文的“安装前核对”是配置决策，不由命令自动判断。

### Requirement: 钩子保持 LF 与执行位 [.gitattributes]

#### Scenario: 检出换行为 LF

- Test/check:
  - [X] `git check-attr text eol -- githooks/commit-msg githooks/pre-commit`
  - [X] `git ls-files --eol githooks/commit-msg githooks/pre-commit`
- Assertion scope: 两个钩子均返回 `text: set` 与 `eol: lf`；`git ls-files --eol` 显示索引与工作区均为 `i/lf`/`w/lf`，证明 `.gitattributes` 的 `githooks/* text eol=lf` 已覆盖无扩展名文件且索引/工作区内容均为 LF。

#### Scenario: 核对执行位

- Test/check:
  - [X] `git ls-files -s githooks/commit-msg githooks/pre-commit`
- Assertion scope: 两个钩子在索引中的 mode 均为 `100755`。
- Coverage note: 执行位是 Git 索引属性，本地文件权限不反映它；该检查只证明索引 mode。

### Requirement: 新增 capability 使用门类前缀 [githooks/pre-commit]

#### Scenario: 新增页面规格

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_pre_commit_capability_prefix_matrix`
- Assertion scope: 在临时 clone 中新建 `openspec/changes/<tmp>/specs/frontend--page-example/spec.md`，`git add` 后运行 `githooks/pre-commit`，断言退出 0；不执行 commit。
- Coverage note: 临时 clone 与 `git add` 只模拟新增暂存，不产生真实提交；不证明远端 CI 或人工评审。

#### Scenario: 叠加前缀被拒绝

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_pre_commit_capability_prefix_matrix`
- Assertion scope: 同一临时 clone 新建 `frontend--backend--example/spec.md` 并暂存，断言 `pre-commit` 退出非 0，提示只能使用一个门类前缀。
- Coverage note: 规划 locator；不执行 commit。

#### Scenario: 缺少门类前缀被拒绝

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_pre_commit_capability_prefix_matrix`
- Assertion scope: 同一临时 clone 新建无门类前缀的 `example/spec.md` 并暂存，断言 `pre-commit` 退出非 0，并列出四类前缀职责。
- Coverage note: 规划 locator；不执行 commit。

#### Scenario: 修改既有规格不强制改名

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_pre_commit_capability_prefix_matrix`
- Assertion scope: 同一临时 clone 修改既有 `openspec/specs/<cap>/spec.md` 并暂存，断言 `pre-commit` 退出 0，不要求改名或迁移。
- Coverage note: 规划 locator；只证明 Git 识别的修改路径。

#### Scenario: 旧 capability 首次增加 delta

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_pre_commit_capability_prefix_matrix`
- Assertion scope: 同一临时 clone 为 HEAD 已有主规格的旧 capability 新增 delta `openspec/changes/<tmp>/specs/<cap>/spec.md` 并暂存，断言 `pre-commit` 退出 0，delta 新增不被当作 capability 新增。
- Coverage note: 规划 locator；临时 clone 的 HEAD 来自现有仓库，不创建新提交；不覆盖 archive 下的真实改名路径。

### Requirement: 业务能力组织边界 [README.md]

#### Scenario: Node 保持 8 个能力单元

- Test/check:
  - [ ] `人工检查： Get-ChildItem openspec\specs -Directory -Filter 'backend--*' | Measure-Object`
- Assertion scope: 按 Node `97aa0cb` 基线，该命令列出 9 个 `backend--` 主规格目录（含 `backend--wss-snapshots`）；Scenario 名称与正文仍写“8 个”，数量与正文不一致，不能勾选通过，也不写“必须等于 8”的断言。
- Coverage note: 已由父级在 `E:\AI\Fuxi\FuxiYu_Global\QUESTIONS.md` @ Global `607bbfd` Q78（P3，源码与目录确认）登记：这是文档计数过时，不是能力组织重构。本轮仅记录并暂缓，不新开维护实现、不改 README/主 spec/CLI，不合并或删除能力；待父级另开官方 OpenSpec 文档变更同步后再复核该 `[ ]`。

#### Scenario: 前缀不成为删细节的理由

- Test/check:
  - [ ] `人工核对： openspec/specs/backend--*/spec.md @ Node 97aa0cb`
- Assertion scope: 按 Node `97aa0cb` 基线逐文件核对 9 个 `backend--` 主规格是否仍保留完整类型契约与 Requirement/Scenario 细节，并判断补充要求是否在原文件内最小补写；没有能为该语义判断背书的自动断言。
- Coverage note: 正文明确“前缀不成为删细节的理由”属人工评审；既有目录数/前缀事实不能替代该语义判断。

### Requirement: 仓库入口与规格质量 [README.md]

#### Scenario: 入口唯一

- Test/check:
  - [X] `Test-Path README.md; Test-Path README; Get-ChildItem openspec -Recurse -File -Filter README*`
- Assertion scope: 对当前工作树直接运行上述 PowerShell 命令，观察到根目录 `README.md` 存在（`True`），`README` 无扩展名文件不存在（`False`），且 `openspec` 下没有 `README` 或 `README.md` 文件；不用嵌套 `pwsh`，不把当前树结果写成 `97aa0cb` 基线结果。

#### Scenario: 格式通过不等于语义完整

- Test/check:
  - [ ] `openspec validate procedure--repository-workflow --strict`
- Assertion scope: 在 Node `97aa0cb` 工作树运行该命令只证明主 spec 结构可解析；它不判断业务逻辑、状态转换与失败边界描述是否完整。
- Coverage note: 正文要求“格式校验通过不等于语义完整”；需要人工评审，不能把 strict 通过当成语义完整证明。

### Requirement: 规范各仓库独立 [README.md]

#### Scenario: 不依赖外部规范

- Test/check:
  - [X] `人工核对： githooks/commit-msg, githooks/pre-commit, scripts/ci/check_pr.py @ Node 97aa0cb`
- Assertion scope: 按 Node `97aa0cb` 基线逐文件核对三条调用路径：提交信息/钩子/PR 正文校验只读取本仓库的钩子与 `scripts/ci/check_pr.py`，不读取 `FuxiYu_CtrKernel`、`FuxiYu_Web` 或其他仓库的规范文件；预期观察是三条路径的输入只有本仓库文件或 GitHub event JSON。
- Coverage note: 这是无 PR 也可复现的只读文件审查；只核对调用路径与读取范围，不证明人工评审过程绝不查阅外部资料，也不把源码字串扫描当成运行时行为证明。

### Requirement: 问题集中记录并区分证据等级 [Global/QUESTIONS.md]

#### Scenario: 新问题带证据等级

- Test/check:
  - [X] `人工核对： E:\AI\Fuxi\FuxiYu_Global\QUESTIONS.md @ Global 607bbfd, lines 1-191, Q75-Q78`
- Assertion scope: 按 Global `607bbfd` 基线核对 2026-10-28 新增条目：Q75-Q77 使用“本地复现 / 源码确认 / 待验证”三词标签；Q78 使用扩展标签【源码与目录确认】（源码确认与目录核对的组合），不是三词逐字之一。按现有 Global 原文记录 Q78 的扩展标签，不修改 Global，也不把它冒充为三选一。
- Coverage note: 只核对 Q75-Q78 的证据等级标签存在与语义，不判断证据是否充分，也不声称所有历史条目已重审；Global 文件不在本仓库，未纳入自动测试。

#### Scenario: 修复后标注状态

- Test/check:
  - [ ] `人工核对： E:\AI\Fuxi\FuxiYu_Global\QUESTIONS.md @ Global 607bbfd, Q78 lines 185-191 + 未完成问题区`
- Assertion scope: 按 Global `607bbfd` 基线核对 Q78：仍在“未完成问题”区、保留编号与证据，不标为已修复；本轮没有新增已修复条目，若出现则须保留原编号与证据并明确标记已修复。
- Coverage note: 这是对当前未修复项的流程核对，不把“标记已修复”当成业务已修复的运行证明；Q78 保持暂缓。

### Requirement: 流程通过不代表业务问题已修复 [README.md]

#### Scenario: 待办不写成已修复

- Test/check:
  - [X] `git diff --stat 97aa0cb..d35a10a`
  - [ ] `人工检查： 本变更尚无 PR；PR 正文交付栏待实际 PR 出现后核对`
- Assertion scope: 提交侧只读核对固定范围 `97aa0cb..d35a10a`：实际有 b02820e NEW 与 d35a10a AMEND 两个提交，diff 涉及创建凭据归档、测试计划等实际交付；PR 侧无该变更 PR，不能用提交内容冒充 PR 正文，PR 正文交付栏保持 `[ ]`。待父级创建实际 PR 后只核对 PR 正文，不使用 HEAD 漂移范围。
- Coverage note: 提交侧与 PR 侧分开记录：已有提交不等于已有 PR 交付证据；`check_pr.py` 只判断结构，不判断内容真伪。PR 缺失时只暂缓 PR 侧，不把提交范围写成空。

#### Scenario: 钩子通过不等于业务通过

- Test/check:
  - [X] `git log --format=%B 97aa0cb..d35a10a`
  - [ ] `人工检查： 本变更尚无 PR 校验记录；待实际 PR 出现后核对`
- Assertion scope: 提交侧只读核对固定范围 `97aa0cb..d35a10a`：包含 b02820e NEW 与 d35a10a AMEND，提交信息真实存在；PR 侧无该变更 PR/校验记录与业务验证证据，保持 `[ ]`。不把“提交/钩子能通过”写成“业务已通过”，也不把两个提交当作 PR 校验记录。
- Coverage note: 提交侧与 PR 侧分开记录；该区分是评审约定，不存在自动断言；PR 缺失时只暂缓 PR 侧，不伪造校验记录，也不声称钩子能判断业务结果。

### Requirement: PR 正文采用四类中英双语栏目 [.github/pull_request_template.md]

#### Scenario: 只有一栏交付

- Test/check:
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_enhancement_only_is_delivery`
- Assertion scope: 只填 `优化工作 | Enhancements & Patches` 且含真实条目时，`validate_body` 返回空错误列表。

#### Scenario: 只有计划不通过

- Test/check:
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_plan_only_is_not_delivery`
- Assertion scope: 正文只填 `下一步计划 | Coming Up` 时，`validate_body` 返回错误（计划不算本次交付）。

#### Scenario: 交付栏写“无”

- Test/check:
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_empty_column_with_wu_is_allowed`
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_only_wu_in_every_column_fails`
- Assertion scope: 某交付栏写 `- 无` 而另一交付栏有真实条目时结构通过；所有交付栏都只有 `- 无` 时失败，证明“无”不产生结构错误但也不计为真实条目。

#### Scenario: 原样保留模板不通过

- Test/check:
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_template_placeholders_cannot_pass_validation`
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_placeholder_items_are_rejected`
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_missing_verification_is_valid`
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_verification_bullet_cannot_replace_delivery_item`
- Assertion scope: 原样模板被 `validate_body` 判为错误；占位符（`-`、`- ...`、`- TODO`、`- 待填写`、`- 无` 等）逐个被拒；缺失验证说明仍可校验通过；验证栏下的 bullet 不能满足交付条目，证明验证说明不是交付条目的替代。

### Requirement: PR 标题与正文结构分离 [.github/pull_request_template.md]

#### Scenario: 自然描述标题

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_pr_title_is_ignored_by_checker`
- Assertion scope: 以自然描述标题（无 conventional 类型前缀）构造 event JSON，只校验合法正文，断言 `main(["--event", path])` 退出 0；标题不被当作交付内容。
- Coverage note: 自然标题是否“概括本次主要变更”仍由人工评审；测试只证明检查器不因缺少类型前缀而失败。

#### Scenario: 检查器不校验标题

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_pr_title_is_ignored_by_checker`
- Assertion scope: 同一 event JSON 的 `pull_request.title` 写入 `feat: ...` 或命令样文本，正文合法，断言退出 0 且输出不含标题内容；证明检查器只读取正文。
- Coverage note: 规划 locator；不证明 GitHub 或人工评审不检查标题。

### Requirement: PR 栏目与提交关键字相互独立 [scripts/ci/check_pr.py]

#### Scenario: AMEND 提交不改写

- Test/check:
  - [X] `git log --format=%B 97aa0cb..d35a10a`
  - [ ] `人工检查： 该范围对应 PR 正文（本变更尚无 PR）`
- Assertion scope: 提交侧只读核对固定范围 `97aa0cb..d35a10a`：实际包含 b02820e `NEW 补齐创建凭据校验和异步生命周期回归测试` 与 d35a10a `AMEND 归档创建凭据补测映射并保留已知恢复路径缺口`，d35a10a 的 AMEND 关键字保持不变；PR 侧无该变更 PR，不能核对 PR 正文是否改写 AMEND，保持 `[ ]`。固定范围 `97aa0cb..d35a10a` 不随 HEAD 后续变化。
- Coverage note: 正文明确二者相互独立；`check_pr.py` 不读取提交历史，无法自动证明 PR 正文部分。提交侧事实已核对，PR 正文单独保持 `[ ]`，不把两者混为延期。

#### Scenario: 旧栏目仍被接受

- Test/check:
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_new_only_is_valid`
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_fix_only_is_valid`
- Assertion scope: 旧版 `NEW | 新增内容` 与 `FIX | 修复漏洞` 标题均被 `validate_body` 接受。

### Requirement: PR 正文重验与工作流信任边界 [.github/workflows/pr-format.yml]

#### Scenario: 修改正文后重验

- Test/check:
  - [X] `Select-String -Path .github/workflows/pr-format.yml -Pattern 'types: \[opened, edited, synchronize, reopened, ready_for_review\]'`
  - [X] `Select-String -Path .github/workflows/pr-format.yml -Pattern '^permissions:'`
  - [X] `Select-String -Path .github/workflows/pr-format.yml -Pattern 'contents: read'`
  - [X] `Select-String -Path .github/workflows/pr-format.yml -Pattern 'persist-credentials: false'`
- Assertion scope: 在 Node `97aa0cb` 的 `.github/workflows/pr-format.yml` 中，四项声明分别匹配：pull_request 五种触发类型、`permissions:`、`contents: read`、两处 checkout 的 `persist-credentials: false`；四条独立命令不能用单条 alternation 互相替代。
- Coverage note: 只核对工作流声明触发类型与权限文本；未触发 GitHub 实际事件，不证明线上重跑、运行成功或权限在运行期生效。

#### Scenario: 首次接入先校验摘要

- Test/check:
  - [X] `Select-String -Path .github/workflows/pr-format.yml -Pattern 'sha256sum --check --status'`
- Assertion scope: 在 Node `97aa0cb` 的 `.github/workflows/pr-format.yml` 中，声明在基准分支无检查器时对提议分支脚本执行固定 SHA256 校验；摘要不符时 `sha256sum --check --status` 使步骤失败。
- Coverage note: 只核对声明与命令；未执行 GitHub Actions 的首次接入，不证明线上摘要校验已发生。

#### Scenario: 正文只作数据

- Test/check:
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_event_metadata_with_quotes_and_backticks_stays_data`
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_event_body_only_inside_fence_fails`
  - [X] `tests/test_anvil_accounts_procedure.py::test_pr_body_canary_command_does_not_execute`
- Assertion scope: 既有两行证明 event JSON 中的引号、反引号、命令样文本能被读取并按正文结构返回 0/1，但没有断言执行副作用。规划用例在合法正文中放入会创建临时标记文件的命令样文本，运行 `check_pr.main` 后断言退出 0 且标记文件不存在；另以只含围栏命令的正文断言退出 1 且标记仍不存在。
- Coverage note: 既有两行只证明读取/结构判定，不能单独支撑“不产生执行”；规划 canary 才承担无副作用断言，且不使用 `test_checker_does_not_eval_or_shell_out` 的源码字串检查冒充。

### Requirement: 检查能力边界不得夸大 [README.md]

#### Scenario: 不夸大自动检查

- Test/check:
  - [X] `人工核对： README.md@97aa0cb lines 89-93; githooks/commit-msg@97aa0cb lines 51-59; githooks/pre-commit@97aa0cb lines 27-41; scripts/ci/check_pr.py@97aa0cb lines 3-8; openspec/specs/procedure--repository-workflow/spec.md@97aa0cb lines 285-287`
- Assertion scope: 按 Node `97aa0cb` 基线逐处观察，上述文档/注释只声称钩子与检查器覆盖文本结构，不声称能判断中文真实性、PR 标题质量、能力单元划分恰当或业务问题已修复。
- Coverage note: 能力边界表述属人工评审；没有自动断言可证明“没有夸大”，但文件、行号与基线已固定，可复现核对。

### Requirement: 规范入口不使用代理说明文件

#### Scenario: 生成代理说明文件

- Test/check:
  - [X] `git ls-files 'AGENT.md' 'AGENTS.md'`
  - [X] `Get-ChildItem -Recurse -File -Filter 'AGENT*.md'`
- Assertion scope: 在 Node `97aa0cb` 工作树，索引中没有 AGENT.md 或 AGENTS.md，递归工作区扫描也没有 `AGENT*.md` 文件；两条分别覆盖索引与工作区。

### Requirement: 测试替身不得污染测试运行时

#### Scenario: 挂载准备使用真实临时目录

- Test/check:
  - [X] `tests/test_create_container.py::test_create_container_mount_setup_keeps_global_os_stat_real`
- Assertion scope: 创建容器的真实临时目录挂载准备后，进程全局 `os.stat` 对象身份未变；对测试源文件返回 `st_size > 0` 且 `S_ISREG(st_mode)`。

#### Scenario: 权限模拟限制在被测模块

- Test/check:
  - [X] `tests/test_mount_usage_cache.py::test_path_gate_maps_permission_error_without_stat`
  - [X] `tests/test_mount_usage_cache.py::test_invalid_not_found_and_permission_never_start_du`
- Assertion scope: 权限错误被映射为 `permission_denied` 且全局 `os.stat` 仍是真实对象；多个错误路径不启动 `du`。
- Coverage note: 第二条用例的用途是防止权限模拟重新引入全局替换；两条共同承担“只替换被测模块视图”的边界。
