# Proposal

## Why

`backend--container-creation`（30 个 Scenario）与 `backend--container-credentials`（24 个 Scenario）的主 spec 已同步，但映射台账不完整：creation 侧车只登记 12 个 Scenario，credentials 侧车把只验证“模型 dump 不含密码”的弱断言记为已覆盖，另有构建空正文、恢复挂载缺 `containers` 段、恢复协作者缺 `password` 的 422、非法 `root_password` 脱敏 422 等已定规则没有可在真实断言上定位的测试。另有 `public_key`/私钥、restore realpath、`chpasswd`→sshd 顺序、失败日志、422 detail 键集等无独立 Scenario 的正文约束需要覆盖，且 restore 实现当前放行 base 自身、与 spec 的“之下”不符；本变更补齐 54 个 Scenario 与这些约束的映射。按用户“先记录缺陷，继续其他测试”的决定，base 自身拒绝的修复及依赖回归暂缓，不弱化 spec。

## What Changes

- 为 `backend--container-creation` 与 `backend--container-credentials` 编写 delta spec：两个能力的全部 Requirement 块以 MODIFIED 形式**逐字**复制（12 + 5 个 Requirement，30 + 24 个 Scenario），业务语义零变更，不新增字段、不新增协议、不改实现。
- 编写 design.md：记录本轮“只补映射、不改语义”的取舍、测试定位规则（既有测试优先复用、缺口只落在新文件）、以及“行为断言而非反射断言”的边界；断开证据必须走真实 app 的 ASGI 请求/取消生命周期，不用 `isCoroutineFunction` 或直接调用 handler 代替。
- 编写 test-plan.md：按 capability → Requirement → Scenario 嵌套给出 54 条映射，逐条登记真实测试定位与 Assertion scope；`[X]` 只在核对过实际断言范围时使用，`[ ]` 指向本变更规划的新测试位置；无独立 Scenario 的正文约束在最近 Scenario 的 Coverage note 中说明其测试定位或仓库边界。
- 规划 29 个缺口测试定位，全部落在 `tests/test_anvil_creation_credentials.py`；其中 base 自身拒绝独立为 1 个暂缓定位，其余 28 个可在修订计划通过独立复审后实施。覆盖模型边界、API 422/响应头、fake Docker 实际调用序列、status/WSS 投影、ASGI 生命周期断开与失败后无副作用，不以“属性存在/源码字符串”代替行为断言。既有 `tests/`、共享 fake、fixture、主 spec 与业务代码都不改。
- 不写 review.md 与 tasks.md（由独立 review 与后续 apply 阶段产出），不修改 `openspec/specs/**/spec.md`、`openspec/specs/**/test-plan.md`。

## Capabilities

### New Capabilities

（无。本轮不引入新能力。）

### Modified Capabilities

- `backend--container-creation`：仅重建 12 个 Requirement / 30 个 Scenario 的测试映射与缺口定位；Requirement 文本逐字复制，行为契约不变。
- `backend--container-credentials`：仅重建 5 个 Requirement / 24 个 Scenario 的测试映射与缺口定位；Requirement 文本逐字复制，行为契约不变。

## Impact

- 规划期：只写 `openspec/changes/complete-anvil-creation-credential-mappings/` 下的 proposal、design、delta spec、test-plan；日志写外部 `E:/AI/Fuxi_audit_artifacts/anvil-rollout-2026-10-28/node-batch-2/`。
- 实施期（后续 apply）：仅新增 `tests/test_anvil_creation_credentials.py`，使用既有 fake（`tests/conftest.py`、`tests/password_fakes.py`）与 Pydantic/API/服务层可观察行为断言；不改既有测试、不改 fake/fixture、不新增业务字段、不接真实 Docker daemon 或网络。
- 不涉及 Ctrl/Web 仓库：`凭据响应禁止缓存`、`ROOT 交接逐项凭据`、`不新增重复密码审计` 中属于 Ctrl/Web 的断言在 Node 侧不可执行，只在 test-plan 的 Coverage note 里如实标注边界。
- 已知缺陷：自定义 `NODE_CONTAINERS_BASE` 自身含 `containers` 路径段时，`restore_mount_path` 等于根目录仍会放行。用户已明确本轮仅记录，不应用外部修正草案；对应独立测试定位保留 `[ ]`，不以 skip/xfail 或改规格消除缺口。其余测试不依赖此修复，修订计划经独立复审后可继续；本批不得宣称该缺陷已解决或全部覆盖。
