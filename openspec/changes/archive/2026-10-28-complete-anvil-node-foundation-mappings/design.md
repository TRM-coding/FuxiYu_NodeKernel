# Design

## Context

本变更是三仓库全量 Anvil 测试映射轮次中的 Node 第 1 批，只做"已有主 spec 的 Scenario ↔ 测试"对账与缺口补测规划（动机见 proposal.md）。约束来自三方面：

- 三个目标能力（`backend--common-contracts`、`backend--node-identity`、`backend--runtime-configuration`）已是同步完成的主 spec，共 12 个 Scenario；本轮不得改动其业务语义。
- 现状测试覆盖极不均衡：`schemas/common.py` 的四个类型没有任何直接测试；`network/wss.py` 的身份类型只有间接覆盖（在别的测试里构造 `NodeIdentity`、设置 `NODE_IDENTITY_FILE`）；`config.py` 的四个配置类只有 `PortConfig` 被各处按类属性读取，没有对缺省值本身的断言。
- Scenario 文本高度模板化（`字段校验与缺省值`、`内部值传递`），THEN 是"模型采用声明的缺省值并保持继承字段""成员名称和数据职责保持一致"这类面向契约的表述，不是逐字段行为清单。

既有测试基础设施（不改动，只复用）：`tests/conftest.py` 的 `FakeDockerClient` 等 fake、`tests/test_blueprint_api.py` 的 `client` fixture（`create_app()` + `TestClient`）、`monkeypatch.setenv` + `tmp_path` 的路径隔离写法；`pytest.ini` 默认 `-m "not docker"`。

## Goals / Non-Goals

**Goals:**

- 12 个 Scenario 各有一条可审查的映射行：能复用既有断言就复用并标 `[X]`，否则落到专属缺口测试并标 `[ ]`。
- delta spec 用 MODIFIED 完整 Requirement 块表达，Scenario 名与 WHEN/THEN 原文逐字保留，使后续 sync 幂等。
- 缺口测试校验真实可观察行为（Pydantic 校验结果、FastAPI 响应 JSON、dataclass 结构与冻结性、配置类属性），避免"断言实现文本"或"只镜像实现"。

**Non-Goals:**

- 不新增业务能力、数据表、字段；不改 `schemas/common.py`、`network/wss.py`、`config.py` 的实现。
- 不改主 spec、不写各能力侧车 `openspec/specs/<cap>/test-plan.md`、不写 `review.md` 与 `tasks.md`。
- 不重构 `tests/` 目录与既有夹具，不在本批引入真实 Docker 或外网依赖。
- 不为"让测试通过"而反向修改业务规格或弱化 Scenario。

## Decisions

### 1. delta 用 MODIFIED 完整块 + 零语义改动

每条 Requirement 从 `### Requirement:` 逐字复制到 `来源：` 行，Scenario 名与 WHEN/THEN 原样保留，delta 的 Requirement 块与主 spec 完全相同（逐字节相等），不在说明段落追加任何"本轮变更"之类的时效性说明。理由：Anvil 只要求 MODIFIED 携带完整 Requirement 块，完整原文本身已构成非空 delta，无需额外声明；sync 时块被同内容替换，结果幂等，主 spec 零业务与零文本变化。测试意图（对账、缺口、归属）只写在 proposal / design / test-plan，不进 delta，避免归档后把指向本变更的措辞永久留在主 spec 中。

替代方案：用 ADDED 记录测试映射——被否决，会把测试意图写成新业务能力，污染主 spec。曾在说明段追加对账声明——已撤回，sync 后会在主 spec 里留下失效引用。

### 2. 缺口测试集中在单一新文件 `tests/test_anvil_node_foundations.py`

理由：本批缺口横跨三个能力但都是"契约级小断言"，放进既有业务测试文件会打散归属、并迫使改动既有文件。单文件、按能力分组（`schemas/common.py`、`network/wss.py`、`config.py`）即可，且不触碰目录结构。

替代方案：在 `tests/test_blueprint_api.py` 追加用例——被否决，该文件体量大且已有明确的端点测试职责。

### 3. 断言选择以"真实行为"为界

- 模型类：用 `pydantic.ValidationError`、实例属性值断言（缺省 `success == 0/1`、`error_reason is None`、必填缺失被拒）、`model_fields` 集合断言（错误字段名为 `error`），并对明显不可强转的输入（如对象/列表）断言被拒。
- 身份类型：用 `dataclasses.fields()` 与 `FrozenInstanceError` 断言"冻结、只有一个 uid"与 `Path` 字段契约；路径覆盖复用 `monkeypatch.setenv("NODE_IDENTITY_FILE", ...)` / `NODE_TLS_CERT_FILE` + `tmp_path`，走既有 `ensure_self_signed_certificate()` 真实生成路径（本地文件，不联网）。
- 端点：沿用 `TestClient` + `tmp_path` 环境隔离，断言 `enrollment_profile` 的 `uid`/`identity_initialized`/`snapshot_endpoint`/`hardware` 键与"无 `certificate_fingerprint`"；`snapshot_endpoint` 的字面量 `/ws/ctrl` 由已有的 `tests/test_blueprint_api.py::test_ctrl_link_endpoint_registered_on_same_app`（断言 `CTRL_LINK_PATH == "/ws/ctrl"`）承担，不靠间接比较冒充。
- 结果标记与 HTTP 状态：`success` 是否为"结果标记而非 HTTP 状态"需要用真实的"状态与标记不一致"分支证明。规划一条端点级用例：`/api/add_collaborator` 用 `_patched_service(monkeypatch, "add_collaborator", lambda *a, **k: False)` 让服务返回 False，端点仍返回 HTTP 200 且响应体 `success` 为 `0/False`；再结合 `/api/remove_collaborator` 的成功 200/1 与失败 500/0，得到"同一 HTTP 200 可同时承载 `success` 1 与 0、`success` 0 同时出现在 200 与 500"的证据，因此 `success` 不能被 HTTP 状态替代；不让只覆盖单侧的既有用例承担该结论。
- 配置类：断言类属性存在、`PortConfig` 缺省段为 20000–29999（spec 原文写明）、`NetConfig.NODE_PORT` 为合法监听端口范围、`KeyConfig` 是 `AppConfig` 的基类、`AppConfig` 三个键与 `KeyConfig` 同名；不把具体密钥值写进断言。

不使用源码文本扫描（读 `.py` 找字符串）作为断言，因为它不验证行为。

### 4. 配置类默认值与覆写的测法：局部环境 + 强制恢复加载

`config.py` 的类属性在模块导入时由 `_env_int(...)` / `os.getenv(...)` 求值，因此：

- 缺省值断言（`NODE_PORT` 合法端口、`NODE_PORT_RANGE_START/END` 为 20000/29999）必须先隔离环境：在 `with monkeypatch.context() as local:` 内 `local.delenv("NODE_PORT", raising=False)`、`local.delenv("NODE_PORT_RANGE_START", raising=False)`、`local.delenv("NODE_PORT_RANGE_END", raising=False)`，再 `importlib.reload(config_module)` 后断言；否则在设置了这些变量的机器上会取到环境值而误判。
- 覆写断言同理：在同一个局部 context 内 `local.setenv(...)` 后 `importlib.reload(config_module)`，断言 `AppConfig` 读到环境值。

恢复方式统一为 `try:` + `with monkeypatch.context() as local:` + `finally: importlib.reload(config_module)`：context 退出时局部环境已还原，`finally` 里再 reload 一次让类属性回到真实环境值。绝不调用 `monkeypatch.undo()`——那会提前撤销共享 fixture 注入的全部 patch（含 `TestClient` 用的 fake docker client），污染同用例其余断言与后续用例。

替代方案：子进程跑一段脚本——被否决，增加运行时耦合与本批"不接外部环境"的边界。用 `yield` fixture 收尾——不如 `try/finally` 直接，且不能保证异常路径一定 reload。

### 5. 不可断言的边界如实记录，不虚构

探读实现后确认两处 Scenario THEN 的"边界"表述存在真实歧义，plan 中按实际可断言范围收窄并在 Coverage note 写明，绝不反向断言实现细节：

- `EmptyConfig` 无声明字段，Pydantic 默认忽略额外键，因此"违反类型或 Field 边界的输入不作为有效实例"只能在"非映射输入"这一层断言，额外键被接受属实现事实，记为歧义。
- `SuccessResponse.success` 为 `int | bool` 且处于宽松模式，字符串 `"yes"` 会被强转为 `True` 而非拒绝；因此边界断言只覆盖不可强转的输入类型。

## Risks / Trade-offs

- `importlib.reload(config)` 依赖恢复时机，若收尾失败会让类属性停留在局部环境值 → 统一用 `monkeypatch.context()` 限定环境、`finally` 强制 reload 恢复，不用 `monkeypatch.undo()`；reload 会重建配置类对象，其他模块已持有的旧类引用仍指向原值，因此不会反向影响其断言。相关行在 apply 前保持 `[ ]`。
- `dataclasses.fields()` 与类属性集合断言对新增字段敏感 → 这是本批想要的"形状契约"，但需在 Coverage note 说明它不等价于"数据职责"层面的完整校验。
- 12 个 Scenario 的 THEN 多为泛化表述，"完整覆盖"在语义上无法被测试行 1:1 证明 → 每个泛化点都用 Coverage note 指出剩余部分，避免用 `[X]` 冒充全覆盖。
- `enrollment_profile` 的 `hardware` 来自 `extensions.sys_cache.collect_static()`，属于运行期缓存；断言只校验键存在与形状，不固化具体硬件值，避免把运行时结果写进测试或 plan。
