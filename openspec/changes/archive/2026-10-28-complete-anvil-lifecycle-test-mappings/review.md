# Plan Review

## Review Record

- Change: complete-anvil-lifecycle-test-mappings
- Reviewer: 独立 fresh 上下文 reviewer（未参与作者计划；本次为上次 REVISE 后的复审）
- Access: 只读；仅写本文件 review.md
- Reviewed plan: proposal.md、specs/backend--container-lifecycle/spec.md、design.md、test-plan.md
- Read-only context: openspec/specs/backend--container-lifecycle/spec.md、被引用的既有测试函数体与相关源码（仅用于核对 locator、断言范围和可执行性）
- Invalidation scope: 对 requirement、scenario、design decision、scenario mapping、test/check locator、Assertion scope 或 Coverage note 的任何语义修改都会使本 review 失效；仅重算 checkbox（实际断言未变）或外部运行/日志变化不失效。
- Scope limit: 仅计划阶段；实现、任务完成、测试执行与归档就绪不在本 review 范围。本轮未运行测试或构建，不声称任何计划测试已实现、已通过。
- 核对结果: delta 与主规格 requirement 段逐字一致（42 个 Requirement、93 个 Scenario）；test-plan 的 93 个 Scenario 顺序一致；127 个 `[X]`、50 个 `[ ]`、29 个 `tests/test_anvil_lifecycle_contracts.py` 计划 locator；50 个 `[ ]` 均有 Coverage note，69 个既有 locator 均存在，计划测试文件尚不存在且未被写成已创建/已通过。计划测试以 fake Docker、Pydantic、caplog 为边界，未发现真实 Docker daemon/容器/网络依赖，也未发现对目标状态机或 HTTP/WSS 入口的 mock。
- 上次 REVISE 的残留项复核: 硬阻塞删除重建恢复、exited 非硬阻塞、真实 sshd probe、unpause 未 ready 门禁、事件 inspect 诊断、unknown 不排删除、旧观察 generation 失效、`_container_name` 优先级、`MachineStatus` 类型边界、状态响应 hard_block 字段、受控 TTL 均已落到具体 `[ ]` locator 或 Coverage note；exec 的 `[X]` scope 已收窄，旧 Ctrl/旧 Node 的跨仓限制已明确写出。

## Findings

### Blocking

- None.

### Non-blocking

- None.

## Verdict

VERDICT: APPROVE
