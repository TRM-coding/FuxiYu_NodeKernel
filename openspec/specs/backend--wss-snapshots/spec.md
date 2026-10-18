# WSS 快照

## Purpose

共享缓存的状态/SSH/磁盘/系统事实经四 topic 批次推送，删除为单独增量事件。本文件是 chester-next 33672c4edd96 在 2026-10-11 的代码逆向基线，按能力组织相关类型而非每个 class 单独建文件。完整字段、继承与兼容定义保留在下列 Requirements 中；跨能力使用以公共类型及源文件为准，已知问题集中于 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)。

## Requirements

### Requirement: delete-event 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：`type='delete'`；`container_name` 为经 Docker 存在性确认后消失的容器名称；从状态缓存的删除队列取出后在快照批次之前推送；这是增量事件，不替代全量状态对账。入队后若同名新代开始创建或重新出现，Node MUST 丢弃旧候选，不得以旧代消失事实报告新代删除。Docker 采集失败或尚处创建过渡态时 MUST NOT 发送删除帧。

#### Scenario: 状态缓存报告某容器删除

- **WHEN** 状态缓存确认某个已知代际容器在 Docker 中消失，且发送前该候选未失效
- **THEN** 先发送该 `container_name` 的 `delete` 事件，再发送本轮快照批次

#### Scenario: 排队后同名新建

- **WHEN** 某名称的删除候选已排队，但同名新代在发送前开始创建或重新出现在 Docker 中
- **THEN** Node 丢弃旧候选，本轮不发送该名称的 `delete` 事件

#### Scenario: Docker 采集不可判定

- **WHEN** 本轮列表或单容器核实失败，无法确认容器是否消失
- **THEN** Node 发送采集错误状态，不发送该容器的 `delete` 事件

来源：[network/wss.py](../../../network/wss.py)。

### Requirement: snapshot-batch 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：type='snapshot_batch'；node_uid 为 NodeIdentity.uid；payload 依次包含 container_status、last_ssh、disk_usage、sys_snapshot 四帧；Ctrl 主动连接 Node /ws/ctrl，Node 仅推送事实。

#### Scenario: 建立有效身份的 WSS 链接

- **WHEN** 建立有效身份的 WSS 链接
- **THEN** 在一批中提供四个 topic 的快照，使用持久化 node_uid，不要求 Node 配置 Ctrl 目标地址

来源：[network/wss.py](../../../network/wss.py)。

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

来源：[network/wss.py](../../../network/wss.py)。

### Requirement: snapshot-disk-usage 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：type='snapshot'；topic='disk_usage'；payload 为 {machine_disk, containers:{name:usage}}；容器用量包含既有字节/路径/来源字段、`mount_path_status` 与真实 `measured_at`。MUST NOT 携带目录对象/PID/identity 门禁字段或新增 epoch/seq、measurement_*、configured_mount_path 等协议字段（详见「路径控制与测量字段作用域」）。`mount_path_status` 只是路径控制信号，不是 total 有效性或 Ctrl 业务门禁；unresolved 不使同路径有效测量失败，重复推送/读取不刷新 measured_at；HTTP 与 WSS 共用同一模型。

#### Scenario: 读取磁盘快照

- **WHEN** 读取磁盘快照
- **THEN** 返回缓存、业务路径、路径控制状态和真实测量时间，不把缓存缺失、正在测量和实际零用量混为一谈

#### Scenario: 路径 unresolved 但同路径测量有效

- **WHEN** mount_path_status=unresolved，而既有业务 bind_mount_path 未变、测量成功且 measured_at 为真实测量时间
- **THEN** total_bytes 保持有效；路径诊断不阻断业务，也不改写为测量失败

#### Scenario: 路径变更后的旧样本

- **WHEN** 业务 bind_mount_path 已从 A 改为 B，而缓存中用量的 bind 字节仍来自 A
- **THEN** 该旧样本不得作为 B 的 total，必须按 B 重新测量；快照可显示旧值仅作诊断

#### Scenario: 旧协议缺少真实测量时间

- **WHEN** 旧 Node 的 usage 缺少 measured_at
- **THEN** 消费方按既有接收时间兼容或未验证处理，不能推断缺少目录身份，也不能把接收时间补齐为真实测量时间

#### Scenario: 无 bind 与 overlay-only

- **WHEN** Docker 成功确认无 `/root` bind，且 overlay 测量有效
- **THEN** bind_mount_path=null、mount_path_status=no_bind，total 可按明确 no_bind 的 overlay 规则有效；Ctrl 接收端清空当前活跃业务 bind 路径，不能保留旧路径再判同路径；异常不得被当成 no_bind

#### Scenario: unresolved 不清空路径

- **WHEN** 路径核对为 unresolved/not_running，或 Docker inspect/Source 诊断不可读
- **THEN** 保留已有 bind_mount_path；只有明确 no_bind 才置空

#### Scenario: 相同样本被多次推送

- **WHEN** WSS 在一个测量周期内多次推送同一结果
- **THEN** 保持该结果真实的 measured_at，新的发送/接收时间不能把它变成新测量

来源：[network/wss.py](../../../network/wss.py)。

### Requirement: snapshot-last-ssh 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：type='snapshot'；topic='last_ssh'；payload 为 {container_name: {last_ssh_connect_time, updated_at}}；未采到或非运行态时间为 None，由 Ctrl 保留旧观测。updated_at 序列化为不带后缀的时间字符串。

#### Scenario: 某容器本轮没有真实 SSH 时间

- **WHEN** 某容器本轮没有真实 SSH 时间
- **THEN** last_ssh_connect_time 保持 None，不用当前采集时间冒充用户真实登录时间

来源：[network/wss.py](../../../network/wss.py)。

### Requirement: snapshot-static-hardware 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：静态 payload 包含 hostname/platform、cpu.cores、memory.total_gb、gpu 列表、disk.total_gb；disk.total_gb 取 bind_mount 所在分区容量；注册建档使用这个结构，不把动态使用百分比写成分配许可。

#### Scenario: Ctrl 首连获取硬件画像

- **WHEN** Ctrl 首连获取硬件画像
- **THEN** 返回缓存有效的静态硬件事实，缓存到期重新采集；CPU/内存许可由 Ctrl 管理策略另行确定

来源：[network/wss.py](../../../network/wss.py)。

### Requirement: snapshot-sys 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：type='snapshot'；topic='sys_snapshot'；payload 为 hostname/platform/cpu/memory/gpu/disk/collected_at；disk 分 bind_mount 和 docker_data 两个挂载点；collected_at 以 UTC 生成，无采集时 payload 可以为 None。

#### Scenario: 两个数据目录位于不同分区

- **WHEN** 两个数据目录位于不同分区
- **THEN** 分别返回 bind_mount 和 docker_data 分区容量、用量及路径；该显示数据不替代容器管理限额

来源：[network/wss.py](../../../network/wss.py)。

### Requirement: Ctrl 拨入链路端点与身份门禁 [network/wss.py]

Node SHALL 在既有 HTTPS 监听上以路径 `/ws/ctrl` 提供 Ctrl 拨入的 WebSocket 端点，复用同一张 Node 证书与同一套客户端证书校验；该端点 MUST NOT 要求新增监听端口或新增证书。Node MUST NOT 主动向 Ctrl 发起连接，也 MUST NOT 自行维护到 Ctrl 的重连循环——连接的生灭与重建由 Ctrl 侧承担。

本机身份牌未就绪时，端点 SHALL 关闭连接且不进入推送循环。连接查询参数携带的 `uid` 缺失或与本机持久化身份牌不一致时，端点 SHALL 在推送任何帧之前关闭连接。

#### Scenario: 复用既有端口与证书

- **WHEN** Node 以既有入口启动，且配置了 Ctrl 的 CA 信任文件
- **THEN** `/ws/ctrl` 与操作接口在同一监听、同一证书下同时可用，WSS 握手继承既有的客户端证书校验

#### Scenario: uid 不符则拒绝

- **WHEN** 连接未携带 `uid`，或携带的 `uid` 与本机身份牌不一致
- **THEN** Node 在推送任何帧之前关闭该连接

#### Scenario: 身份牌未就绪不推送

- **WHEN** 本机尚无身份牌
- **THEN** 端点关闭连接，不建立推送循环；等待 Ctrl 下发身份牌后重拨

#### Scenario: 无入站连接时不产生出站流量

- **WHEN** Node 启动后没有任何 Ctrl 连接
- **THEN** Node 不向任何 Ctrl 地址发起连接尝试

来源：[network/wss.py](../../../network/wss.py)、[run.py](../../../run.py)。

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

### Requirement: 路径控制与测量字段作用域

`bind_mount_path` SHALL 表示业务路径并由 Node 在确认后返回修正值；`mount_path_status` 为 resolved/unresolved/not_running/no_bind（缺省 unresolved），只用于消费方决定更新/保留/清空，不是业务门禁；`measured_at` 为合计真实测量时间，取 overlay/bind 完成时间中较早者。目录 dev/inode/PID MUST NOT 作为 HTTP/WSS 字段、长期资格/冻结/删除/清理门禁或测量有效性前置。HTTP 与 WSS 复用同一字段语义，`null` 字段不得被 response model/JSON 静默丢弃。`configured_mount_path`、`mount_path_observed_at` 只留在 Node 内部日志/调试，不进入线路。

#### Scenario: 路径控制字段缺失

- **WHEN** 旧 Node 缺 mount_path_status
- **THEN** 按 unresolved 处理；已有业务 bind_mount_path 仍可使用，不推断新的目录身份，也不改写已校正路径

#### Scenario: 测量字段缺失

- **WHEN** 旧 Node 缺 measured_at
- **THEN** 消费方按既有接收时间兼容或未验证处理；不推断目录身份，不把接收时间冒充真实测量时间

#### Scenario: HTTP 与 WSS 一致

- **WHEN** 同一用量分别经 HTTP 手动查询和 WSS 快照返回
- **THEN** bind_mount_path、mount_path_status、measured_at 和字节字段保持一致

#### Scenario: 路径纠正只体现为业务路径

- **WHEN** 消费方检查 WSS/HTTP usage 中的路径信息
- **THEN** 业务路径由 bind_mount_path 表达，路径修正/保留/清空由 mount_path_status 表达；不依赖目录对象编号、PID、configured_mount_path 或 observed_at

#### Scenario: 禁止新增测量协议字段

- **WHEN** 消费方检查 usage 的字段集合
- **THEN** 不存在 `disk_protocol_version`、`collector_epoch`、`observation_seq`、`measurement_status`、`measurement_mount_path` 或 `measurement_reason`；路径纠正不建立第二套测量状态/排序协议

## Source references

- [network/wss.py](../../../network/wss.py)
- [run.py](../../../run.py)
- [__init__.py](../../../__init__.py)
- [tests/](../../../tests/)：默认套件 331 passed, 1 skipped, 16 deselected, 24 subtests passed；Docker 分项：旧用例 10 passed + 1 skipped、本变更专项 4 passed + 1 skipped；未合并重跑全量 `-m docker`。
