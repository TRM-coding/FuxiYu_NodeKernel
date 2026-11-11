# Test Plan

映射范围：`backend--common-contracts`、`backend--node-identity`、`backend--runtime-configuration`，共 3 个能力、12 个 Scenario（4 + 4 + 4）。本文件只记录映射与断言范围，不含执行结果。`[X]` 表示已存在的测试且其断言已按测试代码核对；`[ ]` 表示该测试尚待创建或 locator 未确认。缺口测试统一规划到新文件 `tests/test_anvil_node_foundations.py`，默认不接真实 Docker 与网络。

## backend--common-contracts

### Requirement: EmptyConfig 数据契约 [schemas/common.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_blueprint_api.py::test_machine_status_online`
  - [X] `tests/test_anvil_node_foundations.py::test_empty_config_accepts_empty_mapping_and_rejects_non_mapping`
- Assertion scope: 既有用例经 `/api/machine_status` 提交 `{"config": {}}` 得到 200 与 `machine_status == "online"`，证明空映射可被该模型接受并照常进入业务；规划用例直接构造 `EmptyConfig()` 并断言其无声明字段、空映射校验通过、非映射输入（如数组/标量）被 `ValidationError` 拒绝。
- Coverage note: 既有用例只间接覆盖"空映射可接受"，未触及模型层缺省与边界；该类型无声明字段，Pydantic 默认忽略额外键，因此 THEN 中"违反类型或 Field 边界的输入不作为有效实例"只能在"非映射输入"这一层断言，额外键被接受是当前实现事实、不在断言范围。

### Requirement: ApiErrorResponse 数据契约 [schemas/common.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_api_error_response_defaults_and_required_error`
  - [X] `tests/test_blueprint_api.py::test_remove_collaborator_failure_returns_500`
- Assertion scope: 规划用例断言 `ApiErrorResponse.model_fields` 恰为 `{"success","error","error_reason"}`（错误字段名字面为 `error`）、`ApiErrorResponse(error="x")` 的 `success == 0` 且 `error_reason is None`、缺 `error` 时抛 `ValidationError`、`error` 传非字符串被拒；既有用例只断言真实 500 响应的 `status_code == 500`、`body["success"] == 0`、`body["error_reason"] == "remove_failed"`，不断言 `error` 键。
- Coverage note: `error` 字段名与模型缺省/必填校验此前无任何断言，全部由规划行承担，既有 `[X]` 不承担该面；"`success` 不能替代 HTTP 状态"的结论归 SuccessResponse 场景的规划行，本场景不重复声明。

### Requirement: SuccessResponse 数据契约 [schemas/common.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_success_response_default_and_int_bool_forms`
  - [X] `tests/test_anvil_node_foundations.py::test_success_marker_is_independent_of_http_status`
  - [X] `tests/test_mount_usage_models.py::test_response_wire_fields_are_exact`
  - [X] `tests/test_blueprint_api.py::test_create_container_success`
- Assertion scope: 规划模型用例断言 `SuccessResponse()` 的 `success == 1`、`success=0`/`True`/`False` 原样保留、不可强转的输入被 `ValidationError` 拒绝；规划端点用例在 `/api/add_collaborator` 上用 `_patched_service(monkeypatch, "add_collaborator", lambda *a, **k: False)` 让服务返回 False，断言 HTTP 200 且响应体 `success` 为 `0/False`（真实"状态与标记不一致"分支），并结合 `/api/remove_collaborator` 成功分支的 HTTP 200/`success == 1` 与失败分支的 HTTP 500/`success == 0`，证明同一 HTTP 200 可承载 `success` 1 与 0、`success` 0 可同时出现在 200 与 500，结果标记不能替代 HTTP 状态；既有模型用例只断言 `CheckMountUsageResponse` 的 wire 字段集合恰为 `{"success","mounts"}`，既有端点用例只断言 200 响应体 `success == 1`。
- Coverage note: 两条 `[X]` 都不覆盖缺省值与"标记不替代 HTTP 状态"，这两面分别由两条规划行承担；其中端点规划行用 `/api/add_collaborator` 的真实不一致分支（服务 False → HTTP 200/`success` 0）配合 `/api/remove_collaborator` 的 200/1 与 500/0，才能排除"`success` 只是镜像 HTTP 状态"的实现，仅靠 remove 的 200/1 与 500/0 无法排除；`success` 为 `int | bool` 宽松模式，字符串 `"yes"` 会被强转为 `True` 而非拒绝，因此边界断言只覆盖不可强转的输入类型。

### Requirement: ErrorResponses 数据契约 [schemas/common.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_error_responses_declaration_uses_api_error_model`
  - [X] `tests/test_blueprint_api.py::test_remove_collaborator_failure_returns_500`
- Assertion scope: 规划用例断言声明容器含 `INVALID_JSON`(400) 与 `INTERNAL_ERROR`(500) 两项、两项都以 `ApiErrorResponse` 为 `model` 且 `description` 非空，并断言真实错误信封 `{"success":0,"error":...,"error_reason":...}` 能通过 `ApiErrorResponse` 校验；既有用例只断言真实 500 信封的取值。
- Coverage note: 400 与 500 的状态区分只由规划行的声明映射承担，既有 `[X]` 不承担；`ErrorResponses` 是声明容器、不构成请求 payload，因此不规划端点级用例；THEN 中"运行配置只传配置值、证书数据只传文件引用"两句在本类型无对应成员，分别由 runtime-configuration 与 NodeCertificateFiles 的映射承载。

## backend--node-identity

### Requirement: IssueNodeUidRequest 数据契约 [network/wss.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_issue_node_uid_request_requires_uid`
  - [X] `tests/test_blueprint_api.py::test_node_identity_enrollment_and_issue_uid`
- Assertion scope: 规划用例断言 `IssueNodeUidRequest(uid="u")` 保留 uid、缺 `uid` 抛 `ValidationError`、非字符串 uid 被拒；既有用例断言 `POST /api/node_identity/issue_uid` 接受 `{"uid": "node-test-uid"}` 并回写 `uid`、`identity_initialized == True`。
- Coverage note: 既有用例只覆盖合法请求进入端点后的身份落盘形状，未覆盖模型必填与类型边界。

### Requirement: NodeIdentity 数据契约 [network/wss.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_node_identity_is_frozen_and_identity_file_override`
  - [X] `tests/test_cache_collectors.py::test_wss_snapshot_batch_reads_all_cache_views`
- Assertion scope: 规划用例断言其为冻结 dataclass、字段集合恰为 `("uid",)`、赋值抛 `FrozenInstanceError`、`NODE_IDENTITY_FILE` 覆写后身份文件读写落在该路径、对象上不存在证书指纹成员；既有用例断言 `NodeIdentity(uid=...)` 的 uid 原样进入快照批次 `node_uid`。
- Coverage note: 既有用例只覆盖"uid 单一职责在线上原样传递"，未覆盖冻结性、字段集合与身份文件路径覆写；身份文件路径在调用时读取环境变量，测试内 `monkeypatch.setenv` 即可，不需要重载模块。

### Requirement: NodeCertificateFiles 数据契约 [network/wss.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_node_certificate_files_are_paths_and_frozen`
  - [X] `tests/test_blueprint_api.py::test_node_self_signed_certificate_is_valid_pin_anchor`
- Assertion scope: 规划用例断言字段集合恰为 `("cert_file","key_file")` 且两者均为 `Path`、对象冻结、在 `NODE_TLS_CERT_FILE`/`NODE_TLS_KEY_FILE` 覆写到 `tmp_path` 后由 `ensure_self_signed_certificate()` 返回的对象指向这两个路径、对象不携带证书正文或私钥内容；既有用例断言返回的 `cert_file` 指向真实 PEM 并可通过 `x509` 解析（证书数据以文件引用传递）。
- Coverage note: 既有用例只覆盖证书文件路径可用与证书内容合法，未断言"仅记录路径、不保存私钥内容"的结构约束。

### Requirement: NodeEnrollmentProfile 数据契约 [network/wss.py]

#### Scenario: Ctrl 查询 Node 首连资料

- Test/check:
  - [X] `tests/test_blueprint_api.py::test_node_identity_enrollment_and_issue_uid`
  - [X] `tests/test_blueprint_api.py::test_enrollment_profile_advertises_snapshot_endpoint`
  - [X] `tests/test_blueprint_api.py::test_ctrl_link_endpoint_registered_on_same_app`
  - [X] `tests/test_anvil_node_foundations.py::test_enrollment_profile_contains_static_hardware_and_issued_uid`
- Assertion scope: 三条既有用例分别断言首连资料 `uid is None`、`identity_initialized is False`、响应不含 `certificate_fingerprint`；断言 `snapshot_endpoint == CTRL_LINK_PATH` 且 `wss_enabled` 不在响应中；断言 `CTRL_LINK_PATH == "/ws/ctrl"` 且该路径注册在同一张 app 上（快照路径字面量的唯一来源）。规划用例断言 `hardware` 键存在且为映射形状（复用静态硬件画像来源，不固化具体硬件值），并在 `issue_uid` 之后断言 `uid`/`identity_initialized` 反映已初始化状态。
- Coverage note: 前两条 `[X]` 只把返回值与常量比较，字面量 `/ws/ctrl` 由第三条 `[X]` 承担；`hardware` 与"颁发 uid 后再次查询"此前无覆盖，由规划行承担。指纹部分由 THEN 归给 Ctrl 从 TLS 层计算，Node 侧只能断言"响应不含指纹"。

## backend--runtime-configuration

### Requirement: NetConfig 数据契约 [config.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_net_config_declares_only_node_port`
- Assertion scope: 在 `with monkeypatch.context() as local:` 内先 `local.delenv("NODE_PORT", raising=False)`，再 `importlib.reload(config)`，断言 `NetConfig` 只声明 `NODE_PORT` 一项且其值为合法监听端口整数、不存在 Ctrl 地址类配置键，与"Node 只知道自己的监听端口、不要求配置 Ctrl 地址"一致；`finally` 中再 `importlib.reload(config)` 恢复，不使用 `monkeypatch.undo()`。
- Coverage note: 该能力此前无任何直接测试；缺省端口的具体数值未在 spec 中声明，故只校验类型与端口范围、不固化实现默认值；类属性在导入时由 `_env_int` 求值，不做环境隔离会读到机器上的 `NODE_PORT` 而误判。

### Requirement: PortConfig 数据契约 [config.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_port_config_default_range_constants`
  - [X] `tests/test_port_allocator.py::test_ports_are_handed_out_sequentially_from_range_start`
- Assertion scope: 规划用例在 `with monkeypatch.context() as local:` 内 `local.delenv("NODE_PORT_RANGE_START", raising=False)` 与 `local.delenv("NODE_PORT_RANGE_END", raising=False)`，再 `importlib.reload(config)`，断言两项缺省为 20000 与 29999 且起止有序，`finally` 中再 reload 恢复；既有用例断言分配器从 `NODE_PORT_RANGE_START` 顺序取号，证明配置只以配置值形式被运行入口消费。
- Coverage note: 既有用例以类属性为起点推导期望值，因此不构成对缺省值本身的断言；缺省值断言必须先隔离 `NODE_PORT_RANGE_*` 环境变量，否则会读到环境值；缺省段与显式 Docker 绑定由 port_allocator 承担的部分不在本场景范围。

### Requirement: KeyConfig 数据契约 [config.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_key_config_declares_paths_without_secret_material`
- Assertion scope: 断言 `PUBLIC_KEY_PATH`/`PRIVATE_KEY_PATH`/`PUBLIC_KEY_CONTROL` 三个键存在、值为文件名路径字符串、字段内容不含 PEM 标记或私钥正文（不复制密钥）。
- Coverage note: 该能力此前无任何直接测试；spec 明确"是否仍被运行入口消费在 Global 问题清单中核查"，故只断言配置键与"不复制密钥"，不规划消费路径行为断言。

### Requirement: AppConfig 数据契约 [config.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_app_config_inherits_key_config_and_env_overrides`
- Assertion scope: 断言 `AppConfig` 继承 `KeyConfig`、`PUBLIC_KEY_PATH`/`PRIVATE_KEY_PATH` 两键同名覆盖且新增 `SECRET_KEY`；在 `with monkeypatch.context() as local:` 内 `local.setenv(...)` 后 `importlib.reload(config)`，断言读到环境值，`finally` 中再 `importlib.reload(config)` 恢复，不使用 `monkeypatch.undo()`；断言中不出现任何实际凭据值。
- Coverage note: 该能力此前无任何直接测试；`AppConfig` 属性在导入时求值，覆写断言必须用局部 `monkeypatch.context()`，否则 `monkeypatch.undo()` 会连同共享 fixture 注入的 patch（如 fake docker client）一起撤销；"SPEC 不记录实际凭据值"以"不断言具体值"体现。
