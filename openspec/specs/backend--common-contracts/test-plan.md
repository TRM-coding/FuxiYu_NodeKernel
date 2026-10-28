# backend--common-contracts Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: EmptyConfig 数据契约 [schemas/common.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_blueprint_api.py::test_machine_status_online`
  - [X] `tests/test_anvil_node_foundations.py::test_empty_config_accepts_empty_mapping_and_rejects_non_mapping`
- Assertion scope: 既有用例经 `/api/machine_status` 提交 `{"config": {}}` 得到 200 与 `machine_status == "online"`，证明空映射可被该模型接受并照常进入业务；新增用例直接构造 `EmptyConfig()` 并断言其无声明字段、空映射校验通过、非映射输入（如数组/标量）被 `ValidationError` 拒绝。
- Coverage note: 既有用例只间接覆盖"空映射可接受"，未触及模型层缺省与边界；该类型无声明字段，Pydantic 默认忽略额外键，因此 THEN 中"违反类型或 Field 边界的输入不作为有效实例"只能在"非映射输入"这一层断言，额外键被接受是当前实现事实、不在断言范围。

### Requirement: ApiErrorResponse 数据契约 [schemas/common.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_api_error_response_defaults_and_required_error`
  - [X] `tests/test_blueprint_api.py::test_remove_collaborator_failure_returns_500`
- Assertion scope: 新增用例断言 `ApiErrorResponse.model_fields` 恰为 `{"success","error","error_reason"}`（错误字段名字面为 `error`）、`ApiErrorResponse(error="x")` 的 `success == 0` 且 `error_reason is None`、缺 `error` 时抛 `ValidationError`、`error` 传非字符串被拒；既有用例只断言真实 500 响应的 `status_code == 500`、`body["success"] == 0`、`body["error_reason"] == "remove_failed"`，不断言 `error` 键。
- Coverage note: 既有用例只断言真实 500 响应中的状态码、`success` 与 `error_reason`；`error` 字段名以及模型缺省、必填与类型校验由本场景模型行承担。"`success` 不能替代 HTTP 状态"的结论归 SuccessResponse 场景，本场景不重复声明。

### Requirement: SuccessResponse 数据契约 [schemas/common.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_success_response_default_and_int_bool_forms`
  - [X] `tests/test_anvil_node_foundations.py::test_success_marker_is_independent_of_http_status`
  - [X] `tests/test_mount_usage_models.py::test_response_wire_fields_are_exact`
  - [X] `tests/test_blueprint_api.py::test_create_container_success`
- Assertion scope: 模型用例断言 `SuccessResponse()` 的 `success == 1`、`success=0`/`True`/`False` 原样保留、不可强转的输入被 `ValidationError` 拒绝；端点用例在 `/api/add_collaborator` 上用 `_patched_service(monkeypatch, "add_collaborator", lambda *a, **k: False)` 让服务返回 False，断言 HTTP 200 且响应体 `success` 为 `0/False`（真实"状态与标记不一致"分支），并结合 `/api/remove_collaborator` 成功分支的 HTTP 200/`success == 1` 与失败分支的 HTTP 500/`success == 0`，证明同一 HTTP 200 可承载 `success` 1 与 0、`success` 0 可同时出现在 200 与 500，结果标记不能替代 HTTP 状态；既有模型用例只断言 `CheckMountUsageResponse` 的 wire 字段集合恰为 `{"success","mounts"}`，既有端点用例只断言 200 响应体 `success == 1`。
- Coverage note: 两条既有用例（wire 字段集合与 200/`success == 1`）都不覆盖缺省值，也不覆盖"标记不替代 HTTP 状态"；这两面分别由本场景的模型行与端点行承担。端点行用 `/api/add_collaborator` 的真实不一致分支（服务 False → HTTP 200/`success` 0）配合 `/api/remove_collaborator` 的 200/1 与 500/0，排除"`success` 只是镜像 HTTP 状态"的实现。`success` 为 `int | bool` 宽松模式，字符串 `"yes"` 会被强转为 `True` 而非拒绝，因此边界断言只覆盖不可强转的输入类型。

### Requirement: ErrorResponses 数据契约 [schemas/common.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_error_responses_declaration_uses_api_error_model`
  - [X] `tests/test_blueprint_api.py::test_remove_collaborator_failure_returns_500`
- Assertion scope: 新增用例断言声明容器含 `INVALID_JSON`(400) 与 `INTERNAL_ERROR`(500) 两项、两项都以 `ApiErrorResponse` 为 `model` 且 `description` 非空，并断言真实错误信封 `{"success":0,"error":...,"error_reason":...}` 能通过 `ApiErrorResponse` 校验；既有用例只断言真实 500 信封的取值。
- Coverage note: 400 与 500 的状态区分只由本场景的声明映射行承担，既有 500 信封用例不承担；`ErrorResponses` 是声明容器、不构成请求 payload，因此本场景不设端点级用例；THEN 中"运行配置只传配置值、证书数据只传文件引用"两句在本类型无对应成员，分别由 runtime-configuration 与 NodeCertificateFiles 的映射承载。
