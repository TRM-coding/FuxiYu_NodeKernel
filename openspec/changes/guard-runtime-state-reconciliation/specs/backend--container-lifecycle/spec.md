# Spec Delta

## MODIFIED Requirements

### Requirement: ContainerOperationAcceptedResponse 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。

字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：success、container_name 和过渡 container_status 描述已受理操作，最终结果由状态快照确认。新增可选 `action_ref: ActionRef | None`；新 Node 对成功受理的 start/stop/restart/pause/unpause 响应 MUST 输出该引用，旧 Node 可以缺失。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例

#### Scenario: 动作受理返回引用

- **WHEN** 动作已受理并返回过渡 container_status
- **THEN** 响应包含本进程分配、与该动作记录一致的 `action_ref`；旧客户端可忽略，旧 Node 缺字段时消费方按缺失处理

### Requirement: ContainerStatusResponse 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。

字段与成员见文末同名数据附录。

系统 SHALL 保持以下已实现的职责：读运行态、动作诊断及运行指标；动作失败保留独立的 action 诊断，硬阻塞失败才保留 error_reason/failed_reason/failed_detail；cache_updated_at 为缓存时间。新增可选 `last_action: LastAction | None`；新 Node 无本地动作记录时 MUST 显式输出 null，旧 Node 可以缺失。

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例

#### Scenario: 运行态与动作诊断同响应

- **WHEN** pause 软失败但容器实际 running
- **THEN** 响应同时返回 online 与 `last_action.phase=failed`，last_action.failed 不被解释为容器 failed

## ADDED Requirements

### Requirement: 动作受理与完成确认分离

Node SHALL 将动作 API 的 `success=1` 与过渡 `container_status` 仅解释为“已受理”，MUST NOT 据此宣告动作成功或最终运行态。最终确认 MUST 来自新鲜 Docker 实态和既有就绪门禁；动作结果与运行态 SHALL 分别记录，动作失败不得替代或永久覆盖真实运行态。

#### Scenario: 受理后由实态确认

- **WHEN** Node 已返回 unpause 受理响应，随后 Docker 显示容器 running 且 not paused
- **THEN** 该动作可被确认成功，运行态按既有语义收敛为 online，而不是仅凭 HTTP 受理响应直接宣告成功

#### Scenario: start 受理但就绪门禁未通过

- **WHEN** start 的 Docker 调用返回成功，但 sshd 就绪探测尚未通过
- **THEN** 运行态保持既有 starting/ready_check 门禁，不得因 Docker running 或 API 受理而直接变为 online

#### Scenario: 动作失败但实际仍在运行

- **WHEN** 动作结果被记录为失败或未确认，而新鲜 Docker inspect 显示容器 running 且 not paused
- **THEN** 运行态按既有就绪证明报告 online 或符合门禁的起始态，动作失败仅保留在独立诊断/日志中，不形成永久 failed

### Requirement: 统一动作序号与旧写抑制

create/start/stop/restart/pause/unpause SHALL 在受理响应前分配每容器单调动作序号并记录本地代际。所有状态观察 MUST 在发起 Docker inspect/reload 前分配每名称单调 observation ticket（generation/action_seq/read_seq）；完成、事件回填和对账回填 MUST 携带该票。只有票的 generation/action_seq 仍为当前且 read_seq 新于已发布观察时才能写运行态；MUST NOT 以 inspect 完成时间、响应到达顺序或事件接收序号判定事实先后。旧完成/旧观察只记诊断；慢速 list/stats 不直接回写；普通指标不抬动作序号/代际。

#### Scenario: 旧动作完成晚于新动作受理

- **WHEN** 动作序号 N 的 Docker 调用尚未结束，同一容器已受理动作序号 N+1
- **THEN** 序号 N 的完成结果被记录为被取代，不能清除或覆盖序号 N+1 的过渡态与最终状态；旧动作后置观察票 MUST 使用其原受理序号，MUST NOT 从当前值重取

#### Scenario: 慢速对账在 unpause 后回写旧快照

- **WHEN** 对账在 unpause 前取得 Docker 列表或容器对象，逐容器采集耗时后动作已确认 online
- **THEN** 对账在 stats 后按名称新鲜解析并取得观察票，发布时复核票与新鲜实态；旧对象不得把 online 覆盖回 paused，也不得把旧 Docker ID 当当前身份

#### Scenario: 旧列表对象在换名后返回

- **WHEN** 慢速 stats 期间的旧对象属于 Docker ID A，而当前名称已解析到 Docker ID B
- **THEN** Node 不得直接 reload 旧对象 A 并把 A 当当前身份；只有按名称新鲜解析到 B 才能驱动更换，旧对象只作指标/诊断

#### Scenario: 旧读取延迟返回

- **WHEN** 同一代际、同一动作序号下，观察 R1 先取得旧事实但响应延迟；R2 后发起、先返回新事实并发布；R1 随后才返回
- **THEN** R1 的读取前 read_seq 小于已发布的 R2，被拒绝；完成更晚不赋予覆盖资格，也不把响应时间当事实时序

#### Scenario: 后发观察先完成

- **WHEN** 同一代际、同一动作序号下，R2 在 R1 之后取得观察票并先完成发布，R1 后完成
- **THEN** 发布 CAS 以 read_seq 拒绝旧票，不能仅凭线程完成顺序或后到响应接受写入

#### Scenario: 迟到事件不回滚新状态

- **WHEN** 新动作已确认 online 后，才收到一个较早发生或较晚送达的 paused 事件
- **THEN** Node 不以事件时间/接收顺序直接回写，而是先取观察票再触发新鲜 Docker inspect；只有当前实态为 paused 时才收敛为 paused

#### Scenario: 普通指标更新不抬代际

- **WHEN** 对账只更新同一容器的 runtime_metrics，容器对象和动作序号均未变化
- **THEN** 动作序号与本地代际保持不变，指标写入不得使后续旧状态观察获得新的写入资格

### Requirement: 共享本地代际与同名对象更换

Node SHALL 复用 `prevent-false-container-vanished` 的本地容器代际与观察边界，MUST NOT 另建第二套代际。只有通过 generation/action_seq/read_seq 校验的当前代观察 MAY 驱动同名 Docker ID 更换；旧代晚到观察 MUST 在身份比较前被拒绝，MUST NOT 再次推进代际或取消新 pending。首次为当前 create 绑定 `docker_id` MUST NOT 被视为更换；create pending 期间其他观察 MUST NOT 抢先绑定或取消 create。该代际仅限本进程/缓存，MUST NOT 被解释为 Q70 的跨进程端到端身份。

#### Scenario: 有效当前观察驱动同名更换

- **WHEN** 某名称当前记录属于 Docker ID A，一个当前代、当前动作序号且 read_seq 有效的观察返回同名 Docker ID B，且没有 create pending 拥有该名称
- **THEN** 该名称进入新代际，旧代的动作完成、对账对象和删除候选失效，B 按新对象重新执行运行态分类与就绪门禁

#### Scenario: 旧代观察晚到看到新对象

- **WHEN** 旧代 A 的观察延迟返回并看到同名 Docker ID B，而当前已经是 B 代
- **THEN** 该观察的 generation 票先校验失败，不推进 B→C 代、不取消 B 的 pending/动作，也不把 B 当替换

#### Scenario: 当前 create 首次绑定 Docker ID

- **WHEN** 当前 create pending 尚无 `docker_id`，create 自身的确认观察首次看到其 Docker ID
- **THEN** Node 绑定该 ID，不推进代际、不取消该 create；后续按新对象分类并进入就绪门禁

#### Scenario: create pending 期间不同 ID 推迟

- **WHEN** 当前 create pending 已有绑定 ID，另一个观察看到不同的同名 Docker ID
- **THEN** Node 先记 `identity_change_deferred`，不把它当更换并取消 create；create 结束后再由有效新鲜观察处理

#### Scenario: 创建 pending 与旧删除候选交错

- **WHEN** 同名新建已在受理阶段登记 pending，而旧代删除候选仍在队列中
- **THEN** 旧候选被撤销或拒绝发送，不能删除新代缓存，也不能让旧代完成覆盖新代过渡态

#### Scenario: 磁盘路径与测量诊断独立

- **WHEN** pause/unpause、start/stop/restart 或容器对象代际变化
- **THEN** 容器对象代际按本变更处理；verify-bind 的 configured_mount_path/bind_mount_path/mount_path_status/mount_path_observed_at、measurement_status/measured_at/measurement_mount_path 与 collector_epoch/observation_seq 采样会话不被推进、重置或重新解释，仍按其路径/测量契约判定

#### Scenario: 不宣称跨进程代际

- **WHEN** Node 已发送只含名称的既有 `delete` 帧，Ctrl 随后处理同名新建
- **THEN** 本变更不声称 Node 本地代际可为 Ctrl 提供严格跨进程隔离，该剩余边界仍属于 Q70

### Requirement: pause 与 unpause 的新鲜实态确认

pause/unpause MUST 在调用前后以新鲜 Docker inspect 核对实际状态；对 running 且 not paused 的容器再次 unpause SHALL 视为幂等确认，不产生失败。pause 对已 paused 容器同样幂等。offline、dead、NotFound MUST NOT 被视为 unpause 成功；其他 Docker/网络错误 MUST 保留并分类，不得吞成成功，也不得仅凭动作返回写 online。

#### Scenario: 对已 running 容器重复 unpause

- **WHEN** Ctrl 第二次发送 unpause，而新鲜 inspect 显示容器 running、paused=false
- **THEN** Node 记录幂等确认成功，不再产生 `unpause_failed` 或 failed pending；运行态按同一进程的就绪证明保持 online，未通过门的则保持 ready_check/starting，不能仅凭 Docker running 绕过门禁

#### Scenario: unpause 遇到 offline 或 dead

- **WHEN** unpause 请求到达时新鲜 inspect 显示容器 exited、offline 或 dead
- **THEN** 该动作不得报告成功或写 online；运行态按实际显示 offline 或硬阻塞 failed，动作结果单独记录

#### Scenario: 其他 Docker 错误不得吞掉

- **WHEN** Docker unpause 返回权限、daemon、超时或其他非“not paused”错误
- **THEN** 错误被完整记录并分类，随后以新鲜 inspect 决定运行态；无法判定时报告 unknown，而不是成功或永久 failed

#### Scenario: 对已 paused 容器重复 pause

- **WHEN** pause 请求到达时新鲜 inspect 显示容器已 paused
- **THEN** Node 记录幂等确认成功并保持 paused，不制造失败

### Requirement: 就绪证明绑定运行进程

Node SHALL 将 ready_verified 绑定到 Docker 对象与运行进程身份（至少 Docker ID + StartedAt），MUST NOT 只按名称或对象代际复用。显式 restart、start 产生新运行进程（StartedAt 变化）、同 Docker ID 的外部重启、新对象或冷启动 MUST 使旧就绪证明失效并重新进入既有就绪门禁；start 对已 running 且同一进程、已有有效 ready_identity 的幂等情形 MAY 复用证明但仍不得绕过门禁；pause MUST 保留同一进程的就绪证明；无法取得 StartedAt 时 MUST NOT 复用 ready_verified。

#### Scenario: pause 保留同一进程就绪证明

- **WHEN** 容器已 ready 且被 pause，随后 unpause 后 Docker ID 与 StartedAt 均不变
- **THEN** 可复用同一进程的 ready 证明恢复 online，不因 pause 而重新执行 sshd 就绪门禁

#### Scenario: restart 后必须重新验证

- **WHEN** restart 成功，同一 Docker ID 但 StartedAt 已变成新的运行进程
- **THEN** 旧 ready_verified 失效，运行态进入 ready_check，只有 sshd 门禁通过后才 online

#### Scenario: 同 Docker ID 外部重启

- **WHEN** 外部重启导致 Docker ID 不变但 StartedAt 变化
- **THEN** 与 restart 同等地使旧就绪证明失效，不得复用旧 ready 直接 online

#### Scenario: 缺少 StartedAt

- **WHEN** 新鲜实态无法取得 StartedAt，不能证明还是同一运行进程
- **THEN** Node 不得复用 ready_verified，必须先通过既有就绪门禁

### Requirement: 运行态与动作结果分离

运行态 SHALL 只由新鲜 Docker 实态和既有就绪门禁决定；动作结果 SHALL 独立记录为受理、成功、幂等确认、失败、被取代或未确认。动作失败 MUST 保留审计/日志但不永久置容器 failed。exited 是 offline；历史 OOM 在已恢复 running 后 MUST NOT 永久 sticky；动作 TTL 只停止过渡态遮挡，MUST NOT 清除硬阻塞或把真实 failed 按 TTL 抹掉。

#### Scenario: unpause 动作失败但容器实际 online

- **WHEN** 重复 unpause 因 Docker 返回 `is not paused` 被记录为动作失败，而新鲜 inspect 为 running/not paused
- **THEN** 读面返回 online 或按就绪门禁返回起始态，动作失败只进入独立诊断，不形成永久 failed

#### Scenario: 正常退出

- **WHEN** 当前 Docker 实态为 exited/stopped，且不存在硬阻塞故障
- **THEN** 运行态为 offline，不因动作失败痕迹或历史 OOM 标记变成永久 failed

#### Scenario: 历史 OOM 后恢复运行

- **WHEN** 容器曾在历史退出中记录 OOM，但当前新鲜实态为 running/not paused
- **THEN** 运行态按 running 和就绪门禁收敛，历史 OOM 仅保留为诊断，不得永久 sticky

#### Scenario: 动作 TTL 不得清除硬阻塞

- **WHEN** 一个 dead 或 created 半成品硬阻塞已形成，超过原动作 TTL
- **THEN** 硬阻塞保持，直到新鲜实态证明条件消失且门禁通过，或该名称进入新代际/被删除

### Requirement: 硬阻塞边界与恢复

只有两类情况 MAY 形成运行态 failed：既有 start/create 就绪验证门禁的既有终态阻塞（如 sshd 未安装、created 半成品保护），以及当前 Docker 实态证明的 dead 或其他明确真实故障。门禁暂时未通过 MUST 保持 starting/ready_check，MUST NOT 仅因暂未就绪就形成 failed。其余动作异常、采集未知和正常 exited MUST NOT 形成永久 failed。硬阻塞 MUST 在新鲜实态证明条件消失且就绪门禁通过，或该名称进入新代际/删除后恢复；MUST NOT 由 TTL 自动清除。

#### Scenario: created 半成品

- **WHEN** 冷启动或创建结束后 Docker 对象仍为 created，且没有正在进行的创建动作可以推进它
- **THEN** 运行态按既有保护形成硬阻塞 failed，普通对账不得将其直接复活为 online

#### Scenario: sshd 暂未就绪保持门禁

- **WHEN** start/create 后 Docker 已 running，但 sshd 就绪探测暂时未通过且既有门禁仍可重试
- **THEN** 运行态保持 starting/ready_check，不形成 failed；只有既有门禁的终态判定或当前 Docker 实态证明的故障才按硬阻塞处理

#### Scenario: sshd 未安装或门禁终态不可用

- **WHEN** 既有 start/create 就绪探测确认 sshd 未安装，或既有门禁明确判定不可用
- **THEN** 运行态形成硬阻塞 failed 并保留原因，直到修复后重新通过就绪门禁或进入新代际

#### Scenario: 当前 Docker 证明 dead

- **WHEN** 新鲜 Docker 实态为 dead，或存在明确等价真实故障
- **THEN** 运行态可形成硬阻塞 failed；普通事件、旧快照或动作 TTL 不能将其静默清除

#### Scenario: 硬阻塞在新实态下恢复

- **WHEN** 该名称的 Docker 对象已被删除重建，或新鲜实态证明故障消失且既有就绪门禁通过
- **THEN** 硬阻塞按新代际/新实态解除，恢复后的状态仍须经过对应门禁，不能凭旧动作结果直接 online

### Requirement: 未知与采集错误保留最后已知

Docker 列表级采集失败 SHALL 报告 `collect_error`；单容器 inspect/stats 不可判定时 SHALL 保留最后已知事实并在读面报告 unknown，同时给出 status_source/unknown_since，MUST NOT 强行 online 或 failed。错误 SHALL 独立记录；下一次成功观察或事件触发的新鲜 inspect 恢复运行态。

#### Scenario: Docker 列表采集失败

- **WHEN** 全量 Docker 列表不可取得，无法判定任何容器当前状态
- **THEN** Node 保留最后已知缓存，并以既有 collect_error 形状报告采集失败，不发送伪正常空表或强行 online

#### Scenario: 单容器观测不可判定

- **WHEN** 列表成功但某容器的 inspect 或 stats 抛出不可判定异常
- **THEN** 该容器读面报告 unknown 和诊断来源，最后已知事实保留供恢复，不覆盖为 online 或永久 failed

#### Scenario: 未知后恢复

- **WHEN** 后续 observe 或事件触发的新鲜 inspect 成功取得当前实态
- **THEN** 运行态按新实态收敛并清除 unknown 标记，不需要重启 Node

### Requirement: 冷启动运行态重建

Node 重启后 MUST 以空的动作序号、观察票基线、动作结果状态和 ready_identity 冷启动，MUST NOT 继承旧进程的 pending、就绪证明或历史 OOM 结论。冷启动 SHALL 从当前 Docker 实态重建：running 先进入既有就绪门禁，created 半成品保持硬阻塞，exited 为 offline，dead 为硬阻塞；旧 failed pending 不得因重启前状态而复活。

#### Scenario: 冷启动遇到 running

- **WHEN** Node 冷启动枚举到 running 且 not paused 的容器，缓存中没有旧条目与 ready_identity
- **THEN** 容器先进入既有 ready_check/starting 门禁，sshd 确认后才 online，不直接凭 Docker running 宣告 online

#### Scenario: 冷启动遇到 exited 或 dead

- **WHEN** Node 冷启动枚举到 exited 或 dead 容器
- **THEN** exited 映射为 offline，dead 按当前 Docker 实态形成硬阻塞 failed；两者都不继承重启前的动作失败状态

#### Scenario: 旧 failed pending 不复活

- **WHEN** Node 重启前存在 unpause_failed 或其他动作失败 pending，重启后容器实际 running/not paused
- **THEN** 新进程不恢复旧 pending 或旧 ready 证明，状态按当前实态和就绪门禁收敛为 online 或对应起始态

### Requirement: 动作引用 action_ref 契约

Node SHALL 在 create/start/stop/restart/pause/unpause 受理时返回可选 action_ref={node_epoch,generation,seq}，并在返回前分配；node_epoch MUST 为每 Node 进程启动生成一次的 UUID 字符串，generation MUST 复用 prevent 对象代际且为非负 int，seq MUST 为该代际动作序号且为非负 int。action_ref 只关联单 Node 动作，MUST NOT 用于 Q70 跨进程删除授权，MUST NOT 与 verify-bind 的磁盘路径诊断/采样会话/测量路径混用。旧 Node 可缺失，消费方 MUST 兼容。

#### Scenario: 受理前分配并保持一致

- **WHEN** 动作成功受理并返回过渡状态
- **THEN** HTTP `action_ref` 在响应前已分配，并与后续 HTTP/WSS `last_action.ref` 的 node_epoch/generation/seq 完全一致

#### Scenario: create 使用对象代际

- **WHEN** create 受理并推进对象代际
- **THEN** 返回的 action_ref.generation 使用该 create 的新对象代际，seq 为同代动作序号，不与 verify-bind 磁盘路径诊断/采样会话混用

#### Scenario: Node 重启 epoch 变化

- **WHEN** Node 进程重启
- **THEN** 新 node_epoch 与旧进程不同，旧 action_ref 不再匹配；本进程无动作记录时 last_action 为 null

#### Scenario: 旧 Node 缺字段

- **WHEN** 旧 Node 未返回 action_ref/last_action
- **THEN** 新消费方按缺失降级，不据此假定成功或失败；新 Node 不得要求旧 Node 提供该字段

#### Scenario: 不用于跨进程授权

- **WHEN** 消费方收到 action_ref
- **THEN** 只能用于单 Node 的 pause/unpause 等动作关联，不能作为 Q70 删除授权、跨进程对象身份或 verify-bind 的磁盘路径/测量诊断

### Requirement: last_action 诊断与终结语义

Node SHALL 在 HTTP 状态与 WSS 容器条目输出可选 last_action={ref,action,phase,error_reason}（action 为当前六种本地动作名或兼容字符串，error_reason 为 string 或 null）；新 Node 无记录时 MUST 输出 null，旧 Node 可缺失。last_action MUST 只代表最新本地受理动作；confirmed/idempotent_confirmed/failed/superseded 为终结，旧 accepted/unconfirmed/timed_out MUST NOT 覆盖终结；unconfirmed/timed_out 不是完成证明。运行态与 last_action MUST 原子一致；last_action.failed MUST NOT 令运行态 failed；记录 MUST 有界并保留终结日志。

#### Scenario: 无动作记录

- **WHEN** 新 Node 冷启动后尚未受理任何动作
- **THEN** HTTP 状态与 WSS 容器条目显式包含 `last_action: null`，不能被序列化省略；旧 Node 可缺字段

#### Scenario: 重复 unpause 的 online 与幂等终结

- **WHEN** 对真实 running/not paused 容器再次 unpause
- **THEN** 返回新 action_ref；运行态保持 online，last_action 为该 ref 的 idempotent_confirmed，不产生 failed 或 unpause_failed

#### Scenario: pause 软失败但实际 online

- **WHEN** pause 软失败而新鲜实态仍 running
- **THEN** 读面原子返回 online 与 `last_action.phase=failed`（error_reason 可诊断），last_action.failed 不改变容器运行态

#### Scenario: 旧 ref 晚到

- **WHEN** 较新 action_ref 已受理/终结，旧 ref 的 finish 或旧 accepted 晚到
- **THEN** 旧 ref 不得覆盖最新 last_action；同一 ref 已终结后旧 accepted/unconfirmed/timed_out 不得回退

#### Scenario: 对象换代保留终结诊断

- **WHEN** 同名对象换代时旧代仍有未终结的 latest action
- **THEN** 该动作 phase 置 superseded 并保留旧 ref 作为终结诊断，供旧绑定精确匹配；新代动作使用新 ref，旧 ref 不授权新代

#### Scenario: 未确认不是完成

- **WHEN** last_action.phase 为 accepted/unconfirmed/timed_out
- **THEN** 消费方不得据此结束长期过渡、放行冻结或把容器置 failed；只有后续同 ref 终结，或实际 paused/offline 用于 pause 确认时才可收敛；unconfirmed/timed_out 本身不是完成或失败证明

#### Scenario: 记录有界

- **WHEN** 同一容器连续受理大量动作
- **THEN** 读面只保留最新 last_action，历史终结进入有界诊断/日志，不随动作数无界增长
