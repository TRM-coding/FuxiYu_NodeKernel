# Plan Review

## Review Record

- Change: complete-anvil-accounts-procedure-mappings
- Reviewer: 同一独立复审者（fresh context；继 79b5bdc3 quota_exceeded 无产物后的官方 fallback；作者 504bd44c 完成本轮计划整改，未参与本次复审判断）
- Access: read-only；本次只写 review.md。未运行测试套件，未 commit、部署或读取 secret，未改主 spec、sidecar、tasks、tests、app/config/DB/CI；只做只读 Git/文件检查。
- Reviewed plan: proposal.md、specs/backend--collaborator-accounts/spec.md、specs/procedure--repository-workflow/spec.md、design.md、test-plan.md；主 spec、相关源码、测试与 fake 只作可行性核对。
- Re-review scope: 逐项核对本轮 2 个 Blocking 与 non-blocking 整改。
  - AMEND/提交检查已改用固定范围 `97aa0cb..d35a10a`：实查含 `b02820e`（NEW）与 `d35a10a`（AMEND），d35a10a 的 AMEND 关键字可核对；PR 侧仍无该变更 PR，相关人工行保持 `[ ]`，不再写“范围为空/随 HEAD 变化”。
  - root 清理规划已改为 `test_root_cleanup_records_only_with_all_state_command_doubles`：`id`、`deluser`、`mv`、`userdel`、`rm`、`date` 全部记录式替身，`tr`/`grep` 使用只读系统命令；断言退出码、实际分支、目标路径记录与伪宿主 sentinel 不变，不把真实用户/目录变更交给宿主；Scenario 的完整 THEN 仍保留。
  - AddCollaboratorMessage 的既有行已缩窄为“成功分支”；参数转发由规划 `test_add_collaborator_message_requires_outer_config` 记录式 service stub 承担。角色日志规划已明确同时断言 `capsys` 与 `caplog`；README 行已移除嵌套 `pwsh`，改为当前工作树可直接执行的命令。
  - Q78 的“源码与目录确认”按 Global `607bbfd` 原文作为扩展标签记录，保留只记录/暂缓与 `[ ]`，不修改 Global、不发明业务决策、不阻断其他独立测试。
  - 结构核对：35 Requirement/91 Scenario 未变；当前 184 个 locator 行 = 121 `[X]` + 63 `[ ]`；30 个唯一拟补测试 + 11 个非测试 pending 检查。未全仓重扫，未跑 suite；30 个唯一测试仍是规划项，未当作已存在或已运行。
- Invalidation scope: Requirement、Scenario、设计决定、场景映射、Test/check locator、Assertion scope 或 Coverage note 的任何语义变更都会使本审查失效。仅在实际断言不变时重算复选框，或仅有外部运行/日志变化，不会使本审查失效。
- Scope limit: 仅审查计划；实现、任务完成、测试执行和归档就绪不在本次范围内。
- CLI note: `openspec status` 只按文件存在把 review 标为 done、tasks 标为 ready；它不是本 APPROVE 的依据。APPROVE 仅表示本计划可进入 tasks，不表示任何测试、实现或 archive 已验证。

## Findings

### Blocking

None.

### Non-blocking

None.

## Verdict

VERDICT: APPROVE
