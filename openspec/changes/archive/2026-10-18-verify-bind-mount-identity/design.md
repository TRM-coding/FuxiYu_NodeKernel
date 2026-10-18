# Design

## Context

动机见 [proposal.md](proposal.md)。当前 `docker_operates/disk_usage_cache.py` 按 Docker `Mounts.Source` 执行 `du -sb`，bind 缓存以路径为键（第 24-27、134-208、253-326 行）；当 Source 路径与实际 `/root` 挂载目录对象错位时，Node 会测到错误目录，Ctrl 也缺少可信的修正业务路径。旧方案曾把目录对象编号/PID 做成跨端身份门禁，用户已明确否决：精确对象匹配只用于 Node 内部定位真实宿主路径、校正返回的 `bind_mount_path`；恢复、长期资格、冻结、删除、清理和测量有效性一律按业务路径及测量事实判断。

首版范围限定为单台 Node 的本机路径视图：只查 Docker inspect、`/proc/<pid>/root/root` 和既有容器存储根内的有界候选，不做全盘递归，不修改目录、不改 Docker 配置、不重挂载。Q70 的跨进程删除授权与 Q72 的累计冻结策略仍由各自边界负责；本变更不提供删除/清理授权，只提供路径纠正、真实测量时间和失败语义。

## Goals / Non-Goals

**Goals:**

- 让既有 `bind_mount_path` 成为业务路径；Source 与实际挂载一致时确认 Source，错位时在有界候选内唯一匹配后修正真实宿主路径。
- 路径无法唯一确认时保留原有/最后确认路径并如实诊断，不用诊断状态阻断业务，也不把诊断失败说成测量失败。
- 按业务路径测量与缓存；路径变化后重新测量，旧路径样本不得改贴新路径。
- 保留真实测量时间、组成完整性、非零 du 错误、缓存过期与失败语义；不新增测量状态/epoch/seq 线路字段。

**Non-Goals:**

- 不自动改名、重挂载、创建目录或修改 Docker/宿主配置，不删除/清理目录；只返回校正后的业务路径，不改目录本身。
- 不做全盘递归搜索，不把 `/proc` 临时路径返回给 Ctrl，不凭 inode 批改历史快照或旧清理记录。
- 不建立跨机器永久目录 ID，不解决 Q70 的跨进程操作代际，不把路径纠正当作删除/清理授权。
- 不新增 Node restore preflight/API/门禁；不修改 Ctrl 的存储模型或资格 DTO。
- 不修改正式 `openspec/specs/` 或 archive；不修改 guard-runtime-state-reconciliation 的 runtime DockerID、ready_identity、action_ref 或对象代际/动作票。
- 不新增 WSS 连接代际、`collector_epoch`、`observation_seq` 协议；也不删除与本轮无关的既有 Node 状态竞态处理。

## Decisions

### 1. 业务路径模型与有界真实路径纠正

线路上的 `bind_mount_path` 是业务路径（用户通称 `mount_path`）；`mount_path_status` 是路径核对结果，只用于 Ctrl 区分更新/保留/清空，不落 Ctrl、不作业务门禁：

- `resolved`：Node 内部唯一确认实际宿主目录；`bind_mount_path` 非空。
- `unresolved`：无法唯一定位；保留原有/最后确认路径，无已有路径则 null。
- `not_running`：容器没有可验证 PID（停止/重启过渡）；保留原有/最后确认路径。
- `no_bind`：成功 Docker inspect 明确没有 `/root` bind；`bind_mount_path=null` 且只允许 overlay-only。

路径核对使用 Docker inspect 的 `/root` bind Source，以及运行/暂停容器 `/proc/<pid>/root/root` 的实际目录对象 `(st_dev, st_ino)`。该对象比较只在 Node 内部用于定位路径和调试，不进入 HTTP/WSS 字段，不作为恢复、长期资格、冻结、删除或清理的前置。

纠正顺序固定：

1. Docker 成功确认没有 `/root` bind：`no_bind`；`bind_mount_path=null`、bind 字节为空，只允许 overlay-only。单独 inspect 失败、Source 缺失或 unresolved MUST NOT 被解释为 no_bind，也不得清空已有业务路径。
2. 容器没有可验证 PID（停止/重启过渡等）：`not_running`；保留既有/最后确认业务路径，不猜测、不把 Source 单侧当作实际路径。
3. Source 路径可解析且 Source 对象与 `/proc/<pid>/root/root` 一致：`resolved`，使用该 Source 路径作为业务路径。
4. Source 路径缺失/不可解析，或 Source 与实际对象不一致，但 `/proc/<pid>/root/root` 仍可读：仍 MUST 尝试有界候选定位 actual；唯一匹配才 `resolved` 并修正业务路径。Source 改名后旧路径不存在不直接等于 unresolved。
5. actual 可读但在允许根/父目录直接子项、最后确认路径父目录和已有业务路径内没有可命名路径、没有匹配、多个匹配，或实际目录已无可唯一命名的允许范围路径：`unresolved`，保留既有/最后确认路径；无既有路径则为 null。
6. `/proc`/actual 不可读、inspect 失败或无法证明挂载视图：`unresolved`，保留既有路径；无既有路径则为 null。不能只因为 Source 被 unlink 就跳过第 4 步。

有界候选只包括：既有容器存储根 `NODE_CONTAINERS_BASE` 下、带 `containers` 路径段的 Source 父目录直接子项；最后确认业务路径的同类父目录直接子项；以及已有的业务路径本身。Source 缺失时仍可用最后确认/已有业务路径的允许父目录作为候选起点；不得因 Source 缺失就全盘搜索。只查看允许根内的实际目录，不递归、不遍历 symlink 目录；不把 `/proc` 路径、猜测名或 Docker 配置写回。唯一匹配的标准是候选目录对象与 actual 根对象一致；目录对象编号只在这次内部定位中使用，核对结束即丢弃，不持久化、不上线路。

路径核对开始前，Node 内部记录当前活跃容器/Docker ID/PID 与路径核对序号；发布修正前复核仍属于同一活跃容器且本轮序号未被新核对取代。旧定位晚回只丢弃，不得改写新对象或新活跃容器的业务路径。该 token/序号只保护路径纠正，MUST NOT 进入测量有效性、采样、恢复、长期资格、冻结、删除或清理判断，也不上线。

无法唯一确认时 MUST 保留原有/最后确认业务路径并标 `unresolved`；没有已有路径时业务路径为 null。`unresolved` 是诊断，不是错误路径、不是空目录、也不是业务阻断。`no_bind` 才表示 Docker 明确无 bind，Ctrl 接收端应清空当前活跃容器的业务 bind 路径（不能保留旧路径再按同路径判定）；`unresolved`/`not_running` 不得清空路径。Ctrl 只对当前认证机器、活跃容器的 `resolved` 路径修正持久化，不凭 inode 批改历史快照或旧清理记录。

### 2. 按业务路径测量、缓存与有效性

bind 用量一律按当前业务路径 `bind_mount_path` 测量；bind 缓存按规范化业务路径为键，不按目录对象、PID 或旧身份键命中。路径变更（Source 修正、候选唯一匹配、业务路径更新）必须使旧路径测量失效并触发新路径测量；旧路径的字节数 MUST NOT 被改贴到新路径。

快照组装时，Node 内部比较缓存用量的 `bind_mount_path` 与当前业务路径：

- 一致：可发布该业务的 bind 字节；`total_bytes` 只在组成完整时非空。
- 不一致：发布当前业务路径，但 `bind_mount_bytes=null`、`total_bytes=null`，等待新路径测量；不得发布旧路径的路径/字节组合。
- 路径变化后，只有在该变化之后完成的新测量才可作为当前值；旧路径在途 du 晚回只能写旧路径缓存，不能成为新路径的 total。

线路只新增/保留以下测量字段：

| 字段 | 类型与缺省 | 语义 |
| --- | --- | --- |
| `measured_at` | `str \| None` | 合计样本真实测量时间，取 overlay/bind 各自完成时间中较早者；UTC ISO 8601；旧 Node 可缺省 |
| `bind_mount_path` | `str \| None` | 业务路径；校正后返回；unresolved/not_running 保留已有/最后确认路径；no_bind 为 null |
| `mount_path_status` | `Literal["resolved","unresolved","not_running","no_bind"] \| None` | 缺省按 unresolved；只作路径控制信号，不是业务门禁/测量状态 |
| `configured_mount_path` / `mount_path_observed_at` | 不新增线路字段 | Source 与核对时间只进 Node 内部日志/调试，不落 Ctrl |
| `measurement_mount_path` / `measurement_status` / `measurement_reason` / `disk_protocol_version` / `collector_epoch` / `observation_seq` | 不新增 | 用既有 `bind_mount_source`、`overlay_rw_source`、`error`、真实 `measured_at` 和字节完整性表达；不建立第二套测量状态/排序协议 |

`total_bytes` 仅在以下条件同时成立时非空：

- overlay 测量成功且组成完整（Docker 明确 `no_bind` 时只要求 overlay；`no_bind` 必须来自成功 inspect，不能由异常/无 Source 推断）；
- 有业务 bind 路径时，bind du 成功且字节可得；路径无法确认且无已有路径时不得发布 total；
- `measured_at` 是本次 overlay/bind 组成中较早的真实完成时间，不因 WSS 推送/HTTP 读取而刷新；
- 当前业务路径与产生 bind 字节的路径一致；旧路径样本不得参与。

有效性谓词 MUST NOT 检查 `mount_path_status=resolved`、目录 dev/inode、PID 或 Source/actual 对象匹配。已存在有效业务路径且本次测量成功时，仅 `mount_path_status=unresolved` 不影响 total；路径诊断失败也不得写成测量失败。反过来，`mount_path_status=resolved` 不能使失败的 du 变成有效。

失败与过期语义：非零 du 即使 stdout 有数字也不采纳；空/不可解析输出、超时、权限、路径不存在、缺组成或旧缓存值只作诊断，不能当 0。失败不得更新 bind 缓存的成功字节/测量时间；最后成功值只有在 `measured_at` 如实反映其年龄时才能展示，且不得伪装成当前测量。overlay-only 仅限 Docker 明确 `no_bind`；异常不是 `no_bind`。HTTP `check_disk_usage` 的未采集分支必须返回 `total_bytes=None`、`error="not_collected"`，不得返回 0。

### 3. 轻量路径核对与重型测量分开

独立轻量路径核对按有界周期运行，只做 Docker inspect、`/proc` 根对象读取和有界候选核对，不执行 du、不持有 du 缓存锁；路径核对失败/超时只产生 `unresolved` 或 `not_running` 诊断，不把测量改成失败，不阻断已有业务路径的测量与处置。路径变化可唤醒新路径测量；宿主改名没有 Docker 事件，周期核对仍必须存在。WSS/HTTP 读取只读缓存，不执行 du、不刷新 `measured_at`。

路径核对过期后不能恢复旧的 resolved 结论，只能重新核对；但路径诊断不作为业务门禁。路径变更后，在旧路径在途 du 返回前，不得把旧结果关联到新路径；新路径测量完成前 total 为空或 measuring。

### 4. 线路与 Ctrl 消费边界

`ContainerDiskUsage` 保留既有 `overlay_rw_bytes`、`bind_mount_bytes`、`bind_mount_path`、`bind_mount_source`、`total_bytes`、`error`、`container_name`，新增 `mount_path_status` 与 `measured_at`；不新增 `disk_protocol_version`、`collector_epoch`、`observation_seq`、`measurement_status`、`measurement_mount_path`、`measurement_reason`、`configured_mount_path`、`mount_path_observed_at`。HTTP 与 WSS 共用同一模型和校验；`null` 不得被 response model 或 JSON 序列化丢弃。

Ctrl 配套变更只消费：

- `bind_mount_path`：唯一业务路径；`resolved` 时更新，`no_bind` 时清空，`unresolved`/`not_running` 保留；旧 Node 帧不得改写已校正路径。
- `mount_path_status`：只作更新/保留/清空的控制信号，不落库、不作为 `resolved` 业务门禁。
- `measured_at`：用于把真实测量时间写入既有 `disk_checked_at`；缺省时 Ctrl 按旧 Node 接收时间兼容，不因缺字段把旧 Node 自动处置全停。

本变更不要求 Ctrl 新增 `disk_measurement_status`/`disk_measured_at`/`disk_received_at`/`disk_observation`，不要求跨仓资格 DTO，不要求 epoch/seq 落库；这些跨仓要求从本变更删除。Ctrl 的路径清空、旧测量失效和年龄判断由配套变更用既有列完成。

### 5. Q70、Q72、清理与业务门禁边界

**Q70 独立。** 业务 `bind_mount_path` 仍供既有业务选择路径；路径校正本身不授予删除权限。inode、路径诊断和测量事实不得作为跨进程删除授权、对象身份或清理目标选择依据；本变更不实现也不替代 Q70。

**Q72 保留。** 本变更不重写冻结/恢复/长期策略，不新增 `review_required`/invalid 保护，不改变既有累计、deferral 或人工宽限；异常观测不驱动动作，恢复后由既有策略判断。Node 只提供真实 `measured_at`、路径和失败事实。

**清理边界。** 路径纠正、`mount_path_status`、目录对象编号和测量字段 MUST NOT 作为删除/清理授权；清理仍需其既有入口校验和显式授权。路径不存在、du 实际失败、组成缺失或测量过期仍按原测量错误/无效处理；诊断 unresolved 本身不是清理或冻结授权，也不是测量错误。

## Risks / Trade-offs

- [路径纠正候选有限而真实路径超出范围] → 保留最后确认路径并标 `unresolved`，不递归猜测、不阻断既有业务；日志给出诊断。
- [候选目录对象唯一匹配但语义仍可能变化] → 只在本次核对使用对象编号，不持久化、不上线路、不作为业务身份；路径后续变化重新核对/测量。
- [路径诊断失败被误当测量失败] → 状态分离：`unresolved` 不改变测量事实；测量失败只由 du/组成/时间/路径一致性决定。
- [旧 Node 无真实测量时间] → `measured_at` 缺省，Ctrl 按既有接收时间兼容；不因缺字段新增版本门禁，也不恢复旧路径/旧字节。
- [路径变更后旧样本污染新路径] → 缓存键按业务路径，快照组装核对路径；路径变化后只接受变化后的新测量，旧样本只能作旧路径缓存。
- [Q72 被路径诊断误伤] → 不使用路径诊断/inode 做冻结门槛；只不依据无效样本执行动作，既有 Q72 策略不变。
- [全盘搜索造成负载和误修正] → 只允许既有存储根/父目录直接子项和最后确认路径，不递归。
- [非零 du 仍产数字] → 以退出码和输出同时判断，非零退出即使有 stdout 也不采纳；失败不更新成功字节/时间。
- [HTTP 未采集返回 0] → 改为 `total_bytes=None` + `error`，不把缺失当零。

## Migration Plan

1. Node 实现路径核对、业务路径修正、按路径测量、`mount_path_status` 与 `measured_at`；不修改目录/Docker 配置，不做全盘扫描，不新增表/列。
2. Ctrl 配套变更先部署接收修正（路径先落、显式清空旧测量、`measured_at` 写既有 `disk_checked_at`、失败不写 0），再逐机部署 Node。
3. 联合回放：Source/actual 一致、错位唯一匹配、歧义、unlink、offline/no PID、no_bind、路径变更时旧测量失效、unresolved + 有效业务路径测量仍可用、非零 du/缺组成/过期不产生 total、旧 Node 缺 measured_at 不被全局停处置。
4. 回滚 Node 时旧字段按既有接收时间语义处理，不能回落旧路径字节执行冻结/删除；不删除正式 specs/archive，不修改 guard 的 runtime DockerID/ready_identity/action_ref 或对象代际/动作票。

## Verification Strategy

需要真实受控交错，而不只是实现镜像单测：在 Docker inspect、Source/actual 对象读取、候选枚举、du 启动/返回、路径更新、缓存回填、WSS 读取和 Ctrl 消费之间设置 barrier，覆盖：

- Source 与 actual 一致、错位唯一匹配、多个匹配/无匹配、Source unlink、proc 不可读、无 PID、paused、Docker 明确 no_bind。
- 路径从 A 修正到 B 时，A 的在途 du 晚返回不能绑定 B；B 重新测量前 total 为空。
- `mount_path_status=unresolved` 且有既有业务路径、du 成功且 measured_at 为真实时间/路径一致时，total 仍有效；诊断失败不变成测量错误。
- 非零 du、空/不可解析输出、超时、权限、缺组成、overlay-only 非 no_bind 不得当 0/成功；HTTP 未采集不为 0。
- 重复推送同一缓存结果时 `measured_at` 不变；旧连接/旧 HTTP 不刷新测量时间；不新增 epoch/seq 协议。
- 旧 Node 缺 measured_at 不让 Ctrl 全局停处置；旧 Ctrl 忽略新字段后不要求 resolved；新 Node 不要求 Ctrl 新列。
- Q72 既有策略不变；不修改 guard-runtime 对象代际/动作票/ready_identity。

## Source references

- [docker_operates/disk_usage_cache.py](../../../docker_operates/disk_usage_cache.py)：bind 缓存 TTL/du 超时/sweep 第 24-27 行；`collect_container` 第 134-208 行；`snapshot` 第 242-251 行；`get_bind` 第 253-326 行。
- [network/wss.py](../../../network/wss.py)：`build_disk_usage_snapshot` 第 374-377 行、`build_snapshot_batch` 第 386-401 行；现有快照推送无 epoch/seq。
- [network/api.py](../../../network/api.py)：`check_disk_usage_api` 第 438-465 行；未采集分支当前返回 `total_bytes: 0`，需改为 None。
- [schemas/container.py](../../../schemas/container.py)：`ContainerDiskUsage` 第 245-253 行。
