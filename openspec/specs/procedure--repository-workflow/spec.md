# 仓库工作流程

## Purpose

本仓库的提交、钩子、规格命名、PR 正文与问题记录的本地约定。这些约定只约束流程与文本，不描述业务行为；流程校验通过不代表业务问题已修复。

全部检查都在本仓库内完成：提交与命名由 `githooks/` 承担，PR 正文由 `scripts/ci/check_pr.py` 与 `.github/workflows/pr-format.yml` 承担。本文件自足，不依赖其它仓库的规范文件。

检查边界先说明：钩子与检查器只能判断**文本结构**。中文表述是否真实、PR 标题是否恰当、能力单元划分是否合理、问题是否真的修好，均由人工评审确认，不由脚本判定。

## Requirements

### Requirement: 提交信息采用真实变更条目 [githooks/commit-msg]

提交信息 SHALL 每行采用 `- NEW 中文短句`、`- AMEND 中文短句` 或 `- FIX 中文短句`，一行一项。关键字 SHALL 仅取 `NEW`、`AMEND`、`FIX` 三者之一，不可自造。连字符后 SHALL 有空格。

每条 SHALL 说明实际变更，使读者脱离对话也能读懂。空行与 Git 插入的以 `#` 开头的注释行 SHALL NOT 计入条目；非合并提交 SHALL 至少存在一条条目。

行格式与关键字由 `githooks/commit-msg` 拒绝；条目内容是否真实、中文表述是否通顺由人工评审确认，钩子 MUST NOT 被描述为能判断语义。

#### Scenario: 多项变更

- **WHEN** 提交同时新增脚本并修复缺陷
- **THEN** 分别写 NEW 与 FIX 条目，每条可独立理解

#### Scenario: 自造关键字或缺空格被拒绝

- **WHEN** 使用 DOCS、SPEC、DEBUG 等自造关键字，或写成 `-NEW` 形式
- **THEN** commit-msg 拒绝该提交并列出允许格式

#### Scenario: 没有真实条目被拒绝

- **WHEN** 信息文件只有空行或 Git 注释
- **THEN** 拒绝并说明至少需要一条实际变更

### Requirement: 禁止工具署名与生成标记 [githooks/commit-msg]

非合并提交的提交信息 SHALL NOT 包含 `Co-Authored-By`、`Generated with` 或生成图标。工具参与编写不改变提交的作者归属。

钩子 SHALL 检查没有终止换行的最后一行，并兼容 CRLF 提交信息文件。

#### Scenario: 署名尾注被拒绝

- **WHEN** 提交信息含 Co-Authored-By 或 Generated with
- **THEN** commit-msg 拒绝该提交并列出命中行

#### Scenario: 末行不合法仍受检

- **WHEN** 不合法的条目位于文件末尾且没有终止换行
- **THEN** 仍被拒绝

### Requirement: 真实合并提交豁免 [githooks/commit-msg]

Git 正处于 merge（Git 目录存在 `MERGE_HEAD`）时，commit-msg SHALL 放行 Git 自动生成的合并信息。该豁免 SHALL NOT 通过提交信息文字判断。

#### Scenario: 真实合并

- **WHEN** Git 正处于 merge
- **THEN** 不要求把自动生成的信息改写成变更条目

#### Scenario: 标题写 Merge 不获豁免

- **WHEN** 普通提交仅在标题写 Merge
- **THEN** 仍按普通提交的条目规则校验

### Requirement: 钩子随仓库交付并显式启用 [githooks/pre-commit]

仓库 SHALL 自带 `githooks/pre-commit` 与 `githooks/commit-msg`，无需手工复制脚本进 `.git/hooks`。每个克隆 SHALL 执行一次 `git config --local core.hooksPath githooks`。

该配置是**替换**而非叠加 `.git/hooks`，因此安装前 SHALL 核对该克隆是否已有需要保留的钩子内容。

启用与否由各克隆本地决定，仓库自身不能代替克隆完成该配置；未启用时钩子不会执行，本地钩子也不替代远端必需检查。

#### Scenario: 新克隆启用

- **WHEN** 新克隆执行 core.hooksPath 配置
- **THEN** 两个钩子按仓库内文件生效

#### Scenario: 安装前核对既有钩子

- **WHEN** 该克隆的 `.git/hooks` 下已有自定义钩子
- **THEN** 先判断是否需要保留，再决定是否切换 hooksPath

### Requirement: 钩子保持 LF 与执行位 [.gitattributes]

新增或修改的 shell 钩子 SHALL 使用 LF 换行，并以 Git mode `100755` 交付。`.gitattributes` SHALL 覆盖没有扩展名的 `githooks` 文件。Windows 上 SHALL 用显式命令补齐执行位。

执行位是 Git 索引属性，本地文件权限不反映它；缺失时表现为他人克隆后钩子静默不执行或报 Permission denied。

#### Scenario: 检出换行为 LF

- **WHEN** 查看入库的 githooks 文件
- **THEN** 其换行规则为 LF

#### Scenario: 核对执行位

- **WHEN** 用 `git ls-files -s` 检查两个钩子
- **THEN** 两者 mode 为 100755

### Requirement: 新增 capability 使用门类前缀 [githooks/pre-commit]

新增 capability SHALL 使用 `standard--`、`frontend--`、`backend--`、`procedure--` 之一，名称使用小写与连字符；一个名称 SHALL NOT 叠加两个门类前缀。

落点按职责选取：公共仓库约定归 `standard--`，页面归 `frontend--`，服务端归 `backend--`，工作流程归 `procedure--`。四者穷尽，拿不准的归 `standard--`。

pre-commit SHALL 只检查 Git 暂存区判定为新增的 `spec.md` 标记文件，并以 NUL 分隔读取路径以保留空格与非 ASCII 字符。既有 `spec.md` 的修改、Git 识别的改名、`openspec/changes/archive` 下的内容，以及 HEAD 已有主规格的 delta，SHALL NOT 被强制改名或迁移。

本条只约束新增；既有 capability 保留原名。

#### Scenario: 新增页面规格

- **WHEN** 新增一个页面 capability
- **THEN** 目录名使用 `frontend--` 前缀

#### Scenario: 叠加前缀被拒绝

- **WHEN** 新增 `frontend--backend--example`
- **THEN** pre-commit 拒绝并提示只能使用一个门类

#### Scenario: 缺少门类前缀被拒绝

- **WHEN** 新增的 capability 名没有四类前缀之一
- **THEN** pre-commit 拒绝并列出四类前缀的职责

#### Scenario: 修改既有规格不强制改名

- **WHEN** 暂存区只是修改既有 `spec.md`
- **THEN** 保留原名，不要求迁移

#### Scenario: 旧 capability 首次增加 delta

- **WHEN** HEAD 已有 `openspec/specs/<cap>/spec.md`，本次新增该 capability 的 delta
- **THEN** 放行，delta 新增不等于 capability 新增

### Requirement: 业务能力组织边界 [README.md]

Node 业务规格 SHALL 按既有的 8 个 `backend--` 能力单元组织，并在文件内保留完整类型契约；Ctrl 业务按表、Web 按页面。命名前缀 SHALL NOT 作为合并业务单元、虚构数据库表或删除细节的理由。

该边界 SHALL NOT 被钩子自动校验：pre-commit 只校验前缀形态，能力单元划分是否恰当由人工评审确认。

#### Scenario: Node 保持 8 个能力单元

- **WHEN** 整理 Node 的创建、生命周期、挂载与快照契约
- **THEN** 使用既有 `backend--*` 能力文件，不为套用按表规则发明表

#### Scenario: 前缀不成为删细节的理由

- **WHEN** 为既有能力补充要求
- **THEN** 在既有文件内最小补写，不改名、不拆并能力

### Requirement: 仓库入口与规格质量 [README.md]

仓库根目录 SHALL 保留 README；`openspec` 目录内 SHALL NOT 放 README。

格式校验（含 strict 校验）SHALL 只被视为结构可解析的证明，MUST NOT 被当作业务逻辑、状态转换与失败边界描述完整的证明。

#### Scenario: 入口唯一

- **WHEN** 检查仓库入口文档
- **THEN** README 在根目录，openspec 内没有 README

#### Scenario: 格式通过不等于语义完整

- **WHEN** 规格通过格式校验但只写了字段清单
- **THEN** 仍认为逻辑描述不足，不称其为语义完整

### Requirement: 规范各仓库独立 [README.md]

本文件 SHALL 自足：提交、钩子、命名、PR 与问题记录的约定 SHALL 在本仓库内可读、可执行，MUST NOT 依赖其它仓库的规范文件。仓库之间的规范差异由各仓库自己的流程规格承担。

#### Scenario: 不依赖外部规范

- **WHEN** 在本仓库校验提交信息、钩子行为与 PR 正文
- **THEN** 只用本仓库的 `githooks/` 与 `scripts/ci/check_pr.py`，不读取其它仓库的规范文件

### Requirement: 问题集中记录并区分证据等级 [Global/QUESTIONS.md]

跨仓库已知问题 SHALL 集中记录在 Global 的 `QUESTIONS.md`。每条 SHALL 标注证据等级：**本地复现**、**源码确认**或**待验证**；已解决的问题 SHALL 标记为**已修复**，MUST NOT 静默删除条目。

源码确认表示调用路径已对照，不代表生产环境已发生。

#### Scenario: 新问题带证据等级

- **WHEN** 登记一个新发现的问题
- **THEN** 条目带上本地复现、源码确认或待验证之一

#### Scenario: 修复后标注状态

- **WHEN** 某条已记录问题被修复
- **THEN** 该条标记为已修复，保留原编号与证据

### Requirement: 流程通过不代表业务问题已修复 [README.md]

流程校验 SHALL NOT 被解释为业务问题已修复。PR 交付类栏目 SHALL 只写本次实际交付，MUST NOT 把待办或审查发现写成已修复。

#### Scenario: 待办不写成已修复

- **WHEN** 本次只记录了发现，尚未修复
- **THEN** 不把它写进交付类栏目

#### Scenario: 钩子通过不等于业务通过

- **WHEN** 提交信息与 PR 正文都通过校验
- **THEN** 这只说明文本结构合规，不说明业务缺陷已修

### Requirement: PR 正文采用四类中英双语栏目 [.github/pull_request_template.md]

PR 正文 SHALL 使用四个栏目：`新增内容 | WHAT'S NEW`、`漏洞修复 | Bug Fixes`、`优化工作 | Enhancements & Patches`、`下一步计划 | Coming Up`。

前三栏为交付类，至少一栏 SHALL 有真实条目；`下一步计划` 为可选，SHALL NOT 计为本次交付。没有内容的交付栏 SHALL 可以整栏删除或写“无”——“无”SHALL NOT 计为真实条目。验证说明与通过率 SHALL 为可选内容，省略不导致校验失败。

栏目占位、HTML 注释与围栏代码块中的条目 SHALL NOT 计为交付。栏目标题由 `scripts/ci/check_pr.py` 校验；条目是否真实由评审核对，脚本不判断内容真伪。

#### Scenario: 只有一栏交付

- **WHEN** 只填了 `优化工作 | Enhancements & Patches` 且有真实条目
- **THEN** 校验通过

#### Scenario: 只有计划不通过

- **WHEN** 正文只填 `下一步计划 | Coming Up`
- **THEN** 校验失败，计划不算本次交付

#### Scenario: 交付栏写“无”

- **WHEN** 某交付栏无内容并写“- 无”
- **THEN** 该栏不产生结构错误，但“无”不计入真实条目

#### Scenario: 原样保留模板不通过

- **WHEN** 提交者未替换模板占位文字
- **THEN** 校验失败并说明需要真实交付条目

### Requirement: PR 标题与正文结构分离 [.github/pull_request_template.md]

PR 标题 SHALL 概括本次主要变更，沿用自然描述，MUST NOT 强制 conventional 类型前缀。标题为人工评审约定，标题措辞 SHALL NOT 被当前的正文检查器校验。

#### Scenario: 自然描述标题

- **WHEN** 标题直接描述本次变更
- **THEN** 不因缺少类型前缀而被判不合规

#### Scenario: 检查器不校验标题

- **WHEN** 检查器读取 event JSON
- **THEN** 只读取 PR 正文，不评判标题

### Requirement: PR 栏目与提交关键字相互独立 [scripts/ci/check_pr.py]

PR 的四类栏目 SHALL 与提交信息的 `NEW` / `AMEND` / `FIX` 规则相互独立。commit 的 `AMEND` SHALL NOT 被改写成 PR 的栏目关键字；PR 只说明本次实际交付。

旧版 `NEW | 新增内容` / `FIX | 修复漏洞` 栏目在接入过渡期内 SHALL 继续被接受。

#### Scenario: AMEND 提交不改写

- **WHEN** PR 内存在 AMEND 提交
- **THEN** 该提交关键字保持不变，PR 正文按四类栏目说明实际交付

#### Scenario: 旧栏目仍被接受

- **WHEN** 正文仍使用旧的 NEW / FIX 栏目
- **THEN** 过渡期内检查器仍然接受

### Requirement: PR 正文重验与工作流信任边界 [.github/workflows/pr-format.yml]

`pull_request` 的 opened、edited、synchronize、reopened、ready_for_review SHALL 触发 pr-format 工作流。工作流 SHALL 把事件正文当作 JSON 数据处理，正文文本 MUST NOT 被拼入 shell 命令或作为表达式求值；工作流 SHALL 声明 `contents: read`，并关闭 checkout 凭据持久化。

工作流 SHALL 优先使用 PR 基准分支上的检查器。基准分支尚无检查器时，SHALL 只接受与该工作流内固定 SHA256 一致的脚本作为首次引导，摘要不符即失败，MUST NOT 静默跳过检查。基准分支已有脚本后，SHALL NOT 执行提议分支提供的替代检查器。

#### Scenario: 修改正文后重验

- **WHEN** 把占位改成真实交付条目
- **THEN** 工作流重新校验

#### Scenario: 首次接入先校验摘要

- **WHEN** 基准分支没有 `scripts/ci/check_pr.py`
- **THEN** 从提议分支取该脚本，先校验固定摘要再读取 event JSON

#### Scenario: 正文只作数据

- **WHEN** 正文含引号、反引号或命令样文本
- **THEN** 它们只被当作字符串，不产生执行

### Requirement: 检查能力边界不得夸大 [README.md]

本文件各项检查 SHALL 只声称其能覆盖的部分。SHALL NOT 声称钩子能验证中文表述真实性、PR 标题合规、能力单元划分恰当或业务问题已修复——这些由人工评审承担。

#### Scenario: 不夸大自动检查

- **WHEN** 描述提交或 PR 的自动检查能力
- **THEN** 不声称它能判断内容真实性与标题质量


### Requirement: 规范入口不使用代理说明文件

本仓库的流程规范 SHALL 维护在 OpenSpec 中，SHALL NOT 生成、保留或提交 AGENT.md、AGENTS.md。此规则由维护与评审落实，MUST NOT 声称现有 hook 会自动拒绝这些文件。

#### Scenario: 生成代理说明文件

- **WHEN** 工具在仓库中生成 AGENT.md 或 AGENTS.md
- **THEN** 移除该文件并从暂存区排除，适用规范整理到本仓库 OpenSpec

## Source references

- [githooks/commit-msg](../../../githooks/commit-msg)
- [githooks/pre-commit](../../../githooks/pre-commit)
- [.gitattributes](../../../.gitattributes)
- [scripts/ci/check_pr.py](../../../scripts/ci/check_pr.py)
- [scripts/ci/tests/test_check_pr.py](../../../scripts/ci/tests/test_check_pr.py)
- [.github/pull_request_template.md](../../../.github/pull_request_template.md)
- [.github/workflows/pr-format.yml](../../../.github/workflows/pr-format.yml)
- [README.md](../../../README.md)
- [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)
