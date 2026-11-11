# Tasks

## 1. 共享状态基础

- [x] 1.1 在状态缓存中拆分 RuntimeState、ActionRecord、Observation 三类内部结构；RuntimeState 含 `ready_identity`（Docker ID + StartedAt），ActionRecord 含 `ref`（node_epoch/generation/seq）、action、phase、error_reason 及 last_action 投影；Observation 为读取前签发的 `{generation, action_seq, read_seq}` 票；实现“硬阻塞 > 就绪门禁 > 当前受理过渡 > 运行态/未知”的读面优先级。用纯状态表测试验证动作失败不会改变运行态，且硬阻塞、门禁、过渡、unknown、ready_identity、last_action 各自可解释。
- [x] 1.2 接入 `prevent-false-container-vanished` 已规划的本地代际/观察边界，不新增第二套 generation；在同一锁内提供受理、观察票、同名换代和取消旧动作的共享入口。用测试验证：只有当前代/当前动作序号/有效 read_seq 的观察能驱动同名 Docker ID 更换；旧代晚到观察不得再次换代或取消新 pending；当前 create 首次绑定 `docker_id` 不推进代际/不取消 create；create pending 期间不同 ID 记录 deferred。普通指标更新不推进代际。
- [x] 1.3 实现每名称受理序号与读取前 observation ticket，并用 `last_applied_read_seq` 发布 CAS；票校验（generation/action_seq/read_seq）必须先于 Docker ID 比较和运行态写入。用受控测试验证：同代同动作序号下旧读取延迟返回、后发先到均不能覆盖已发布状态；完成时间/响应顺序/事件接收序号不作为事实时序；普通 metrics 写入使用独立 read_seq，不抬高状态观察票，也不抬动作序号/代际。
- [x] 1.4 定义并测试 DockerFact 与硬阻塞允许集合：只允许既有 start/create 门禁终态、created 半成品和当前 dead；exited、restarting、历史 OOM、动作失败、采集未知均不得进入硬阻塞 failed；真实 Docker 故障不得被软失败规则泛化清除。

## 2. 受理、动作队列与创建协同

- [x] 2.1 为 create/start/stop/restart/pause/unpause 提供统一受理入口，在返回受理响应前分配 action_seq 与 `action_ref={node_epoch,generation,seq}`、登记过渡态并推进 create 的可见 building/creating；node_epoch 每进程启动生成一次 UUID，generation 复用 prevent 对象代际，seq 同代动作序号。用 API 测试验证响应前状态可见、ref 已分配且非负、create 使用新代际、后台线程未启动也不会出现空快照。
- [x] 2.2 为每名称建立按受理顺序执行的串行动作队列，代际更换时取消/跳过旧代未执行项；用两个并发动作测试验证 Docker 调用顺序、旧 finish 记 superseded、新请求状态不被旧完成覆盖，且不同容器互不阻塞。
- [x] 2.3 将 create 受理与 prevent 的创建 pending、代际和删除候选失效逻辑接通；明确 create 自身确认的首次 `docker_id` 绑定、create pending 期间不同 ID 的 deferred 行为。用“旧 delete 候选 + 同名新 create”“旧观察晚到 + 当前 create 首次绑定”“create pending + 不同 ID”交错测试验证旧候选不删新代、旧完成不覆盖新代、首次绑定不取消 create。
- [x] 2.4 处理后台线程启动失败、动作入队失败和进程关闭边界：受理后无法执行时以 ActionRecord failed 收尾，不写永久运行态 failed；用故障注入测试验证 failed 只出现在动作诊断，读面仍按最后已知/unknown。

## 3. 新鲜观察、事件与分类

- [x] 3.1 改造对账：`Docker.list` 只用于发现对象；逐容器 stats 后按名称新鲜解析（`containers.get(name)` 或等价查询），在解析前签发 observation ticket，并核对 Docker ID、generation、action_seq、read_seq。用慢速 list/stats 交错测试验证旧 `container.status`/旧对象永远不能把动作后的 online 写回 paused，也不能把旧列表对象的 ID 当当前身份；按名解析失败的容器转 unknown 并保留最后已知；指标使用独立 metrics_read_seq，不冒充状态观察。
- [x] 3.2 改造 Docker 事件路径：复用 prevent 的 `Action` 优先/`status` 兼容解析和 `exec_*` 冒号后缀噪声规则，事件只作为触发器和诊断；事件回调先取观察票再触发新鲜 inspect，不直接写缓存。用迟到 paused 事件、destroy 事件、exec 噪声、未知事件和 inspect 失败测试验证不回滚新状态、不凭事件删除、事件时间/接收顺序不参与事实排序。
- [x] 3.3 实现 DockerFact 分类：paused→paused、running+门禁通过→online、running+未验证→starting/ready_check、restarting→restarting、exited/stopped→offline、created 半成品→硬阻塞、dead→硬阻塞、不可判定→unknown；`ready_verified` 只在同一 `(docker_id, started_at)` 且进程未变化时复用，pause 保留，start/restart/外部重启/StartedAt 变化必须重新门禁，probe 通过时记录当次 ready_identity。用每种实态、OOMKilled 历史组合和重启前后 StartedAt 测试验证映射。
- [x] 3.4 实现列表级 `collect_error` 与单容器 unknown 的分层：列表失败保留最后已知并发既有 collect_error 形状，单容器 inspect/stats 失败只让该容器 unknown 并附 status_source/unknown_since；用恢复测试验证下一次成功 inspect 清除 unknown、不强行 online。
- [x] 3.5 实现同名 Docker ID 更换路径：票校验通过后才允许比较 ID；最终状态事实必须按名称新鲜解析，不能 reload 慢列表旧对象并以其 ID 驱动换代；旧代晚到观察看到新对象必须先被拒绝，不得再次推进代际/取消新 pending；当前 create 首次绑定走 bind 路径，create pending 期间不同 ID 记录 deferred。用“旧动作在途 + 同名 ID B 出现”“旧代观察晚到看到 B”“慢列表旧对象 A + 当前名称 B”“create 首次绑定”测试验证旧完成被拒绝，并断言测试不声称 Q70 跨进程能力。

## 4. 动作执行、幂等与错误保留

- [x] 4.1 将 `pause_container`/`start_container`/`stop_container`/`restart_container` 的动作路径改为结构化结果，区分 NotFound、Docker API/daemon 错误、超时、状态矛盾与幂等条件，禁止把其他 API 错误统一吞成 False；动作后置观察票固定使用该动作受理序号，不从当前值重取。用错误注入测试验证 detail 进入审计/日志且不被改写成成功，旧动作完成只记 superseded。
- [x] 4.2 实现 pause/unpause 调用前后新鲜 inspect 和幂等表：running/not paused 的重复 unpause 直接确认成功不调用 Docker，paused 的重复 pause 同理，offline/dead/NotFound 不报成功；用事故时序测试验证第二次 unpause 不产生 `unpause_failed`，且运行态保持 online/offline/dead 的真实语义。
- [x] 4.3 实现 start/stop/restart 的通用确认：start/restart 必须重新进入既有 sshd 门禁，已 running 的 start 不能绕过门禁；显式 restart 受理即清除旧 ready 证明，restart 或同 Docker ID 外部重启导致 StartedAt 变化时旧 ready 证明失效；start 对同一进程已有有效 ready_identity 的幂等情形可复用但仍不绕门禁；stop 对已 offline 幂等、对 dead 不报成功。用门禁通过与失败、StartedAt 变化、实际状态矛盾、Docker 调用失败四类测试验证动作结果与运行态分离。
- [x] 4.4 实现动作结果审计与 TTL 语义：记录 ref/action/phase/error_reason/时间，维护 latest action 的终结/非终结相位机，TTL 只停止受理过渡遮挡；用超时、硬阻塞、soft failure 测试验证 TTL 不删除硬失败、不永久写 failed，unconfirmed/timed_out 不结束过渡，动作失败后新请求与下一次 observe 可恢复。

## 5. 读面、WSS 与冷启动

- [x] 5.1 改造 `get_state`/`list_states` 使用统一运行态优先级，禁止 failed pending 优先于真实 online；用 unpause 失败但实际 running、硬阻塞 dead、动作超时、无缓存 miss 的测试验证返回 online/failed/unknown/miss 各自正确，动作结果不冒充运行态。
- [x] 5.2 改造 WSS `build_status_snapshot` 的容器状态条目：不新增 WSS 必需字段/状态值，条目增加可选 `last_action`（ref/action/phase/error_reason），新 Node 无记录时显式输出 null；动作失败不发送容器 status=failed，未知发送 unknown+status_source/unknown_since，全局 collect_error 形状不变。用旧 Ctrl 状态映射夹具、帧快照和 JSON 序列化测试验证 last_action:null 与 failed+online 不被丢弃且旧消费方可收敛。
- [x] 5.3 实现冷启动：生成新 node_epoch，清空动作序号、观察票基线、ActionRecord、pending、ready_identity 和历史 OOM 结论；用冷启动遇到 running/created/exited/dead 及重启前 failed pending 的测试验证 running 先进门禁、created/dead 硬阻塞、exited 为 offline、旧 pending/旧 ready 不复活、last_action 为 null 且旧 ref epoch 失效。
- [x] 5.4 增加 ActionRef/LastAction Pydantic 模型及响应字段：`ContainerOperationAcceptedResponse` 与 `CreateContainerResponse` 增加可选 `action_ref`，`ContainerStatusResponse` 增加可选 `last_action`；字段使用 node_epoch:str、generation:int>=0、seq:int>=0、phase 枚举、error_reason:str|null。用模型构造、API 端点实际响应、response_model 序列化测试验证字段类型、缺省、null 与旧客户端缺失兼容，且 Pydantic response 不会丢弃字段。
- [x] 5.5 实现 latest last_action 状态机与有界记录：同 ref 终态不可回退，旧 ref/晚到 finish 不覆盖新 ref，unconfirmed/timed_out 非终结且可后续终结，generation 换代将未终结动作置 superseded 并保留 ref，Node 重启/删除清空；读面运行态与 last_action 在同一锁原子投影。用旧 ref 晚到、同 ref 终态后 accepted、换代、重启、连续动作有界性测试验证。

## 6. 受控交错与旧 Ctrl 回归

- [x] 6.1 建立可注入屏障的并发测试夹具，在受理、action_ref 分配、观察票签发、动作队列取出、Docker 调用前后、列表枚举、逐容器 stats、reload、响应延迟返回、事件投递、HTTP ACK 返回、WSS 快照构造和删除队列取出处设置 barrier；用测试自身的交错日志验证每个屏障都能稳定复现，不靠 sleep 猜测时序。
- [x] 6.2 用 2026-10-17 Sylvan 时间线做受控回放：19:33:16 首次 unpause 确认 online → 慢速对账旧快照 → 19:33:48 第二次 unpause 遇 `is not paused` → 底层已 online；断言读面不出现永久 failed、重复 unpause 为幂等确认、旧 stats/list 不回写 paused。
- [x] 6.3 编写随机交错/属性测试：动作序号单调、旧 finish 不改运行态、观察票 read_seq 不回退、旧读取延迟返回/后发先到不覆盖、旧代晚到观察不触发二次换代、慢列表旧对象不再成为当前身份、create 首次绑定不取消自己、硬阻塞原因属于允许集合、soft failure/unknown 不产生永久 failed、普通 metrics 不改变代际/序号；用固定种子和失败最小化输出验证不变量。
- [x] 6.4 用既有 WSS 帧和旧 Ctrl 状态映射夹具做消费回放，覆盖 online/unknown/paused/offline/failed 及 DB 复位后下一次快照；验证 `unpause_failed` 不再被回写、旧 Ctrl 完全忽略 action_ref/last_action 仍可恢复、选择使用可选契约的独立变更在旧 Node 缺字段时自行按方向/自身 timeout 降级。不修改 Ctrl 仓库文件。
- [x] 6.5 在隔离本地 Docker 环境做可选集成测试：真实 unpause running/not paused 幂等、offline/dead 不成功、stats 慢时 reload 后状态正确、同 Docker ID 外部重启 Changed StartedAt 后重新门禁、WSS 快照语义；禁止使用 SSH/生产主机，无法提供 Docker 时明确标记 skipped 而不是伪造通过。（本地 Docker Desktop 上 4 项真实通过；真实 dead 无法在不破坏 storage/宿主挂载的前提下安全制造，保留显式 skip 并由 `test_pause_unpause_offline_dead_never_report_success` 覆盖映射，未宣称真实 dead 集成通过。）
- [x] 6.6 做动作引用与独立消费方终结的受控交错测试：HTTP ACK 先到/WSS 终结先到、早到终结按 ref 暂存、精确 ref+方向匹配才结束自身过渡、旧/未知 ref 和缺字段只能按该消费方自身 timeout 降级、Node 不因 ACK 缺失强发 failed；覆盖 pause 软失败 online+last_action.failed、online 不被当 pause_failed、dead 硬故障仍 failed。用真实 WSS/HTTP 帧回放验收，不修改 Ctrl 文件。
- [x] 6.7 做动作契约矩阵测试：重复 unpause 返回新 ref + online + idempotent_confirmed；pause 失败仍 online + last_action.failed；相同 ref 终态后旧 accepted 不回退；旧 ref 晚到不覆盖新 ref；last_action 与运行态原子一致；Node 重启 last_action=null 且旧 epoch 失效；mixed-version（新 Node/旧 Ctrl、旧 Node/选择使用可选契约的独立变更、新 Node/该独立变更）按契约降级。用 Pydantic dump、WSS JSON 帧和受控交错日志验收。

## 7. 部署边界与联合验收

- [x] 7.1 核对并记录部署前置：Ctrl `guard-container-vanish-deletion` 已落地、Node `prevent-false-container-vanished` 的共享代际/观察边界/事件归一化先落地，且事件运行态只经统一观察入口（不得新增直接按事件文本写运行态的路径）；用发布清单和依赖检查验证本变更不会单独部署在旧代际实现或双写事件路径上。（本地核对：Ctrl HEAD `d2ba7be` 的 guard 变更 6/6 且 `openspec validate --strict` 通过，`test_cross_repo_protocol_replay.py` 隔离 SQLite 回放 13 passed；Node 仅 `_meta[].generation` 一套代际，事件只经 `_apply_event → issue_observation → _inspect_fact → publish_observed`。本项是发布清单核对，未部署、未上线；跨仓联合验收见 prevent 3.1。）
- [x] 7.2 做 prevent + gate 联合受控交错验收：创建 pending 与旧 delete、create 首次绑定与不同 ID deferred、同名 ID 更换、慢速 list/stats、旧读取延迟返回、start/create sshd 门禁、old failed pending 与 cold start；验证本变更不另造事件解析、事件只触发新鲜 inspect、不绕过门禁、不把 prevent 删除候选发到新代。
- [x] 7.3 明确并验证 Ctrl 边界：Node 不修改 Ctrl 变更；长期资格静态守卫不依赖 action_ref、动作绑定或新增数据库字段；旧 Ctrl 可忽略可选字段并继续按既有运行态收敛。软失败不写容器 status=failed，但可通过 last_action.failed 诊断；不新增必需 wire 字段。
- [x] 7.4 验证滚动/回滚：记录 Node 版本、node_epoch、动作序号、观察票和代际为进程内存状态、无 DB/WSS 迁移；用回滚演练验证重启后 node_epoch 更换、last_action=null、旧 ref 失效、冷启动重建，旧 Ctrl 仍按既有状态语义工作，回滚不单独撤回 Ctrl 消失防护或 prevent 基础。
- [x] 7.5 验证 verify-bind 路径边界独立：本变更不改变其业务路径校正及磁盘测量契约，不把 action_ref 的 node_epoch/对象 generation/动作 seq 映射成磁盘业务字段，不要求 Ctrl 新增磁盘列。按 verify-bind 当前提案验收，不预设采样会话或诊断持久化结构；不修改 verify-bind 文件。runtime DockerID/ready_identity/action_ref/对象防旧写保持。

## Workflow follow-up

- 本阶段仅完成本地 OpenSpec 提案；实现、部署、SSH、生产操作和提交 push 均需后续明确授权。
- 实现完成并通过受控交错、旧 Ctrl 回放和联合验收后，再按仓库流程归档本变更。
