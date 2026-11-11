# Proposal

## Why

Node 仓库的 `backend--storage-and-mounts` 与 `backend--wss-snapshots` 已有同步主 spec，共 124 个 Scenario（79 + 45），但两份能力都没有逐 Scenario 的测试台账：部分 Scenario 只有间接覆盖，部分 THEN 没有任何对应断言，Anvil 侧也没有可供独立审查的映射基线。本轮处于三仓库全量 Anvil 映射补测的第 4 批，需要在不改变业务语义的前提下补齐可审查的映射与缺口补测计划。

## What Changes

- 为 `backend--storage-and-mounts` 与 `backend--wss-snapshots` 各写一份 delta spec：逐条 `MODIFIED Requirement` 完整块，与主 spec 对应块逐字相同（Requirement 标题、说明段、全部 Scenario 名与 WHEN/THEN、来源行原样保留），不追加任何“本轮变更/测试对账”说明，业务语义与文本零变化。
- 建立本变更的 test-plan：以 canonical Requirement → Scenario → Test/check → Assertion scope → 可选 Coverage note 的嵌套清单，记录 124 个 Scenario 的映射；只把已读测试源码并核对断言的行标为 `[X]`，真实缺口标为 `[ ]` 并指向专属新测试文件。
- 记录 Global Q77（607bbfd / 现 6392692）：non-running `LastSshCache` 保留旧值、`list_last_ssh()` 直接回传，与主 spec 的 None 口径不一致。本轮只做登记与计划隔离：不改业务、主 spec、观测字段/协议/DB，也不改 LastSSH 历史保留策略；Q77 依赖的非运行态断言在 test-plan 中单独保留 `[ ]`/未创建/不 skip/xfail，其他独立 LastSsh 与其余缺口测试继续规划。
- 规划缺口测试落点：单文件 `tests/test_anvil_storage_snapshots.py`，用真实模型校验、真实 `DiskUsageCache`/WSS 帧构造、FastAPI 入口与 `tmp_path`；Docker、`du`、WSS 传输用可编程替身，不接真实 daemon、不接外网、不 mock 被测目标逻辑。
- 本轮只写 proposal、design、delta specs、test-plan；不写 `review.md`、`tasks.md`，不创建测试文件，不改主 spec、能力侧车、既有测试、共享夹具、依赖、配置、数据库或 CI。

## Capabilities

### New Capabilities

（无。本变更不引入新能力。）

### Modified Capabilities

- `backend--storage-and-mounts`: 24 个既有 Requirement、79 个 Scenario 建立测试映射；delta 为逐字原文的 MODIFIED no-op，Requirement 行为不变。
- `backend--wss-snapshots`: 12 个既有 Requirement、45 个 Scenario 建立测试映射；delta 为逐字原文的 MODIFIED no-op，Requirement 行为不变。

## Impact

- 受影响产出：仅 `openspec/changes/complete-anvil-storage-snapshot-mappings/` 下的 proposal、design、两份 delta spec 与 test-plan；apply 阶段才允许新增 `tests/test_anvil_storage_snapshots.py`。
- 代码：不改 `docker_operates/disk_usage_cache.py`、`network/wss.py`、`network/api.py`、`schemas/container.py`、`services/container_service.py` 或任何业务实现；不重构 `tests/` 目录、既有测试与共享 fixture。
- 接口 / 数据：不新增或扩展 HTTP/WSS 字段、topic、表、列、迁移、观测协议或目录身份门禁；路径纠正沿用既有业务 `bind_mount_path`，Ctrl 的存储模型与业务授权不在本变更规定。
- 依赖 / 配置 / 安全：无新依赖、不改默认 schema、不改全局 skills/config/CI；不 SSH、不接触生产或 secrets；测试默认不连真实 Docker 与网络。
- Q77 边界：该缺陷的修复、历史保留策略与主 spec 口径调整均不在本变更；仅 Q77 依赖的 LastSsh 非运行态断言等待修复，其他独立计划测试与后续 apply 不因它阻塞。
