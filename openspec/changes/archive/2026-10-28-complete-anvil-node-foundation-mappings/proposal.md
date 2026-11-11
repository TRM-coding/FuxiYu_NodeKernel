# Proposal

## Why

三仓库全量 Anvil 测试映射轮次中，Node 第 1 批的三个基础能力（`backend--common-contracts`、`backend--node-identity`、`backend--runtime-configuration`）已有主 spec，共 12 个 Scenario，但缺少逐 Scenario 的测试对账：部分 Scenario 没有任何对应断言，部分只有间接或残缺断言，Anvil 侧车尚无可供独立审查的映射基线。

本轮只做"已有主 spec Scenario ↔ 测试"的对账与缺口补测规划，不新增业务能力、数据表或字段，不修改既有业务规格语义。

## What Changes

- 为 `backend--common-contracts`、`backend--node-identity`、`backend--runtime-configuration` 各写一份 delta spec，内容为逐条 MODIFIED Requirement 完整块，与主 spec 对应块逐字相同（完整原文本身即非空 delta）：Requirement 标题、说明段落、全部 Scenario 名与 WHEN/THEN 一律原样保留，不追加任何对账说明句，业务语义与文本零变化（sync 应幂等）。测试意图只写在 proposal / design / test-plan。
- 建立本变更的 test-plan：以 canonical Requirement → Scenario → Test/check → Assertion scope 嵌套清单记录 12 个 Scenario 的映射，复用既有测试断言，明确标出未确认 locator 与缺口。
- 规划缺口测试落点：专属新文件 `tests/test_anvil_node_foundations.py`，校验真实的模型校验行为、接口响应与配置类行为，默认不接真实 Docker / 网络，复用既有 fake 夹具。
- 明确不写：`review.md`、`tasks.md`（独立审查通过后再写）；主 spec 与各能力侧车（`openspec/specs/<cap>/test-plan.md`）本轮不动。

## Capabilities

### New Capabilities

（无。本变更不引入新能力。）

### Modified Capabilities

- `backend--common-contracts`: 4 个既有 Requirement 的 Scenario 建立测试映射（`EmptyConfig`、`ApiErrorResponse`、`SuccessResponse`、`ErrorResponses`），delta 为逐字原文的 MODIFIED 块，业务语义与文本均不变。
- `backend--node-identity`: 4 个既有 Requirement 的 Scenario 建立测试映射（`IssueNodeUidRequest`、`NodeIdentity`、`NodeCertificateFiles`、`NodeEnrollmentProfile`），业务语义与文本均不变。
- `backend--runtime-configuration`: 4 个既有 Requirement 的 Scenario 建立测试映射（`NetConfig`、`PortConfig`、`KeyConfig`、`AppConfig`），业务语义与文本均不变。

## Impact

- 受影响产出：仅 `openspec/changes/complete-anvil-node-foundation-mappings/` 下的规划 artifact；apply 阶段新增单个测试文件 `tests/test_anvil_node_foundations.py`。
- 代码：不改 `schemas/common.py`、`network/wss.py`、`config.py` 及任何业务实现；不重构测试目录、既有夹具与 fixture。
- 接口 / 依赖 / 配置：无 API 变更、无新依赖、不改默认 schema、`config` 与 skills。
- 安全边界：不读取 `.env` / APIKEY / PASSCODE，不 SSH，不触达生产；测试默认不连接真实 Docker 或外网。
