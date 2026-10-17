# Design

## Context

现有 Node 状态缓存把运行态、动作过渡态和动作失败混在同一个读面：`begin_action` 登记 pending，`finish_action(failed)` 保留 failed pending，`get_state`/`list_states` 又让 pending 优先于运行缓存；对账在 `Docker.list` 之后逐个调用 `stats`，最后无条件 `update`，没有动作序号、观察时间或代际保护。事故中 19:33:16.945 的 `finish_action online` 是动作完成，不是 Docker 事件；19:33:31 的缓存回退 `paused` 与慢速对账旧快照吻合；19:33:48 对已 running 容器再次 unpause 得到 `is not paused`，被统一转成 False 并留下 failed pending；19:34:20 底层缓存已 online，但读面仍被 failed pending 覆盖。父代理 20:06:38 的 mTLS 只读结果仍为 `failed/unpause_failed`，Ctrl 单行复位在约 15 秒后被 WSS 快照回写覆盖，Node 重启后旧 pending 消失才持续 online。该证据把问题定位为通用的“旧动作/旧观察覆盖新状态”，而非 unpause 单点。

现有 `prevent-false-container-vanished` 已规划本地容器代际与观察边界，并修正 Docker 事件 `Action` 优先、`status` 兼容及 `exec_*` 噪声识别。本设计把动作序号、动作结果、运行态和观察发布都挂到同一代际与观察边界上，不另造第二套代际，也不改动其删除帧语义。当前约束是：只能使用既有线路状态和可选诊断字段，旧 Ctrl 必须能按 `online/offline/paused/starting/unknown/failed` 与 `status_source` 收敛；不依赖 Ctrl 新 DB 字段、新协议或 Q70 跨进程证明。

## Goals / Non-Goals

**Goals:**

- 让所有 create/start/stop/restart/pause/unpause 共享同一套受理序号、代际和发布 CAS，旧完成、旧对账快照、旧 stats 和迟到事件不能覆盖新状态。
- 让运行态与动作结果分离；动作失败仅保留审计/诊断，不再永久形成 `failed` 读面。
- 让 pause/unpause 以新鲜 Docker 实态做幂等确认；真实 running 不被重复 unpause 报成失败，offline/dead 不被报成成功。
- 仅保留既有 start/create 就绪门禁与当前 Docker 实态证明的硬阻塞；未知保留最后已知但对外报告 unknown/collect_error。
- 保持旧 Ctrl 兼容和无 DB/线路迁移，并给出与 prevent、门禁、Ctrl freeze 变更共享的部署边界。

**Non-Goals:**

- 不修复已经发生的 Ctrl DB 数据或生产容器状态，不执行 SSH、生产操作、代码实现、提交或 push。
- 不改变 Ctrl“普通 unpause accepted 后立即授宽限”的遗留行为，不在 Node 失败时强写 online，也不替 Ctrl 推断动作结果。
- 不新增 WSS 状态值、必需字段或 Ctrl DB 字段；不宣称 Q70 的跨进程同名代际隔离。
- 不把 `OOMKilled`、普通 `exited`、采集未知或动作异常泛化为永久 `failed`；也不把所有 `failed` 按 TTL 清除。

## Decisions

### 1. 状态模型：运行态、动作记录、观察记录分离

在 `ContainerStatusCache` 内部拆成三个层次，读面按明确优先级合成：

| 层 | 内容 | 生命周期/作用 |
| --- | --- | --- |
| RuntimeState | `status`、`status_source`、`unknown_since`、`last_known_status`、`ready_verified`、`ready_identity`（Docker ID + StartedAt）、`docker_id`、`generation`、有效时间 | 只表达当前可解释的运行态；`unknown` 时保留最后已知供恢复，但不把它冒充当前 |
| ActionRecord | `ref`（node_epoch/generation/seq）、`action`、`transition`、`phase`、`error_reason`、`accepted_at`、`finished_at`、`docker_id` | 只表达本次动作；有界保存最新记录并写结构化日志，不作为永久运行态；`last_action` 是它的读面投影 |
| Observation | `generation_at_issue`、`action_seq_at_issue`、`read_seq`、`source`、`from_create_confirmation`、DockerFact | 在发起 Docker 读取前取得的观察票；发布时先校验票，再允许身份比较或状态写入 |

`DockerFact` 至少包含 Docker ID、`Running/Paused/Restarting/Dead/OOMKilled/Status/ExitCode/Error`、`StartedAt`、读取来源与诊断用的完成时间。`OOMKilled`、`State.Error`、退出码只作为诊断字段，不单独决定永久状态。观察的完成时间 `read_ns` 只用于日志/测试，**不是发布资格或事实先后依据**；资格来自读取前签发的 `read_seq`。

读面优先级固定如下，避免动作结果再次盖住运行态：

1. 当前代际的硬阻塞运行态（`failed` 且原因属于允许集合）；
2. 既有就绪门禁（`ready_check` 的 starting/creating/restarting）；
3. 当前动作序号且未完成、未超读面 TTL 的受理过渡态（accepted/starting/stopping/...）；
4. 新鲜运行态或最后已知运行态；最后观察为不可判定时返回 `unknown`，不返回 `online` 或 `failed`；
5. 无任何事实时返回 miss/unknown。

动作完成后的结果 NEVER 直接成为读面 `status`。`failed_reason`/`failed_detail` 只在硬阻塞时进入读面；动作失败使用独立字段与可选 wire 诊断，运行态恢复不依赖该诊断，旧 Ctrl 可忽略。

硬阻塞原因只允许：既有 start/create 门禁的终态原因（至少包括 `sshd_not_installed`、既有门禁明确判定的不可用状态）、`created` 半成品保护，以及当前 Docker 实态证明的 `dead`。`restarting`、普通 `exited`、非零退出、历史 OOM、动作超时、采集异常都不是硬阻塞。其他明确的 Docker `State.Error` 先作为诊断，不直接扩成永久 failed；若它同时表现为 `dead`，按 `docker_dead` 处理。

动作结果分类固定为：`accepted`（已受理未完成）、`confirmed`（必要 Docker 效果已被新鲜实态确认）、`idempotent_confirmed`（目标运行态已存在）、`failed`（Docker 错误或状态矛盾）、`unconfirmed`（无法取得可判定实态）、`superseded`（旧序号）、`timed_out`（过渡读面过期，动作可能仍在途）。这些是动作结果，不是线路状态；`confirmed` 仍不豁免就绪门禁。软失败不自动重放已发出的状态变更（避免重复副作用），由新的显式动作重试；下一次 reconcile、事件触发的新鲜 inspect 或冷启动会自动恢复运行态。`unknown` 不阻塞新的显式动作，但 pause/unpause 在调用前 inspect 不可判定时不得盲发；硬阻塞只在条件消失且门禁通过，或名称进入新代际/被删除后解除，TTL 不触发自动重试。

### 2. 共享代际、动作序号与动作队列

复用 prevent 的每名称本地代际，不新增第二套 generation。代际在创建受理、构建开始、同名重建/忘记旧代，以及通过有效观察票确认同名 Docker ID 更换时推进。普通指标更新、普通动作成功和同一 Docker 对象的对账不推进代际。动作序号是同一代际内的每名称单调计数，在**受理响应前**分配；动作结束携带受理票，任何状态观察在发起 Docker 读取前另取 `{generation, action_seq, read_seq}` 观察票。`read_seq` 每名称在本进程内单调（跨代际也不回退，冷启动重置），用于拒绝晚到的旧读取。

每个名称使用一个串行动作队列，实际 Docker 调用按受理顺序执行。这样解决两个问题：旧 Docker 调用不会在新调用之后才产生副作用；旧 `finish` 即使晚到也不能写运行态。受理时更新 `current_action` 和可见过渡态；队列中的旧动作仍可执行其 Docker 意图，但其完成若已不是当前序号，只能记 `superseded` 审计，不能改读面。代际更换时取消旧代尚未执行的队列项，并拒绝旧代完成；已发出的 Docker 调用无法撤销，其晚到完成仍受序号/代际 CAS 拒绝。

选择串行队列而不是仅做“最后写入者获胜”的序号比较，因为后者只能保护缓存，不能保护 Docker 副作用顺序；也不使用全局锁，避免一个容器的长 build/stats 阻塞其他容器。

受理流程在锁内完成：校验名称 → 取当前代际 → `action_seq += 1` → 登记 pending/current_action → 入队 → 返回 accepted。create 的受理还要同步登记 prevent 要求的 `building`/`creating` 可见态并推进代际；不能等后台线程启动后才可见。后台线程启动失败也走动作失败收尾，不把容器永久置 failed。

### 3. 读取前观察票、发布 CAS 与新鲜 inspect

所有状态观察必须在发起 Docker inspect/reload **之前**，在缓存锁内取得 `Observation` 票：`{generation, action_seq, read_seq, source, from_create_confirmation}`。`read_seq` 是每名称在读取前分配的单调序号；它表达“读取请求的发起先后”，不是响应完成时间、事件接收序号或线程调度顺序。发布时**先校验票，再允许 Docker ID 比较、代际推进或运行态写入**：

```text
publish_runtime(ticket, fact):
  under cache lock:
    if ticket.generation != current.generation: reject stale generation
    if ticket.action_seq != current.action_seq: reject superseded action
    if ticket.read_seq <= last_applied_read_seq: reject stale read

    if fact.docker_id differs from state.docker_id:
        if state.docker_id is None:
            if active_create_for_current_generation() and not ticket.from_create_confirmation:
                record identity_bind_deferred; reject
            else:
                bind_runtime_docker_id(ticket, fact)  # 首次绑定，不推进代际/不取消 create
        elif active_create_for_current_generation():
            record identity_change_deferred; reject  # create 拥有该名称，先不换
        else:
            begin_new_generation_from_valid_ticket(ticket, fact)
            # 票已验证后才允许：推进对象代际、取消旧代动作/观察/删除候选；
            # 该观察作为新代 seed，记入新代 last_applied_read_seq
    classify fact -> runtime / hard block / unknown
    write runtime; last_applied_read_seq = ticket.read_seq
```

校验顺序是硬要求：旧代 A 的晚到观察即使看到同名 Docker ID B，也会先在 generation 校验失败，**不得**再次推进代际、取消 B 的动作/pending 或把 B 当替换。只有当前代、当前动作序号、且 `read_seq` 新于已发布观察的有效票，才可驱动身份更换。首次为当前 create 绑定 `docker_id` 时走 `bind_runtime_docker_id`，不推进代际、不取消自己的创建；create pending 期间，非 create 自身确认的观察不得抢先绑定或替换，已有绑定时不同 ID 先记 `identity_change_deferred`，等 create 结束后再由有效新鲜观察处理。

`fact.read_ns`（inspect 完成时间）只用于诊断。旧 Docker 请求可能早已取得旧事实、晚收到响应却得到更晚的完成时间；因此**不能**用完成时间判断新旧。读取前 `read_seq` + 发布 CAS 可拒绝这种晚到旧结果：后发起但先完成的观察若已发布，会抬高 `last_applied_read_seq`；早发起、晚返回的旧票即使完成更晚也不能覆盖。若早发起、晚返回的观察实际拿到了更新事实但票更旧，本设计保守丢弃该次结果，由下一次观察收敛，不冒回滚风险。该 CAS 只在本进程内有意义，冷启动重置，不构成跨进程时间或代际。

对 `Docker.list` 的处理：列表只用于发现名称和取得对象；每个容器的状态观察票必须在 **stats 之后的最终按名称新鲜解析之前**签发。最终状态事实 MUST 通过 `containers.get(name)` 或等价的新鲜按名查询取得，不能对 stats 期间的旧对象直接 `reload()` 后把该对象自己的旧 Docker ID 当作当前身份；旧对象只能用于指标/诊断。若按名称解析 NotFound/失败，则按删除/unknown 路径处理，不驱动身份更换；若返回不同 Docker ID，才是当前名称的更换证据。stats 本身慢时，旧 `container.status` 不能作为发布事实；按名解析失败则该容器标记 unknown 并保留最后已知，不能沿用旧状态。指标写入使用独立的 `metrics_read_seq` 与同一 generation/action_seq 校验，不推进 `last_applied_read_seq`，也不抬高动作序号或代际。

Docker 事件完全复用 prevent 的归一化：`Action` 优先、缺失时回退 `status`，`exec_create: ...`/`exec_start: ...` 等带冒号后缀的 `exec_*` 仍按噪声处理；本变更不新增事件解析器。状态事件只作为“需要新鲜 inspect”的触发器和诊断：事件回调先取观察票、再触发新鲜 inspect，不直接写缓存。事件的 `timeNano`、接收顺序和回调顺序均**不是**事实时序，不能用于覆盖状态；`destroy` 也不单独写 offline/删除，删除仍由 prevent 的存在性再确认和删除队列决定。

### 4. 动作执行、幂等与错误保留

通用动作协调器按“受理 → 串行执行 → 前/后新鲜 inspect → 分类 → CAS 完成”运行。动作后的 inspect 也必须先取观察票，且票的 `action_seq` MUST 固定为该动作受理时的序号，不能从当前值重取；若已不是当前序号，只记 `superseded`/诊断，不得发布运行态。`pause_container`/`start_container`/`stop_container`/`restart_container` 目前把任何异常统一转成 False；本变更要求动作路径取得结构化结果（至少区分 `not_found`、Docker API/daemon 错误、超时、状态矛盾），不能吞掉其他 API 错误。既有 bool 接口如需保留，只能作为兼容包装，不能是动作协调器唯一信息来源。

pause/unpause 的规则：

| 前/后新鲜实态 | pause | unpause |
| --- | --- | --- |
| running 且 not paused | 调用 pause；后 inspect 为 paused → confirmed，仍 running → failed（运行态 online），unknown → unconfirmed | **幂等确认成功**，不调用 Docker；保持/收敛 online |
| paused | 幂等确认成功，不调用 Docker | 调用 unpause；后 inspect running/not paused → confirmed；仍 paused → failed；unknown → unconfirmed |
| exited/offline | 不得报告成功；动作 failed，运行态 offline | **不得报告成功**；动作 failed，运行态 offline |
| dead | 不得报告成功；运行态按 `docker_dead` 硬阻塞 | **不得报告成功**；运行态按 `docker_dead` 硬阻塞 |
| NotFound | 动作 failed/not_found；不伪造 offline 成功 | 动作 failed/not_found；不伪造成功；删除由既有删除路径处理 |
| inspect 不可判定 | 不盲目调用状态变更；动作 unconfirmed，运行态 unknown | 同左 |

对 `is not paused` 这类 Docker 错误，不能直接判失败：先做新鲜 inspect；若实际 running/not paused，按幂等确认成功；若实际 paused，按失败；其他错误保留原始类型和受控长度的 detail。任何非幂等、非 running 的情形都不得写 online。

start/stop/restart 的规则：

- start：前 inspect 已 running 时仍要遵守就绪门禁；只有 `ready_identity`（Docker ID + StartedAt）与当前 fresh fact 一致且已 `ready_verified`，才能幂等确认 online，否则进入 ready_check。offline 才调用 Docker；Docker 返回成功但 sshd 未就绪时动作只到 `confirmed`（Docker 效果），运行态保持 starting/ready_check。
- stop：已 exited/offline 且无 dead 时为幂等确认 offline；running 才调用；后 inspect 仍 running 为动作 failed、运行态 online；dead 为硬阻塞，不报“停止成功”。
- restart：Docker 调用成功不等于 online；必须清空旧 `ready_verified` 并重新走既有 sshd 就绪门禁；即使 Docker ID 不变，只要 `StartedAt` 变化也不能复用旧就绪证明。调用失败后以新鲜 inspect 决定运行态，动作失败不永久置 failed。
- create：build/creating 先于受理响应可见；Docker 对象建立后进入 ready_check。创建动作失败且 Docker 对象仍是 `created` 时按半成品硬阻塞；没有对象时运行态为 unknown/最后已知，不把 build/create 动作失败永久写成 failed。

就绪门禁保持不变：`ready_check` 通过前不得仅凭 Docker running 写 online；sshd 缺失/未安装沿用既有硬阻塞；启动/重启/创建成功后的 probe 自愈路径不绕过。`ready_verified` MUST 绑定到 `(docker_id, started_at)` 运行进程身份，不能只绑名称或对象代际：pause 保留同一进程的就绪证明；显式 restart 在受理时即清除旧证明，start 产生新的运行进程（StartedAt 变化）、同 Docker ID 外部重启、新对象或冷启动 MUST 使旧证明失效；start 对已 running 且同一进程、已有有效 ready_identity 的幂等情形可复用证明，但仍不能绕过既有门禁检查。probe 通过时 MUST 用当次新鲜 Docker 事实记录 `ready_identity` 并把 `ready_verified` 置真。无法取得 `StartedAt` 时不得复用 `ready_verified`，必须重新门禁。

### 5. 未知、采集错误与冷启动

- 全量 Docker 列表失败：保留最后已知缓存，置全局 `collect_error`，WSS 继续发送既有 `{collect_error: reason}` 形状；不发送空表、不强行 online。
- 单容器 inspect/stats 失败：只影响该容器，读面 `status=unknown`，附 `status_source`（如 `collect_error`/`cold_start_verify`/`action_unknown`）与 `unknown_since`；`last_known_status` 保留供恢复和诊断。下一次成功观察或事件触发的新鲜 inspect 清除 unknown。
- 动作失败：写 ActionRecord 和结构化日志，动作结果可为 failed；运行态仍按新鲜实态/门禁，不因失败记录变成永久 failed。动作 TTL 只让受理过渡态停止遮挡，不删除 ActionRecord、不清硬阻塞、不把硬失败按 TTL 抹掉。
- 冷启动：生成新的 `node_epoch`，清空动作序号、观察票基线、ActionRecord、pending、`ready_identity` 和观察时间诊断；从当前 Docker 事实重建。running 先 ready_check，created 硬阻塞，exited 为 offline，dead 为硬阻塞；不重放历史 OOM，不复活重启前的 failed pending，`last_action` 为 null。旧 Ctrl 重启后自然看到 online/unknown/offline 等既有语义。

### 6. 同名 Docker ID 更换、创建 pending 与删除候选

同名 Docker ID 更换只能由**通过票据校验的当前代观察**驱动：ticket 的 generation/action_seq 必须仍是当前值，`read_seq` 必须新于 `last_applied_read_seq`，然后才允许比较 Docker ID。旧代 A 的晚到观察看到 B 时会在 generation 校验即被拒绝，不得推进成 B→C 的第二次更换，也不得取消 B 的 pending/动作。首次为当前 create 绑定 `docker_id` 不是更换：`state.docker_id is None` 时走绑定路径，不推进代际、不取消 create；create pending 期间非 create 自身确认的观察不抢先绑定，已有绑定后遇到不同 ID 先记 `identity_change_deferred`，等 create 结束再处理。这样避免旧观察或错误绑定取消正在创建的容器。

有效更换路径才执行：推进共享代际、取消旧代动作队列和旧观察资格、清空旧代 current_action/`ready_identity`，并把旧代删除候选交给 prevent 的失效逻辑；新对象按冷启动/新代规则重新分类，不能继承旧代的 online、failed 或 pending。若旧代仍有未终结的 latest action，将其 phase 置 `superseded` 并保留其 ref 作为终结诊断，供仍持有旧 ref 的 Ctrl 精确匹配释放过渡；已有终结 phase 不回归，新代动作使用新 ref。创建受理本身也按 prevent 推进代际；旧代删除候选不得作用于新代，旧代动作完成不得写新代。

该路径只提供本进程/缓存内的保护。Node 发给 Ctrl 的既有 `delete` 仍只有名称；本变更不宣称能撤回在途帧或向 Ctrl 证明 Docker ID，Q70 的跨进程身份问题保持不变。

### 7. 与 verify-bind 路径诊断/采样会话的边界

`verify-bind-mount-identity` 现在提供 `configured_mount_path`、业务 `bind_mount_path`、`mount_path_status`、`mount_path_observed_at`、`measurement_status`、`measured_at`、`measurement_mount_path` 以及仅用于采样会话排序的 `collector_epoch`/`observation_seq`；这些是磁盘路径/测量诊断，不是运行时对象身份、动作引用或目录业务门禁。本变更 MUST NOT 共享、推进、重置或重新解释这些字段。`action_ref` 使用独立的 `node_epoch` + 对象 generation + 动作 seq，MUST NOT 混用或映射磁盘路径诊断/采样会话字段。pause/unpause/start/stop 及容器对象换代 MUST NOT 被当作新的磁盘采样会话，也不得让旧磁盘样本因运行态变化显得新鲜。运行态 DockerID、ready_identity、action_ref 和对象防旧写保持不变；磁盘缓存仍按其 `measurement_status`/`measured_at`/`measurement_mount_path` 契约判定。本变更不修改 verify-bind 的任何文件或路径/测量协议。

### 8. API、WSS 与旧 Ctrl 兼容

动作 API 的 `success=1` 和过渡状态只表示 accepted；端点不得把后台结果提前写进响应，也不得把动作失败编码为“未受理”。新增可选 `action_ref`/`last_action`（见 §9）；不新增必需字段、不改 `snapshot_batch` 形状、不改 `delete` 帧。所有 HTTP/WSS 状态值继续使用既有 Literal；未知使用既有 `status=unknown` 与既有 `status_source`/`unknown_since` 语义；硬阻塞才发送 `failed`。动作结果作为可选诊断暴露，运行态恢复不依赖它，旧 Ctrl 可完全忽略。

WSS `build_status_snapshot` 仍读 `list_container_status`；其条目必须来自上述读面优先级，不能出现“底层 cache online、条目却因动作失败返回 failed”。运行态与 `last_action` 必须来自同一原子读面，可同时出现 `last_action.phase=failed` 与 `status=online`。`collect_error` 全局形状保持不变。旧 Ctrl 的恢复路径就是既有 online/unknown 语义，不依赖本变更的新字段。

pause 终态契约：Node 只在运行态确实为 paused 时提供 pause 成功终态；pause 软失败 MUST NOT 使容器 status=failed，MAY 以 `last_action.phase=failed` 提供动作诊断。消费方实际确认 pause 只以终态 `paused`；稳定 offline 仅能解除长期资格过渡，不能确认暂停或冻结；看到 `online` 或其他非终态继续等待，超时按 `unconfirmed`，不得把 `online` 当 `pause_failed`。动作过渡可按 §9 的精确 ref+方向匹配终结，但 `last_action.failed` 不改变运行态；当前 Docker 实态证明 dead 等硬故障仍可按既有 failed 发送，但不得伪装成 `pause_failed`。start/create 就绪硬阻塞和真实 Docker 故障不被泛化清除。

### 9. 动作引用与 last_action 兼容 wire

Node 在六个动作（create/start/stop/restart/pause/unpause）受理前分配 `action_ref`，并随受理响应返回；`action` 记录对应动作名。字段形状与 Ctrl `guard-long-term-container-transitions` 一致：

```json
action_ref = {
  "node_epoch": "UUID string",
  "generation": 0,
  "seq": 0
}
last_action = {
  "ref": action_ref,
  "action": "create|start|stop|restart|pause|unpause",
  "phase": "accepted|confirmed|idempotent_confirmed|failed|unconfirmed|superseded|timed_out",
  "error_reason": "string|null"
}
```

- `node_epoch` 每 Node 进程启动生成一次 UUID，同一进程所有动作共用；重启即更换，旧 ref 永不匹配。`generation` 复用 prevent 的对象代际，`seq` 为该代际的本地动作序号，均为非负整数。create 的 ref 使用创建受理推进后的新对象代际。`action_ref` 只关联单 Node 动作，不是 Q70 删除授权/跨进程身份，也不与 verify-bind 的磁盘路径诊断、采样会话或测量路径混用。
- 新 Node 对成功受理的六类动作响应 MUST 带 `action_ref`；旧 Node 可缺失。HTTP 状态响应和 WSS 容器条目 MUST 带 `last_action`，无本进程动作记录时显式输出 `null`；旧 Node 可缺字段。`error_reason` 可为 null 或受控诊断字符串。
- `last_action` 只代表该容器最新本地受理动作；新受理替换旧记录。终态为 `confirmed`、`idempotent_confirmed`、`failed`、`superseded`；`accepted`、`unconfirmed`、`timed_out` 非完成证明，不能结束过渡、放行冻结或清除硬阻塞。相同 ref 进入终态后，旧 accepted/unconfirmed/timed_out 不得回退；旧 ref 的 finish 不得覆盖新 ref。`unconfirmed`/`timed_out` 可在同 ref 仍为最新时随后转终结，但不因 TTL 释放。
- `last_action` 与运行态在同一读锁内投影，保证原子一致；可同时出现 `failed + online`、`confirmed + online` 等历史动作与当前实际状态组合。`last_action.failed` MUST NOT 使运行态 status 变成 failed。读面只保留每容器最新动作；终结、相位变化和旧 ref 拒绝写有界结构化日志，避免无界历史。
- 同名对象换代时，旧代未终结的 latest action 置 `superseded` 并保留旧 ref 作为终结诊断，供旧绑定按精确 ref 释放；已终结 phase 不回归，新代动作使用新 ref。Node 重启后无内存记录，`last_action:null`，旧 epoch/ref 失效。删除/忘记容器代际时清理该容器动作记录。
- Ctrl 集成：HTTP ACK 绑定 `action_ref`；只有精确 `{node_epoch,generation,seq}` 且 action 方向匹配的终结 phase 可结束对应长期过渡/冻结请求。`paused` 仍可按实际运行态确认暂停；`online` 不得推断 `pause_failed`。缺 ref/字段、旧 ref、未知 phase 只能 timeout unconfirmed，不得放行。早到 WSS 终结由 Ctrl 按 ref 有界暂存、ACK 到达后精确匹配；Node 不因 ACK 缺失强发 failed。非 pause/unpause 的 last_action 不匹配 pause/unpause 过渡。普通 unpause accepted 后立即授宽限仍是 Ctrl 遗留行为，不在本变更修复。
- Pydantic 响应模型必须声明 `action_ref: ActionRef | None` 与 `last_action: LastAction | None`：`ContainerOperationAcceptedResponse` 与 `CreateContainerResponse` 提供 action_ref，`ContainerStatusResponse` 与 WSS 容器条目提供 last_action；WSS 条目构造必须显式复制字段。`null` 不得被 response model、exclude 逻辑或 JSON 序列化丢弃。旧 Ctrl 忽略新字段；旧 Node 缺字段时新 Ctrl 降级为 timeout unconfirmed。

## Risks / Trade-offs

- [串行动作队列使后受理的动作等待] → 只按名称串行，不阻塞其他容器；受理响应仍立即返回 accepted，读面 TTL 到期后不再用过渡态遮挡，动作结果和运行态分开。
- [读取前票据可能保守丢弃“晚发起但拿到更新事实”的观察] → 优先保证不回滚：丢弃后由下一次观察/reconcile 收敛，不使用完成时间冒险；受控交错测试验证旧响应晚到和后发先到都不会覆盖已发布状态。
- [每次状态发布都做新鲜 inspect 增加 Docker 调用] → 只对动作前后、事件触发的状态和每轮每个容器的状态发布做（stats 后一次 reload）；指标可用独立节流，不能以性能为由复用旧对象写状态。
- [只允许很窄的硬阻塞会让部分真实故障停留在 unknown/诊断] → 宁可报告未知与日志，也不把动作失败或 OOM 永久写成 failed；当前 dead 和既有门禁仍能形成明确硬阻塞。
- [旧 Ctrl 对通用 unknown 的落库行为未必与 cold_start_verify 完全一致] → 只使用既有 unknown + status_source 语义，并把旧 Ctrl 消费快照作为受控联调门禁；不新增 DB 字段，不以强写 online 规避。
- [同名 Docker ID 更换仍可能有在途旧帧] → 本地代际只保护 Node 读面；删除帧/跨进程隔离仍受 Q70 边界约束，不能宣称绝对安全。
- [last_action 只保留最新动作] → 旧 ref 的终结在中途被新动作替换后不会出现在读面；旧 Ctrl 绑定会因 ref 不匹配保持 unconfirmed，由新动作/方向状态收敛，不伪造成功或失败。
- [旧 Node 缺 action_ref/last_action] → 新 Ctrl 只能按方向终态或 timeout unconfirmed；部署说明必须记录旧 Node 覆盖率，不承诺同等恢复能力。
- [action_ref 被误用为跨进程身份] → 仅单 Node 动作关联；不与 Q70 删除授权、对象身份或 verify-bind 磁盘路径诊断/采样会话混用。
- [early WSS/ACK 交错] → Node 在受理前分配 ref，HTTP/WSS 同源；Ctrl 按 ref 有界暂存并精确匹配，Node 不因 ACK 缺失强发 failed。
- [动作诊断序列化丢失] → Pydantic 响应模型和 WSS 构造都显式保留可选字段及 null；任务用模型 dump/JSON 帧测试验证。

## Migration Plan

1. 前置：Ctrl `guard-container-vanish-deletion` 已部署；Node `prevent-false-container-vanished` 的共享代际、观察边界、创建 pending 和事件归一化先落地。事件运行态只能经统一观察入口：prevent 不得新增直接写运行态的路径，guard 落地后事件只触发新鲜 inspect；若两变更分开发布，联合验收以唯一入口为准，不允许双写并存。两者是共享基础，不把 `guard-runtime-state-reconciliation` 单独部署在旧代际实现上。
2. 部署 Node 本变更（与 prevent 可同一版本发布，但内部必须先生效代际/观察基础，再启用动作序号、observation ticket 与可选 action_ref/last_action）。旧 Ctrl 可忽略新字段并继续按既有状态恢复；旧 Node 缺字段时新 Ctrl 按 timeout unconfirmed 降级。无数据库迁移、无 WSS 必需字段升级。建议 Node 可选字段先于 Ctrl `guard-long-term-container-transitions`/`unify-disk-freeze-workflow` 可用，以取得完整精确 ref；若 Ctrl 先部署，旧 Node 缺字段按 timeout unconfirmed 降级，不承诺同等恢复能力。
3. 与既有 start/create 就绪门禁共享验收：门禁仍然阻挡 running→online；本变更不得以 Docker running 绕过 sshd 检查或 created 半成品保护；start/restart 或同 Docker ID 外部重启后必须按 `StartedAt` 重新验证，pause 可保留同一进程的已就绪证明。
4. 与 Ctrl `guard-long-term-container-transitions`/`unify-disk-freeze-workflow` 的边界：本仓不修改 Ctrl，也不新增必需 wire 字段。Node 提供可选 action_ref/last_action；Ctrl 精确 ref+方向匹配终结过渡，实际 pause 只以 paused 确认，offline 仅解除资格过渡，online 不当 pause_failed，缺 ref/字段 timeout unconfirmed。软失败只提供动作诊断，不写容器 failed。普通 unpause accepted 后立即授宽限仍是 Ctrl 遗留行为。该 Ctrl 变更应在 Node 可选字段覆盖率核对后启用完整精确 ref 路径，旧 Node 缺口只能降级。
5. 与 `verify-bind-mount-identity` 的边界：其磁盘路径诊断、采样会话 `collector_epoch`/`observation_seq`、`measurement_status`/`measured_at`/`measurement_mount_path` 与本变更对象代际/action_ref 独立；本变更不修改该协议、不推进其采样会话，pause/unpause 不冒充新的磁盘路径/测量身份。验收时保留其原有契约测试，不做跨字段映射；runtime DockerID、ready_identity、action_ref 和对象防旧写不在本次修正范围。
6. 观察窗口内核对：动作 accepted→confirmed、对账旧对象不回退、重复 unpause 幂等、pause 失败+online+last_action.failed、旧 ref 晚到、ACK/WSS 早到、Node 重启 last_action=null、dead/created/sshd 硬阻塞、unknown/collect_error 和冷启动恢复。回滚时回滚 Node 代码并重启服务；内存动作状态随重启清空，不单独回滚 Ctrl 防护或 prevent 基础；旧 Ctrl 仍按既有状态语义工作。

## Verification Strategy

回归不能只写与实现同构的单测。实现阶段需要一个可注入屏障的受控交错测试夹具：在受理、ref 分配、观察票签发、动作队列取出、Docker 调用前/后、列表枚举、逐容器 stats、按名新鲜解析、响应延迟返回、事件投递、HTTP ACK 返回、WSS 快照构造和删除队列取出处设置 barrier，按事故时间线复现“unpause 成功 → 旧对账回写 paused → 再次 unpause not paused → pending failed → 底层 online”，并断言读面始终为 online/unknown 而不是永久 failed。必须专门覆盖：同代同动作序号下旧读取延迟返回/后发先到；旧代 A 观察晚到看到 B 不触发第二次换代；慢列表旧对象 A 在当前名称 B 时不得把自己当当前身份；当前 create 首次绑定不取消自己；create pending 期间不同 ID 推迟；restart/同 Docker ID 外部重启后 StartedAt 变化使 ready 失效；pause 保留同一进程 ready；重复 unpause 返回新 ref + online + idempotent_confirmed；pause 软失败返回 online + last_action.failed；旧 ref 晚到不覆盖新 ref；早到 WSS 终结与 HTTP ACK 的 ref 一致；Node 重启 last_action=null 且旧 epoch 失效；旧 Ctrl/旧 Node mixed-version；可选字段及 null 在 HTTP Pydantic dump 和 WSS JSON 中不被丢弃；Ctrl 只凭终态 paused 确认实际暂停、exact ref+方向终结过渡、online/缺 ref 超时 unconfirmed；verify-bind 磁盘路径诊断/采样会话不被本变更改动。另加随机交错/属性测试验证：动作序号单调；观察票 read_seq 不回退；旧完成不改变运行态；硬阻塞原因只来自允许集合；动作失败/未知不产生永久 failed；普通指标不抬代际/序号。旧 Ctrl 兼容以既有 WSS 帧回放和既有状态映射夹具验收，不以修改 Ctrl 代码为测试手段。
