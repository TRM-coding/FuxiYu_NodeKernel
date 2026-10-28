# procedure--repository-workflow Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: 提交信息采用真实变更条目 [githooks/commit-msg]

#### Scenario: 多项变更

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_commit_msg_hook_entry_grammar`
- Assertion scope: 用 NEW、AMEND、FIX、SPEC、TEST 参数化验证各自的单条消息，调用真实 `githooks/commit-msg`，断言退出 0；另验证多条消息、空行与 `#` 注释仍按原规则处理。
- Coverage note: 正文约束“钩子只判断文本结构，条目是否真实与中文是否通顺由人工评审”不由该测试证明；该部分保持人工评审，不用静态断言冒充。

#### Scenario: 自造关键字或缺空格被拒绝

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_commit_msg_hook_entry_grammar`
- Assertion scope: 同一临时钩子用例分别写入 DOCS、DEBUG、小写 spec、`-NEW` 与缺少短句的 TEST 消息，断言 `commit-msg` 退出非 0，并输出允许的 NEW/AMEND/FIX/SPEC/TEST 与“连字符后有空格”的提示。
- Coverage note: 该行是规划 locator；自动检查以临时消息文件驱动真实 `commit-msg`，不执行真实 Git 提交。

#### Scenario: 没有真实条目被拒绝

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_commit_msg_hook_entry_grammar`
- Assertion scope: 同一用例写入只含空行与 Git 注释的消息文件，断言 `commit-msg` 退出非 0，并说明至少需要一条实际变更。
- Coverage note: 规划 locator；不执行真实 Git 提交。

### Requirement: 禁止工具署名与生成标记 [githooks/commit-msg]

#### Scenario: 署名尾注被拒绝

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_commit_msg_hook_attribution_and_last_line`
- Assertion scope: 临时消息分别包含 `Co-Authored-By`、`Generated with` 与生成图标，断言 `commit-msg` 退出非 0，并输出命中行。
- Coverage note: 正文约束“工具参与不改变作者归属”；该测试只证明钩子拒绝文本，不判断真实作者归属。

#### Scenario: 末行不合法仍受检

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_commit_msg_hook_attribution_and_last_line`
- Assertion scope: 同一用例写入没有终止换行、且最后一行不合法的消息，断言仍被拒绝；另写 CRLF 消息，断言行尾 `\r` 被容忍而文件末尾非法条目仍受检。
- Coverage note: 规划 locator；覆盖正文的“末行检查 + CRLF 兼容”，不代表真实提交。

### Requirement: 真实合并提交豁免 [githooks/commit-msg]

#### Scenario: 真实合并

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_commit_msg_hook_merge_exemption_uses_git_state`
- Assertion scope: 在临时 Git 目录写入 `MERGE_HEAD` 后，用由 Git 自动生成的合并信息调用 `commit-msg`，断言退出 0；不创建真实提交。
- Coverage note: 正文约束“豁免由 Git merge 状态而非文本判断”；临时 `MERGE_HEAD` 只模拟该状态。

#### Scenario: 标题写 Merge 不获豁免

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_commit_msg_hook_merge_exemption_uses_git_state`
- Assertion scope: 同一用例在没有 `MERGE_HEAD` 时写入标题含 `Merge` 的消息且无变更条目，断言仍退出非 0。
- Coverage note: 规划 locator；证明标题文字本身不触发豁免。

### Requirement: 钩子随仓库交付并显式启用 [githooks/pre-commit]

#### Scenario: 新克隆启用

- Test/check:
  - [X] `git config --local --get core.hooksPath`
  - [X] `git ls-files githooks/commit-msg githooks/pre-commit`
- Assertion scope: 本仓库克隆的 `core.hooksPath` 为 `githooks`，两个钩子文件已被 Git 跟踪并由仓库交付。
- Coverage note: 只核对本仓库克隆；新克隆仍需执行一次 `git config --local core.hooksPath githooks`。本检查不创建真实 commit，不证明 Git 实际调用钩子。

#### Scenario: 安装前核对既有钩子

- Test/check:
  - [X] `Get-ChildItem .git/hooks -File | Select-Object -ExpandProperty Name`
- Assertion scope: 本仓库 `.git/hooks` 只有 `*.sample`，没有需要保留的自定义钩子；切换 `core.hooksPath` 不会覆盖或合并这些 sample，是否为该克隆保留由配置者判断。
- Coverage note: 人工核对本仓库克隆；正文的“安装前核对”是配置决策，不由命令自动判断。

### Requirement: 钩子保持 LF 与执行位 [.gitattributes]

#### Scenario: 检出换行为 LF

- Test/check:
  - [X] `git check-attr text eol -- githooks/commit-msg githooks/pre-commit`
  - [X] `git ls-files --eol githooks/commit-msg githooks/pre-commit`
- Assertion scope: 两个钩子均返回 `text: set` 与 `eol: lf`；`git ls-files --eol` 显示索引与工作区均为 `i/lf`/`w/lf`，证明 `.gitattributes` 的 `githooks/* text eol=lf` 已覆盖无扩展名文件且索引/工作区内容均为 LF。

#### Scenario: 核对执行位

- Test/check:
  - [X] `git ls-files -s githooks/commit-msg githooks/pre-commit`
- Assertion scope: 两个钩子在索引中的 mode 均为 `100755`。
- Coverage note: 执行位是 Git 索引属性，本地文件权限不反映它；该检查只证明索引 mode。

### Requirement: 新增 capability 使用门类前缀 [githooks/pre-commit]

#### Scenario: 新增页面规格

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_pre_commit_capability_prefix_matrix`
- Assertion scope: 在临时 clone 中新建 `openspec/changes/<tmp>/specs/frontend--page-example/spec.md`，`git add` 后运行 `githooks/pre-commit`，断言退出 0；不执行 commit。
- Coverage note: 临时 clone 与 `git add` 只模拟新增暂存，不产生真实提交；不证明远端 CI 或人工评审。

#### Scenario: 叠加前缀被拒绝

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_pre_commit_capability_prefix_matrix`
- Assertion scope: 同一临时 clone 新建 `frontend--backend--example/spec.md` 并暂存，断言 `pre-commit` 退出非 0，提示只能使用一个门类前缀。
- Coverage note: 规划 locator；不执行 commit。

#### Scenario: 缺少门类前缀被拒绝

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_pre_commit_capability_prefix_matrix`
- Assertion scope: 同一临时 clone 新建无门类前缀的 `example/spec.md` 并暂存，断言 `pre-commit` 退出非 0，并列出四类前缀职责。
- Coverage note: 规划 locator；不执行 commit。

#### Scenario: 修改既有规格不强制改名

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_pre_commit_capability_prefix_matrix`
- Assertion scope: 同一临时 clone 修改既有 `openspec/specs/<cap>/spec.md` 并暂存，断言 `pre-commit` 退出 0，不要求改名或迁移。
- Coverage note: 规划 locator；只证明 Git 识别的修改路径。

#### Scenario: 旧 capability 首次增加 delta

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_pre_commit_capability_prefix_matrix`
- Assertion scope: 同一临时 clone 为 HEAD 已有主规格的旧 capability 新增 delta `openspec/changes/<tmp>/specs/<cap>/spec.md` 并暂存，断言 `pre-commit` 退出 0，delta 新增不被当作 capability 新增。
- Coverage note: 规划 locator；临时 clone 的 HEAD 来自现有仓库，不创建新提交；不覆盖 archive 下的真实改名路径。

### Requirement: 业务能力组织边界 [README.md]

#### Scenario: Node 保持 8 个能力单元

- Test/check:
  - [ ] `人工检查： Get-ChildItem openspec\specs -Directory -Filter 'backend--*' | Measure-Object`
- Assertion scope: 按 Node `97aa0cb` 基线，该命令列出 9 个 `backend--` 主规格目录（含 `backend--wss-snapshots`）；Scenario 名称与正文仍写“8 个”，数量与正文不一致，不能勾选通过，也不写“必须等于 8”的断言。
- Coverage note: 已由父级在 `E:\AI\Fuxi\FuxiYu_Global\QUESTIONS.md` @ Global `607bbfd` Q78（P3，源码与目录确认）登记：这是文档计数过时，不是能力组织重构。本轮仅记录并暂缓，不新开维护实现、不改 README/主 spec/CLI，不合并或删除能力；待父级另开官方 OpenSpec 文档变更同步后再复核该 `[ ]`。

#### Scenario: 前缀不成为删细节的理由

- Test/check:
  - [ ] `人工核对： openspec/specs/backend--*/spec.md @ Node 97aa0cb`
- Assertion scope: 按 Node `97aa0cb` 基线逐文件核对 9 个 `backend--` 主规格是否仍保留完整类型契约与 Requirement/Scenario 细节，并判断补充要求是否在原文件内最小补写；没有能为该语义判断背书的自动断言。
- Coverage note: 正文明确“前缀不成为删细节的理由”属人工评审；既有目录数/前缀事实不能替代该语义判断。

### Requirement: 仓库入口与规格质量 [README.md]

#### Scenario: 入口唯一

- Test/check:
  - [X] `Test-Path README.md; Test-Path README; Get-ChildItem openspec -Recurse -File -Filter README*`
- Assertion scope: 对当前工作树直接运行上述 PowerShell 命令，观察到根目录 `README.md` 存在（`True`），`README` 无扩展名文件不存在（`False`），且 `openspec` 下没有 `README` 或 `README.md` 文件；不用嵌套 `pwsh`，不把当前树结果写成 `97aa0cb` 基线结果。

#### Scenario: 格式通过不等于语义完整

- Test/check:
  - [ ] `openspec validate procedure--repository-workflow --strict`
- Assertion scope: 在 Node `97aa0cb` 工作树运行该命令只证明主 spec 结构可解析；它不判断业务逻辑、状态转换与失败边界描述是否完整。
- Coverage note: 正文要求“格式校验通过不等于语义完整”；需要人工评审，不能把 strict 通过当成语义完整证明。

### Requirement: 规范各仓库独立 [README.md]

#### Scenario: 不依赖外部规范

- Test/check:
  - [X] `人工核对： githooks/commit-msg, githooks/pre-commit, scripts/ci/check_pr.py @ Node 97aa0cb`
- Assertion scope: 按 Node `97aa0cb` 基线逐文件核对三条调用路径：提交信息/钩子/PR 正文校验只读取本仓库的钩子与 `scripts/ci/check_pr.py`，不读取 `FuxiYu_CtrKernel`、`FuxiYu_Web` 或其他仓库的规范文件；预期观察是三条路径的输入只有本仓库文件或 GitHub event JSON。
- Coverage note: 这是无 PR 也可复现的只读文件审查；只核对调用路径与读取范围，不证明人工评审过程绝不查阅外部资料，也不把源码字串扫描当成运行时行为证明。

### Requirement: 问题集中记录并区分证据等级 [Global/QUESTIONS.md]

#### Scenario: 新问题带证据等级

- Test/check:
  - [X] `人工核对： E:\AI\Fuxi\FuxiYu_Global\QUESTIONS.md @ Global 607bbfd, lines 1-191, Q75-Q78`
- Assertion scope: 按 Global `607bbfd` 基线核对 2026-10-28 新增条目：Q75-Q77 使用“本地复现 / 源码确认 / 待验证”三词标签；Q78 使用扩展标签【源码与目录确认】（源码确认与目录核对的组合），不是三词逐字之一。按现有 Global 原文记录 Q78 的扩展标签，不修改 Global，也不把它冒充为三选一。
- Coverage note: 只核对 Q75-Q78 的证据等级标签存在与语义，不判断证据是否充分，也不声称所有历史条目已重审；Global 文件不在本仓库，未纳入自动测试。

#### Scenario: 修复后标注状态

- Test/check:
  - [ ] `人工核对： E:\AI\Fuxi\FuxiYu_Global\QUESTIONS.md @ Global 607bbfd, Q78 lines 185-191 + 未完成问题区`
- Assertion scope: 按 Global `607bbfd` 基线核对 Q78：仍在“未完成问题”区、保留编号与证据，不标为已修复；本轮没有新增已修复条目，若出现则须保留原编号与证据并明确标记已修复。
- Coverage note: 这是对当前未修复项的流程核对，不把“标记已修复”当成业务已修复的运行证明；Q78 保持暂缓。

### Requirement: 流程通过不代表业务问题已修复 [README.md]

#### Scenario: 待办不写成已修复

- Test/check:
  - [X] `git diff --stat 97aa0cb..d35a10a`
  - [ ] `人工检查： 本变更尚无 PR；PR 正文交付栏待实际 PR 出现后核对`
- Assertion scope: 提交侧只读核对固定范围 `97aa0cb..d35a10a`：实际有 b02820e NEW 与 d35a10a AMEND 两个提交，diff 涉及创建凭据归档、测试计划等实际交付；PR 侧无该变更 PR，不能用提交内容冒充 PR 正文，PR 正文交付栏保持 `[ ]`。待父级创建实际 PR 后只核对 PR 正文，不使用 HEAD 漂移范围。
- Coverage note: 提交侧与 PR 侧分开记录：已有提交不等于已有 PR 交付证据；`check_pr.py` 只判断结构，不判断内容真伪。PR 缺失时只暂缓 PR 侧，不把提交范围写成空。

#### Scenario: 钩子通过不等于业务通过

- Test/check:
  - [X] `git log --format=%B 97aa0cb..d35a10a`
  - [ ] `人工检查： 本变更尚无 PR 校验记录；待实际 PR 出现后核对`
- Assertion scope: 提交侧只读核对固定范围 `97aa0cb..d35a10a`：包含 b02820e NEW 与 d35a10a AMEND，提交信息真实存在；PR 侧无该变更 PR/校验记录与业务验证证据，保持 `[ ]`。不把“提交/钩子能通过”写成“业务已通过”，也不把两个提交当作 PR 校验记录。
- Coverage note: 提交侧与 PR 侧分开记录；该区分是评审约定，不存在自动断言；PR 缺失时只暂缓 PR 侧，不伪造校验记录，也不声称钩子能判断业务结果。

### Requirement: PR 正文采用四类中英双语栏目 [.github/pull_request_template.md]

#### Scenario: 只有一栏交付

- Test/check:
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_enhancement_only_is_delivery`
- Assertion scope: 只填 `优化工作 | Enhancements & Patches` 且含真实条目时，`validate_body` 返回空错误列表。

#### Scenario: 只有计划不通过

- Test/check:
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_plan_only_is_not_delivery`
- Assertion scope: 正文只填 `下一步计划 | Coming Up` 时，`validate_body` 返回错误（计划不算本次交付）。

#### Scenario: 交付栏写“无”

- Test/check:
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_empty_column_with_wu_is_allowed`
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_only_wu_in_every_column_fails`
- Assertion scope: 某交付栏写 `- 无` 而另一交付栏有真实条目时结构通过；所有交付栏都只有 `- 无` 时失败，证明“无”不产生结构错误但也不计为真实条目。

#### Scenario: 原样保留模板不通过

- Test/check:
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_template_placeholders_cannot_pass_validation`
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_placeholder_items_are_rejected`
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_missing_verification_is_valid`
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_verification_bullet_cannot_replace_delivery_item`
- Assertion scope: 原样模板被 `validate_body` 判为错误；占位符（`-`、`- ...`、`- TODO`、`- 待填写`、`- 无` 等）逐个被拒；缺失验证说明仍可校验通过；验证栏下的 bullet 不能满足交付条目，证明验证说明不是交付条目的替代。

### Requirement: PR 标题与正文结构分离 [.github/pull_request_template.md]

#### Scenario: 自然描述标题

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_pr_title_is_ignored_by_checker`
- Assertion scope: 以自然描述标题（无 conventional 类型前缀）构造 event JSON，只校验合法正文，断言 `main(["--event", path])` 退出 0；标题不被当作交付内容。
- Coverage note: 自然标题是否“概括本次主要变更”仍由人工评审；测试只证明检查器不因缺少类型前缀而失败。

#### Scenario: 检查器不校验标题

- Test/check:
  - [X] `tests/test_anvil_accounts_procedure.py::test_pr_title_is_ignored_by_checker`
- Assertion scope: 同一 event JSON 的 `pull_request.title` 写入 `feat: ...` 或命令样文本，正文合法，断言退出 0 且输出不含标题内容；证明检查器只读取正文。
- Coverage note: 规划 locator；不证明 GitHub 或人工评审不检查标题。

### Requirement: PR 栏目与提交关键字相互独立 [scripts/ci/check_pr.py]

#### Scenario: AMEND 提交不改写

- Test/check:
  - [X] `git log --format=%B 97aa0cb..d35a10a`
  - [ ] `人工检查： 该范围对应 PR 正文（本变更尚无 PR）`
- Assertion scope: 提交侧只读核对固定范围 `97aa0cb..d35a10a`：实际包含 b02820e `NEW 补齐创建凭据校验和异步生命周期回归测试` 与 d35a10a `AMEND 归档创建凭据补测映射并保留已知恢复路径缺口`，d35a10a 的 AMEND 关键字保持不变；PR 侧无该变更 PR，不能核对 PR 正文是否改写 AMEND，保持 `[ ]`。固定范围 `97aa0cb..d35a10a` 不随 HEAD 后续变化。
- Coverage note: 正文明确二者相互独立；`check_pr.py` 不读取提交历史，无法自动证明 PR 正文部分。提交侧事实已核对，PR 正文单独保持 `[ ]`，不把两者混为延期。

#### Scenario: 旧栏目仍被接受

- Test/check:
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_new_only_is_valid`
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_fix_only_is_valid`
- Assertion scope: 旧版 `NEW | 新增内容` 与 `FIX | 修复漏洞` 标题均被 `validate_body` 接受。

### Requirement: PR 正文重验与工作流信任边界 [.github/workflows/pr-format.yml]

#### Scenario: 修改正文后重验

- Test/check:
  - [X] `Select-String -Path .github/workflows/pr-format.yml -Pattern 'types: \[opened, edited, synchronize, reopened, ready_for_review\]'`
  - [X] `Select-String -Path .github/workflows/pr-format.yml -Pattern '^permissions:'`
  - [X] `Select-String -Path .github/workflows/pr-format.yml -Pattern 'contents: read'`
  - [X] `Select-String -Path .github/workflows/pr-format.yml -Pattern 'persist-credentials: false'`
- Assertion scope: 在 Node `97aa0cb` 的 `.github/workflows/pr-format.yml` 中，四项声明分别匹配：pull_request 五种触发类型、`permissions:`、`contents: read`、两处 checkout 的 `persist-credentials: false`；四条独立命令不能用单条 alternation 互相替代。
- Coverage note: 只核对工作流声明触发类型与权限文本；未触发 GitHub 实际事件，不证明线上重跑、运行成功或权限在运行期生效。

#### Scenario: 首次接入先校验摘要

- Test/check:
  - [X] `Select-String -Path .github/workflows/pr-format.yml -Pattern 'sha256sum --check --status'`
- Assertion scope: 在 Node `97aa0cb` 的 `.github/workflows/pr-format.yml` 中，声明在基准分支无检查器时对提议分支脚本执行固定 SHA256 校验；摘要不符时 `sha256sum --check --status` 使步骤失败。
- Coverage note: 只核对声明与命令；未执行 GitHub Actions 的首次接入，不证明线上摘要校验已发生。

#### Scenario: 正文只作数据

- Test/check:
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_event_metadata_with_quotes_and_backticks_stays_data`
  - [X] `scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_event_body_only_inside_fence_fails`
  - [X] `tests/test_anvil_accounts_procedure.py::test_pr_body_canary_command_does_not_execute`
- Assertion scope: 既有两行证明 event JSON 中的引号、反引号、命令样文本能被读取并按正文结构返回 0/1，但没有断言执行副作用。规划用例在合法正文中放入会创建临时标记文件的命令样文本，运行 `check_pr.main` 后断言退出 0 且标记文件不存在；另以只含围栏命令的正文断言退出 1 且标记仍不存在。
- Coverage note: 既有两行只证明读取/结构判定，不能单独支撑“不产生执行”；规划 canary 才承担无副作用断言，且不使用 `test_checker_does_not_eval_or_shell_out` 的源码字串检查冒充。

### Requirement: 检查能力边界不得夸大 [README.md]

#### Scenario: 不夸大自动检查

- Test/check:
  - [X] `人工核对： README.md@97aa0cb lines 89-93; githooks/commit-msg@97aa0cb lines 51-59; githooks/pre-commit@97aa0cb lines 27-41; scripts/ci/check_pr.py@97aa0cb lines 3-8; openspec/specs/procedure--repository-workflow/spec.md@97aa0cb lines 285-287`
- Assertion scope: 按 Node `97aa0cb` 基线逐处观察，上述文档/注释只声称钩子与检查器覆盖文本结构，不声称能判断中文真实性、PR 标题质量、能力单元划分恰当或业务问题已修复。
- Coverage note: 能力边界表述属人工评审；没有自动断言可证明“没有夸大”，但文件、行号与基线已固定，可复现核对。

### Requirement: 规范入口不使用代理说明文件

#### Scenario: 生成代理说明文件

- Test/check:
  - [X] `git ls-files 'AGENT.md' 'AGENTS.md'`
  - [X] `Get-ChildItem -Recurse -File -Filter 'AGENT*.md'`
- Assertion scope: 在 Node `97aa0cb` 工作树，索引中没有 AGENT.md 或 AGENTS.md，递归工作区扫描也没有 `AGENT*.md` 文件；两条分别覆盖索引与工作区。

### Requirement: 测试替身不得污染测试运行时

#### Scenario: 挂载准备使用真实临时目录

- Test/check:
  - [X] `tests/test_create_container.py::test_create_container_mount_setup_keeps_global_os_stat_real`
- Assertion scope: 创建容器的真实临时目录挂载准备后，进程全局 `os.stat` 对象身份未变；对测试源文件返回 `st_size > 0` 且 `S_ISREG(st_mode)`。

#### Scenario: 权限模拟限制在被测模块

- Test/check:
  - [X] `tests/test_mount_usage_cache.py::test_path_gate_maps_permission_error_without_stat`
  - [X] `tests/test_mount_usage_cache.py::test_invalid_not_found_and_permission_never_start_du`
- Assertion scope: 权限错误被映射为 `permission_denied` 且全局 `os.stat` 仍是真实对象；多个错误路径不启动 `du`。
- Coverage note: 第二条用例的用途是防止权限模拟重新引入全局替换；两条共同承担“只替换被测模块视图”的边界。
