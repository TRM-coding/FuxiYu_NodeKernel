# NodeKernel 规范吸收复核记录（两轨）

主审说明：以下保留 DSH 原始过程记录。主审随后修正了部分语义及检查能力表述，条款数量也可能因拆分改变；本报告不作为实施或验收依据，现行规则以本仓库 `openspec/specs` 为准。

复核对象：`E:\AI\Fuxi\FuxiYu_NodeKernel`
复核日期：2026-10-11
本文件是过程记录，不是 SPEC，也不引入新规范。

两轨：

- **Track A**：Global 旧业务 SPEC 退役吸收（`bak/2026-10-11/Global/openspec/changes` 下 7 个 change、12 份 `spec.md`，共 66 条 Requirement）——需要核对业务代码。
- **Track B**：已删除的 AGENTS/AGENT 文件中 hook、commit、PR 代码规范的本地化——规范类要求，不做业务代码核对，也不把规范条款混入业务表或类型契约。

---

## 一、结论与改动清单

### 结论

| 轨 | 结论 |
| --- | --- |
| Track A | 66 条 Global 业务要求中，**10 条涉及的 Node 侧事实被吸收**，落成 **4 条新 Requirement** 写入 **3 份既有业务 SPEC**；其余为 Ctrl/Web/数据库侧（本仓库不适用）或已由既有 SPEC 覆盖。无 Node 侧未实现项。 |
| Track B | 新建 **1 份**本地流程规范 `openspec/specs/procedure--repository-workflow/spec.md`（16 条 Requirement），自足、不依赖 Global SPEC，不直接搬 Global 三篇。 |

### 改动清单（仅 4 个文件）

| 文件 | 变更 |
| --- | --- |
| `openspec/specs/backend--wss-snapshots/spec.md` | +1 Requirement「Ctrl 拨入链路端点与身份门禁」（4 Scenario）；Source references 增补 `run.py`、`__init__.py` |
| `openspec/specs/backend--container-creation/spec.md` | +2 Requirement「构建段命中本机标签即跳过构建」「恢复挂载来源只由入参决定」（共 8 Scenario）；Source references 增补 `network/api.py` |
| `openspec/specs/backend--collaborator-accounts/spec.md` | +1 Requirement「恢复重建账号时修正家目录属主」（3 Scenario）；Source references 增补 `services/container_service.py`、`network/api.py` |
| `openspec/specs/procedure--repository-workflow/spec.md` | 新建（Track B） |
| `scripts/ci/spec-absorption-review.md` | 本文件，更新为两轨结论 |

### 未触碰

未编辑 AGENTS.md/AGENT.md、`githooks/`、`scripts/ci/check_pr.py`、`.github/` 模板与工作流、Global 任何文件、Git 配置、暂存区。未 commit / push / stage。未新增 `openspec` 内 README。未恢复 Container 大规模细节扩展——本轮只吸收 Global 明确列出的业务条目。

---

## 二、Track A：Global 旧业务 SPEC 逐条判定

来源目录：`E:\AI\Fuxi\FuxiYu_Global\bak\2026-10-11\Global\openspec\changes\`（只读，未复制）。

判定口径：

- **吸收**：要求含 Node 侧事实，NodeKernel 已实现，且既有 SPEC 未覆盖 → 本轮写入既有 SPEC。
- **已覆盖**：要求含 Node 侧事实，NodeKernel 已实现，且既有 SPEC 已叙述。
- **未实现**：要求含 Node 侧事实，但 NodeKernel 未实现 → 不得写成现状需求。
- **过时**：要求是已过去的一次性迁移/接入动作，对当前代码无常驻约束。
- **本仓库不适用**：要求的落点在 Ctrl / Web / 数据库 / 调度 / 前端页面，NodeKernel 无对应实现面。

### A.1 `container-image-provenance`

| Global Requirement | 判定 | 依据 |
| --- | --- | --- |
| 容器记录其构建所依据的模板版本时刻 | 本仓库不适用 | 落点是 Ctrl 的 `containers` 列与 `images.updated_at`；Node 无容器表、不持有模板版本 |
| 落后判据由版本戳与模板版本比较得出 | 本仓库不适用 | 同上；Node 不参与新旧判定 |
| 运行基底展示的唯一出口一律取容器侧留痕 | 本仓库不适用 | 展示出口在 Ctrl/Web |
| 容器留存构建配方的输入，而非渲染结果 | 本仓库不适用 | 落点是 Ctrl 的容器列；Node 侧对应事实是「接收 `dockerfile_text` + `image_tag` 两项」，已由 `backend--container-creation` 的 ImageBuildConfig 要求覆盖 |
| 镜像标签可推导且不落库 | **吸收**（部分） | 「标签是 Node 侧的缓存键」是 Node 事实 → 并入 A.13 新要求①；推导与不落库本身在 Ctrl |

### A.2 `container-image-binding`

| Global Requirement | 判定 | 依据 |
| --- | --- | --- |
| 容器的镜像归属由外键保持完整 | 本仓库不适用 | `containers.image_id` → `images.id` 外键，Ctrl 数据库 |
| 创建容器必须指定镜像归属（400/404/403） | 本仓库不适用 | Ctrl API 边界校验；Node 的 `create_container` 不接收 `image_id`（`schemas/container.py:66-72`） |
| 运行镜像由平台解析，调用方不得指定 | 本仓库不适用 | 平台=Ctrl；Node 只消费下发值，已由 `ContainerConfig.image`（`schemas/container.py:39`）覆盖 |
| 存量容器的归属按标签回填 | 过时 / 本仓库不适用 | 一次性 Ctrl 迁移动作 |

### A.3 `container-image-restore`

| Global Requirement | 判定 | 依据 |
| --- | --- | --- |
| 恢复以配方留痕为前提，不以镜像归属为前提 | 本仓库不适用 | 是否允许恢复由 Ctrl 判定 |
| 内容来源由模板状态与新鲜度共同判定 | 本仓库不适用 | Ctrl 选内容 |
| 内容发生变化时不得静默替换 | 本仓库不适用 | Ctrl 语义 |
| 内容会变时先给人看两份内容 | 本仓库不适用 | Ctrl 响应形状 |
| 恢复接口的入参与响应形状固定（`content_source` 等） | 本仓库不适用 | Ctrl API |
| 恢复必须有内容可依 | **吸收**（部分） | Node 侧支撑事实「构建段缺文本即失败，MUST NOT 降级为按运行标签直接启动」→ 新要求①；`data_not_recoverable` 拒绝在 Ctrl |
| 恢复必须刷新构建版本戳与配方留痕 | 本仓库不适用 | Ctrl 容器列 |
| 恢复来源可事后分辨 | 本仓库不适用 | Ctrl 操作日志 |
| 恢复的挂载行为与镜像来源无关 | **吸收** | 新要求②；Node 挂载来源取 `restore_mount_path`，与镜像来源无关 |
| 容器改名不改变数据位置 | **吸收** | 新要求②；挂载来源不由容器名推导 |
| 账号重建后家目录属主被修正 | **吸收** | 新要求④；Node 重建账号并 `chown` 家目录 |

### A.4 `image-template-lifecycle`

| Global Requirement | 判定 | 依据 |
| --- | --- | --- |
| 镜像模板的移除是停用而非删除 | 本仓库不适用 | Ctrl `images` 表 |
| 停用状态在业务读点一致生效 | 本仓库不适用 | Ctrl 读点 |
| 管理路径必须仍能取到已停用的模板 | 本仓库不适用 | Ctrl 原语查询 |
| 停用可撤销 | 本仓库不适用 | Ctrl |
| 模板名唯一性由应用层保证 | 本仓库不适用 | Ctrl 应用层 |
| 内置模板的收敛只作用于系统行 | 本仓库不适用 | Ctrl SEED |

### A.5 `machine-image-cache-record`

| Global Requirement | 判定 | 依据 |
| --- | --- | --- |
| 派发过的构建被记录在案 | 本仓库不适用 | Ctrl 侧记录表 |
| 记录的语义是「请求过」而非「建成过」 | 本仓库不适用 | Ctrl 记录语义 |
| 该记录不在执行链上 | **吸收**（Node 部分） | 该条前半在 Ctrl（不因记录省略构建段）；后半是 Node 事实：构建是否执行由 Node 本机判定，命中即返回、未命中则构建 → 新要求① |
| 记录不设失效与删除逻辑 | 本仓库不适用 | Ctrl 维护路径 |

### A.6 `reverse-wss-dial-direction` / `node-link`

| Global Requirement | 判定 | 依据 |
| --- | --- | --- |
| 连接集合由 machines 表驱动 | 本仓库不适用 | Ctrl 出站链路管理器 |
| 机器集合变更自动跟随 | 本仓库不适用 | Ctrl 对齐周期 |
| 按机器独立退避重连 | 本仓库不适用 | Ctrl |
| 连接结果即机器在线状态 | 本仓库不适用 | Ctrl `machine_status` |
| 快照帧的接收与落库保持不变 | 本仓库不适用 | Ctrl 消费侧（队列、落库、`delete` 作用域） |
| 链路使用按机器 pin 的 TLS 信任 | 本仓库不适用 | Ctrl 客户端证书与 pin 文件 |

### A.7 `reverse-wss-dial-direction` / `node-snapshot-endpoint`

| Global Requirement | 判定 | 依据 |
| --- | --- | --- |
| Node 在既有 HTTPS 监听上提供 WSS 端点 | **吸收** | 新要求③；`network/wss.py:34-35`、`:483-485`；`__init__.py:44`；`run.py:20-36` |
| 端点校验 Ctrl 出示的 uid | **吸收** | 新要求③；`network/wss.py:414-419`、`:468-472` |
| 接受连接后按周期推送快照 | 已覆盖 + **吸收**（部分） | 四 topic 与 `delete` 先于批次已由既有 `snapshot-batch` / `delete-event` / `snapshot-*` 要求覆盖（`network/wss.py:386-399`、`:449-450`）；「身份牌就绪前不推送」未覆盖 → 并入新要求③（`network/wss.py:463-467`） |
| 推送线程与重连职责移交 Ctrl | **吸收** | 新要求③；`__init__.py:18-19`；全仓无出站 WS 客户端（检索 `websockets.connect`/`aiohttp`/`ws://` 零命中） |

### A.8 `renew-machine-trust` / `machine-trust-renewal`

| Global Requirement | 判定 | 依据 |
| --- | --- | --- |
| 只对已登记的机器重钉信任锚 | 本仓库不适用 | Ctrl |
| 重抓对端证书并覆盖 pin | 本仓库不适用 | Ctrl |
| 失败时整体不落地 | 本仓库不适用 | Ctrl |
| uid 按需重发 | 已覆盖 | Node 侧义务只是上报身份状态：`network/wss.py:303-317`（`identity_initialized`）已由 `backend--node-identity` 的 NodeEnrollmentProfile 要求叙述 |
| 重钉全程留痕 | 本仓库不适用 | Ctrl 操作日志 |
| 可从机器详情页触发 | 本仓库不适用 | Web 机器详情页 |

### A.9 `track-machine-last-seen` / `machine-last-seen`

| Global Requirement | 判定 | 依据 |
| --- | --- | --- |
| 记录机器最后一次被成功采集的时刻 | 已覆盖（Node 侧）/ 本仓库不适用（其余） | Ctrl 写 `last_seen_at`；Node 侧支撑事实「采集异常仍算听到」要求 Node 发出显式 `collect_error` 形状，已由既有 `snapshot-container-status` 要求覆盖（`network/wss.py:356-357`） |
| 以最后可见时刻兜住窗口起点 | 本仓库不适用 | Ctrl 启动扫描 |
| 扫描必须先于链路拨号 | 本仓库不适用 | Ctrl 启动顺序 |
| 不修改结算与消费口径 | 本仓库不适用 | Ctrl |
| 迁移携带该信号 | 本仓库不适用 | Ctrl 数据迁移 |

### A.10 `unify-action-task-scope` / `machine-scope-gate`

| Global Requirement | 判定 | 依据 |
| --- | --- | --- |
| 单一定义机器的管辖范畴 | 本仓库不适用 | Ctrl 共享判定 |
| 动作任务在范畴外不动作 | 本仓库不适用 | Ctrl 三个自动任务 |
| 范畴外不产生任何记录 | 本仓库不适用 | Ctrl 日志口径 |
| 范畴内失败仍照常留痕 | 本仓库不适用 | Ctrl |

### A.11 `per-machine-node-port` / `machine-node-endpoint`

| Global Requirement | 判定 | 依据 |
| --- | --- | --- |
| 每台机器的 Node 端点（主机 + 可选端口，回落默认） | 已覆盖（Node 自身端口）/ 本仓库不适用（其余） | Node 只知道自己监听端口：`backend--runtime-configuration` 的 NetConfig 已叙述（`config.py:21-27`）；机器端口记录在 Ctrl |
| 端口在机器建档时录入 | 本仓库不适用 | Ctrl `Register_machine` |
| 三条出站路径共用同一端口来源 | 本仓库不适用 | Ctrl 出站 |
| pin 文件键统一为裸主机 | 本仓库不适用 | Ctrl pin 文件命名 |
| 端点变更后链路跟随 | 本仓库不适用 | Ctrl 对齐 |
| 端点变更只改登记，不涉信任 | **吸收**（Node 部分）/ 本仓库不适用（其余） | 该条明确「对端身份的最终判据 SHALL 落在对端——Node 校验链路携带的 uid 并拒绝不符者」→ 并入新要求③；登记/取证部分在 Ctrl |

### A.12 `defer-freeze-and-mount-windows` / `unavailable-window-deferral`

| Global Requirement | 判定 | 依据 |
| --- | --- | --- |
| 顺延覆盖全部「起点 + 窗口」型到期判定 | 本仓库不适用 | Ctrl 到期判定（ssh 清理、磁盘冻结、mount 清理的**判定**在 Ctrl） |
| 顺延的结算与进行中窗口 | 本仓库不适用 | Ctrl 读侧 |
| 结算与 ssh 清理同事务 | 本仓库不适用 | Ctrl 事务 |
| 起点复位时顺延归零 | 本仓库不适用 | Ctrl |
| 无顺延时行为不变 | 本仓库不适用 | Ctrl |

> 说明：Node 侧确实有 `clean_mount` 执行面（`services/container_service.py:874-876` 的 realpath + `/containers/` 约束），但 Global 该变更约束的是**何时判定到期**（Ctrl），不是 Node 的执行动作，故为不适用，未据此扩张 Node SPEC。

### A.13 吸收落点：新要求 ↔ Node 代码证据

| # | 新 Requirement | 目标文件 | 代码证据 |
| --- | --- | --- | --- |
| ① | 构建段命中本机标签即跳过构建 | `backend--container-creation` | `services/container_service.py:189-213`（`:196-201` 两字段必填、缺 `dockerfile_text` 抛错；`:206-209` `images.get(image_tag)` 命中即 `return`；`:210-211` `ImageNotFound` 才构建）、`:232-238`（`tag=image_tag` 构建）、`network/api.py:130,135-148`（有构建段才进构建态，`:147` 以构建出的 tag 覆盖运行镜像） |
| ② | 恢复挂载来源只由入参决定 | `backend--container-creation` | `services/container_service.py:323-328`（`restore_mount_path` 入参）、`:378-379`（仅无入参时按 base/owner/name 推导）、`:382-394`（realpath + base 前缀 + `containers` 段 + 目录存在校验后 `host_root_mount = mount_real`）、`:422-426`（同名容器直接拒绝）、`:432`（`Mount(source=host_root_mount)`）、`network/api.py:151-156`（透传入参） |
| ③ | Ctrl 拨入链路端点与身份门禁 | `backend--wss-snapshots` | `network/wss.py:34-35`（`CTRL_LINK_PATH` 与「共用同一 HTTPS 监听、同一张 Node 证书」）、`:483-485`（路由）、`__init__.py:44`（同一 app 挂载）、`run.py:20-30`（单次 `uvicorn.run` 带 `ssl_certfile`/`ssl_keyfile`，配 `NODE_CTRL_CA_FILE` 时 `ssl_ca_certs` + `CERT_REQUIRED`）、`network/wss.py:414-419`（读取查询参数 `uid`）、`:463-467`（无身份牌 → 关闭，不推送）、`:468-472`（uid 缺失/不符 → 关闭）、`__init__.py:18-19`（Node 不再自行出站） |
| ④ | 恢复重建账号时修正家目录属主 | `backend--collaborator-accounts` | `network/api.py:157-160`（`restore_accounts` 逐条重建，失败即抛）、`services/container_service.py:659-668`（`useradd -M -d /root/.collaborators/<user>`、`ln -s` 到 `/home/<user>`、`chown -R <user>:<user>`、按 role 加组）、`:432`（`/root` 即持久化 bind 挂载，家目录落在其内） |

### A.14 Node 侧未实现项

**无。** 12 份 Global 业务 SPEC 中，凡是把义务落在 Node 上的条款（A.3 之「不得降级」「挂载与改名」「家目录属主」、A.5/A.1 之「标签即本机缓存键、本机判定构建」、A.7 之四条、A.11 之「uid 判据在对端」、A.8/A.9 之身份状态与采集异常标记），在当前 `chester-next 33672c4edd96` 代码中均可指认实现行号。故本轮没有把任何未实现要求写成现状需求。

### A.15 既有 SPEC 与代码不一致（只报告，未借此扩大修复范围）

| 位置 | 问题 | 代码事实 |
| --- | --- | --- |
| `openspec/specs/backend--container-creation/spec.md:34` | 「`dockerfile_text` 为 Ctrl 生成的最终 Dockerfile，image_tag 为最终制品 tag；**正文为空走既有镜像**」 | 实现并非如此二分：是否进入构建只取决于 `image_build` 是否为 `None`（`network/api.py:130,135`）；一旦声明了构建段而 `dockerfile_text` 为空，`build_image` **抛错**（`services/container_service.py:198-199`），不会「走既有镜像」 |

本轮新增的 Requirement① 已把实际行为写明（缺文本即失败）。**旧句未改写**，按「冲突只报告」处理，供父代理决定是改为「未提供构建段时按 `config.image` 运行」还是删除该半句。

另有两处既有措辞为刻意存疑，本轮亦未改：

- `backend--container-lifecycle/spec.md:488`：`RemoveContinaerReturn`「是否存在消费需以调用搜索核对」——实际已被 `services/container_service.py:638,640,643,646` 消费，并被 `tests/test_remove_container.py:9,18,29,46` 断言。
- `backend--runtime-configuration/spec.md:52`：`KeyConfig`「是否仍被运行入口消费在 Global 问题清单中核查」——`config.py:69-74` 的 `get_config()` 返回 `AppConfig`（继承 `KeyConfig`），存疑表述与代码一致。

---

## 三、Track B：本地流程规范

### B.1 处置口径

- Global 三篇（`standard--code-style`、`procedure--spec-naming`、`standard--pull-request-format`）已归档到 `bak/2026-10-11/retired-global-standards/openspec/specs/`；本仓库**不搬用**其文件，也**不新增同名或替代**规范 SPEC。
- 按用户最新授权，规范类内容进入三仓库 `openspec`。本轮综合成**一篇本地规范**：`openspec/specs/procedure--repository-workflow/spec.md`（16 条 Requirement）。
- 规范类要求不做业务代码核对，也**未**混入任何业务能力表或类型契约。

### B.2 新规范内容 ↔ 实现证据对照

| 新 Requirement | 依据（可执行件或仓库结构） | 是否自动校验 |
| --- | --- | --- |
| 提交信息采用真实变更条目 | `githooks/commit-msg:70`（白名单）、`:63-69`（跳过空行/注释并计数）、`:77-80`（至少一条） | 行格式与关键字**自动**；中文真实性与通顺**不自动** |
| 禁止工具署名与生成标记 | `githooks/commit-msg:45-49`、`:63-64`（末行与 CRLF） | 自动 |
| 真实合并提交豁免 | `githooks/commit-msg:37-39`（`MERGE_HEAD`） | 自动 |
| 钩子随仓库交付并显式启用 | `githooks/pre-commit:8`、`githooks/commit-msg:9`；两文件在库内 | 配置本身**不能**由仓库代替克隆完成 |
| 钩子保持 LF 与执行位 | `.gitattributes:3`（`githooks/* text eol=lf`） | LF 由检出规则保证；`100755` 是 Git 索引属性，需 `git ls-files -s` 核对，**不自动** |
| 新增 capability 使用门类前缀 | `githooks/pre-commit:83-89`（禁叠加）、`:91-99`（需前缀）、`:100`（`--diff-filter=A` + `-z` + `--find-renames`）、`:51`（archive 跳过）、`:67-70`（HEAD 已有主规格的 delta 放行） | 自动 |
| 业务能力组织边界 | `openspec/specs` 现有 8 个 `backend--*`；`README.md:83` | **不自动**（钩子只查前缀形态） |
| 仓库入口与规格质量 | 根 `README.md` 存在；`openspec/` 仅含 `config.yaml`、`changes/archive/.gitkeep`、`specs/` | **不自动** |
| 规范各仓库独立 | `scripts/` 下检索 `Global` 零命中；`check_pr.py` 与 `pr-format.yml` 无跨仓库路径 | — |
| 问题集中记录并区分证据等级 | `E:\AI\Fuxi\FuxiYu_Global\QUESTIONS.md:14`（本地复现 / 源码确认 / 待验证 三级证据口径） | **不自动** |
| 流程通过不代表业务问题已修复 | `QUESTIONS.md:3`「下列业务问题尚未修复」 | — |
| PR 正文采用四类中英双语栏目 | `scripts/ci/check_pr.py:20-30`（三交付类 + 标签）、`:32-36`（双语标题正则）、`:37` + `:174`（计划栏归入 `_OTHER_HEADING`，不计交付）、`:49-79`（「无」属占位，不计真实条目）、`:43-44` + `:189`（验证/通过率可选）、`:85-147`（注释与围栏剔除）、`:228-283`（至少一栏有非占位条目） | 结构**自动**；条目真实性**不自动** |
| PR 标题与正文结构分离 | `check_pr.py` 全文无标题校验；`pull_request_template.md:2`（自然描述、不强制类型前缀） | **不自动**（按要求不得声称校验标题） |
| PR 栏目与提交关键字相互独立 | `check_pr.py:40-42`（旧 `NEW`/`FIX` 兼容）与 `githooks/commit-msg:70`（`AMEND`）分属两套 | 各自**自动**，互不转换 |
| PR 正文重验与工作流信任边界 | `pr-format.yml:4-5`（触发事件）、`:8`（`contents: read`）、`:25`/`:46`（`persist-credentials: false`）、`:20-34`（base.sha 检查器优先）、`:37-46`（首次引导仅取该脚本）、`:57-60`（固定 SHA256 校验）；`check_pr.py:286`（`load_event_body`）、`:348`（以 `--event` 读取），全文无表达式求值；`tests/test_check_pr.py:479-491`（断言无 `eval(`/`subprocess`/`os.system(` 等） | 自动 |
| 检查能力边界不得夸大 | 同上一列；钩子与检查器均无中文语义、标题、能力划分判定逻辑 | — |

### B.3 相对上一轮的更新点

上一轮记录中关于 PR 正文的表（`NEW | 新增内容` / `FIX | 修复漏洞` 两栏）**已被父代理的新实现取代**，本轮以四类中英双语栏目为准：

- 交付类：`新增内容 | WHAT'S NEW`、`漏洞修复 | Bug Fixes`、`优化工作 | Enhancements & Patches`；至少一栏真实条目。
- 下一步计划栏归入非交付标题（`check_pr.py:24`、`:37`、`:174`）：`下一步计划 | Coming Up` 不计交付（见 `test_check_pr.py:45-54`）。
- `无` 允许出现在空交付栏，但不计真实条目（`check_pr.py:61`；`test_check_pr.py:48-50`、`:287`）。
- 旧 `NEW`/`FIX` 栏目仅作过渡兼容（`check_pr.py:40-42`）。
- 工作流固定摘要已更新为 `18c7f5a20a07d38d98b86609204b4d17d64b214254f1f187538054b7ce75fe0c`（`pr-format.yml:59`），与用户告知值一致；单元测试 40 个（`test_check_pr.py` 中 `def test_` 计数 40）。

---

## 四、检查结果

| 项 | 结果 |
| --- | --- |
| Track A 逐条判定 | 已完成：12 份 SPEC、66 条 Requirement 全部给出判定与代码路径行号（第二节） |
| 既有 SPEC ↔ 代码一致性 | 已完成（本轮新增要求所引证据均已逐一读源确认；另见 A.15） |
| 新增/改写事实的证据充分性 | 已满足：4 条新 Requirement 的每条事实均对应上文 A.13 的源码行号 |
| `openspec validate --specs --strict` | **未运行** —— 本会话无可用 shell，由父代理接管 |
| PR checker 单元测试 | **未运行** —— 同上；父代理已报 40 tests 通过 |
| `git ls-files -s` 的 `100755` 核对 | **未运行** —— 同上，由父代理接管 |
| 固定摘要比对 | 静态证据一致（`pr-format.yml:59` 与用户告知值相同）；实际哈希计算由父代理接管 |

本会话的 pwsh 通道因工作区 Windows 文件权限（工作区根缺少「修改权限/取得所有权」，沙箱无法授权）在启动前即失败，故上述命令不可执行。按用户指示，本轮不再做 ACL 诊断、不提权、不反复重试、不再使用探针；仅以文件工具读写并报告静态证据。

静态度量（由文件工具得出）：

- `openspec/specs` 现有 **9** 个 capability 目录：8 个 `backend--*` + 1 个新增 `procedure--repository-workflow`。
- `openspec/` 内无 README；根 `README.md` 保留。
- 新增 capability 名 `procedure--repository-workflow` 为单一门类前缀，符合 `githooks/pre-commit:83-99`。

---

## 五、未决问题与移交

1. **`backend--container-creation/spec.md:34` 的措辞与代码不符**（A.15）：需父代理择一改写（「未提供构建段时按 `config.image` 运行」或删除「正文为空走既有镜像」半句）。本轮只报告。
2. **Node 的 `/issue_uid` 不校验既有身份**：`network/wss.py:330-339` 无条件覆盖已存 uid，因此 Global `renew-machine-trust`「对端已持有身份牌时 MUST NOT 更换 uid」这条不变量**完全依赖 Ctrl 先读 `identity_initialized`**，Node 侧不设防。Node 只保证上报状态（`network/wss.py:303-317`）。这不是 Node 违反 Global 要求（该条约束对象是 Ctrl 操作），但如需端侧防线应作为独立议题，本轮未擅自加要求。
3. **`QUESTIONS.md` 的证据等级口径**：现行文件只实例化三级（本地复现 / 源码确认 / 待验证，见 `QUESTIONS.md:14`）并以「尚未修复」为默认态；**已修复**是用户要求纳入的解决态标记，尚未在该文件中出现实例。Track B 规范按用户口径写成「已解决问题标记为已修复」，若与 Global 实际维护方式有出入，请以 Global 为准调整该条。
4. **`RemoveContinaerReturn` 与 `KeyConfig` 的存疑措辞**（A.15）可收紧，但与本轮吸收无关，未改。
5. **工作区残留**：`.dsh-write-probe.tmp`（内容 `probe`，未跟踪，上一轮探针产物）。本轮无 shell 无法删除，请父代理清理：`Remove-Item -Force 'E:\AI\Fuxi\FuxiYu_NodeKernel\.dsh-write-probe.tmp'`。
6. **提交归属**：本轮 5 个文件改动（4 个 SPEC + 本记录）为 DSH 新增，按用户说明不会自动纳入父代理此前已暂存的那次提交。
7. 8 份业务 SPEC 的 `Source references` 中「Linux 安全默认套件 152 passed、11 deselected；未运行 Docker 集成测试」本轮未复跑，保持原状。

报告结束。
