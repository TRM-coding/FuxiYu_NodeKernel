# Design

## Context

- 两个能力的主 spec 已在 `openspec/specs/backend--container-creation/spec.md`（12 Requirement / 30 Scenario）与 `openspec/specs/backend--container-credentials/spec.md`（5 Requirement / 24 Scenario）同步完成，本轮不改它们的文本。
- 既有主侧车台账不可直接沿用：creation 侧车只登记 12 个 Scenario（表格 + 状态标记格式），credentials 侧车虽列满 24 行，但多行指向的测试只断言“Pydantic 模型 `repr`/`model_dump()` 不含明文”，没有断言 Scenario 要求的 status/action 缓存、WSS 快照、日志、响应或“不自动重试”等部分。
- 既有测试资产已实地核对（只读）：`tests/test_password_contracts.py`、`tests/test_password_api.py`、`tests/test_password_services.py`、`tests/test_password_exec.py`、`tests/test_role_adversarial.py`、`tests/test_create_container.py`、`tests/test_blueprint_api.py`、`tests/test_update_role.py`、`tests/test_add_collaborator.py`、`tests/test_runtime_guard.py`、`tests/test_action_contracts.py`；fake 为 `tests/conftest.py`（`FakeDockerClient`/`FakeContainers`/`FakeImages`/`FakeExecAPI`）与 `tests/password_fakes.py`（`PasswordFakeDockerClient`/`PasswordFakeContainer`）。
- 实现侧事实（只读核对，作为规划依据，不改动）：`services/container_service.py::build_image` 对空 `dockerfile_text`/`image_tag` 直接 `RuntimeError` 且不经 `containers.run`，非空时把文本写入临时 `Dockerfile`；`create_container` 的恢复挂载先 realpath 再判定越界，并独立拒绝缺 `containers` 段、目录不存在；但当前 `mount_norm == base_norm` 会放行 base 自身，与 spec 的“之下”不符，已作为待授权回归；`network/api.py::create_container_api` 成功体固定四个键 `success`/`container_status`/`container_name`/`action_ref`；`CreateContainerReturn.port/port_mappings` 来自 `extract_port_info(container.attrs)`，`port_mappings` 元素是 `{"container_port","host_port","protocol"}` 字典；四个密码路由处理函数均为同步 `def`。

## Goals / Non-Goals

**Goals:**

- 让 54 个 Scenario 每个都有具体测试/检查定位，`[X]` 行都能在测试源码里指出真实断言范围，`[ ]` 行指向具体可实施的新测试。
- 对无独立 Scenario 的 Requirement 正文约束（public_key/私钥、restore realpath 与 base 自身、chpasswd→sshd 顺序、失败日志、422 detail 键集）也给出测试定位或跨仓边界，不把“Scenario 有行”当成完整覆盖。
- 把“既有测试只覆盖 THEN 的一部分”如实写进 Assertion scope 与 Coverage note，而不是用台账状态标记掩盖。
- 断开类 Scenario 必须用真实 app 的 ASGI 请求/取消生命周期证明，不以 `isCoroutinefunction`、直接调用 handler 或“响应已回”代替。
- 缺口补测只落在一个新文件 `tests/test_anvil_creation_credentials.py`，且只用可观察行为断言（HTTP 响应体/头、Pydantic 校验结果、真实 ASGI 请求、真实生成命令与 fake Docker 调用序列、失败后无副作用）。

**Non-Goals:**

- 不改业务实现、不新增字段/接口/协议、不重构错误处理；若发现实现与主 spec 不符，只报告不改。
- 不改既有 `tests/`、fake、fixture、主 spec 与主侧车；不写 review.md / tasks.md。
- 不连真实 Docker daemon、不接网络、不读密钥文件、不 commit/push。
- 不应用 `proposed-existing-spec-fixes.diff`；用户已决定本轮只记录 base 自身缺陷，暂缓其修复及依赖回归，其余测试继续。
- 不重复 Ctrl/Web 仓库的断言（凭据清单、Ctrl 审计名、浏览器存储）。

## Decisions

1. **delta 用逐字 MODIFIED 副本。** 两个 delta spec 由脚本从主 spec 的 `### Requirement:` 段落到 `## Data model appendix`（credentials 为文件末尾）原样抽取，仅加 `# Spec Delta` + `## MODIFIED Requirements` 头。理由：Anvil 的 delta 是“重述被修改的 Requirement 块”，而本轮语义零变更，手写改写会引入漂移。备选（ADDED 新 Requirement 承载测试意图）被否：会把测试意图写进 Requirement，违反“业务语义零变”。
2. **测试意图只放 proposal/design/test-plan。** Requirement 文本里不追加任何本轮说明。
3. **`[X]` 的判据是“实测断言范围 ⊇ 该行声明的范围”。** 逐条读完测试函数体后才勾选；一次测试只覆盖 THEN 的一部分时，勾选该行并在 Assertion scope 写明实际断言，再用 Coverage note 指出缺失的 THEN 部分和对应的 `[ ]` 补测。
4. **缺口用“可实施的新测试定位”表达，不用伪待决策。** 已定规则（主 spec 里已有 THEN）一律计划补测；`[ ]` 行给出 `<新文件>::<测试函数名>` 与将要断言的可观察行为。确属仓库外（Ctrl/Web、浏览器存储）的 THEN 只在 Coverage note 标注边界，不伪造 `[ ]` 行。
5. **补测一律行为断言，禁止反射式假断言。** 计划中的断言落在：Pydantic 校验通过/拒绝与序列化键集、FastAPI 响应状态码/键集/`Cache-Control`、`extensions.status_cache.list_states()`/`get_state()` 投影、`wss.build_status_snapshot()` 载荷、fake Docker 的 `containers.run` 入参、`api.created`（exec argv）与 `api.started[].socket.sent`（stdin 字节）、exec 失败后的调用次数与无副作用。不使用“isinstance/类型签名/源码字符串搜索”代替行为。
6. **新测试文件单一入口。** 命名 `tests/test_anvil_creation_credentials.py`，复用既有 fake 与 fixture（`monkeypatch`、`tmp_path`、`NODE_CONTAINERS_BASE`、`port_allocator._system_bound_ports` 打空），不修改共享 fake；测试内自建最小桩容器/容器集合（如带 `NetworkSettings.Ports` 的容器、把 `run` 结果登记到 `get` 的 `FakeContainers` 子类）补齐端口回填与恢复成功路径。
7. **`[X]` 与 `[ ]` 的行粒度按“测试函数”而非“文件”。** 同一测试服务多个 Scenario 时在各自 Scenario 下分别登记，Assertion scope 只写该测试真实断言的部分。
8. **正文约束不另造 Scenario。** 无独立 Scenario 的明确约束映射到最近 Scenario 的 Coverage note，并单列计划测试；delta 中仍只有原 Requirement 全文，不追加任何测试说明。跨仓/浏览器约束只标注责任边界，不伪造 Node 测试。
9. **断开必须走真实 ASGI 生命周期。** 计划测试用 `create_app` + `httpx2.ASGITransport` 发起真实 `POST`，fake Docker 的 `containers.run`/`exec_create` 在 worker 线程由 `threading.Event` 阻塞；进入服务后取消 ASGI request task（或发送 ASGI disconnect），释放 worker，断言服务/exec 只执行一次、stdin 字节正确、无自动重试、失败不出现成功。测试用 `asyncio.run` 驱动异步客户端，不新增 pytest-asyncio 依赖。明确这是 ASGI transport 的取消/断开边界，不声称真实 TCP 断开；`isCoroutinefunction` 和直接 handler 只作为 handler 层证据，不能算本 Scenario 覆盖。
10. **base 自身缺陷单独记录，其他补测继续。** spec 的“之下”要求 base 自身不能作为恢复源；当前实现放行，是已核对的真实差异。用户已决定“先记录缺陷，继续其他测试”。将拒绝 base 自身拆为独立定位 `test_restore_mount_base_itself_is_rejected`，保留 `[ ]`，暂不创建或执行；不加 skip/xfail，不应用业务修复，不改 spec。原挂载校验测试继续覆盖缺段、缺失目录、symlink 逃逸和有效子目录。修订后的计划须重新独立审查，获批后可实施其他测试；仍不得宣称 base 自身拒绝已覆盖。

## Risks / Trade-offs

- 补测可能暴露实现与主 spec 的偏差（例如“未断言到”的规则实际行为不符）。处理：实施期只报告并以失败测试定位，不顺手改业务代码。
- 54 条映射依赖人工读测；若后续有人改测试断言而不改台账，`[X]` 会失真。缓解：Assertion scope 写到“断言了什么”，reviewer 可直接比对测试函数。
- 计划测试定位共 29 个，其中 1 个因已知缺陷按用户决定暂缓，其余 28 个独立补测。若实施时发现某计划测试与既有测试完全重合，应删计划行而不是重复实现——但需重新 review。
- base 自身拒绝仍是明确未解决的缺陷，不计入完整覆盖；不能因其暂缓就把全部挂载校验或整个批次都判作完成。
- Node 侧无法覆盖的跨仓 THEN（Ctrl/Web）只能标注边界，可能被读成“覆盖不足”；Coverage note 已明确责任范围。
