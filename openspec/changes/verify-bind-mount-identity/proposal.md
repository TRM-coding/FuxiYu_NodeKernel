# Proposal

## Why

`daity_ori` 的 Docker bind Source 与数据库都指向 `daity_ori_51555`，但运行容器实际挂载的目录一度来自 `daity_64760`。Node 按 Docker Source 路径采集用量，连续上报约 6 GiB，而容器实际使用约 1.1 TiB。仅比较路径字符串不能发现目录改名后的错位；但用户已明确，精确目录对象只用于 Node 内部确定真实宿主路径、校正返回的 `bind_mount_path`，不能成为恢复、长期资格、冻结、删除、清理或用量测量的业务身份门禁。

## What Changes

- 将既有 `bind_mount_path` 明确为业务路径（用户通称 `mount_path`）。Node 在 Docker Source 与运行容器 `/root` 实际挂载对象一致时确认 Source 路径；不一致时仅在既有容器存储根、Source 父目录的直接子项和最后确认路径父目录等有界候选内定位，唯一匹配才修正业务路径。`configured_mount_path` 只作 Docker Source 诊断。
- 新增路径诊断字段 `configured_mount_path`、`mount_path_status=resolved|unresolved|not_running|no_bind`、`mount_path_observed_at`。无法唯一定位时保留原有/最后确认路径并标 `unresolved`，无已有路径则为 null；不猜目录、不全盘递归、不返回 `/proc` 临时路径，不修改目录/Docker 配置/重挂载。
- 路径诊断仅用于展示和修正业务路径，MUST NOT 作为恢复、长期资格、冻结、删除、清理或测量有效性的独立前置/授权。已存在有效业务路径且本次路径测量成功时，仅路径核验 `unresolved` 不得阻断业务；诊断失败也不得伪装成 `measurement_error`。
- 用量按业务路径采集并缓存：保留 `disk_protocol_version=1`、`collector_epoch`、`observation_seq`、`measurement_status`、`measured_at`、`measurement_mount_path`；删除旧目录/对象身份字段及基于目录对象/PID 的门禁。路径变更必须重新测量，旧路径样本不能改贴新路径。
- 保留独立测量失败/过期/缺组成不能当 0、乱序保护、Q72 累计政策；overlay-only 只在 Docker 明确 `no_bind` 时成立，异常不当 0。Ctrl 只消费新的测量字段与路径诊断，不再以目录身份门禁业务。
- Ctrl 持久化契约调整为 `disk_measurement_status`、`disk_measured_at`、`disk_received_at`、`disk_observation`；移除旧目录身份列。Ctrl 只将当前认证机器/活跃容器的 `mount_path_status=resolved` 修正持久化到 `containers.bind_mount_path`，不凭 inode 批改历史快照或旧清理记录；固定 8 字段 `long_term_eligibility` 不变。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--storage-and-mounts`：业务路径纠正、有界真实路径定位、路径诊断不门禁、按路径测量、测量有效性与失败语义。
- `backend--wss-snapshots`：`disk_usage` 快照改为路径纠正与测量会话字段，移除目录身份协议，保留真实测量时间与乱序保护。

## Impact

涉及 `docker_operates/disk_usage_cache.py`、`network/wss.py`、`schemas/container.py` 的 `ContainerDiskUsage`、HTTP 磁盘响应模型及测试。Ctrl 配套计划移除目录身份门禁并持久化修正后的 `containers.bind_mount_path`；本仓不改 Ctrl。Q70 的跨进程删除/清理授权独立于本变更；Q72 已由用户决定：异常期不动作、采集盲区不额外补偿且累计继续、不新增顺延，恢复可信高用量后按原累计有效冻结天数判断，既有机器不可用 deferral 与人工宽限保留，不新增 `review_required` 阻挡。固定 8 字段 `long_term_eligibility` 不变。目录 dev/inode/PID 只保留在 Node 内部路径定位与调试日志，不进入跨端业务协议或清理授权。
