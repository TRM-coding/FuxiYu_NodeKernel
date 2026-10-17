# Spec Delta

## ADDED Requirements

### Requirement: 声明路径与实际挂载的身份验证

Node SHALL 在本机比较 Docker 声明的 `/root` bind Source 与该容器实际 `/root` 挂载对象的 `(st_dev, st_ino)`，并关联本次 Docker 对象、PID starttime、boot ID 和 collector epoch。设备号、inode 与 starttime MUST 以十进制字符串上报；相同 inode 但设备不同 SHALL 判为 mismatch；Source 路径不存在 SHALL 标为 missing，其他必要证据不可取得 SHALL 标为 unknown。身份结果 MUST NOT 自动改名、重挂载、改写 Docker 配置、搜索或切换另一条宿主路径，也不得把 actual 路径替换 Source 后用于删除/清理。

#### Scenario: 手工改名造成声明与实际挂载错位

- **WHEN** Source 指向目录 A，运行中容器实际挂载目录 B，且两者设备号或 inode 不同
- **THEN** 报告 `mismatch` 及双方身份，不把 A 的用量标为该容器可信用量

#### Scenario: inode 相同但位于不同文件系统

- **WHEN** 两个目录 inode 数值相同但设备号不同
- **THEN** 比较结果为 `mismatch`，不能报告匹配

#### Scenario: 未改名但目录被替换

- **WHEN** Source 字符串未变而路径解析所得目录对象改变
- **THEN** 报告新的身份观测，并使旧对象对应的用量失效

#### Scenario: 错位时不自动修目录

- **WHEN** 身份比较结果为 `mismatch`、`missing` 或 `unknown`
- **THEN** Node 只报告状态与证据，不改名、不重挂载、不改 Docker 配置、不选择另一条宿主路径，也不执行自动磁盘处置

### Requirement: 身份观测独立于重型用量采集

Node SHALL 用有界的轻量观测周期检测挂载身份变化，不能等到全目录用量缓存到期才检查身份。轻量探测 MUST NOT 执行 du 或占用 du 的缓存锁；快照只读取观测缓存，身份观测过期、失败或发现不匹配时 MUST 显式降级，不能继续发布旧的匹配结论。发布与用量线程回填 SHALL 遵守同一代际检查。

#### Scenario: 用量缓存有效期间发生目录替换

- **WHEN** 最近用量仍在缓存期内，但下一次身份探测发现 Source 已换成不同目录对象
- **THEN** 后续快照报告错位并停止将旧用量标为有效，不等待原用量 TTL 到期

#### Scenario: 身份线程停止而 WSS 仍在推送

- **WHEN** 身份观测超过允许年龄而没有新的成功观测
- **THEN** 快照报告 `unknown` 或过期状态，重复推送不能延长身份有效期

#### Scenario: du 扫描阻塞时探测仍更新

- **WHEN** 大目录 du 扫描持续较长时间，身份探测线程仍按周期完成观测
- **THEN** 身份时间正常推进；若测量本身已过期，`total_bytes` 仍为空，不能因探测新鲜而恢复旧测量

#### Scenario: WSS 读取不触发 du

- **WHEN** Ctrl 建立 WSS 连接并读取磁盘快照
- **THEN** 读取路径只返回缓存和状态，不执行新的 du，也不因读取动作刷新测量时间

### Requirement: 目录身份约束测量与缓存回填

有效用量 SHALL 属于经验证的目录对象、Docker 对象、进程代际和扫描代际，并保留真实测量时间；确认 `no_bind` 时没有目录对象，overlay 用量 SHALL 绑定已确认的 Docker 对象、进程和采集代际，`measurement_identity` MUST 非空且 `source`/`actual` 为 null；match 时 `measurement_identity.source`/`actual` MUST 非空。缓存命中与回填 MUST 同时匹配 Docker ID、PID starttime、boot ID、collector epoch、Source/actual 的 dev+inode（no_bind 时为 null）和本地 generation；仅路径、名称或 inode 相同不足以命中。测量前后验证失败或代际改变时 MUST 丢弃结果；身份恢复匹配后 SHALL 重新测量，不能把旧对象的字节数改贴新身份。首版 mismatch 时 SHALL 停止发布可供自动处置的总用量。

#### Scenario: 同名路径已恢复为正确目录

- **WHEN** Source 的 inode 从 A 变成实际挂载的 B，旧缓存测的是 A
- **THEN** 身份可以恢复匹配，但用量保持 `measuring`，直到 B 的新测量完成

#### Scenario: 长时间扫描与同名重建交错

- **WHEN** 旧容器的扫描完成前发生同名重建或同 PID 被新进程复用
- **THEN** 旧结果不能回填到新容器或新进程的有效用量中

#### Scenario: Node 重启后的旧测量

- **WHEN** Node 进程重启产生新的 collector epoch，而缓存里仍有上一 epoch 的字节数
- **THEN** 旧字节数不能作为新 epoch 的有效测量，必须重新测量

#### Scenario: 身份与测量时间都新鲜但代际不匹配

- **WHEN** `checked_at` 和 `measured_at` 都在允许年龄内，但 `measurement_identity` 的 Docker ID、进程、目录或 generation 与当前身份不同
- **THEN** 该样本标为 `stale` 或 `error`，`total_bytes` 为空，不能只凭时间新鲜发布

### Requirement: 不完整扫描与不支持视图显式失败

超时、非零退出码、空输出、解析失败、权限错误和视图不支持 SHALL 标为测量失败，MUST NOT 把部分输出或旧值升级为成功；`rc != 0` 时即使 stdout 含数字也不采纳。仅根目录身份匹配不能证明嵌套挂载视图一致；无法验证的视图 SHALL 标为不支持或未知。持续写入中的成功扫描 SHALL 表示一段时间内的观测，不声称具有文件系统快照的一致性。

#### Scenario: 扫描报错但标准输出含一个数字

- **WHEN** 用量命令退出码非零，即使标准输出包含字节数
- **THEN** 不接受该数字作为新的有效测量，保留错误原因与最后成功测量时间

#### Scenario: 扫描超时或输出不可解析

- **WHEN** du 超过超时时间、输出为空或无法解析为单个非负整数字节数
- **THEN** 终止该次扫描并标为失败，保留最后成功值仅作诊断，不发布新的 `total_bytes`

#### Scenario: 根目录相同但存在不同的嵌套挂载

- **WHEN** Source 与实际 `/root` 根目录身份相同，但无法证明其子挂载视图与计量范围相符
- **THEN** 不报告有效总用量，明确标记视图未验证

### Requirement: 运行状态下的验证边界

运行及暂停且进程仍存续的容器 SHALL 按相同身份规则验证；停止或重启过渡且无可验证 PID 时 SHALL 标为 `not_running`，有 PID 但宿主 proc 不可见时 SHALL 标为 `unknown`。Docker 观测成功且明确未配置 `/root` bind 的容器 SHALL 显式标为 `no_bind`，仅在 overlay 测量有效且 `measurement_identity` 与当前 Docker 对象、进程、collector epoch、generation 一致时提供总用量；读取 Mounts 异常 MUST 标为 unknown，不能当作 no_bind。不可验证 MUST NOT 等同于零用量或容器不存在。

#### Scenario: 容器暂停但进程与挂载保留

- **WHEN** 容器处于 paused 且进程代际和挂载可验证
- **THEN** 允许验证和采集，不因暂停自动把磁盘事实标成缺失

#### Scenario: 容器停止或 Node 看不到宿主 proc

- **WHEN** 没有可验证的容器进程，或当前部署权限无法读取其实际挂载
- **THEN** 报告 `not_running` 或 `unknown`，不能用 Source 单侧观测冒充实际挂载验证

#### Scenario: Docker 确认没有配置 root bind

- **WHEN** 本次 Docker 观测成功且确认不存在 `/root` bind
- **THEN** 明确报告 `no_bind`，有效总用量只包含可信 overlay，不把探测异常解释为没有 bind

#### Scenario: 读取 Docker Mounts 异常

- **WHEN** Docker inspect 调用失败、超时或 `Mounts` 字段不可用
- **THEN** 报告 `unknown` 与采集错误，不能推断为 `no_bind`，也不能发布可处置总量

#### Scenario: no_bind 的 overlay 测量缺少进程身份

- **WHEN** Docker 确认无 bind，overlay 字节数有效，但 `measurement_identity` 缺少 process 或 collector epoch
- **THEN** `total_bytes` 为空并标为未验证，不能用 overlay 数字独立发布

### Requirement: 磁盘证据不构成删除或清理授权

Node SHALL 仅将身份与测量用于磁盘事实和样本有效性。MUST NOT 将 inode、Docker ID、collector epoch、observation_seq、本地 generation 或 match 状态用作跨进程操作代际、删除/清理授权、清理目标选择或目录改名依据。Q70 的跨进程同名代际协议独立于本变更；任何清理必须另行验证预期目标身份，首版 mismatch 时 MUST NOT 自动清理。

#### Scenario: 身份匹配后请求清理

- **WHEN** Node 报告 `match` 且 Ctrl 准备清理宿主目录
- **THEN** 该磁盘证据不能单独授权清理；清理入口仍需验证自己的预期目标身份，mismatch 或过期时不得自动清理

#### Scenario: 同名新容器出现后的旧删除帧

- **WHEN** 旧容器的删除帧在途，随后同名新容器创建
- **THEN** 磁盘身份匹配不能证明删除帧属于新代；Q70 的跨进程代际隔离仍需独立实现，不能把本变更当成已解决

## MODIFIED Requirements

### Requirement: ContainerDiskUsage 数据契约 [schemas/container.py]

Node SHALL 通过 Pydantic 模型处理此对象，保留嵌套类型、继承字段和 Field 约束；缺失必填字段或非法值在进入业务操作前由请求校验拒绝。新增 version 1 顶层字段均为可选，旧负载缺省为 `None`；`bind_identity=None` 按 `unknown`、`measurement_status=None` 按 `unverified` 处理。消费方 MUST 把缺少 `disk_protocol_version` 或测量身份的样本标为未验证，不能推断 match。HTTP 与 WSS 共用此模型，手动刷新 MUST NOT 用接收时间伪造 `measured_at`。

原有职责保持不变：overlay 与 bind_mount 分开计 bytes，total_bytes 为合计；bind_mount_source 保留 fresh/cache/measuring/missing 采集来源语义。`bind_mount_source` 仅为旧展示/诊断兼容，MUST NOT 覆盖 `bind_identity.status`、`measurement_status` 或 `measured_at`；新消费方以 version 1 字段为准。`total_bytes` 还要求 overlay 与 bind 组成完整（no_bind 时只要求 overlay），任一组分缺失或为 `None` 时为 `None`。`measured_at` 不是单次 du 完成时间，也不是接收时间；bind 的 du 时间只作为内部组成。有效 total（含 no_bind）要求 `measurement_identity` 非空且 Docker ID、process、collector_epoch、generation 与当前观测一致；no_bind 时 `source`/`actual` 为 null 且 `bind_identity.status=no_bind`，match 时 `source`/`actual` 必须非空；缺少进程或 epoch 证据时不得发布 total。

| 字段/成员 | 类型或值 | 默认值/约束 |
| --- | --- | --- |
| `container_name` | `str \| None` | `None` |
| `overlay_rw_bytes` | `int \| None` | `None` |
| `bind_mount_bytes` | `int \| None` | `None`；可保留最后成功值，但不得当作当前可信总量 |
| `bind_mount_path` | `str \| None` | `None`；保留既有路径语义 |
| `bind_mount_source` | `str \| None` | `None`；既有 fresh/cache/measuring/missing 来源 |
| `total_bytes` | `int \| None` | `None`；仅 match/no_bind + `measurement_status=ok` + 身份与测量均未过期且 `measurement_identity` 与当前身份一致时非空 |
| `error` | `str \| None` | `None` |
| `disk_protocol_version` | `int \| None` | `None`；存在时为 `1` |
| `docker_id` | `str \| None` | `None` |
| `collector_epoch` | `str \| None` | `None`；采集进程启动 UUID |
| `observation_seq` | `int \| None` | `None`；同 epoch 内单调递增 |
| `bind_identity` | `BindIdentity \| None` | `None` |
| `measurement_status` | `Literal["ok", "measuring", "stale", "error", "unverified"] \| None` | `None`；缺失按 unverified |
| `measured_at` | `str \| None` | `None`；合计样本测量时间，取 overlay 与 bind 各自完成时间中较早者；no_bind 时为 overlay 完成时间；RFC3339 UTC 带 Z |
| `measurement_identity` | `MeasurementIdentity \| None` | `None` |
| `measurement_reason` | `str \| None` | `None` |

`BindIdentity` 成员：

| 成员 | 类型或值 | 约束 |
| --- | --- | --- |
| `status` | `Literal["match", "mismatch", "missing", "unknown", "not_running", "no_bind"]` | 必填 |
| `source_path` | `str \| None` | Docker 声明的宿主路径 |
| `source` | `{device: str, inode: str} \| None` | 设备号和 inode 为十进制字符串 |
| `actual` | `{device: str, inode: str} \| None` | 设备号和 inode 为十进制字符串 |
| `process` | `{pid: int, start_ticks: str, boot_id: str} \| None` | start_ticks 为十进制字符串 |
| `mount_id` | `int \| None` | 仅本轮诊断，不是永久 ID |
| `checked_at` | `str \| None` | 身份观测完成时间，不是测量时间 |
| `reason` | `str \| None` | 可枚举原因 |

`MeasurementIdentity` 成员：

| 成员 | 类型或值 | 约束 |
| --- | --- | --- |
| `collector_epoch` | `str` | 采集进程启动 UUID |
| `docker_id` | `str` | 本次 Docker 对象 ID |
| `process` | `{pid: int, start_ticks: str, boot_id: str} \| None` | 采样进程代际 |
| `source` | `{device: str, inode: str} \| None` | 采样时 Source 对象；no_bind 时为 null |
| `actual` | `{device: str, inode: str} \| None` | 采样时 actual 对象；no_bind 时为 null |
| `generation` | `int` | 本地扫描/身份代际 |

#### Scenario: 字段校验与缺省值

- **WHEN** 消费者构造该模型且提供有效必填字段
- **THEN** 模型采用声明的缺省值并保持继承字段；违反类型或 Field 边界的输入不作为有效实例

#### Scenario: 旧协议负载缺少新字段

- **WHEN** 旧 Node 只返回既有字节数、路径和来源字段
- **THEN** 新字段使用 `None` 缺省，`disk_protocol_version` 缺失，消费方将其标为未验证而不是推断 match

#### Scenario: 大整数身份往返

- **WHEN** device、inode 或 PID starttime 的十进制值大于 2^53，模型经 JSON 编码再解码
- **THEN** 身份字符串逐字保持不变，不能因浮点舍入改变比较结果

#### Scenario: mismatch 样本不产生当前总量

- **WHEN** `bind_identity.status` 为 `mismatch` 或 `unknown`，即使 `bind_mount_bytes` 保留了最后成功值
- **THEN** `total_bytes` 为 `None`，最后成功值只能作为诊断字段，不能作为当前可处置用量

#### Scenario: HTTP 手动刷新复用同一测量时间

- **WHEN** 手动刷新接口返回与缓存相同的测量结果
- **THEN** `measured_at` 保持原值，不能用响应时间刷新；没有新测量时 `measurement_status` 不能变成 `ok`

来源：[schemas/container.py](../../../../../schemas/container.py)。
