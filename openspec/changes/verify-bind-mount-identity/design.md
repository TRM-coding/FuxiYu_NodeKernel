# Design

## Context

动机见 [proposal.md](proposal.md)。当前 `docker_operates/disk_usage_cache.py` 按 Docker `Mounts.Source` 执行 `du -sb`，bind 缓存仅以路径为键，容器缓存以名称为键，两层 TTL 均为 900 秒。`collect_bind` 还会接受非零退出码的 stdout；失败时保留旧 bytes。WSS 每次读取容器缓存，尚不携带用量真正产生的时间。

现场曾同时存在 Source inode 31924552、实际挂载 inode 31924550，且路径改正后旧 6 GiB 缓存仍被推送。该证据说明需要比较目录对象并绑定采样代际，不能只加一个 inode 字段。

首版范围限定为单台 Node 的本机文件系统视图：比较 Docker 声明的 bind Source 与运行容器 `/root` 实际挂载对象的 `(st_dev, st_ino)`，并把结果与 Docker 对象、进程代际、宿主 boot、采集进程 epoch、本地扫描代际和真实测量时间绑定。首版不把 inode 当作永久身份，不做跨机器目录查找，不自动修改目录，也不解决 Q70 的跨进程操作代际。

## Goals / Non-Goals

**Goals:** 建立“本次实际挂载—被测对象—缓存结果—Ctrl 收到的证据”闭环；在观测有效期内发现路径替换，显式失效旧测量；让 Ctrl 能区分当前可信测量、最后成功值和不可验证状态。

**Non-Goals:** 不自动修复目录名，不自动搜索或选择另一条宿主路径，不建立永久文件系统对象 ID，不实现 Q70 的跨进程操作身份协议，不改变 `du -sb` 的 apparent-size 计量口径，不把磁盘证据变成删除/清理授权。Q71 的实际对象计量与冻结扩展、Q72 的冻结累计策略由 Ctrl 侧配套变更负责；本变更只提供可判定的事实。扫描期间文件持续变化时，不承诺快照级精确性。

## Decisions

### 1. 本机比较 Source 与 actual 的 dev+inode

使用本次 Docker inspect 的不可变 Docker ID、`State.Pid`，与 `/proc/<pid>/stat` starttime（第 22 字段；解析时必须正确处理 comm 字段中的空格和括号）关联进程。记录宿主 boot ID 和每次采集进程启动生成的 collector epoch；epoch 不是机器业务身份，不替代 `node_uid`。

解析 Docker 声明的 `/root` bind Source，读取 Source 与 `/proc/<pid>/root/root` 的 `(st_dev, st_ino)`，并核对 `/proc/<pid>/mountinfo` 中确有对应 `/root` 挂载。设备号、inode 与 PID starttime 以十进制字符串上报，避免通用 JSON 数值精度损失；相同 inode 但设备不同必须判为 mismatch。`mount_id` 与 mount namespace 标识只用于本轮视图检查和诊断，不能跨宿主或重启比较。

进程变化、无权限、宿主 proc 不可见、mountinfo 不可读或无法证明 `/root` 挂载视图时降级为 unknown，不能只检查路径还存在。Docker 声明了 `/root` bind 但 Source 路径不存在或无法解析时标为 missing；两者都不能等同于 no_bind。Docker inspect 明确没有 `/root` bind 时才是 no_bind；不能把读取 `Mounts` 的异常吞掉后当作零 bind。paused 的进程可验证；stopped/restarting 且无稳定 PID 时为 not_running，有 PID 但宿主 proc 不可读时为 unknown。符号链接 Source 的解析口径必须与 Docker 挂载时的行为一致；未验证前不假定跟随或不跟随。

相同 dev/inode 只证明当时根对象一致，不证明目录下的挂载视图相同；首版对 `/root` 下无法验证的嵌套挂载明确报告 `unsupported_view`，不输出可信总量。inode 只在单台机器、文件系统和采样代际内作为比较证据，不成为跨机器永久 ID。

### 2. 轻量探测与目录扫描分开

独立后台探测目标周期 10 秒，默认身份最大年龄 30 秒；超限直接标 unknown。探测只做 Docker inspect、`/proc` 身份读取和 mountinfo 检查，不执行 du、不持缓存锁，并与 du 使用不同的线程/执行器；Docker 调用设置超时。WSS 仍只读缓存，按当前时间降级过期证据；探测故障不能使旧 match 无限有效。大量容器下记录一轮耗时，无法达到周期时报告过期并提供可调参数，不声称所有规模下都有固定十秒保证。

任一 Docker/进程/目录身份改变、停止或 probe 失败，递增本地 generation，取消旧样本资格；start/stop/restart 事件可唤醒探测，但宿主改名没有 Docker 事件，轮询仍必须存在。paused 的进程可验证；stopped/restarting 且无稳定 PID 时为 not_running，有 PID 但宿主 proc 不可读时为 unknown。Docker inspect 明确无 bind 时才是 no_bind，不能把取 Mounts 异常吞掉后当作零 bind。

### 3. 固定扫描对象并阻止旧线程回填

仅在 source 和 actual 匹配、挂载视图受支持时建立有效扫描任务。使用目录 FD 固定该对象：打开 Source 的目录 FD 后 `fstat`，与已验证身份一致才扫描该 FD 对应目录；Python 实现可把 FD 传给子进程并通过 `/proc/self/fd/<fd>/.` 访问。任务中保留 FD，避免目录被改名或被删除重建后扫描另一个对象。

缓存命中与回填必须同时匹配 `collector_epoch`、Docker ID、PID/starttime、boot ID、Source 与 actual 的 dev/inode、以及本地 generation，不能仅按路径、名称或 inode 命中。扫描前后检查容器与挂载视图、Source/actual 身份、进程 starttime、boot、collector epoch 和 generation；任何变化都丢弃结果。不能只比较前后 inode 来声称排除了 A→B→A 全部交错。

仅 rc=0、stdout 能解析为单个非负整数字节数且扫描后验证通过才发布。超时、非零退出、权限错误、空输出和解析失败均发布失败状态；`rc != 0` 时即使 stdout 含数字也不采纳。保留最后成功结果只供诊断，不能进入 `total_bytes`。扫描完成后立即按相同 generation 原子组装容器快照，避免再等下一轮 900 秒 sweep；overlay 与 bind 各保留采集时间，合计样本 `measured_at` 取两者中较早时间。默认测量最大年龄 900 秒；过期旧值不能继续成为有效 total，即使后台重试中。

#### 隔离 Linux 验证计划（实现前置）

FD 传递和 du 对已固定目录的遍历必须在隔离的 Linux 临时目录或命名空间中先验证，不能以“Python 打开 FD 后仍传路径”或未经验证的符号链接跟随假设直接实现。最低验证矩阵：

1. 创建 A、B 两个目录，打开 A 的 `O_DIRECTORY` FD，将 FD 传给子进程，确认 `du -sb /proc/self/fd/<fd>/.` 统计的是 A；确认 FD 回收后不泄漏。
2. 在扫描前或扫描中把 A rename 为 A'，并在原路径重建 A 指向 B；确认 FD 扫描仍是 A'，而路径扫描会得到 B，最终只接受与 FD `fstat` 身份一致的结果。
3. 覆盖目录被删除、替换、嵌套 bind/overlay 挂载、无权限、du 非零退出和超时；确认不跨未验证挂载视图发布、不把部分输出当成功，并单独验证符号链接 Source 的解析口径与 Docker 一致；未验证前不假定跟随或不跟随。
4. 在容器或命名空间中重复，验证 `/proc/self/fd` 可见性、`pass_fds`/`close_fds`、子进程超时清理和线程/FD 释放，并记录不可用的内核或运行时边界。

该计划是实现的验收前置；本次文档任务不执行它，也不修改生产代码。

### 4. 线路契约 version 1

Node 的 `usage` 保留旧字段，新增以下字段；HTTP `ContainerDiskUsage` 与 WSS 共用同一模型和校验。身份大整数以十进制字符串无损编码。时间为带 Z 的 UTC RFC3339；Node 的单调时钟用于本地超时和缓存年龄。本表是 Node/Ctrl 共同的 version 1 线路字段总表，不随意改协议名。

| 字段 | 类型与缺省 | 语义 |
| --- | --- | --- |
| `disk_protocol_version` | `int`；缺省 `None` | 存在时为 `1`；缺失按旧协议/未验证处理，不能默认成 1 |
| `docker_id` | `str \| None` | 本次实际 Docker 对象 ID，不是数据库 ID |
| `collector_epoch` | `str \| None` | 采集进程启动 UUID；进程重启即更换 |
| `observation_seq` | `int \| None` | 同 collector epoch 内单调递增；实际状态更新才递增，重复样本不增 |
| `bind_identity` | `BindIdentity \| None` | 身份观测整体；无 bind 时也可存在，status=no_bind |
| `bind_identity.status` | `match / mismatch / missing / unknown / not_running / no_bind` | 首版身份状态；`missing` 表示声明路径不可解析，不等于 no_bind |
| `bind_identity.source_path` | `str \| None` | Docker 配置的宿主路径；保留 `bind_mount_path`，不改存 proc 路径 |
| `bind_identity.source` | `{device: str, inode: str} \| None` | Source 对象；不可取得时 null |
| `bind_identity.actual` | `{device: str, inode: str} \| None` | `/proc/<pid>/root/root` 对象；不可取得时 null |
| `bind_identity.process` | `{pid: int, start_ticks: str, boot_id: str} \| None` | 进程代际；不存在或不可读时 null |
| `bind_identity.mount_id` | `int \| None` | mountinfo 诊断字段；不是永久 ID |
| `bind_identity.checked_at` | `str \| None` | 身份观测完成时间；不是测量时间 |
| `bind_identity.reason` | `str \| None` | 可枚举原因，例如 `source_replaced / source_missing / proc_unavailable / unsupported_view / pid_reused / mountinfo_unavailable` |
| `measurement_status` | `ok / measuring / stale / error / unverified`；缺省 `None` | 测量资格；缺失按 unverified 处理 |
| `measured_at` | `str \| None` | 合计样本的测量时间：overlay 与 bind 各自完成时间中较早者；no_bind 时为 overlay 完成时间。WSS/HTTP 收发时间不得改写 |
| `measurement_identity` | `{collector_epoch, docker_id, process, source, actual, generation} \| None` | 本次字节数绑定的采集/进程/目录/扫描代际；no_bind 时 `source`/`actual` 为 null，仍绑定 Docker 对象与采集代际 |
| `measurement_reason` | `str \| None` | 超时、rc 非零、输出无效、代际改变、视图不支持等原因；不能吞成零 |
| 既有字段 | 保持既有类型 | `container_name / overlay_rw_bytes / bind_mount_bytes / bind_mount_path / bind_mount_source / total_bytes / error` 保留 |

`total_bytes` 只在 match（或已确认 no_bind）与 ok 同时成立、身份和用量未过期且彼此对应时有有效值；其他情况为 null。`measured_at` 是合计样本时间，不是单次 du 完成时间；bind 的 du 完成时间只作为内部组成时间保留，除非未来显式增加可选 component 字段，否则不上 wire。no_bind 的有效 total 仍要求 `measurement_identity` 非空：`source`/`actual` 为 null，但 Docker ID、process、collector_epoch、generation 必须与当前观测一致；`bind_identity.status` 必须为 no_bind，缺少进程或 epoch 证据时 total 为空。match 的有效 total 则要求 `measurement_identity.source`/`actual` 非空且与当前身份一致。`bind_mount_bytes` 可以保留最后一次成功数值作诊断，但不得被消费方当成当前可信总量。最后一次有效数值不在 `total_bytes` 冒充当前值。`checked_at` 的新鲜不能抵消 `measured_at` 的过期，反之亦然。旧字段 `bind_mount_source` 只作兼容展示，不能覆盖新的身份/测量状态。

Ctrl 的 `disk_identity_status`、`disk_measurement_status`、`disk_identity`、`disk_identity_checked_at`、`disk_measured_at`、`disk_received_at` 是数据库持久化列名，不是线路字段名；`disk_identity` 必须无损保存上表的嵌套对象、epoch/seq 和原因，不得重命名或把整数转成浮点。`disk_received_at` 只由 Ctrl 本地记录，Node 不发送。`bind_identity` 缺失时 Ctrl 按 `unknown`，`measurement_status` 缺失时按 `unverified`。协议名 `disk_protocol_version` 保持不变；旧消费方可以忽略未知字段，但新消费方必须把缺少协议版本的样本视为未验证。

| Ctrl 持久化列 | Node version 1 线路来源 |
| --- | --- |
| `disk_identity_status` | `bind_identity.status` |
| `disk_measurement_status` | `measurement_status` |
| `disk_identity` | `disk_protocol_version`、`docker_id`、`collector_epoch`、`observation_seq`、`bind_identity`、`measurement_identity`、`bind_identity.reason`、`measurement_reason` |
| `disk_identity_checked_at` | `bind_identity.checked_at` |
| `disk_measured_at` | `measured_at` |
| `disk_received_at` | 仅 Ctrl 本地接收时间，无 Node 字段 |

Ctrl 侧持久化与门禁见 [gate-disk-check-on-mount-identity design](../../../../FuxiYu_CtrKernel/openspec/changes/gate-disk-check-on-mount-identity/design.md)。两端按同一 version 1 总表校验；Node 发送真实 UTC 时间，Ctrl 对超出允许偏差或在未来的时间降级为 `clock_skew`/未验证，不能用接收时间补齐。

每个实际状态更新递增 `observation_seq`；同一状态和样本的重发不改变 `measured_at`。Ctrl 按当前有效 WSS 连接和 epoch 接收：旧连接结束后其待处理数据不得覆盖新连接；同 epoch 的倒序观测必须拒绝。新连接在收到首个完整新协议观测前不恢复可信状态。此局部发布排序不解决跨请求的 Q70 同名代际授权问题。

### 5. 首版 Source mismatch：停止自动磁盘响应，不自动改目录

默认 source mismatch 时，Node 不把任一目录用量作为可自动处置的当前总量：`total_bytes` 为空，保留明确的 mismatch 证据和最后成功值（仅诊断）。未知、missing、not_running、身份/测量过期、视图不支持同样不产生可处置总量。

Node 不自动改名、不重挂载、不创建或选择另一条宿主路径、不改写 Docker 配置，也不把 actual 路径替换成 Source 后继续按路径执行删除或清理。Ctrl 侧按配套变更 `gate-disk-check-on-mount-identity` 暂停该容器的自动冻结、解冻重置、升级删除与挂载清理，并显式展示原因；恢复可信匹配和新测量后，再按 Ctrl 的既有累计策略恢复处置。

### 6. Q70、Q71、Q72 的边界

**Q70 独立。** 本变更的 Docker ID、dev/inode、collector epoch、observation_seq 和本地 generation 只服务于磁盘采样有效性，MUST NOT 被当作跨进程操作代际、删除授权或清理路径的原子身份。即使磁盘身份匹配，也不能据此删除容器或目录。严格跨进程同名代际仍需 Q70 单独定义的协议，本变更既不实现也不替代它。

**Q71 仅后续待选。** 首版不按 actual 对象计量，也不允许在 mismatch 时冻结。若后续采纳“按实际对象计量并允许冻结”，必须同时定义预期清理对象身份、所有手动/自动清理入口和动作时验证；冻结资格不等于清理授权，清理必须被阻断或另行显式授权。该扩展不在本变更内。

**Q72 已由用户决定。** 异常观测期不依据无效样本执行删除，也不新增顺延；恢复可信高用量后，按原累计有效冻结天数判断，达到阈值且机器可管辖、无有效人工宽限时可在该轮升级删除。不重设 `first_frozen_at`，不新增 `review_required` 或 invalid 标记阻止累计删除；既有机器不可用 deferral 和人工宽限继续保留。Node 只负责提供真实的 `measured_at`、`checked_at` 和身份/测量状态，不自行解释或改写冻结累计；Ctrl 负责该策略。

## Risks / Trade-offs

- [采集失败时暂时没有自动限额响应] → 显式展示错误、告警节流和最后测量时间；旧 Node 的未验证状态也可见，不隐藏为正常。
- [目录根身份不覆盖子挂载与持续写入] → 无法验证的视图降级；保留扫描时间范围和 apparent-size 口径，不声称块占用或快照精确性。
- [inode/设备号复用] → 只在有 FD 与进程代际约束的短期测量中比较，不用于持久查找目录。
- [删除前再次有人修改目录] → 本补丁不是删除路径的原子校验；清理协议的预期身份与动作时验证仍由 Q71 单独约束。
- [把磁盘证据当成操作代际] → 明确禁止；Q70 的跨进程授权必须独立实现，磁盘匹配不能成为删除/清理依据。
- [恢复时把 checked_at 当成 measured_at] → 时间语义分开，Ctrl 只能按真实测量时间判龄；否则 Q72 的恢复累计会被错误重置或延长。
- [FD 验证不足] → 隔离 Linux 计划作为实现前置；未验证前不把 `/proc/self/fd` 或符号链接跟随当作已证明行为。

## Migration Plan

先部署 Ctrl `gate-disk-check-on-mount-identity`，完成加列与未验证默认值；再逐机部署 Node，核对协议版本、身份覆盖率、真实测量时间及失败原因，最后验证正常长期容器的冻结链路。不得在生产通过制造错误挂载或真实删除验收。

联合验收至少覆盖 Q72：异常期不动作、恢复可信高用量可按原累计立即升级、恢复低用量正常重置、机器不可用 deferral 与人工宽限保留、没有 `review_required` 阻挡；同时验证 Q70 的操作代际独立性，以及 Q71 扩展启用后冻结可用但清理仍被阻断的边界（当前首版不启用该扩展）。

Node 回滚后 Ctrl 把旧格式标为 unverified，自动磁盘响应暂停且异常可见，不能回落旧字节数执行删除。保留原数据库历史值和新增列。回滚 Ctrl 会丢失门禁，必须明确该风险，不把回滚当作无影响操作。

## Source references

- `docker_operates/disk_usage_cache.py`：`collect_bind`、`collect_container`、`get_bind`、`snapshot`。
- `schemas/container.py`、`network/api.py`、`network/wss.py`：HTTP 磁盘响应与 WSS 缓存输出。
- [inode(7)](https://man7.org/linux/man-pages/man7/inode.7.html)：inode 的文件系统作用域。
- [proc_pid_root(5)](https://man7.org/linux/man-pages/man5/proc_pid_root.5.html)、[proc_pid_mountinfo(5)](https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html)：进程文件系统视图与挂载信息。
- [proc(5)](https://man7.org/linux/man-pages/man5/proc.5.html)：`/proc/<pid>/stat` 的 starttime 与进程代际。
- [open(2)](https://man7.org/linux/man-pages/man2/open.2.html)、[fstat(2)](https://man7.org/linux/man-pages/man2/fstat.2.html)：目录 FD 与身份一致性检查。
