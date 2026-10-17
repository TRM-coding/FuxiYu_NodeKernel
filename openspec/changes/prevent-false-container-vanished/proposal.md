# Proposal

## Why

`jyz`、`test2` 在 Docker 创建成功且仍运行时，被 Node 状态缓存误报为 `vanished`。Node 随即推送 `delete` 帧，Ctrl 把有效记录软删除，后续重试又因 Docker 名称已占用而失败。现有对账把较早取得的 Docker 列表与较晚读取的缓存集合比较，创建与慢速指标采集交错时会产生这一结果。

## What Changes

- 明确一次对账的观察边界：本轮开始后才进入缓存的容器不得被本轮判为消失；排队删除前核实该容器在 Docker 中确实不存在，并防止旧代删除候选影响同名新建。
- 修正 Docker 事件类型读取，使 `Action` 字段的真实事件进入状态缓存；无法识别的事件仍保持可观测，不以事件缺失推断容器已删除。
- 在创建受理响应返回前登记 `building`/`creating`，让 Ctrl 的下一帧快照不会因后台线程尚未开始而缺少新容器。
- 收紧 `delete` 帧的来源与发送条件；采集错误和创建过渡期不得产生删除帧。
- 增加受控交错回归，覆盖创建发生于枚举前、枚举中、删除排队后，以及 Docker 列表或单容器核实失败。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--container-lifecycle`：创建过渡态、对账观察边界、Docker 存在性再确认、事件动作兼容与本地代际边界。
- `backend--wss-snapshots`：`delete-event` 只表达经 Node 确认的容器消失，不能把本轮新建或采集失败发送成删除。

## Impact

主要涉及 Node 的 `docker_operates/status_cache.py`、`network/api.py`、`network/wss.py` 及其测试。Ctrl 另有非空快照按名称缺席直接软删除的独立路径，配套修复见 Ctrl 变更 `guard-container-vanish-deletion`；两份变更需共同验收，部署顺序为先 Ctrl 防护、后 Node 对账修复。跨进程同名代际身份是否需要扩展协议，单列于 Global `QUESTIONS.md`。`daity` 的挂载数据修正不属于本变更。
