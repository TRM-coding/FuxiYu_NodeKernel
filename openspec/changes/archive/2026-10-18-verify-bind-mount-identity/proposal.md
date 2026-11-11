# Proposal

## Why

`daity_ori` 的 Docker bind Source 与数据库都指向 `daity_ori_51555`，但运行容器实际挂载的目录一度来自 `daity_64760`。Node 按 Docker Source 路径采集用量，连续上报约 6 GiB，而容器实际使用约 1.1 TiB。仅比较路径字符串不能发现目录改名后的错位；但精确目录对象只应用于 Node 内部确定真实宿主路径、校正返回的 `bind_mount_path`，不能成为恢复、长期资格、冻结、删除、清理或用量测量的业务身份门禁。

## What Changes

- 将既有 `bind_mount_path` 明确为业务路径（用户通称 `mount_path`）。Node 在 Docker Source 与运行/暂停容器 `/proc/<pid>/root/root` 实际挂载对象一致时确认 Source；不一致时仅在既有容器存储根、Source 父目录直接子项和最后确认路径父目录等有界候选内定位，唯一对象匹配才修正业务路径。`(st_dev, st_ino)`/PID 只留在 Node 内部定位与日志，不进入 HTTP/WSS 字段，不落 Ctrl。
- 线路只新增两个必要字段：`mount_path_status=resolved|unresolved|not_running|no_bind`（Ctrl 只用于区分更新/保留/清空，缺省按 unresolved）和 `measured_at`（合计样本真实测量时间，组成中较早者）。`configured_mount_path`、`mount_path_observed_at`、`measurement_mount_path`、`measurement_status`、`measurement_reason`、`disk_protocol_version`、`collector_epoch`、`observation_seq` 均不进入线路或跨端持久化要求。
- 无法唯一定位时保留原有/最后确认路径并标 `unresolved`；无已有路径则为 null；不猜目录、不全盘递归、不返回 `/proc` 临时路径，不修改目录/Docker 配置/重挂载。成功 Docker 明确 no_bind 时 `bind_mount_path=null`、`mount_path_status=no_bind`、bind 字节为空，只允许 overlay-only，异常不得当 no_bind。
- 路径诊断仅用于展示和修正业务路径，MUST NOT 作为恢复、长期资格、冻结、删除、清理或测量有效性的独立前置/授权。`resolved` 不能使失败测量有效，`unresolved` 不阻断同路径成功测量；诊断失败不得伪装成测量失败。
- 用量按业务路径采集并缓存：bind 缓存按规范化业务路径为键；路径变化使旧路径测量失效并触发新测量；快照组装时若缓存用量的路径与当前业务路径不一致，发布当前路径但 bind 字节/总量为空，不得把旧路径字节贴到新路径。`measured_at` 取 overlay/bind 各自完成时间中较早者；失败、缺组成、非零 du、空/不可解析输出、超时不得当 0 或成功。
- 不新增 Ctrl 列、不定义跨仓资格 DTO、不要求 `disk_observation`/epoch/seq 落库；Ctrl 配套变更只复用既有 `bind_mount_path`、`disk_*_bytes`、`disk_checked_at`。本变更不修改 Ctrl 代码。
- 不改变恢复、冻结、长期、删除、清理资格与 Q72 累计；不新增 review/invalid，不重写冻结流程；不把路径/测量作为删除清理授权。不修改 guard-runtime 的 runtime DockerID、ready_identity、action_ref 或对象代际/动作票；不新增 WSS 连接代际或采样 epoch 协议。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--storage-and-mounts`：业务路径纠正、有界真实路径定位、路径诊断不门禁、按路径测量、真实测量时间与失败语义。
- `backend--wss-snapshots`：`disk_usage` 快照携带校正后的业务路径、`mount_path_status` 与 `measured_at`；不引入 epoch/seq/连接代际协议。

## Impact

涉及 `docker_operates/disk_usage_cache.py`、`network/wss.py`、`network/api.py`、`schemas/container.py` 的 `ContainerDiskUsage`/磁盘响应模型及测试。Ctrl 配套变更复用既有列持久化修正后的 `containers.bind_mount_path` 和 `disk_checked_at`；本仓不新增表、列或迁移，不修改 Ctrl。Q70 的跨进程删除/清理授权独立于本变更；Q72 既有策略不变，本变更不新增 review/invalid，不重写冻结流程。目录 dev/inode/PID 只保留在 Node 内部路径定位与调试日志。
