# Proposal

## Why

`backend--container-lifecycle` 主规格包含 42 个 Requirement、93 个 Scenario，当前没有测试侧车；现有断言分散在运行时守卫、动作契约、消失确认、API 与创建流程等测试中，当前未逐 Scenario 建立 canonical 映射，也未区分真实缺口与已覆盖行为。需要在不动业务语义、不改实现的前提下完成全量测试对账，并把真正缺口规划到独立测试文件。

## What Changes

- 为 `backend--container-lifecycle` 的 93 个 Scenario 建立 change test-plan；每个 Scenario 映射到已核实存在且断言范围相符的测试，或标记为待补的真实缺口。
- delta 逐字复制原 42 个 Requirement，作为 no-op `MODIFIED` 映射锚点；不新增、删除或改写任何行为，不插入测试说明、台账或运行结果。
- 真实缺口集中规划到 `tests/test_anvil_lifecycle_contracts.py`，只替换 Docker/事件日志等外部边界，使用仓库既有 fake 运行时，不 mock 目标状态机、动作执行或 HTTP/WSS 入口。
- 不修改主规格、测试侧车、既有测试、`tests/runtime_fakes.py`、`tests/conftest.py`、业务源码、共享 fixture、配置、skills、CI、数据库；不执行 commit、push、SSH 或 secrets 操作。

## Capabilities

### New Capabilities

无新增能力；本变更只补测试映射与缺测规划。

### Modified Capabilities

- `backend--container-lifecycle`: Requirement 行为不变；仅以逐字 no-op `MODIFIED` delta 提供 93 个 Scenario 的映射锚点，实际改动是 change test-plan 与待新增的独立测试文件。

## Impact

- 规划影响：`openspec/changes/complete-anvil-lifecycle-test-mappings/` 下的 proposal、design、delta specs、test-plan。
- 测试影响：已规划的 `tests/test_anvil_lifecycle_contracts.py` 覆盖真实缺口，当前未创建、未核实；实施范围限于默认 `pytest.ini` 的 `-m "not docker"`，不依赖真实 Docker daemon、容器或网络。
- 不影响生产代码、wire 协议、数据结构、主规格文本、测试侧车或既有测试断言；业务语义以主规格为准，若补测暴露实现矛盾，应报告父代理，不以测试或规格弱化实现。
