# Plan Review

## Review Record

- Change: complete-anvil-node-foundation-mappings（已归档：`openspec/changes/archive/2026-10-28-complete-anvil-node-foundation-mappings`）
- Reviewer: 独立接替审查代理（fresh context；未参与 proposal/specs/design/test-plan 的编写；原 reviewer3a7eb9fe 因 intern-ai quota_exceeded 不可用，由本代理独立接替；本次为归档后 sidecar 续核）
- Access: read-only；本文件 `review.md` 是唯一写入
- Reviewed plan: 归档 `proposal.md`、`specs/backend--common-contracts/spec.md`、`specs/backend--node-identity/spec.md`、`specs/backend--runtime-configuration/spec.md`、`design.md`、归档 `test-plan.md`；续核对象为 `openspec/specs/backend--common-contracts/test-plan.md`、`openspec/specs/backend--node-identity/test-plan.md`、`openspec/specs/backend--runtime-configuration/test-plan.md` 三个 canonical sidecar。
- Invalidation scope: 本结论覆盖当前这版计划与上述三个 canonical sidecar 的映射文本。此后任何对 Requirement、Scenario、设计决策、Scenario 映射、Test/check locator、Assertion scope 或 Coverage note 的语义改动，都会使本结论失效；只重新计算 checkbox（被核对的断言本身没变）或外部运行结果/日志变化不使本结论失效。
- Scope limit: 仅审计划/映射文本。本次续核只核对归档 test-plan、3 个 canonical sidecars、13 条新测试与 sidecar 所列既有测试的实际断言支撑关系；不审实现正确性、tasks 完成度、测试是否执行或归档流程，未跑测试套件、未全仓扫描。`[X]` 只表示映射与断言已核对，不代表测试执行结果；父代理提供的定向/全量运行结果未在本轮复跑，也不作为本续核的覆盖结论。
- 续核 notes（sidecar ↔ 归档 test-plan ↔ 测试断言）:
  - 三个 sidecar 共 12 Scenario、25 条 `[X]`（common 10、node 10、runtime 5），locator 与归档 test-plan 的 25 条完全一致；归档 test-plan 对应行也均为 `[X]`（仅为实现后 checkbox 重算，locator/断言文本未改）。
  - 13 条新测试均存在于 `tests/test_anvil_node_foundations.py`，并逐条支撑 sidecar 的 Assertion scope：ApiError 的 model_fields/default/required/type（`:57-68`）、Success 的 default/int-bool（`:71-80`）与 add 200/0 + remove 200/1 + 500/0（`:83-113`）、ErrorResponses 的 400/500 声明（`:116-129`）、NodeIdentity/CertificateFiles 的冻结与路径（`:142-189`）、NodeEnrollment 的 hardware/issue_uid 后状态（`:192-228`）、Config 的 Net/Port env 隔离与 Key/App 断言（`:231-297`）。
  - sidecar 所列既有测试按实际断言核对，例如 `tests/test_blueprint_api.py:124-145` 的 200/`success == 1`、`:85-93` 的 `/ws/ctrl` 字面量与同 app 注册、`:51-69` 的 enrollment/issue、`:369-385` 的 remove 500/0、`tests/test_cache_collectors.py:771-783` 的 `node_uid`、`tests/test_port_allocator.py:116-121` 的顺序取号。
  - 时态清理未放大覆盖：ApiError 的默认/字段明确落到本场景新模型行；Success 的“两条既有用例”明确指 wire 字段与 200/1 两行，不再误指全部四个 `[X]`；ErrorResponses 指本场景声明行；NodeEnrollment 点名 `test_ctrl_link_endpoint_registered_on_same_app`，并删除“此前无覆盖”的历史句、保留新增端点行；Config 删除“此前无直接测试”。未发现新增覆盖断言或把历史缺口写成已覆盖。
  - 原 Success 独立性 Blocking 由 `tests/test_anvil_node_foundations.py:83-113` 的真实断言闭合，sidecar 仍保留 add 200/0 + remove 200/1 + 500/0 的证据链；该行 `[X]` 仅表示映射/断言已核对。
  - 主 spec 零变化：`.git/node-batch-1/sync-noop.log` 显示三能力 delta=4/main=4 且各 Requirement IDENTICAL；按同一 LF 归一化口径重算三份 `spec.md` 的 SHA-256 分别为 `37d7063c...`、`653cc1d9...`、`2c1ed19a...`，与日志 `main_sha256` 完全一致。
  - 上轮非阻塞项（新文件需自带 `client` fixture 与 `_patched_service`）已落实于 `tests/test_anvil_node_foundations.py:33-42`。

## Findings

### Blocking

- None.

### Non-blocking

- None.

## Verdict

VERDICT: APPROVE
