# WSS 快照

## Purpose

共享缓存的状态/SSH/磁盘/系统事实经四 topic 批次推送，删除为单独增量事件。本文件是 chester-next 33672c4edd96 在 2026-10-11 的代码逆向基线，按能力组织相关类型而非每个 class 单独建文件。完整字段、继承与兼容定义保留在下列 Requirements 中；跨能力使用以公共类型及源文件为准，已知问题集中于 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)。

## Requirements

### Requirement: delete-event 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：type='delete'；container_name 为被删除 Docker 容器名称；从状态缓存的删除队列取出后在快照批次之前推送；这是增量事件，不替代全量状态对账。

#### Scenario: 状态缓存报告某容器删除

- **WHEN** 状态缓存报告某容器删除
- **THEN** 先发送该 container_name 的 delete 事件，再发送本轮快照批次

来源：[network/wss.py](../../../network/wss.py)。

### Requirement: snapshot-batch 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：type='snapshot_batch'；node_uid 为 NodeIdentity.uid；payload 依次包含 container_status、last_ssh、disk_usage、sys_snapshot 四帧；Ctrl 主动连接 Node /ws/ctrl，Node 仅推送事实。

#### Scenario: 建立有效身份的 WSS 链接

- **WHEN** 建立有效身份的 WSS 链接
- **THEN** 在一批中提供四个 topic 的快照，使用持久化 node_uid，不要求 Node 配置 Ctrl 目标地址

来源：[network/wss.py](../../../network/wss.py)。

### Requirement: snapshot-container-status 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：type='snapshot'；topic='container_status'；payload 为 {container_name: 状态条目}，条目含 source/status、可选 runtime_metrics 和失败上下文。采集器有 collect_error 时 payload 改为 {collect_error: reason}，不发送伪正常空表。

#### Scenario: Docker 状态采集失败

- **WHEN** Docker 状态采集失败
- **THEN** 发送显式 collect_error 形状，Ctrl 可以区分采集失败与机器没有容器

来源：[network/wss.py](../../../network/wss.py)。

### Requirement: snapshot-disk-usage 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：type='snapshot'；topic='disk_usage'；payload 为 {machine_disk, containers:{name:usage}}；容器用量分别包含 overlay_rw_bytes/bind_mount_bytes/total_bytes、挂载路径和来源；读共享缓存，可能处于 measuring 或 cache 状态。

#### Scenario: 读取磁盘快照

- **WHEN** 读取磁盘快照
- **THEN** 返回缓存和来源信息，不把缓存缺失、正在测量和实际零用量混为一谈

来源：[network/wss.py](../../../network/wss.py)。

### Requirement: snapshot-last-ssh 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：type='snapshot'；topic='last_ssh'；payload 为 {container_name: {last_ssh_connect_time, updated_at}}；未采到或非运行态时间为 None，由 Ctrl 保留旧观测。updated_at 序列化为不带后缀的时间字符串。

#### Scenario: 某容器本轮没有真实 SSH 时间

- **WHEN** 某容器本轮没有真实 SSH 时间
- **THEN** last_ssh_connect_time 保持 None，不用当前采集时间冒充用户真实登录时间

来源：[network/wss.py](../../../network/wss.py)。

### Requirement: snapshot-static-hardware 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：静态 payload 包含 hostname/platform、cpu.cores、memory.total_gb、gpu 列表、disk.total_gb；disk.total_gb 取 bind_mount 所在分区容量；注册建档使用这个结构，不把动态使用百分比写成分配许可。

#### Scenario: Ctrl 首连获取硬件画像

- **WHEN** Ctrl 首连获取硬件画像
- **THEN** 返回缓存有效的静态硬件事实，缓存到期重新采集；CPU/内存许可由 Ctrl 管理策略另行确定

来源：[network/wss.py](../../../network/wss.py)。

### Requirement: snapshot-sys 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：type='snapshot'；topic='sys_snapshot'；payload 为 hostname/platform/cpu/memory/gpu/disk/collected_at；disk 分 bind_mount 和 docker_data 两个挂载点；collected_at 以 UTC 生成，无采集时 payload 可以为 None。

#### Scenario: 两个数据目录位于不同分区

- **WHEN** 两个数据目录位于不同分区
- **THEN** 分别返回 bind_mount 和 docker_data 分区容量、用量及路径；该显示数据不替代容器管理限额

来源：[network/wss.py](../../../network/wss.py)。

### Requirement: Ctrl 拨入链路端点与身份门禁 [network/wss.py]

Node SHALL 在既有 HTTPS 监听上以路径 `/ws/ctrl` 提供 Ctrl 拨入的 WebSocket 端点，复用同一张 Node 证书与同一套客户端证书校验；该端点 MUST NOT 要求新增监听端口或新增证书。Node MUST NOT 主动向 Ctrl 发起连接，也 MUST NOT 自行维护到 Ctrl 的重连循环——连接的生灭与重建由 Ctrl 侧承担。

本机身份牌未就绪时，端点 SHALL 关闭连接且不进入推送循环。连接查询参数携带的 `uid` 缺失或与本机持久化身份牌不一致时，端点 SHALL 在推送任何帧之前关闭连接。

#### Scenario: 复用既有端口与证书

- **WHEN** Node 以既有入口启动，且配置了 Ctrl 的 CA 信任文件
- **THEN** `/ws/ctrl` 与操作接口在同一监听、同一证书下同时可用，WSS 握手继承既有的客户端证书校验

#### Scenario: uid 不符则拒绝

- **WHEN** 连接未携带 `uid`，或携带的 `uid` 与本机身份牌不一致
- **THEN** Node 在推送任何帧之前关闭该连接

#### Scenario: 身份牌未就绪不推送

- **WHEN** 本机尚无身份牌
- **THEN** 端点关闭连接，不建立推送循环；等待 Ctrl 下发身份牌后重拨

#### Scenario: 无入站连接时不产生出站流量

- **WHEN** Node 启动后没有任何 Ctrl 连接
- **THEN** Node 不向任何 Ctrl 地址发起连接尝试

来源：[network/wss.py](../../../network/wss.py)、[run.py](../../../run.py)。

## Source references

- [network/wss.py](../../../network/wss.py)
- [run.py](../../../run.py)
- [__init__.py](../../../__init__.py)
- [tests/](../../../tests/)：Linux 安全默认套件 152 passed、11 deselected；未运行 Docker 集成测试。
