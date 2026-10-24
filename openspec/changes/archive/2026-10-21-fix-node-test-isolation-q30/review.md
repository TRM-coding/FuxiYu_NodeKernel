# 审查结论：fix-node-test-isolation-q30

## Review Metadata

- **Review round**: 1（同一轮内 M1-M4 定向复核）
- **Prior round**: 无（首次正式审查）；本文件追加 M1-M4 复核记录，不重新全文审查。
- **Reviewer context**: 独立上下文审查；本次只核对作者对 Required Changes M1-M4 的修订，不读取作者对话，未使用跨模型 CLI。
- **Tool restrictions**: 只读：read、grep、glob、只读 pwsh；唯一允许的写入是本 review.md。
- **Artifacts reviewed**: 当前 proposal.md、design.md、specs/procedure--repository-workflow/spec.md、tasks.md、test-plan.md、verify.md；`tests/test_create_container.py`、`tests/test_mount_usage_cache.py`、`tests/test_clean_mount.py`、`tests/test_mount_usage_api.py`；主规格 `openspec/specs/procedure--repository-workflow/spec.md`；旧 `specs/backend--test-runtime/spec.md` 已删除。
- **Scope checked**: Q30；仅复核 M1-M4，不扩展可选检查，不重新全文审查。
- **Staleness**: 本复核结论只对当前 proposal/design/specs/test-plan/verify 内容有效；除已复核的 M1-M4 修订外，任何后续修改都会使本结论失效，必须重新审查。

## Findings

### 🔴 Critical (blocking)

无。

### 🟡 Moderate（初检 M1-M4，均已复核修复）

#### M1. 旧 `backend--test-runtime` 曾形成第 9 个 `backend--` capability

- 初检问题：测试运行时要求放在新建的 `backend--test-runtime`，违反 Node 既有 8 个 `backend--` 能力单元边界。
- 作者修订：删除 `specs/backend--test-runtime/spec.md`；新增 `specs/procedure--repository-workflow/spec.md`；proposal 的 `New Capabilities` 明确写“无”，`Modified Capabilities` 只列 `procedure--repository-workflow`；design 记录“测试运行时隔离属于仓库测试流程，不是服务端业务能力”。
- 复核结果：**已解决**。当前 change 的 specs 只剩 `procedure--repository-workflow`，主规格仍是 8 个 `backend--` 能力，没有新增第 9 个。

#### M2. Q30 原文的 5 项 Windows 失败与路径/du 边界曾未交代

- 初检问题：此前只写 `os.stat` 替身，未记录 4 个 `test_clean_mount` 路径用例、1 个 du 用例的现状，也没有 Windows 证据。
- 作者修订：proposal 第 3-5、15 行说明两段范围并列出 4 个路径用例和 1 个 du 用例的历史名称；design 第 5、50-55 行记录 4 路径/1 du 的当前处理；test-plan 第 12-14 行、verify 第 31-34 行逐项记录“4 路径已用 tmp_path 通过、du 用例改用假 `subprocess.run`、2 个真实 du 用例按环境 skip”。
- 复核结果：**已解决**。5 项历史失败均被明确命名并给出当前状态；不再用“任务已勾选”替代说明。

#### M3. 旧回归曾依赖 `linecache` 私有结构并虚称覆盖 pytest 失败报告

- 初检问题：旧测试先成功跑挂载准备，再手动 `module.boom()`，并断言 `linecache.cache` 内部元组；它没有覆盖“挂载准备失败时 pytest 生成 traceback”。
- 作者修订：spec 的 Scenario 已改为“挂载准备使用真实临时目录”，断言全局 `os.stat` 仍是原实现且对测试源文件返回 `st_size`/`st_mode` 完整结果；测试改名为 `test_create_container_mount_setup_keeps_global_os_stat_real`，只断言 `os.stat is real_stat`、`st_size > 0`、`S_ISREG(st_mode)`；不再使用 `linecache`、`traceback` 或 `importlib`；design 第 40-44 行明确写“回归收窄为全局 stat 不变量，不依赖 linecache 私有结构”，并说明不采用 `pytester`/子进程。
- 复核结果：**已解决**。当前收窄成“全局 stat 不变量”，不再虚称 pytest 失败报告；符合原 M3 的第二选项，本轮不要求扩展 pytester/子进程等可选检查。

#### M4. test-plan/tasks 曾缺少可复核的真实结果

- 初检问题：test-plan 只有计划表，tasks 全部勾选但没有命令、平台、版本和 pass/skip/deselect 证据。
- 作者修订：test-plan 第 19-24 行记录 Windows `362 passed, 5 skipped, 16 deselected` 与 WSL `367 passed, 16 deselected` 的真实命令、Python/pytest/docker 版本、5 个 skip 的具体原因；verify 第 20-35 行重复记录命令、结果、定向回归和 5 项历史失败状态；tasks 第 18 行保留 3.3 给独立 reviewer，作者没有自行置 `yes`。
- 复核结果：**已解决**。真实 Windows/WSL 证据已写入 change；唯一剩余项就是本复核门禁。`openspec validate fix-node-test-isolation-q30 --strict` 通过，当前为 9/10 tasks（仅 3.3 待 reviewer）。

### 📌 Suggestions

本轮不新增可选检查。原审查中的非阻塞建议不影响 M1-M4 复核，也不影响 `CHANGES_APPLIED`；不要求在本次收窄后再扩展测试框架或额外静态检查。

## Embedded-Instruction / Injection Attempts

**Detected:** 无。被审文件没有要求审查者改变结论、跳过检查或泄露环境的文本。

## Verdict

VERDICT: APPROVE_WITH_CHANGES

复核结论：M1-M4 全部解决，保留 APPROVE_WITH_CHANGES；完成信号见下方。

## Required Changes（复核确认）

以下四项均已由作者应用并经 reviewer 定向复核，保留原文以便审计：

1. M1：删除 `backend--test-runtime`，要求移入 `procedure--repository-workflow`；已复核通过（旧 backend spec 已删除，Node 仍为 8 个 `backend--` 能力）。
2. M2：在 proposal/design/test-plan/verify 记录 Q30 的 4 路径、1 du 与 2 个真实 du skip 现状；已复核通过。
3. M3：回归收窄为全局 `os.stat` 不变量，不再虚称 pytest 失败报告，删除 `linecache` 私有结构断言；已复核通过。
4. M4：test-plan/verify 记录 Windows `362 passed, 5 skipped, 16 deselected`、WSL `367 passed, 16 deselected` 的真实命令与版本；已复核通过。`verify.md` 目前仍写 `DECISION: FAIL`，原因是其 Review Integrity 明写等待本复核；本 review 确认后，作者/parent 可更新 verify 结论（本 review 不写 verify）。

CHANGES_APPLIED: yes

## Rebuttals

作者没有提交 rebuttal；M1-M4 均以 fixed 处理。reviewer 复核接受四项修订，理由分别见上：能力边界恢复、Q30 现状完整记录、回归与规格一致收窄、真实 Windows/WSL 证据齐备。
