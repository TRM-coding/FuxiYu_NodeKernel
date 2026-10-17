# Proposal

## Why

`daity_ori` 的 Docker bind Source 与数据库都指向 `daity_ori_51555`，但运行容器实际挂载的目录对象一度位于 `daity_64760`。Node 按 Source 路径采集磁盘用量，因而连续上报约 6 GiB，而容器实际使用约 1.1 TiB；仅核对路径字符串无法发现这种目录改名后的错位。

## What Changes

- Node 在采集时比较 Docker 声明的 bind Source 与运行容器 `/root` 实际挂载对象的 `(st_dev, st_ino)`，上报匹配、错位或无法验证的显式状态及所比较的身份；设备号、inode 与 PID starttime 使用十进制字符串，避免 JSON 大整数精度损失。
- 磁盘用量与采集时的目录身份、Docker 对象、PID starttime、宿主 boot、collector epoch、本地扫描代际和测量完成时间绑定；路径指向新对象、验证失败、代际改变或旧值过期时，不把旧字节数标为本次有效测量。
- 为 `ContainerDiskUsage` 补充 version 1 字段、嵌套类型和缺省语义，HTTP 与 WSS 共用；字段总表见 [design.md](design.md)，协议名保持 `disk_protocol_version`，不随意改名。
- WSS `disk_usage` 快照携带上述状态，供 Ctrl 决定是否接受用量和执行限额响应；首版 source mismatch 时停止自动磁盘响应，不自动改名、改 Docker 配置、替用户选择数据目录或把 actual 路径用于清理授权。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--storage-and-mounts`：声明路径、实际挂载及磁盘测量对象的身份验证、缓存失效与失败语义。
- `backend--wss-snapshots`：`disk_usage` 快照增加目录身份、验证状态与真实测量时间。

## Impact

涉及 `docker_operates/disk_usage_cache.py`、`network/wss.py`、`schemas/container.py` 的 `ContainerDiskUsage`、磁盘用量响应模型和采集测试。Ctrl 配套变更为 `gate-disk-check-on-mount-identity`；应先部署兼容新字段的 Ctrl，再部署 Node。该补丁采用错位时不自动处置的首版保守方案；错位时按实际对象继续计量并允许冻结的选项见 Global `QUESTIONS.md` Q71，且清理仍须阻断，只能作为后续待选扩展。inode 只在单台机器、文件系统和采样代际内作为比较证据，不成为跨机器永久 ID，也不替代 Q70 的操作代际协议。Q72 已由用户决定：异常期不动作、不新增顺延，恢复可信高用量后按原累计有效冻结天数判断；既有机器不可用 deferral 与人工宽限保留，不新增 `review_required` 阻挡。Node 只提供真实 `measured_at`、`checked_at` 和身份/测量状态，不自行改写冻结累计。
