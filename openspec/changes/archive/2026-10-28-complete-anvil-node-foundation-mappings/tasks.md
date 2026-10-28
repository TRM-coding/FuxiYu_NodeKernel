# Tasks

## 1. backend--common-contracts 缺口测试

- [x] 1.1 在 `tests/test_anvil_node_foundations.py` 内定义本文件专用的 `client` fixture（`create_app()` + `TestClient`，`monkeypatch` 注入 `FakeDockerClient`）与 `_patched_service` helper；实现 `EmptyConfig` 与 `ApiErrorResponse` 用例，覆盖 `backend--common-contracts` / `EmptyConfig 数据契约 [schemas/common.py]` / `字段校验与缺省值` 和 `backend--common-contracts` / `ApiErrorResponse 数据契约 [schemas/common.py]` / `字段校验与缺省值`；运行 `python -m pytest tests/test_anvil_node_foundations.py::test_empty_config_accepts_empty_mapping_and_rejects_non_mapping tests/test_anvil_node_foundations.py::test_api_error_response_defaults_and_required_error -q` 验证。
- [x] 1.2 实现 `SuccessResponse` 模型用例与真实端点独立性用例，覆盖 `backend--common-contracts` / `SuccessResponse 数据契约 [schemas/common.py]` / `字段校验与缺省值`；端点用例必须实测 `/api/add_collaborator` 服务返回 False 时 HTTP 200 且响应体 `success` 为 `False/0`，并与 `/api/remove_collaborator` 的 200/1、500/0 组合；运行 `python -m pytest tests/test_anvil_node_foundations.py::test_success_response_default_and_int_bool_forms tests/test_anvil_node_foundations.py::test_success_marker_is_independent_of_http_status -q` 验证。
- [x] 1.3 实现 `ErrorResponses` 声明容器用例，覆盖 `backend--common-contracts` / `ErrorResponses 数据契约 [schemas/common.py]` / `内部值传递`；运行 `python -m pytest tests/test_anvil_node_foundations.py::test_error_responses_declaration_uses_api_error_model -q` 验证。

## 2. backend--node-identity 缺口测试

- [x] 2.1 实现 `IssueNodeUidRequest` 与 `NodeIdentity` 用例，覆盖 `backend--node-identity` / `IssueNodeUidRequest 数据契约 [network/wss.py]` / `字段校验与缺省值` 和 `backend--node-identity` / `NodeIdentity 数据契约 [network/wss.py]` / `内部值传递`；`NodeIdentity` 用例通过 `NODE_IDENTITY_FILE` 覆写到 `tmp_path` 并执行真实保存/读取；运行两条定向用例验证。
- [x] 2.2 实现 `NodeCertificateFiles` 用例，覆盖 `backend--node-identity` / `NodeCertificateFiles 数据契约 [network/wss.py]` / `内部值传递`；通过 `NODE_TLS_CERT_FILE`/`NODE_TLS_KEY_FILE` 指向 `tmp_path` 并调用 `ensure_self_signed_certificate()`；运行定向用例验证。
- [x] 2.3 实现 `NodeEnrollmentProfile` 用例，覆盖 `backend--node-identity` / `NodeEnrollmentProfile 数据契约 [network/wss.py]` / `Ctrl 查询 Node 首连资料`；断言 `hardware` 映射形状、`issue_uid` 后 `uid`/`identity_initialized` 状态与响应不含证书指纹；运行定向用例验证。

## 3. backend--runtime-configuration 缺口测试

- [x] 3.1 实现 `NetConfig` 与 `PortConfig` 用例，覆盖 `backend--runtime-configuration` / `NetConfig 数据契约 [config.py]` / `内部值传递` 和 `backend--runtime-configuration` / `PortConfig 数据契约 [config.py]` / `内部值传递`；环境隔离统一使用 `monkeypatch.context()` + `importlib.reload(config_module)` + context 外 `finally` 再 reload，禁止 `monkeypatch.undo()`，断言只读 `config` 模块自身属性；运行两条定向用例验证。
- [x] 3.2 实现 `KeyConfig` 与 `AppConfig` 用例，覆盖 `backend--runtime-configuration` / `KeyConfig 数据契约 [config.py]` / `内部值传递` 和 `backend--runtime-configuration` / `AppConfig 数据契约 [config.py]` / `内部值传递`；`AppConfig` 覆写同样使用局部 `monkeypatch.context()` + reload + `finally` 恢复 reload，断言中不出现真实凭据；运行两条定向用例验证。

## 4. 全量验证与映射收口

- [x] 4.1 运行 `python -m pytest tests/test_anvil_node_foundations.py -q`，确认 13 条 planned tests 全部通过；命令、退出码与输出保存到 `.git/node-batch-1/targeted.log`（不纳入版本控制）。
- [x] 4.2 运行 Node 全量默认安全 suite `python -m pytest -q --no-header`（默认 `-m "not docker"`，不连接真实 daemon），确认无失败；命令、退出码与 pass/deselect 计数保存到 `.git/node-batch-1/full-suite.log`（不纳入版本控制）。
- [x] 4.3 仅将已实现并核对过的 13 条 test-plan 映射行 checkbox 改为 `[X]`，不改 locator、Assertion scope 或 Coverage note；核对仍为 12 个 Scenario、12 条既有 `[X]`、13 条新实现映射，不加入运行 ledger。
- [x] 4.4 运行 official verify advisory（`openspec-verify-change`），记录结果；不创建 `verify.md`，不写 Anvil verify artifact。

## Workflow follow-up

- 执行 official no-op sync；确认三个主 spec 的完整 Requirement、Purpose 与附录文本零变化。
- 使用 `anvil-test-plan` 更新 `backend--common-contracts`、`backend--node-identity`、`backend--runtime-configuration` 三个 canonical 主 sidecar，保留真实覆盖边界，不复制过期时态句。
- 执行 official archive，目标 `openspec/changes/archive/2026-10-28-complete-anvil-node-foundation-mappings/`。
