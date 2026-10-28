# Proposal

## Why

三仓库全量 Anvil 测试映射补齐轮次中，Node 的 `backend--collaborator-accounts`（17 个 Requirement / 51 个 Scenario）与 `procedure--repository-workflow`（18 个 Requirement / 40 个 Scenario）已有主 spec，但缺少逐 Scenario 的 canonical 测试映射：现有侧车仍使用表格和运行结果台账，`procedure--repository-workflow` 的 38 个既有场景未被复核，无法作为独立审查与后续 apply 的可靠基线。

本轮只补齐"已有主 spec Scenario ↔ 测试/人工检查"的对账规划与缺口落点，不新增业务能力、不改变任何需求语义，也不把测试意图写回主 spec。

## What Changes

- 为两个既有能力各写一份 delta spec：每个 Requirement 从主 spec 完整逐字复制为 `MODIFIED` 块（标题、说明、全部 Scenario 名与 WHEN/THEN、来源行均保持原样），不追加任何对账说明句；业务语义与文本零变化，后续 sync 应幂等。
- 建立本变更的 canonical test-plan：按 `capability → Requirement → Scenario → Test/check → Assertion scope` 记录 91 个 Scenario，复用已核对的既有断言并标 `[X]`；账号行为缺口标 `[ ]` 并落到专属新文件 `tests/test_anvil_accounts_procedure.py` 的具体测试名，procedure 的非自动化规则标 `[ ]` 时落到可复现人工检查。无独立 Scenario 的明确正文约束写入对应 Scenario 的 Coverage note，并限定实际检查范围。
- 账号缺口测试规划使用 fake Docker 与 argv/stdin 命令捕获，不执行真实 `adduser` / `chpasswd`，也不连接真实 Docker daemon；保留 ROOT 交接与旧 ROOT 降级路径，并补足角色密码矩阵、旧 ROOT 降 ADMIN 管理组、reset root stdin、无持久化/重试、调用顺序与绑定隔离等缺失 THEN；ROOT 清理完整脚本只使用 `id`/`deluser`/`mv`/`userdel`/`rm`/`date` 记录式替身，不执行宿主真实变更。
- PR 正文“只作数据”增加 canary 无执行计划：正文中的命令样文本运行后不得产生临时标记文件；不以 `test_checker_does_not_eval_or_shell_out` 的源码字串检查冒充行为证明。
- procedure 的非自动化规则（钩子文本结构、人工评审、Git 状态豁免、工作流声明边界）规划为真实可复现的人工检查，逐条写 Node `97aa0cb` / Global `607bbfd` 基线、文件/行号或 `git log 97aa0cb..d35a10a` 范围及预期观察；PR 侧缺失时只暂缓 PR 侧并保持相应 `[ ]`，固定提交范围 `97aa0cb..d35a10a` 不写成空；不凭无 PR 造证据，也不为测试制造真实 Git 提交或生产动作。
- 明确不写/不改：`review.md`（由独立 reviewer 独占维护）、`tasks.md`、任何实际测试文件、主 spec、各能力侧车、应用代码、共享 fixture、依赖、配置、数据库、CI、钩子、skills、SSH 或 secrets；不执行 commit。

## Capabilities

### New Capabilities

（无。本变更不引入新能力。）

### Modified Capabilities

- `backend--collaborator-accounts`: 17 个既有 Requirement、51 个 Scenario 建立完整测试映射；delta 为逐字原文的 `MODIFIED` 块，业务语义与文本均不变。
- `procedure--repository-workflow`: 18 个既有 Requirement、40 个 Scenario 建立完整测试/人工检查映射；delta 为逐字原文的 `MODIFIED` 块，业务语义与文本均不变。

## Impact

- 受影响产出：仅 `openspec/changes/complete-anvil-accounts-procedure-mappings/` 下的 proposal、design、两份 delta spec 与 test-plan；后续 apply 才新增单个专属测试文件 `tests/test_anvil_accounts_procedure.py`。
- 代码与接口：不改 `schemas/container.py`、`services/container_service.py`、`network/api.py`、`constant.py`、任何测试公共夹具或目录结构；无 API 变更、无新依赖、不改默认 schema。
- 安全边界：测试仅使用 fake Docker 与命令捕获，不创建真实系统账号、不执行真实密码写入、不连接生产、不读取 secrets。
- 已知不一致：procedure 正文与 README 写 Node“8 个 `backend--` 能力单元”，仓库实际有 9 个 `backend--` 主规格目录（含 `backend--wss-snapshots`）。父级已在 Global `607bbfd` 的 Q78 登记该文档计数差异；本变更只记录并把相关人工定位保持 `[ ]` 暂缓，不新开维护实现、不改 README/主 spec、不绕 CLI、不写“必须等于 8”的假测试，也不合并/删除能力。
