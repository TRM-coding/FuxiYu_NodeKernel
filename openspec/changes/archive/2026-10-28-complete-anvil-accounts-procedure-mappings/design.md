# Design

## Context

本变更是三仓库全量 Anvil 映射补齐轮次中的 Node 第 5 批，只规划两个既有能力的 Scenario 对账（动机见 proposal.md）。约束如下：

- `backend--collaborator-accounts` 与 `procedure--repository-workflow` 均已同步为主 spec，共 35 个 Requirement、91 个 Scenario；本轮不得改变主 spec 的任何业务文本。
- 现有测试已覆盖账号密码、ROOT 交接、旧 ROOT 降级和重置密码的大量行为，但覆盖不均衡；已有侧车是表格 + 运行结果台账，不是 canonical 映射。
- `tests/conftest.py` 提供 `FakeDockerClient` / `FakeContainers` / `FakeContainer`，`tests/password_fakes.py` 提供 `PasswordFakeContainer` / `PasswordFakeDockerClient` 与 exec socket 捕获；`pytest.ini` 默认排除真实 Docker 用例。上述夹具均不修改，只复用。
- procedure 的多数要求是人工流程或文本结构规则，不存在等价业务运行结果；只有 `scripts/ci/tests/test_check_pr.py` 等少量既有自动检查和可用 Git 命令能提供真实可复现证据。

## Goals / Non-Goals

**Goals:**

- 91 个 Scenario 每个都有 canonical 的 `Test/check`、`Assertion scope`，必要时有 `Coverage note`。
- 已存在的测试或检查只有在其断言确已核对时标 `[X]`；缺口统一标 `[ ]`，账号行为缺口落到专属 `tests/test_anvil_accounts_procedure.py` 的具体测试名，procedure 的非自动化规则落到可复现人工检查。
- delta spec 的 Requirement 块与主 spec 逐字相同，不追加"本轮"说明，保证 sync 幂等。
- procedure 的人工检查明确其可复现命令或操作、证据边界和不可自动判定的部分，避免用源码字串、反射或测试名冒充行为证明。

**Non-Goals:**

- 不修改应用实现、主 spec、sidecar、共享 fixture、依赖、配置、数据库、CI、钩子、skills、SSH 或 secrets。
- 不写/不改 `review.md`（独立 reviewer 独占）、不创建 `tasks.md` 或任何实际测试文件；不执行 commit。
- 不为让测试通过而弱化 Scenario，也不把真实业务矛盾私自定为新规格。

## Decisions

### 1. delta 采用逐字 `MODIFIED` 完整块

每个 Requirement 从 `### Requirement:` 到该块的 `来源：` 行完整复制，包含所有 Scenario 与空行；两份 delta 与主 spec 对应块的 Requirement 文本逐字相同（工作树换行符按 Git `core.autocrlf` 归一后比较，空行结构也一致）。理由：Anvil/official spec 要求 MODIFIED 携带完整 Requirement 块，完整原文本身即非空 delta；测试意图只存在于 proposal / design / test-plan。替代方案（追加"本轮只做映射"句、使用 ADDED）会污染主 spec 或在 sync 后留下失效文字，均否决。

### 2. 账号缺口集中在单一专属测试文件

`tests/test_anvil_accounts_procedure.py` 按能力与 Requirement 分组，只新增测试，不修改既有文件或夹具。测试通过 fake Docker 捕获 `exec_run` 的 argv、`api.exec_create`/`exec_start` 的 stdin 与响应体，断言服务下发的命令、退出码分支、脱敏和单目标范围；不执行真实 `adduser` / `chpasswd`，不启动容器，不连接 Docker daemon。既有真实断言优先复用，不能复用才落缺口。

替代方案：把账号用例追加到 `tests/test_password_*.py`；否决，因为会打散归属并迫使修改既有业务测试文件。

### 3. 断言选择以真实可观察行为为界

- Pydantic 模型：直接构造并断言接受/拒绝、缺省值、`ValidationError`、SecretStr 掩码与 `get_secret_value()`；用不同角色值的行为证明 Literal 值域，不靠 `__args__` 反射。
- 服务/端点：用 fake Docker 记录命令与 stdin，断言 `["chpasswd"]` argv + stdin 明文、密码不出现在 argv/log/响应；用 `TestClient` 断言 422/404/409/500、`success` 和错误信封。
- 更新角色密码矩阵：既有参数化之外，规划补 `collaborator + root_password` 的真实分支，以及 admin 空、超长、全空白、CR/LF/NUL 的完整非法密码矩阵；均由模型拒绝与 HTTP 422 无副作用两层断言。
- 旧 ROOT 降 ADMIN：规划断言建号/复用账号后下发 `usermod -aG sudo <user>`（失败再 wheel）命令，并断言不写共享 root 密码；命令层面的组断言不冒充真实组数据库结果。
- ROOT 交接：按旧 ROOT → 目标顺序调用多次 `update_role`，记录精确调用顺序、每次命令和 stdin，断言每次只触达该次 `user_name`（ROOT 分支必然涉及的 `root` 与目标原账号除外），两次请求之间不共享绑定状态，不扫描其他账号；第二步失败不回滚第一步。
- ROOT 清理：完整清理命令只在临时 PATH 下执行，`id`、`deluser`、`mv`、`userdel`、`rm`、`date` 全部为记录式替身，`tr`/`grep` 只用只读系统命令；断言组判断退出码、`deluser` 未被无组分支调用、`mv`/`userdel`/`rm` 各只记录目标路径，宿主 sentinel 不变；不把真实用户删除或目录变更交给宿主。
- 恢复账号：断言恢复清单逐项调用、任一项失败使创建动作失败；家目录属主由 `chown -R <new_user>:<new_user> /root/.collaborators/<new_user>` 命令承担；恢复挂载复用同一宿主目录并保留其中文件。
- 重置密码：断言普通账号与 root 的真实服务路径分别产生 `u1:` / `root:` stdin，运行中容器才进入 `chpasswd`，缺失/停止容器不执行 exec，非法输入在请求边界 422；另以写入守卫 + exec 计数证明成功/失败均不持久化、不重试；无查回路由由 `network/api.py@97aa0cb` 路由清单与 OpenAPI 人工核对。
- 客户端断开：用原始 ASGI scope 和自定义 `receive` 注入 `http.disconnect`，断言同步 chpasswd 继续完成；不把客户端任务取消、`httpx.ASGITransport` 任务生命周期或直接调用 handler 冒充连接断开，也不声称真实 TCP 半关闭。
- PR 正文 canary：在合法正文中放入会创建临时标记文件的命令样文本，运行 `check_pr.main` 后断言标记不存在；既有“可读取/结构判定”测试不能单独承担“无执行”结论。
- 纯源码文本、测试名、反射结果不作为行为证明；静态检查最多作为配置声明的人工核对，并在 Coverage note 写明边界。

### 4. 不把 fake Docker 的代理结论扩大成真实账号/内核结论

fake Docker 只能证明 Node 下发的命令序列、stdin、退出码分支和响应边界，不能证明真实 Linux 账号的 ACL、家目录实际可读写或容器内文件实际可见。对应 Coverage note 明确写"命令/挂载来源层面的证据"，不声称真实 `adduser` / `chpasswd` 或生产环境已验证；这属于测试边界说明，不是 Weak 化 Scenario。

### 5. procedure 分离自动检查与人工检查

- `scripts/ci/tests/test_check_pr.py` 中已有的结构化断言直接作为 `[X]` locator；只选能证明该 Scenario 的测试，不用 `test_checker_does_not_eval_or_shell_out` 这种源码字串检查替代"正文只作数据"的行为断言。
- 钩子格式、合并豁免、新克隆启用、安装前核对、执行位、LF、pre-commit 前缀、8/9 能力单元、README/QUESTIONS/流程语义等，按 Scenario 分别映射到可复现的 Git/文件命令或人工评审；每条人工检查写 Node `97aa0cb` 或 Global `607bbfd` 基线、文件/行号、`git log 97aa0cb..d35a10a` 范围或 OpenAPI 清单及预期观察。无 PR 时只暂缓 PR 侧并保持相应 `[ ]`，不把固定提交范围写成空，也不以本地 body 文件、规划文本或“尚无 PR”的推断造证据；人工检查只声明其实际覆盖的文本/配置范围，不声称能判断中文真实性、PR 标题质量或业务已修复。
- 新测试只为可用临时 Git 状态/事件 JSON 安全复现的规则规划，例如 `commit-msg` 的临时消息文件与 `MERGE_HEAD` 状态；不为测试制造真实提交，也不在真实仓库执行 pre-commit 所需的暂存/提交动作。依赖 bash/`/bin/sh` 的用例只在 Linux/WSL 执行，Windows 默认套件无 bash 时显式 skip。

### 6. 发现真实不一致时保留原文并上报

procedure 正文与 README 写"8 个 `backend--` 能力单元"，仓库实际是 9 个（含 `backend--wss-snapshots`）。父级已在 Global `607bbfd` Q78 登记该文档计数差异；本变更只记录并把相关人工定位保持 `[ ]` 暂缓，不新开维护实现、不改 README/主 spec/CLI、不写"必须等于 8"的假测试、不合并/删除能力。类似的主 spec 内部矛盾不得由本变更擅自改文或改 app。

## Risks / Trade-offs

- fake Docker 只能证明命令与 stdin，不能证明真实账号权限/文件可见性 → 在 Coverage note 限定到命令或挂载来源层，不把代理证据写成真实系统结论。
- 部分 `[X]` 既有测试只覆盖 Scenario 的一个分支（例如仅成功路径、仅命令形状） → 同一 Scenario 用多行 locator 组合，并在 Coverage note 明示剩余缺口；不因组合行全部 `[X]` 就宣称全 Scenario 覆盖。
- ASGI `http.disconnect` 测试是进程内边界，不是真实 TCP → 明确只证明应用收到断开帧后同步工作继续完成，不声称 socket 半关闭/生产网络行为。
- procedure 的人工检查依赖执行者按命令操作，不能机械化保证 → 每条写清 Node/Global 基线、文件/行号或提交范围、预期观察与不可判定部分；无 PR 时保持 `[ ]` 暂缓，不伪造证据。
- 依赖 bash/`/bin/sh` 的规划测试在 Windows 默认套件可能不可运行 → 显式 skip 并只在 WSL/Linux 执行，不用跳过或替代结果冒充验证。
- delta 逐字复制使 diff 看起来只有 `MODIFIED` 外壳，容易被误读为无变更 → design/proposal 明确这是映射载体，sync 幂等；测试意图不进入主 spec。
- 新测试 locator 在映射核对完成前保持 `[ ]`；review 只能按规划可行性判断，不能把规划测试当作已存在或已运行。
