# Design

## Context

- 目标主规格：`openspec/specs/backend--container-lifecycle/spec.md`，当前 SHA256 `7D55260436028F4616D849CE485C5D29413ACAF3E985292B3771837385A450F5`，42 个 Requirement、93 个 Scenario；无 `test-plan.md` 侧车。
- 现有默认测试集：27 个测试文件、468 个 pytest node，`pytest.ini` 默认 `-m "not docker"`；真实 Docker 用例被显式排除，不能作为本次缺口的默认验收依据。
- 现有覆盖集中在 `tests/test_runtime_guard.py`（63 个测试）、`tests/test_action_contracts.py`、`tests/test_prevent_vanished.py`、`tests/test_runtime_barriers.py`、`tests/test_action_inspect_errors.py`、`tests/test_blueprint_api.py`、`tests/test_cache_collectors.py` 等；它们通过 `status_cache`、服务层、FastAPI 与 WSS 真实入口断言，Docker 仅以 `tests/runtime_fakes.py` 的 fake 替换。
- 目标 change 在本次开始前不存在；旧句柄 `f32e0731` 未留下可继续的 change 工件。本 change 从空目录新建；其他活动 change 不在本次范围，不读取、不修改、不归档其工件或测试文件。
- 规划根为仓库 nearest root `E:\AI\Fuxi\FuxiYu_NodeKernel`，schema 为 `anvil`。

## Goals / Non-Goals

**Goals:**

- 对 93 个 Scenario 逐条建立 canonical 映射：`[X]` 表示已从现有测试代码核实 locator 与断言范围，`[ ]` 表示待补或断言不完整。
- 保持 delta 与主规格 Requirement 逐字一致，使用完整 `MODIFIED` no-op，不污染主规格。
- 把真实缺口收敛到一个专属测试文件，明确每个待补测试的断言目标、fake 边界和不可覆盖部分。
- 让 fresh reviewer 能只读地核对 Scenario、locator、Assertion scope、Coverage note 与缺口文件路径。

**Non-Goals:**

- 不实现、不运行新增测试，不生成 tasks/review，不修改既有测试或共享 fixture。
- 不修改主规格、测试侧车、业务源码、配置、skills、CI、数据库。
- 不宣称真实 Docker daemon、真实容器、真实网络或 Ctrl/Web 跨仓行为已验证。
- 不替父代理做业务决策；发现实现与规格矛盾时只报告。

## Decisions

### 1. 全部 Requirement 以逐字 `MODIFIED` no-op 进入 delta

从主规格 `### Requirement:` 起、到 `## Data model appendix` 前，按原顺序逐字复制 42 个 Requirement 与全部 Scenario，只在文件开头添加 `# Spec Delta` 与 `## MODIFIED Requirements`。不复制 Data model appendix 的表格标题，不添加测试说明、覆盖状态或运行台账。

理由：Anvil 需要 delta 作为 Scenario 清单，但本变更没有行为差异；逐字复制可避免测试内容污染主规格，也避免把数据附录误当 Requirement。替代方案“只写新增/删除”不适用，因为 93 个 Scenario 都需要映射锚点。

### 2. `[X]` 只授予已核实断言，不按文件存在或函数名猜测

对每个候选 locator，读取测试函数体，确认其实际断言覆盖 Scenario THEN 的核心行为；仅“同名”“导入模型”“静态源字符串”“反射检查类型别名”不算行为覆盖。部分覆盖的 Scenario 同时保留 `[X]` 行与 `[ ]` 缺口行，并在 Coverage note 写清缺哪一部分；只有完全没有可用断言的 Scenario 才不给 `[X]`。

理由：change test-plan 的 checkbox 是“映射已核实”，不是“测试通过”；现有测试常有共享覆盖，必须让 review 看见边界。

### 3. 真实缺口集中到 `tests/test_anvil_lifecycle_contracts.py`

该文件按行为分组，而不是每个 Scenario 机械一个函数：

- 数据契约组：模型必填/缺省、Literal 值域、wire alias、`container_name` 优先级、内部枚举与 `MachineStatus` 类型边界、`RemoveContinaerReturn`、状态响应硬阻塞字段、WSS `last_ssh` 的 None。
- 事件组：正向事件轨迹、inspect 失败诊断、未知事件诊断且不排队删除、迟到事件不回滚。
- 动作边界组：unpause 非 `not paused` 错误、重复 unpause 未过 ready 门禁、重复 pause 幂等、动作 TTL 不清硬阻塞。
- 硬阻塞/恢复组：created/dead 边界、exited 不形成硬阻塞、sshd 未安装端到端硬阻塞、同名对象删除重建后按新代解除硬阻塞。
- 代际/采集/有界组：旧观察票失效、列表失败保留最后已知、unknown 后恢复、旧 failed pending 不复活、动作记录上限。

待补测试使用现有 `tests/runtime_fakes.py` 的 `FakeRuntimeContainer`、`FakeRuntimeContainers`、`install_runtime`，不修改该共享 helper；模型测试直接构造 Pydantic 实例。只替换 fake Docker 客户端/容器、`docker.from_env`、`event_log.record`、`caplog`，以及 API 测试的 `extensions.status_cache` 接线；WSS last_ssh 测试写入真实 `extensions.last_ssh_cache` 后调用真实 `build_snapshot_batch`，不替换 WSS 入口。不 monkeypatch `accept_action`、`publish_observed`、`execute_*`、`_apply_event`、`_reconcile_once`、`_probe_ready_once` 等目标函数。TTL 测试通过调整 `accepted_at`/`expires_at` 的可控时间推进，不 sleep；硬阻塞读取使用 `cache.get(name)[\"hard_block\"]`，不靠 `get_state()` 投影猜测。

理由：用户要求只 mock 外部边界；状态收敛、并发、幂等、错误清理必须由真实 `accept_action`、`publish_observed`、`execute_*`、`_apply_event`、`_reconcile_once`、`_probe_ready_once` 执行。替代方案“每个 Scenario 一个 mock 单测”会绕开目标逻辑，不能作为行为证据。禁止用源码字符串或反射代替行为断言。

### 4. 现有真实 Docker 用例只作补充，不作默认映射主证据

`tests/test_docker_runtime_integration.py`、`tests/test_docker_status_cache.py` 等带 `docker` marker，默认 deselected；本次 `[X]` 优先引用默认集内 fake 断言。只有 fake 无法覆盖且待补测试明确不依赖 daemon 时，才在 Coverage note 说明真实 Docker 验证不在本计划范围。

理由：基线环境不保证 daemon/网络，且用户明确 fakeDocker 无真实 daemon/container/network。

### 5. 不写侧车、不做主规格同步

change test-plan 只服务本次 review/apply；持久侧车由父代理在官方 sync 成功后按 `anvil-test-plan` 维护。delta 不包含测试说明，主规格因此保持原样。

## Risks / Trade-offs

- 数据契约 Scenario 多为通用模板，现有测试通常只间接证明“可构造/可响应”，未逐字段证明缺省与拒绝；映射会显示较多 `[ ]`，这是真实缺口而非测试失败。
- 93 行计划很长，review 必须逐条对照断言；任何 locator、Assertion scope、Coverage note 或 Scenario 变化都会使 review 失效。
- 待补 locator 未创建、未核实，`[ ]` 行只代表缺口映射，不能写成“已通过”；若 apply 后发现实现与规格矛盾，应保留规格并报告父代理。
- 不覆盖 Ctrl/Web 跨仓删除授权与 Q70 严格隔离，也不覆盖 Ctrl 在没有新 last_ssh 观察时保留旧值的跨仓策略；Node 侧只能证明本地代际、delete 帧只含名称、旧 epoch/旧 ref 被拒绝、WSS last_ssh 允许 None，不能宣称跨进程授权或 Ctrl 收敛已验证。
- 不覆盖真实 Docker 的 daemon/网络/容器行为；fake 断言只证明 Node 侧决策与状态机契约。
