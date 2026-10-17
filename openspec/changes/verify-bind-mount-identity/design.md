# Design

## Context

动机见 [proposal.md](proposal.md)。当前 `docker_operates/disk_usage_cache.py` 按 Docker `Mounts.Source` 执行 `du -sb`，bind 缓存以路径为键；当 Source 路径与实际 `/root` 挂载目录对象错位时，Node 会测到错误目录，Ctrl 也缺少可信的修正业务路径。旧方案曾把目录对象编号/PID 做成跨端身份门禁，用户已明确否决：精确对象匹配只用于 Node 内部定位真实宿主路径、校正返回的 `bind_mount_path`；恢复、长期资格、冻结、删除、清理和测量有效性一律按业务路径及测量事实判断。

首版范围限定为单台 Node 的本机路径视图：可以在既有容器存储根和已有路径父目录的有界范围内定位真实目录，不做全盘递归，不修改目录、不改 Docker 配置、不重挂载，不把路径诊断或目录对象编号变成业务授权。Q70 的跨进程删除授权与 Q72 的累计冻结策略仍由各自边界负责；本变更不提供删除/清理授权，只提供路径纠正、真实测量时间和测量状态。Ctrl 的 restore 静默一次宽限由 Ctrl 持久化，并在新实例上走正常磁盘链路检查；Node 不新增 restore preflight/API/门禁。

## Goals / Non-Goals

**Goals:**

- 让既有 `bind_mount_path` 成为业务路径；Source 与实际挂载一致时确认 Source，错位时在有界候选内唯一匹配后修正真实宿主路径。
- 路径无法唯一确认时保留原有/最后确认路径并如实诊断，不用诊断状态阻断业务，也不把诊断失败说成测量失败。
- 按业务路径测量与缓存；路径变化后重新测量，旧路径样本不得改贴新路径。
- 保留真实测量时间、组成完整性、非零 du 错误、过期与乱序保护、Q72 累计政策。
- 删除旧目录/对象跨端身份协议，目录 dev/inode/PID 只留 Node 内部定位与调试。

**Non-Goals:**

- 不自动改名、重挂载、创建目录或改挂 Docker/宿主配置，不删除/清理目录；只返回校正后的业务路径，不改目录本身。
- 不做全盘递归搜索，不把 `/proc` 临时路径返回给 Ctrl，不凭 inode 批改历史快照或旧清理记录。
- 不建立跨机器永久目录 ID，不解决 Q70 的跨进程操作代际，不把路径纠正当作删除/清理授权。
- 不新增 Node restore preflight/API/门禁；Ctrl restore 政策不在本变更扩展。
- 不改动正式 `openspec/specs/` 或 archive；不改动 guard-runtime-state-reconciliation 的 runtime DockerID、ready_identity、action_ref 或对象防旧写。

## Decisions

### 1. 业务路径模型与有界真实路径纠正

线路上的 `bind_mount_path` 是业务路径（用户通称 `mount_path`）；`configured_mount_path` 只记录 Docker Source，是诊断字段。新增：

- `mount_path_status`：`resolved | unresolved | not_running | no_bind`，可选缺省 `unresolved`。
- `mount_path_observed_at`：UTC 路径核对时间，不是测量时间；`configured_mount_path`/`bind_mount_path` 为 `str | null`。

路径核对使用 Docker inspect 的 `/root` bind Source，以及运行/暂停容器 `/proc/<pid>/root/root` 的实际目录对象 `(st_dev, st_ino)`。该对象比较只在 Node 内部用于定位路径和调试，不进入 HTTP/WSS 业务身份字段，不作为恢复、长期资格、冻结、删除或清理的前置。

纠正顺序固定：

1. Docker 成功确认没有 `/root` bind：`no_bind`；`bind_mount_path=null`、`measurement_mount_path=null`，只允许 overlay-only。单纯 inspect 不可读、Source 缺失或 unresolved MUST NOT 被解释为 no_bind，也不得清空已有业务路径。
2. 容器没有可验证 PID（停止/重启过渡等）：`not_running`；保留既有/最后确认业务路径，不猜测、不把 Source 单侧当作实际路径。
3. Source 路径可解析且 Source 对象与 `/proc/<pid>/root/root` 一致：`resolved`，使用该 Source 路径作为业务路径。
4. Source 路径缺失/不可解析，或 Source 与实际对象不一致，但 `/proc/<pid>/root/root` 仍可读：仍 MUST 尝试有界候选定位 actual；唯一匹配才 `resolved` 并修正业务路径。Source 改名后旧路径不存在不直接等于 unresolved。
5. actual 可读但在允许根/父目录直接子项、最后确认路径父目录和已有业务路径内没有可命名路径、没有匹配、多个匹配，或实际目录已无可唯一命名的允许范围路径：`unresolved`，保留既有/最后确认路径；无既有路径则为 null。
6. `/proc`/actual 不可读、inspect 失败或无法证明挂载视图：`unresolved`，保留既有路径；无既有路径则为 null。不能只因为 Source 被 unlink 就跳过第 4 步。

有界候选只包括：既有容器存储根 `NODE_CONTAINERS_BASE` 下、带 `containers` 路径段的 Source 父目录直接子项；最后确认业务路径的同类父目录直接子项；以及已有的业务路径本身。Source 缺失时仍可用最后确认/已有业务路径的允许父目录作为候选起点；不得因 Source 缺失就全盘搜索。只查看允许根内的实际目录，不递归、不遍历 symlink 目录；不把 `/proc` 路径、猜测名或 Docker 配置写回。唯一匹配的标准是候选目录对象与 actual 根对象一致；目录对象编号只在这次内部定位中使用，核对结束即丢弃，不持久化、不上线路。

路径核对开始前，Node 内部记录当前活跃容器/Docker ID/PID 与路径核对序号；发布修正前复核仍属于同一活跃容器且本轮序号未被新核对取代。旧定位晚回只丢弃，不得改写新对象或新活跃容器的业务路径。该 token/序号只保护路径纠正，MUST NOT 进入测量有效性、采样、恢复、长期资格、冻结、删除或清理判断。

无法唯一确认时 MUST 保留原有/最后确认业务路径并标 `unresolved`；没有已有路径时业务路径为 null。`unresolved` 是诊断，不是错误路径、不是空目录、也不是业务阻断。`no_bind` 才表示 Docker 明确无 bind，Ctrl 接收端应清空当前活跃容器的业务 bind 路径（不能保留旧路径再按同路径判定）；`unresolved`/`not_running` 不得清空路径。Ctrl 只对当前认证机器、活跃容器的 `mount_path_status=resolved` 修正持久化到 `containers.bind_mount_path`；不凭 inode 批改历史快照或旧清理记录，后续新记录读取新路径。

### 2. 按业务路径测量、缓存与有效性

bind 用量一律按当前业务路径 `bind_mount_path` 测量，并在 `measurement_mount_path` 记录实际测量路径。bind 缓存按规范化业务路径为键，不按目录对象、PID 或旧身份键命中。路径变更（Source 修正、候选唯一匹配、业务路径更新）必须使旧路径测量失效并触发新路径测量；旧路径的字节数 MUST NOT 被改贴到新路径。

保留 `disk_protocol_version=1`（尚未实现，可收窄字段但保持协议名）、`collector_epoch`（采集进程会话）、`observation_seq`（同 epoch 内状态/测量发布排序，不是目录身份）、`measurement_status`、`measured_at`、`measurement_mount_path`、`measurement_reason`。旧目录/对象身份字段从磁盘用量协议中删除；runtime DockerID 仍在状态/动作协议中保留。

`total_bytes` 仅在以下条件同时成立时非空：

- `measurement_status=ok`；
- overlay 与 bind 组成完整（Docker 明确 `no_bind` 时只要求 overlay；`no_bind` 必须来自成功 inspect，不能由异常/无 Source 推断）；
- `measured_at` 在允许真实年龄内，且是 overlay/bind 各自完成时间中较早者；
- `measurement_mount_path` 与当前业务 `bind_mount_path` 相同；
- 响应/观测排序未被同 epoch 更旧序号或旧连接覆盖。

有效性谓词 MUST NOT 检查 `mount_path_status=resolved`、目录 dev/inode、PID 或 Source/actual 对象匹配。已存在有效业务路径且本次路径测量成功时，仅 `mount_path_status=unresolved` 不影响 `measurement_status=ok` 或 `total_bytes`；路径诊断失败也不得写成 `measurement_error`。反过来，`mount_path_status=resolved` 不能使失败的 du 变成有效。

`measurement_status` 取值 `ok | measuring | stale | error | unverified`；`measurement_reason` 记录超时、非零退出、空/不可解析输出、路径不存在、权限、组成缺失、过期、身份/路径变更等真实原因。非零退出即使 stdout 有数字也不采纳；缺组成、异常、超时或旧值只作诊断，不能当 0。overlay-only 仅限 Docker 明确 `no_bind`，异常不是 `no_bind`。

### 3. 轻量路径核对与重型测量分开

独立轻量路径核对按有界周期运行，只做 Docker inspect、`/proc` 根对象读取和有界候选核对，不执行 du、不持有 du 缓存锁；`mount_path_observed_at` 记录核对完成时间。路径核对失败/超时只产生 `unresolved` 或 `not_running` 诊断，不改变测量状态为 `measurement_error`，不阻断已有业务路径的测量与处置。

路径变化可唤醒新路径测量；宿主改名没有 Docker 事件，周期核对仍必须存在。WSS/HTTP 读取只读缓存，不执行 du、不刷新 `measured_at` 或 `mount_path_observed_at`。路径核对过期后不能恢复旧的 resolved 结论，只能重新核对；但路径诊断不作为业务门禁。

### 4. version 1 线路与 Ctrl 持久化

`ContainerDiskUsage` 保留既有 `overlay_rw_bytes`、`bind_mount_bytes`、`bind_mount_path`、`bind_mount_source`、`total_bytes`、`error`，新增/保留：

| 字段 | 类型与缺省 | 语义 |
| --- | --- | --- |
| `disk_protocol_version` | `int \| None` | 存在时为 `1`；旧负载缺失按未验证 |
| `configured_mount_path` | `str \| None` | Docker Source 诊断路径，不是业务路径 |
| `bind_mount_path` | `str \| None` | 业务路径；Node 确认后返回修正值；unresolved/not_running 保留既有/最后确认路径；no_bind 为 null |
| `mount_path_status` | `Literal["resolved","unresolved","not_running","no_bind"] \| None` | 缺省按 `unresolved`；诊断状态，不是业务门禁 |
| `mount_path_observed_at` | `str \| None` | UTC 路径核对时间，不是测量时间 |
| `collector_epoch` | `str \| None` | 采集进程会话，不是目录身份 |
| `observation_seq` | `int \| None` | 同 epoch 采样发布排序，不是目录身份 |
| `measurement_status` | `Literal["ok","measuring","stale","error","unverified"] \| None` | 缺省按 `unverified` |
| `measured_at` | `str \| None` | 合计样本真实测量时间，取组成中较早者；UTC 带 Z |
| `measurement_mount_path` | `str \| None` | 本次测量实际使用的业务路径；no_bind 为 null，unresolved 不清空 |
| `measurement_reason` | `str \| None` | 测量失败/过期/路径变更原因 |

旧 Node 缺少 `disk_protocol_version`、`measured_at` 或 `measurement_mount_path` 时按测量未验证处理，不能解释成缺目录身份；缺少 `mount_path_status` 按 `unresolved`；缺少业务路径时保留 Ctrl 已有值。HTTP 与 WSS 共用同一模型和校验；`null` 不得被 response model 或 JSON 序列化丢弃。

Ctrl 计划持久化字段为 `disk_measurement_status`、`disk_measured_at`、`disk_received_at`、`disk_observation`。`disk_observation` JSON 保存协议版本、collector_epoch/observation_seq（采样会话排序）、measurement_mount_path、configured_mount_path、mount_path_status、mount_path_observed_at 和 measurement_reason；不再保存旧目录身份列。`disk_received_at` 仅由 Ctrl 本地记录，Node 不发送。Ctrl 只按当前认证机器/活跃容器的 `mount_path_status=resolved` 修正持久化 `containers.bind_mount_path`，不按 inode 批改历史快照或旧清理记录。Ctrl 接收端在 `no_bind` 时清空当前活跃容器的业务 bind 路径（不能保留旧路径再判同路径）；unresolved/not_running 不清空。固定 8 字段 `long_term_eligibility` 不变。

### 5. Q70、Q72、清理与业务门禁边界

**Q70 独立。** 业务 `bind_mount_path` 仍供既有业务选择路径；路径校正本身不授予删除权限。inode、collector_epoch、observation_seq 和路径诊断不得作为跨进程删除授权、对象身份或清理目标选择依据；本变更不实现也不替代 Q70。

**Q72 保留。** 采集盲区不额外补偿，累计仍继续；异常观测期不依据无效样本执行删除，也不新增顺延；恢复可信高用量后，按原累计有效冻结天数判断，不重设 `first_frozen_at`，不新增 `review_required` 或 invalid 标记阻挡累计删除；既有机器不可用 deferral 与人工宽限保留。Node 只提供真实 `measured_at`、`measurement_status`、路径和原因，Ctrl 按既有 Q72 策略解释，不把路径诊断当门禁。

**清理边界。** 路径纠正、`mount_path_status`、目录对象编号和测量字段 MUST NOT 作为删除/清理授权；清理仍需其既有入口校验和显式授权。路径不存在、du 实际失败、组成缺失或测量过期仍按原测量错误/无效处理；诊断 unresolved 本身不是清理或冻结授权，也不是测量错误。

## Risks / Trade-offs

- [路径纠正候选有限而真实路径超出范围] → 保留最后确认路径并标 `unresolved`，不递归猜测、不阻断既有业务；日志给出诊断。
- [候选目录对象唯一匹配但语义仍可能变化] → 只在本次核对使用对象编号，不持久化、不上线路、不作为业务身份；路径后续变化重新核对/测量。
- [路径诊断失败被误当测量失败] → 状态分离：路径 `unresolved` 不改变 `measurement_status`；测量失败只由 du/组成/时间/路径一致性决定。
- [旧 Node 无真实测量时间] → 标测量未验证，不表示缺目录身份；不因缺字段恢复旧字节数。
- [路径变更后旧样本污染新路径] → 缓存键按业务路径，`measurement_mount_path` 必须等于当前路径；旧样本只能诊断。
- [Q72 被路径诊断误伤] → 不使用路径诊断/inode 做冻结门槛；采集盲区不额外补偿，累计继续；只不依据无效样本执行动作。
- [全盘搜索造成负载和误修正] → 只允许既有存储根/父目录直接子项和最后确认路径，不递归。

## Migration Plan

1. Node 实现路径核对、业务路径修正、按路径测量和 version 1 字段；不修改目录/Docker 配置，不做全盘扫描。
2. Ctrl 先移除旧目录身份门禁并接收 `disk_measurement_status/disk_measured_at/disk_received_at/disk_observation`；只对当前认证机器/活跃容器的 `mount_path_status=resolved` 结果持久化 `containers.bind_mount_path`，不批改历史记录。
3. 联合回放：Source/actual 一致、错位唯一匹配、歧义、unlink、offline/no PID、no_bind、路径变更时旧测量失效、unresolved + 有效业务路径测量仍可用、非零 du/缺组成/过期不产生 total、旧 Node 缺 measured_at 标未验证、Q72 累计与人工宽限/机器不可用保留。
4. 回滚 Node 时旧字段按未验证处理，不能回落旧字节数执行冻结/删除；不删除正式 specs/archive，不修改 guard 的 runtime DockerID/ready_identity/action_ref/对象防旧写。

## Verification Strategy

需要真实受控交错，而不只是实现镜像单测：在 Docker inspect、Source/actual 对象读取、候选枚举、du 启动/返回、路径更新、缓存回填、WSS 读取和 Ctrl 消费之间设置 barrier，覆盖：

- Source 与 actual 一致、错位唯一匹配、多个匹配/无匹配、Source unlink、proc 不可读、无 PID、paused、Docker 明确 no_bind。
- 路径从 A 修正到 B 时，A 的在途 du 晚返回不能绑定 B；B 重新测量前 total 为空。
- `mount_path_status=unresolved` 且有既有业务路径、du 成功且 measured_at 新鲜/路径一致时，total 仍有效；诊断失败不变成 measurement_error。
- 非零 du、空/不可解析输出、超时、权限、缺组成、overlay-only 非 no_bind 不得当 0/成功。
- collector_epoch/observation_seq 乱序、旧连接、Node 重启新 epoch；同一序号只作心跳，不刷新 measured_at。
- 旧 Node 缺 measured_at/measurement_mount_path 标未验证；旧 Ctrl 移除旧 identity 门禁后不要求路径 resolved。
- Q72 异常期不动作、恢复高用量按原累计、机器不可用/人工宽限保留；固定 8 字段 long_term_eligibility 不变。
