# Spec Delta

## ADDED Requirements

### Requirement: 业务路径的确认与有界纠正

Node SHALL 将 `bind_mount_path` 作为业务路径，并在 Docker `/root` bind Source 与运行/暂停容器 `/proc/<pid>/root/root` 实际目录对象一致时确认该 Source 路径。Source 与实际对象不一致，或 Source 缺失/不可解析但 actual 仍可读时，Node MUST 仍只在既有容器存储根、Source 父目录直接子项和最后确认路径父目录直接子项等有界候选内定位，唯一对象匹配才修正 `bind_mount_path`；Source 缺失本身 MUST NOT 直接判 unresolved。只有 actual 不可读、允许范围内无可命名路径、无匹配或歧义才 `unresolved`。目录对象编号只用于本次内部定位与调试，MUST NOT 进入 HTTP/WSS 业务身份字段，MUST NOT 作为恢复、长期资格、冻结、删除或清理前置。Node MUST NOT 修改目录、Docker 配置或重挂载，也 MUST NOT 返回 `/proc` 临时路径；旧核对晚回不得改写新路径。

#### Scenario: Source 与实际挂载一致

- **WHEN** Docker Source 可解析且其目录对象与运行容器 `/root` 实际挂载对象一致
- **THEN** `mount_path_status=resolved`，Node 使用该 Source 路径作为业务 `bind_mount_path`

#### Scenario: 错位且候选唯一

- **WHEN** Source 指向目录 A，实际 `/root` 指向有界候选目录 B，且只有 B 的对象匹配
- **THEN** `mount_path_status=resolved`，`bind_mount_path` 修正为 B，`configured_mount_path` 仍保留 A 作为诊断，不修改 A/B 目录或 Docker 配置

#### Scenario: 候选歧义或无匹配

- **WHEN** 有界候选中有多个或没有目录对象匹配 actual
- **THEN** `mount_path_status=unresolved`，保留原有/最后确认业务路径；无已有路径时为 null，不猜目录、不全盘递归

#### Scenario: Source 改名后原路径缺失但新路径唯一

- **WHEN** Docker Source 指向的旧路径已被改名/删除，而 `/proc/<pid>/root/root` 仍可读且允许父目录直接子项中只有一个目录对象匹配 actual
- **THEN** `mount_path_status=resolved`，`bind_mount_path` 修正为该唯一新路径；不因 Source 缺失直接标 unresolved，不修改目录/Docker 配置

#### Scenario: Source 缺失但无命名候选

- **WHEN** Source 路径已消失且 actual 可读，但允许根/父目录直接子项和已有路径中没有可命名匹配，或多个匹配/越界
- **THEN** `mount_path_status=unresolved`，保留原有/最后确认业务路径；无已有路径时为 null，不猜目录、不全盘递归

#### Scenario: 无 PID 或 proc 不可读

- **WHEN** 容器停止/重启过渡而没有可验证 PID，或 `/proc/<pid>/root/root` 不可读
- **THEN** 分别标 `not_running`/`unresolved`，保留已有业务路径，不返回 `/proc` 临时路径，不把诊断变成业务阻断

#### Scenario: 旧路径核对晚回

- **WHEN** 一次路径核对已开始，期间容器换代或新核对已更新业务路径，旧核对随后返回
- **THEN** Node 内部复核活跃容器/Docker ID/PID 与路径核对序号，丢弃旧结果，不得改写新对象/新活跃容器路径；该保护不进入测量或业务门禁

### Requirement: 路径诊断不构成业务门禁

`configured_mount_path`、`mount_path_status`、`mount_path_observed_at` SHALL 只作路径诊断和业务路径修正依据，MUST NOT 作为恢复、长期资格、冻结、删除、清理或测量有效性的独立前置/授权。已存在有效业务 `bind_mount_path` 且本次路径测量成功时，仅 `mount_path_status=unresolved` MUST NOT 阻断业务；诊断失败 MUST NOT 被伪装成 `measurement_error`。Ctrl 只将当前认证机器、活跃容器的 `mount_path_status=resolved` 修正持久化到 `containers.bind_mount_path`，MUST NOT 凭 inode 批改历史快照或旧清理记录；固定 8 字段 `long_term_eligibility` 不变。

#### Scenario: unresolved 但既有路径测量成功

- **WHEN** 路径核对无法唯一定位而保留既有业务路径，随后该路径的 du 成功、组成完整且测量未过期
- **THEN** 业务仍可使用该路径和有效测量；`mount_path_status=unresolved` 不阻断恢复/长期/冻结/删除/清理，也不把测量标成 error

#### Scenario: 路径诊断失败但测量独立成功

- **WHEN** Docker Source 诊断、proc 读取或候选核对失败，而独立业务路径 du 成功且真实测量时间有效
- **THEN** 测量状态可为 ok；路径诊断保持 unresolved，不能互相伪装

#### Scenario: Ctrl 持久化当前修正

- **WHEN** 当前认证机器上的活跃容器得到 `mount_path_status=resolved` 的真实业务路径
- **THEN** Ctrl 只把该修正写入 `containers.bind_mount_path`；不批量改写历史快照、旧清理记录或其它机器的路径

#### Scenario: Ctrl 使用测量计划字段

- **WHEN** Ctrl 接收路径/测量快照
- **THEN** 持久化 `disk_measurement_status`、`disk_measured_at`、`disk_received_at`、`disk_observation`（协议/会话排序/测量路径/路径诊断），移除旧目录身份列；新记录读取修正后的路径，不按 inode 批改历史

#### Scenario: 固定长期资格字段

- **WHEN** Ctrl 计算长期资格
- **THEN** 固定 8 字段 `long_term_eligibility` 不变；路径诊断或测量路径不是新增门禁字段

### Requirement: 按业务路径测量与路径变更失效

Node SHALL 按当前业务 `bind_mount_path` 执行 bind 用量测量，并在 `measurement_mount_path` 记录本次实际测量路径。缓存 MUST 按规范化业务路径命中，MUST NOT 以目录对象、PID 或旧身份做测量缓存键。业务路径变更后 MUST 使旧路径测量失效并重新测量；旧路径字节数 MUST NOT 改贴到新路径。

#### Scenario: 业务路径 A 修正为 B

- **WHEN** 路径纠正把业务路径从 A 改为 B，而 A 的 du 仍在途
- **THEN** A 的晚到结果不能成为 B 的测量；B 重新测量完成前 total 为空或 measuring

#### Scenario: 测量路径与当前路径不一致

- **WHEN** `measurement_mount_path` 与当前业务 `bind_mount_path` 不同，即使字节数和 measured_at 看似新鲜
- **THEN** 该测量不得作为当前有效 total，必须按新路径重新测量

#### Scenario: 路径未变但测量独立失败

- **WHEN** 业务路径未变，du 非零退出、超时、空输出、权限失败或路径不存在
- **THEN** 按原有测量错误处理，保留真实原因和最后成功值作诊断，不把缺组成或异常当 0

### Requirement: 测量有效性、组成与真实时间

`total_bytes` SHALL 仅在 `measurement_status=ok`、overlay/bind 组成完整（Docker 明确 `no_bind` 时只要求 overlay）、`measured_at` 在真实允许年龄内、`measurement_mount_path` 等于当前业务路径、且响应/观测顺序有效时非空。有效性谓词 MUST NOT 检查 `mount_path_status=resolved`、目录 dev/inode、PID 或 Source/actual 对象匹配；缺组成、异常、超时或旧值 MUST NOT 当 0。overlay-only MUST 只来自 Docker 成功确认的 `no_bind`，异常不得解释为 `no_bind`。

#### Scenario: unresolved 路径的同一路径测量有效

- **WHEN** `mount_path_status=unresolved`，但已有业务路径未变，du 成功、overlay/bind 组成完整、measured_at 新鲜且 measurement_mount_path 与业务路径一致
- **THEN** total 可有效；不因 unresolved 或 inode 未验证而清空

#### Scenario: resolved 但测量失败

- **WHEN** `mount_path_status=resolved`，但 du 非零退出、超时、输出不可解析或组成缺失
- **THEN** total 为空并记录测量失败/未验证，不能因路径 resolved 而发布数字

#### Scenario: overlay-only 非 no_bind

- **WHEN** 容器存在 bind，或 Docker inspect 未明确确认无 bind，而 overlay 数字可得
- **THEN** 不能发布 overlay-only total，也不能把 bind 缺失当 0

#### Scenario: 真实测量时间过期

- **WHEN** measured_at 超过允许年龄，而路径最近刚被核对
- **THEN** total 为空并标 stale/未验证；mount_path_observed_at 不能延长测量有效期

### Requirement: 轻量路径核对独立于重型测量

Node SHALL 用有界轻量周期独立核对业务路径，MUST NOT 执行 du 或持有 du 缓存锁；`mount_path_observed_at` 记录真实核对时间。路径核对失败或过期只产生路径诊断，不得把测量改成 error，也不得阻断已有业务路径的测量；WSS/HTTP 读取 MUST NOT 触发 du 或刷新 measured_at。

#### Scenario: du 阻塞时路径核对仍推进

- **WHEN** 大目录 du 持续较长时间，路径核对线程按周期完成
- **THEN** mount_path_observed_at 推进，但测量是否有效仍只由 measured_at、组成、路径一致和顺序决定

#### Scenario: 路径核对超时

- **WHEN** Docker inspect、proc 读取或有界候选核对超时/失败
- **THEN** 标 unresolved 并保留已有业务路径，不把独立成功的测量改成 error，也不执行全盘搜索

### Requirement: 运行状态与 no_bind 边界

运行或暂停且进程存续的容器 SHALL 按相同路径核对规则处理；停止/重启过渡且无可验证 PID 时 SHALL 标 `not_running`；proc/actual 不可读，或 actual 可读但无唯一允许候选时 SHALL 标 `unresolved`。Docker 成功确认无 `/root` bind 时 SHALL 标 `no_bind`，`bind_mount_path=null`、`measurement_mount_path=null`、只允许 overlay-only；inspect 失败、超时或 Mounts 不可读 MUST NOT 推断为 `no_bind`，unresolved/not_running MUST NOT 清空已有业务路径，也不得把缺少路径当作零用量。

#### Scenario: paused 容器路径可核对

- **WHEN** 容器 paused 且 PID/根挂载仍可读取
- **THEN** 允许路径核对和按业务路径测量，不因暂停自动清空已有路径或测量

#### Scenario: stopped/restarting 无稳定 PID

- **WHEN** 容器没有可验证 PID
- **THEN** 标 `not_running`，保留最后业务路径；不把 Source 单侧当实际路径，也不猜测新路径

#### Scenario: Docker 明确 no_bind

- **WHEN** 成功 Docker inspect 确认不存在 `/root` bind
- **THEN** 标 `no_bind`，`bind_mount_path=null`、`measurement_mount_path=null`，overlay-only 规则按明确 no_bind 处理；Ctrl 接收端清空当前活跃业务 bind 路径，不能保留旧路径再判同路径

#### Scenario: Docker inspect 失败

- **WHEN** Docker inspect 失败、超时或 Mounts 不可用
- **THEN** 标 `unresolved`，保留已有业务路径；不得推断为 no_bind，也不得把路径诊断失败说成测量失败或据此清空路径

#### Scenario: unresolved 不清空路径

- **WHEN** 路径核对为 unresolved 或 not_running
- **THEN** 已有 `bind_mount_path` 与 `measurement_mount_path` 保留；只有成功确认 no_bind 才按 no_bind 置空

### Requirement: 路径与测量不构成删除清理授权

Node SHALL 仅将路径、测量状态和真实时间用于磁盘事实与业务路径修正。MUST NOT 将 inode、PID、路径诊断、collector_epoch、observation_seq 或测量会话用作跨进程删除/清理授权、清理目标选择或目录改名依据。Q70 的跨进程同名代际协议独立于本变更；Q72 的累计政策保持不变：采集盲区不额外补偿、累计继续，异常/无效测量不动作、不新增顺延，恢复可信高用量后按原累计有效冻结天数判断，不重设 first_frozen_at，不新增 `review_required`，机器不可用 deferral 与人工宽限保留。

#### Scenario: Q72 恢复高用量

- **WHEN** 异常期测量无效，随后业务路径测量恢复可信高用量且机器可管辖、无有效人工宽限
- **THEN** 按原累计有效冻结天数判断是否升级；路径诊断 unresolved 若不影响测量有效性，不成为阻断理由

#### Scenario: 路径匹配也不能授权清理

- **WHEN** 路径核对 resolved 且测量有效
- **THEN** 该事实不能单独授权删除容器或清理宿主目录；清理仍需其既有入口校验和显式授权

#### Scenario: 同名新容器与旧帧

- **WHEN** 旧容器删除帧在途，随后同名新容器创建
- **THEN** 路径/测量事实不能证明旧帧属于新代；Q70 隔离仍需独立实现

## MODIFIED Requirements

### Requirement: ContainerDiskUsage 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。磁盘协议保持 `disk_protocol_version=1`；路径诊断和测量字段均可用 `None` 缺省。旧 Node 缺少 `measured_at`、`measurement_mount_path` 或采样排序标识时 MUST 按测量未验证处理，不能解释为缺目录身份；缺少 `mount_path_status` 按 `unresolved`；缺少 `disk_protocol_version` 按未验证。HTTP 与 WSS 共用此模型，`null` 不得在响应模型/JSON 序列化中丢失。

`bind_mount_path` 是业务路径；`configured_mount_path` 是 Docker Source 诊断；`measurement_mount_path` 是实际测量路径。`total_bytes` 仅在 measurement_status=ok、组成完整（明确 no_bind 仅 overlay）、measured_at 真实年龄内、measurement_mount_path 等于当前业务路径且顺序有效时非空；不检查 mount_path_status=resolved 或 inode。缺组成、非零 du、异常、过期或旧值不得当 0；最后 bind bytes 只作诊断。

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `container_name` | `str \| None` | `None` |
| `overlay_rw_bytes` | `int \| None` | `None` |
| `bind_mount_bytes` | `int \| None` | `None`；最后成功值仅诊断 |
| `bind_mount_path` | `str \| None` | 业务路径；Node 确认后返回修正值；unresolved/not_running 保留已有/最后确认路径；no_bind 为 null |
| `configured_mount_path` | `str \| None` | Docker Source 诊断，不是业务路径 |
| `mount_path_status` | `Literal["resolved","unresolved","not_running","no_bind"] \| None` | 缺省按 unresolved |
| `mount_path_observed_at` | `str \| None` | UTC 路径核对时间，不是测量时间 |
| `bind_mount_source` | `str \| None` | 既有 fresh/cache/measuring/missing 采集来源 |
| `total_bytes` | `int \| None` | 仅在 measurement_status=ok、组成完整、真实年龄、同业务路径、顺序有效时非空 |
| `error` | `str \| None` | `None` |
| `disk_protocol_version` | `int \| None` | 存在时为 `1` |
| `collector_epoch` | `str \| None` | 采集会话 UUID，不是目录身份 |
| `observation_seq` | `int \| None` | 同 epoch 采样排序，不是目录身份 |
| `measurement_status` | `Literal["ok","measuring","stale","error","unverified"] \| None` | 缺省按 unverified |
| `measured_at` | `str \| None` | 合计真实测量时间，取组成中较早者；UTC 带 Z |
| `measurement_mount_path` | `str \| None` | 本次实际测量业务路径；no_bind 为 null，unresolved 不因诊断清空 |
| `measurement_reason` | `str \| None` | 失败/过期/路径变化等诊断 |

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例

#### Scenario: 旧 Node 缺少测量时间

- **WHEN** 旧 Node 只返回字节数、路径和来源，缺少 measured_at、measurement_mount_path 或采样排序标识
- **THEN** 消费方按测量未验证处理，不推断目录身份，不用接收时间补齐，也不恢复旧字节数为有效

#### Scenario: unresolved 但有同路径有效测量

- **WHEN** mount_path_status=unresolved，而业务路径未变、measurement_status=ok、measured_at 新鲜且 measurement_mount_path 与业务路径一致
- **THEN** total_bytes 可有效，不因路径诊断被清空

#### Scenario: 路径变更后的旧样本

- **WHEN** 业务 bind_mount_path 已从 A 改为 B，而缓存样本的 measurement_mount_path 仍为 A
- **THEN** 该样本不得成为 B 的 total，必须按 B 重新测量

#### Scenario: 缺组成或非零 du

- **WHEN** overlay/bind 组成缺失，或 du 非零退出/超时/空输出
- **THEN** total_bytes 为 None，measurement_status 标 error/unverified/stale，不把缺失当 0

#### Scenario: null 字段序列化

- **WHEN** 路径或测量字段为 None 并经 HTTP response_model/WSS JSON 返回
- **THEN** 字段仍存在或按协议缺省可解释，不能被静默改名/丢弃为成功值
