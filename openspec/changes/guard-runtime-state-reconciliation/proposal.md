# Proposal

## Why

2026-10-17 Sylvan 事故表明，状态转移期间的旧缓存回写会让真实 running 被旧的 paused 快照覆盖，随后对 running 容器的重复 unpause 又产生 `is not paused` 失败，并把一次动作异常固化为长期 `failed` pending。事故时间线中，19:33:16.945 的 `finish_action online` 是动作完成日志而非 Docker 事件回调；19:33:31 的 `online -> paused` 是慢速对账旧快照覆盖的高置信推断；19:33:48 Docker 实际返回 `Container ... is not paused`，Node 记为 `unpause_failed`；19:34:20 底层缓存已恢复 `online`，但 failed pending 仍优先于真实运行态。父代理 20:06:38 的 mTLS 只读结果仍为 `failed/unpause_failed`，Ctrl 的单行 DB 复位在约 15 秒后被 WSS 快照回写覆盖，直到 Node 重启后旧 pending 消失才持续 `online`。这不是 unpause 独有的问题，而是 create/start/stop/restart/pause/unpause 共有的旧写竞态。

## What Changes

- 为所有容器动作建立统一受理序号：受理时分配动作序号并登记过渡态；所有观察在发起 Docker inspect/reload 前分配单调观察票（generation/action_seq/read_seq），发布时先校验票再比较 Docker ID 或写状态。旧完成、旧观察和迟到事件不得覆盖已受理的新动作或更新后的真实状态；不得以 inspect 完成时间、响应到达顺序或事件接收序号判断事实先后。
- 复用 `prevent-false-container-vanished` 已规划的本地容器代际与观察边界，不另造第二套代际；只有有效当前代观察可驱动同名 Docker ID 更换，旧代晚到观察不得再次换代或取消新 pending；当前 create 首次绑定 `docker_id` 不是更换，create pending 期间不得被其他观察取消。普通指标更新不推进代际，也不抬动作序号。
- 所有动作以新鲜 Docker inspect 的实际状态确认，而不是以 API 返回、事件接收顺序或旧 `Docker.list` 对象为准；慢速列表和逐容器 stats 必须在最终 reload 前取观察票，旧对象只能作为诊断，不能回写运行态。
- 就绪证明绑定运行进程身份（至少 Docker ID + StartedAt）：pause 保留同一进程的 ready，显式 restart、start 产生新运行进程、同 Docker ID 外部重启、StartedAt 变化或冷启动必须重新进入既有 sshd 门禁；不能只按名称/对象代际复用旧 ready。
- pause/unpause 幂等：对真实 running 且 not paused 的容器再次 unpause 是幂等确认，不制造 `failed`；offline/dead/NotFound 不得被当作 unpause 成功；其他 Docker 或网络错误必须保留并分类，不能吞掉或改写成成功。
- 运行状态与本次动作结果分离：动作失败保留审计、日志和可选诊断，但不得永久把容器置为 `failed`；`exited` 是 `offline`，历史 OOM 在已恢复 running 后不得永久 sticky；只有已有的 start/create 就绪验证门禁，以及当前 Docker 实态证明的 `dead`/其他真实故障，才允许继续形成硬阻塞 `failed`。
- 采集/网络不可判定时保留最后已知事实，对外报告 `unknown`/`collect_error`，不得据此强行 `online`；错误独立记录并保留下一次观察或显式动作的恢复路径。动作 TTL 只停止过渡态对读面的遮挡，不清除硬阻塞，也不把所有 `failed` 按 TTL 抹掉。
- WSS/HTTP 继续使用既有运行态语义和线路形状，新增可选 `action_ref`/`last_action` 动作诊断：动作受理返回 `action_ref={node_epoch,generation,seq}`，HTTP 状态与 WSS 容器条目返回 `last_action={ref,action,phase,error_reason}`；新 Node 无动作记录时显式输出 `last_action:null`，旧 Node 可缺字段。旧 Ctrl 可完全忽略，运行态恢复不依赖这些字段；不得把 `last_action.failed` 映射为容器 failed。pause 软失败不发送容器 status=failed/pause_failed；Ctrl 实际 pause 仍只以终态 `paused` 确认，动作过渡仅由精确 ref+方向匹配的终结 phase 结束，缺 ref/字段只能 timeout unconfirmed，不能把 `online` 当 `pause_failed`。
- 明确与 `prevent-false-container-vanished`、既有 start/create 就绪门禁、Ctrl `guard-long-term-container-transitions`/`unify-disk-freeze-workflow` 及 `verify-bind-mount-identity` 的共享边界和部署顺序；verify-bind 的磁盘路径诊断、采样会话与动作引用严格分离，本变更不改其协议。回归采用受控交错而不是仅镜像单测，覆盖事故时间线、并发动作、旧对账快照、旧响应延迟返回、迟到事件、同名 ID 更换、create 首次绑定、就绪进程变化、采集失败、冷启动、mixed-version、ACK/WSS 交错和旧 ref 晚到。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--container-lifecycle`：动作受理/确认语义、动作序号与读取前观察票、行动引用与 last_action 诊断、同名对象更换、pause/unpause 幂等、就绪证明绑定运行进程、运行态与动作结果分离、硬阻塞分类、未知与恢复、冷启动。
- `backend--container-creation`：创建受理响应增加可选 `action_ref`，create generation 复用对象代际。
- `backend--wss-snapshots`：`snapshot-container-status` 保持既有运行态语义并增加可选 `last_action`，动作失败不得成为永久 `failed` 状态，未知保留最后已知；Ctrl 动作过渡按精确 ref/方向终结，旧 Ctrl/旧 Node mixed-version 可降级。

## Impact

主要涉及 Node 的 `docker_operates/status_cache.py`、`network/api.py`、`network/wss.py`、`schemas/container.py`、`services/container_service.py` 及测试；新增可选 wire 字段，不新增必需字段、数据库字段或 Ctrl 必需依赖。`action_ref/last_action` 只关联单 Node 动作，不是 Q70 跨进程删除授权，也不与 `verify-bind-mount-identity` 的磁盘路径诊断/采样会话/测量路径混用；旧 Ctrl 可忽略，旧 Node 缺字段时新 Ctrl 按 timeout unconfirmed 降级。Ctrl `guard-long-term-container-transitions` 与 `unify-disk-freeze-workflow` 按本次只读核对消费该契约，本仓不修改 Ctrl。跨进程同名代际仍受 Q70 边界约束；“普通 unpause accepted 后立即授宽限”仍是 Ctrl 遗留行为，本变更不修。部署顺序为先 Ctrl 消失防护、再 Node `prevent-false-container-vanished` 的共享基础、最后本变更；Node 可选字段应先于 Ctrl `guard-long-term-container-transitions`/`unify-disk-freeze-workflow` 的完整精确 ref 路径可用，旧 Node 缺口按 timeout unconfirmed 降级。不需要数据库迁移，回滚为回滚 Node 代码并重启服务。
