# backend--node-identity Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: IssueNodeUidRequest 数据契约 [network/wss.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_issue_node_uid_request_requires_uid`
  - [X] `tests/test_blueprint_api.py::test_node_identity_enrollment_and_issue_uid`
- Assertion scope: 新增用例断言 `IssueNodeUidRequest(uid="u")` 保留 uid、缺 `uid` 抛 `ValidationError`、非字符串 uid 被拒；既有用例断言 `POST /api/node_identity/issue_uid` 接受 `{"uid": "node-test-uid"}` 并回写 `uid`、`identity_initialized == True`。
- Coverage note: 既有用例只覆盖合法请求进入端点后的身份落盘形状，未覆盖模型必填与类型边界。

### Requirement: NodeIdentity 数据契约 [network/wss.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_node_identity_is_frozen_and_identity_file_override`
  - [X] `tests/test_cache_collectors.py::test_wss_snapshot_batch_reads_all_cache_views`
- Assertion scope: 新增用例断言其为冻结 dataclass、字段集合恰为 `("uid",)`、赋值抛 `FrozenInstanceError`、`NODE_IDENTITY_FILE` 覆写后身份文件读写落在该路径、对象上不存在证书指纹成员；既有用例断言 `NodeIdentity(uid=...)` 的 uid 原样进入快照批次 `node_uid`。
- Coverage note: 既有用例只覆盖"uid 单一职责在线上原样传递"，未覆盖冻结性、字段集合与身份文件路径覆写；身份文件路径在调用时读取环境变量，测试内 `monkeypatch.setenv` 即可，不需要重载模块。

### Requirement: NodeCertificateFiles 数据契约 [network/wss.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_node_certificate_files_are_paths_and_frozen`
  - [X] `tests/test_blueprint_api.py::test_node_self_signed_certificate_is_valid_pin_anchor`
- Assertion scope: 新增用例断言字段集合恰为 `("cert_file","key_file")` 且两者均为 `Path`、对象冻结、在 `NODE_TLS_CERT_FILE`/`NODE_TLS_KEY_FILE` 覆写到 `tmp_path` 后由 `ensure_self_signed_certificate()` 返回的对象指向这两个路径、对象不携带证书正文或私钥内容；既有用例断言返回的 `cert_file` 指向真实 PEM 并可通过 `x509` 解析（证书数据以文件引用传递）。
- Coverage note: 既有用例只覆盖证书文件路径可用与证书内容合法，未断言"仅记录路径、不保存私钥内容"的结构约束。

### Requirement: NodeEnrollmentProfile 数据契约 [network/wss.py]

#### Scenario: Ctrl 查询 Node 首连资料

- Test/check:
  - [X] `tests/test_blueprint_api.py::test_node_identity_enrollment_and_issue_uid`
  - [X] `tests/test_blueprint_api.py::test_enrollment_profile_advertises_snapshot_endpoint`
  - [X] `tests/test_blueprint_api.py::test_ctrl_link_endpoint_registered_on_same_app`
  - [X] `tests/test_anvil_node_foundations.py::test_enrollment_profile_contains_static_hardware_and_issued_uid`
- Assertion scope: 三条既有用例分别断言首连资料 `uid is None`、`identity_initialized is False`、响应不含 `certificate_fingerprint`；断言 `snapshot_endpoint == CTRL_LINK_PATH` 且 `wss_enabled` 不在响应中；断言 `CTRL_LINK_PATH == "/ws/ctrl"` 且该路径注册在同一张 app 上（快照路径字面量的唯一来源）。新增用例断言 `hardware` 键存在且为映射形状（复用静态硬件画像来源，不固化具体硬件值），并在 `issue_uid` 之后断言 `uid`/`identity_initialized` 反映已初始化状态。
- Coverage note: 前两条既有映射只把返回值与常量比较，字面量 `/ws/ctrl` 由 `test_ctrl_link_endpoint_registered_on_same_app` 承担；`hardware` 与"颁发 uid 后再次查询"由本场景新增端点行承担。指纹部分由 THEN 归给 Ctrl 从 TLS 层计算，Node 侧只能断言"响应不含指纹"。
