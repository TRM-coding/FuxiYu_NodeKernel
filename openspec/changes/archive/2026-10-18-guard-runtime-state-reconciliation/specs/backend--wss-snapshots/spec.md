# Spec Delta

## MODIFIED Requirements

### Requirement: snapshot-container-status 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：type='snapshot'；topic='container_status'；payload 为 {container_name: 状态条目}，条目含 source/status、可选 runtime_metrics、失败上下文和可选 last_action（ref/action/phase/error_reason）。状态条目 MUST 表达新鲜运行态，或当前动作等待期的既有受理过渡态；动作软失败 MUST NOT 使容器 status=failed，只有硬阻塞可发 failed；未知 MUST 发 unknown 并保留最后已知于内部。新 Node 无动作记录时 MUST 在条目输出 last_action:null；last_action.failed MUST NOT 令 status=failed。采集器有 collect_error 时 payload 改为 {collect_error: reason}，不发送伪正常空表或强行 online。

#### Scenario: 动作失败但容器实际运行

- **WHEN** unpause 动作被记录为失败，而节点已用新鲜 Docker 实态确认容器 running/not paused
- **THEN** 该容器快照发送 online 或符合就绪门禁的状态，不发送 `failed` 或 `unpause_failed`

#### Scenario: pause 软失败但实际 online

- **WHEN** pause 软失败而容器当前 running/not paused
- **THEN** 条目发送 runtime online 与可选 `last_action.phase=failed`，两者原子一致；不得把条目 status 改成 failed

#### Scenario: 无动作记录仍保留字段

- **WHEN** 新 Node 冷启动后该容器没有本地动作记录
- **THEN** WSS 条目显式包含 `last_action: null`，JSON 序列化不得丢弃；旧 Node 可缺字段

#### Scenario: 只有硬阻塞发送 failed

- **WHEN** 当前 Docker 实态为 dead、created 半成品，或既有 start/create 就绪门禁判定硬阻塞
- **THEN** 快照可以发送 failed 并保留原因，旧事件、动作 TTL 或普通采集不得把它改成永久遮挡真实状态的失败

#### Scenario: 无法判定时发送 unknown

- **WHEN** 单容器新鲜 inspect 或指标采集不可判定，最后已知状态仍保存在缓存
- **THEN** 快照发送 unknown 及既有 status_source/unknown_since 语义，而不是 online、failed 或把最后已知冒充当前实态

#### Scenario: Docker 状态采集失败

- **WHEN** Docker 状态采集失败
- **THEN** 发送显式 collect_error 形状，Ctrl 可以区分采集失败与机器没有容器；不发送空表或强行 online

## ADDED Requirements

### Requirement: 状态快照与旧 Ctrl 收敛

Node SHALL 只使用既有线路状态值和新增的可选动作诊断字段表达运行态与动作关联，MUST NOT 依赖尚未承诺的 Ctrl 新 DB 字段或新协议。旧 Ctrl 完全可忽略 action_ref/last_action；选择使用该可选契约的新 Ctrl/独立变更在旧 Node 缺字段时自行按缺失降级。旧 Ctrl SHALL 能依据 online/offline/paused/starting/unknown/failed 及 status_source 收敛，运行态恢复不依赖动作诊断。

#### Scenario: 旧 Ctrl 忽略动作诊断

- **WHEN** 旧 Ctrl 只读取既有 status/source/status_source，不读取 action_ref/last_action
- **THEN** 运行态仍按既有语义收敛，额外字段不会改变 Node 运行态或旧 Ctrl 行为

#### Scenario: 旧 Ctrl 收到恢复后的 online

- **WHEN** 节点重启后容器持续 running/not paused，快照发送既有 online 语义
- **THEN** 旧 Ctrl 可据此恢复此前被 failed pending 覆盖的状态，不需要读取新字段或执行 Node/Ctrl 协议升级

#### Scenario: 旧 Node 缺字段

- **WHEN** 旧 Node 的响应或快照缺少 action_ref/last_action
- **THEN** 选择使用动作绑定的独立变更按自身 ref/方向或 timeout 规则降级，不要求 Node 补发必需回执；不使用动作绑定的消费方只按真实状态处理

#### Scenario: 可选动作诊断缺失

- **WHEN** 消费方不支持任何可选动作诊断字段，只读取既有 status/source/status_source
- **THEN** 运行态仍能按既有语义收敛，动作诊断缺失不影响状态判断

#### Scenario: 不依赖新 DB 字段

- **WHEN** Ctrl 数据库没有新增动作诊断列，仍按既有容器状态字段接收快照
- **THEN** Node 的快照仍可被消费，运行态和 unknown/硬阻塞语义保持可解释

### Requirement: pause 终态与 Ctrl 确认边界

Node SHALL 只在运行态确实为 paused 时提供 pause 成功终态；pause 软失败 MUST NOT 使容器 status=failed，MAY 通过可选 last_action.phase=failed 提供动作诊断。实际 pause 确认 MUST 依赖真实 paused 状态；选择使用可选动作引用的独立变更可按精确 action_ref/last_action 契约终结其自身过渡，并自行定义 timeout/降级；Node 不规定消费方必须使用该可选契约。当前 Docker 实态证明 dead 等硬故障仍可按既有 failed 发送，但不得伪装成 pause_failed。

#### Scenario: pause 软失败但容器仍在运行

- **WHEN** pause 动作被记录为软失败，而新鲜 Docker 实态仍为 running/not paused
- **THEN** WSS 发送 runtime online 与可选 `last_action.phase=failed`，不发送容器 status=failed；选择使用动作引用的独立变更可按精确 ref 结束自身过渡，但不能视为 pause 已确认

#### Scenario: 终态 paused 才确认

- **WHEN** WSS 快照中的运行态到达 paused
- **THEN** Ctrl 可据此确认 pause 终态，不需要 `last_action` 或新的必需字段

#### Scenario: online 不得被当作 pause_failed

- **WHEN** 选择使用动作引用的独立变更在 pause 后看到 online 或其他非 paused 状态
- **THEN** 不能把 online 单独解释为 pause_failed 或暂停成功；动作绑定按消费方所属变更的 ref/方向及超时契约处理，实际暂停仍等待真实 paused

#### Scenario: 缺 ref 或字段

- **WHEN** 没有 action_ref/last_action，或旧 Node 缺字段
- **THEN** 实际 pause 只按真实 WSS `paused` 确认；选择使用动作引用的独立变更才按自身 ref/超时规则降级，不假定成功或失败；不使用该契约的消费方不因缺字段等待 timeout

#### Scenario: confirmed 但运行态反向

- **WHEN** last_action 为 pause 的 confirmed/idempotent_confirmed，但当前 WSS 运行态仍为 online
- **THEN** Ctrl 不得仅凭动作 phase 确认 pause 或写容器 paused；保留收敛屏障，等待实际 paused 或超时 unconfirmed

#### Scenario: 真实 Docker 故障仍可失败

- **WHEN** 当前 Docker 实态为 dead 等明确硬故障
- **THEN** 快照仍可按既有硬阻塞发送 failed，但该 failed 表示运行态故障，不是 pause_failed，也不清除 start/create 就绪硬阻塞

### Requirement: 动作引用与 Ctrl 过渡终结

Node SHALL 在动作受理响应提供可选 action_ref，并在 HTTP/WSS 的 last_action 中保持同一 ref；这是 Node 自身动作诊断，不规定 Ctrl 必须消费。选择使用该可选契约的独立变更在依据动作记录终结自身绑定过渡时，MUST 精确匹配 {node_epoch,generation,seq}、action 方向与终结 phase，并按自身契约处理缺字段/旧 ref/未知 phase 的 timeout 降级；不使用该契约的消费方继续按真实运行态处理，pause 只由 paused 确认，不因缺可选字段拒绝真实状态。早到 WSS 终结可由选择使用该契约的消费方按自身规则暂存；Node MUST NOT 因 ACK/WSS 交错强发 failed。Node epoch 变化旧 ref 失效。

#### Scenario: ACK 先到

- **WHEN** Ctrl 先收到 HTTP action_ref，随后 WSS last_action 到达同一 ref 与终结 phase
- **THEN** 只有 action 方向匹配且 phase 为终结时可结束对应过渡；运行态仍按实际状态决定

#### Scenario: WSS 终结先到

- **WHEN** WSS last_action 终结帧先于 HTTP ACK 到达
- **THEN** Ctrl 可按 ref 有界暂存，ACK 到达并精确匹配后应用；Node 不得因等待 ACK 而伪造 failed，回执丢失时保持 unconfirmed

#### Scenario: 旧 ref 或未知 phase

- **WHEN** last_action 的 node_epoch/generation/seq 不匹配当前绑定，或 phase/action 未知
- **THEN** 选择使用该可选契约的独立变更不能结束自身过渡或放行其业务，只能按其自身 timeout 降级；不使用该契约的消费方按真实状态处理，不因 ref 不匹配/未知 phase 阻挡暂停确认

#### Scenario: Node 重启 epoch 失效

- **WHEN** Node 进程重启导致 node_epoch 变化
- **THEN** 旧 action_ref 永不匹配；新 Node 无动作记录时输出 last_action:null；选择使用动作绑定的独立变更才按自身 timeout 降级，不使用该契约的消费方按真实 paused/online 状态处理，不因旧 ref/缺字段阻挡

#### Scenario: 非 pause 动作不误匹配

- **WHEN** last_action 属于 create/start/stop/restart 等非 pause/unpause 动作
- **THEN** 即使 ref 精确也不得结束 pause/unpause 过渡；仅方向匹配的动作 ref 可参与终结
