# Design

## Context

本变更对应 Node 仓库第 4 批 Anvil 映射补测，目标能力是已同步的 `backend--storage-and-mounts`（24 Requirement / 79 Scenario）与 `backend--wss-snapshots`（12 Requirement / 45 Scenario）。两份主 spec 的 SHA-256 分别为 `1BF37A27…C89A1` 与 `2DDE210D…D468`，均无能力侧车 test-plan；现状测试集中在 `tests/test_verify_bind_mount.py`、`tests/test_mount_usage_cache.py`、`tests/test_mount_usage_api.py`、`tests/test_cache_collectors.py`、`tests/test_prevent_vanished.py`、`tests/test_runtime_guard.py`、`tests/test_action_contracts.py`、`tests/test_blueprint_api.py` 与 `tests/test_clean_mount.py`。约束是只做映射与缺口补测规划，不改变主 spec 业务语义，不修改应用实现与既有测试。

测试基础设施可直接复用：`pytest.ini` 默认 `-m "not docker"`；`tests/runtime_fakes.py` 提供 Docker 边界替身与确定性屏障；`tmp_path` + `NODE_CONTAINERS_BASE` 做路径隔离；`TestClient(create_app())` 走真实 FastAPI 入口；`du`/`psutil`/`shutil.disk_usage` 在外部边界替换。设计只决定“怎样把每个 Scenario 映射到可核对断言”，不决定业务行为。

## Goals / Non-Goals

**Goals:**

- 124 个 Scenario 各有 canonical 映射：Requirement 名与 Scenario 名沿用主 spec 原文，每个 Scenario 至少一条具体 Test/check locator，并写明 Assertion scope；部分覆盖或共享覆盖用 Coverage note 说明。
- 现有测试只在读到具体测试代码并核对其断言后标 `[X]`；没有对应断言或只覆盖次要分支的 THEN，标 `[ ]` 并规划到单一新文件 `tests/test_anvil_storage_snapshots.py`。
- 把 Q77 依赖的 LastSsh 非运行态断言与可独立验证的无登录记录/序列化断言拆开：Q77 行保持 `[ ]`、未创建、不 skip/xfail，其他独立测试继续；不把当前缓存旧值写成规范期望。
- 缺口测试验证真实可观察行为：Pydantic 校验/缺省、FastAPI 状态码与 JSON、真实 `DiskUsageCache` 的缓存键/路径失效/测量状态、真实 WSS 帧字段与顺序、真实 `SysSnapshotCache` 静态提取；外部 Docker、`du`、`psutil`、WSS 传输才使用替身。
- delta 采用完整 Requirement 块的逐字 MODIFIED no-op，保证 sync 幂等且不在主 spec 留下测试说明。

**Non-Goals:**

- 不新增业务能力、数据表/列、HTTP/WSS 字段、topic、周期或观测协议；不增加目录 dev/inode/PID 的线路字段或业务门禁。
- 不改 `disk_usage_cache.py`、`wss.py`、`api.py`、`schemas/container.py`、`container_service.py`；不改 Ctrl 的存储模型、资格 DTO 或业务授权。
- 不写 `review.md`、`tasks.md`、任何测试文件、主 spec、能力侧车 test-plan、既有测试、共享 fixture、依赖、配置、DB、CI、skills；不 commit。
- 不与其它 active change 交错，不读取或复用其它 active change 的测试与产物。

## Decisions

### 1. delta 用完整 Requirement 块逐字 MODIFIED no-op

每份 delta 以 `# Spec Delta` + `## MODIFIED Requirements` 开头，随后按主 spec 原顺序放入全部 Requirement 块：从 `### Requirement:` 到该块末尾的 `来源：` 行（无来源行的行为 Requirement 到下一标题前）逐字复制；Scenario 名、WHEN/THEN、空行与标点都不改。生成后按块重新解析 delta，与主 spec 块做逐字节比较，并核对 Requirement 数 24/12、Scenario 数 79/45。

理由：Anvil 的 MODIFIED 需要完整 Requirement 块；完整原文本身构成非空 delta，sync 时同内容替换，结果幂等。若用 ADDED 记录“测试映射”，会把测试意图写成新业务能力；若在说明段追加“本轮仅做测试对账”，sync 后会把时效性说明永久留在主 spec。替代方案“只在 proposal/design 记录映射、不写 delta”不满足 Anvil 的 artifact 依赖和 sync 载体要求。

### 2. 映射标识使用 canonical 路径，不造 ID

test-plan 按能力 → `### Requirement: <原文名>` → `#### Scenario: <原文名>` 组织；标识就是三者路径，不引入 kebab-case ID、状态字段或“Gap”字段。一个 Scenario 可以有多条 Test/check 行；一个测试也可服务多个 Scenario，但每个 Scenario 的 Assertion scope 必须独立写清该场景覆盖到哪一段 THEN。

### 3. `[X]` 只给已核对的既有断言，`[ ]` 只给真实缺口

执行顺序固定：先读主 spec 的完整 Requirement 与 Scenario，再读候选测试源码，逐条对照 WHEN/THEN 与测试断言；只有测试确实构造了对应输入并断言了对应可观察结果，才写 `[X]`。`[X]` 不表示测试已运行或通过，只表示 locator 与断言映射已核对。以下情况不冒充完整覆盖：

- 只有路由成功路径、没有模型缺省/非法输入断言；
- 只有本地消费方策略回放、没有 Node 真实输出断言；
- 只断言路径状态、没有断言测量字节/`measured_at`；
- 只断言“未调用某函数”，但没有覆盖 Scenario 的核心 THEN。

对真实缺口，test-plan 写 `[ ]` 行指向规划测试名，Coverage note 只描述该规划测试要断言的边界与现有行未覆盖的部分，不写泛化的“当前无测试/尚未创建”时态句，也不记录执行结果。唯一例外是父已登记的 Q77 暂缓项：必须明确标注该 locator 未创建、不 skip/xfail、依赖修复，以便 reviewer 区分可独立补测与暂缓断言。

### 4. 缺口集中到单一新文件，测试真实目标逻辑

缺口统一规划到 `tests/test_anvil_storage_snapshots.py`，按能力分节、按 Scenario 命名测试。实现原则：

- 模型/线路：直接构造 Pydantic 模型并断言缺省值、必填缺失、非法类型/Literal、`model_dump` 字段集合；别名类型用真实 `model_validate`/`model_dump` 验证，不靠源文本扫描。
- 路径与测量：用真实 `DiskUsageCache`，只把 Docker 容器对象、`/proc` 身份读取、`subprocess.run`（`du`/`rm`）替换为可编程替身；路径规范化、缓存键、路径变更失效、singleflight、TTL、错误映射走真实实现。
- HTTP：用 `TestClient(create_app())` 走真实路由与 response_model；需要隔离时注入 `extensions.disk_usage_cache` 或 `tmp_path` 下的 `NODE_CONTAINERS_BASE`，不启动 lifespan 的真实 Docker。
- WSS：直接调用真实 `build_*_snapshot`/`build_snapshot_batch`/`handle_ctrl_ws`，用最小 ASGI WebSocket 替身记录帧；不接真实网络。
- 系统快照：真实 `SysSnapshotCache.collect/collect_static/_collect_disk`，只替换 `psutil`、`nvidia-smi`、`shutil.disk_usage` 等外部读取。
- 安全边界：需要断言“不得发生”的路径（不清理、不扫描父目录、不持久化）时，用真实入口 + 记录型替身/`os.scandir` 视图断言未被调用，而不是断言源码字符串。

不把测试写成对实现私有常量或源码文本的镜像；允许使用现有测试已经采用的公开/半公开读面（`snapshot()`、`read_mount_usage()`、`build_*_snapshot()`、`_effective_usage_for_read`）验证真实行为。

### 5. 路径、dev/inode 与 Ctrl 业务边界

`bind_mount_path` 是唯一业务路径。目录 dev/inode 只在 Node 内部路径核对/有界候选定位时使用，作为内部对象匹配依据，不进入 HTTP/WSS 字段、不成为长期/冻结/删除/清理门禁、不新增观测协议或表字段。WSS/HTTP 只暴露既有 `bind_mount_path`、`mount_path_status`、字节与真实 `measured_at`。Ctrl 的存储模型、资格 DTO、DB 列与 `container:manage` 授权不在本变更；test-plan 中 Ctrl 视角的 Scenario 只映射 Node 可观察事实，跨仓库消费方行为以既有 Node 帧断言 + 本地契约夹具/说明为边界，不伪造 Ctrl 实现。

### 6. 业务矛盾只报告，不改规格

映射过程中若发现主 spec 的 WHEN/THEN 与现有实现/测试存在业务矛盾，只记录到最终报告与外部日志，交父代理决策；不修改应用、不弱化 Scenario、不把矛盾写成“通过”的映射。Anvil 侧只做 no-op delta 与映射，不用测试反向定义业务。

### 7. Q77 已知差异的隔离

Global Q77（607bbfd / 现 6392692）已登记：`LastSshCache.collect()` 对非 running 容器直接返回并保留已采到的真实旧值，`list_last_ssh()` 直接把缓存 `value` 放入快照，没有按当前运行状态过滤；主 spec 的 `snapshot-last-ssh` 要求非运行态时间为 None。该差异的修复、Ctrl 历史登录时间保留策略、主 spec 口径与任何数据结构均不在本变更。

test-plan 把 LastSsh 拆成两组 locator：

- 可独立验证组：running 容器命令成功但空输出 → cache `value=None`；`list_last_ssh()`/`build_last_ssh_snapshot()` 返回 None；`updated_at` 不带后缀。该组不依赖 Q77，可先实现。
- Q77 依赖组：running 时采到真实旧值，容器转非 running 后，按主 spec 快照应返回 None 而非缓存旧值。该 locator 保持 `[ ]`、未创建、不 skip/xfail，待 Q77 修复后再作为普通测试实现；不得把缓存旧值当规范期望。

Q77 只阻塞上述依赖断言，不阻塞其余独立缺口测试、tasks 规划或非依赖项的 apply。reviewer 批准计划后，父仍可决定先做独立测试，Q77 行保持暂缓。

## Risks / Trade-offs

- 124 个 Scenario 中有多段 THEN 属于跨进程/跨仓库消费方语义（Ctrl 收敛、DB 无新列、浏览器边界），Node 仓库只能验证 Node 输出与既有契约夹具；test-plan 必须在 Assertion scope/Coverage note 明确边界，不能把 Node 侧断言说成 Ctrl 已完成。
- 现有测试中部分用例使用私有缓存字段或本地策略夹具，断言虽真实但覆盖范围有限；本计划优先把它们映射到能证明 Scenario 核心 THEN 的行，缺口另起规划行，避免用一条 `[X]` 掩盖部分覆盖。
- 规划测试数量受缺口判断影响；若独立 review 认为某条 `[X]` 的断言不足，需要把该行改为 `[ ]` 并补规划或调整 scope，这会触发重新 review。
- Q77 的暂缓行在 Q77 修复前不能实现；若 reviewer 或父代理要求先修 Q77，会改变实现范围并需要新的计划审查，本轮不擅自扩范围。
- delta 逐字复制依赖生成脚本的块边界；已用重新解析 + 逐字节比较 + 数量核对降低风险，但正式 sync 前仍需 `openspec validate` 与 review。
- 本文件不记录测试执行结果；apply 后的真实结果只留在测试日志或 official verify，不写回主 spec 或本计划。
