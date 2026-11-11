# Spec Delta

## MODIFIED Requirements

### Requirement: delete-event 数据契约 [network/wss.py]

Node SHALL 保持以下线路形状及数据来源：`type='delete'`；`container_name` 为经 Docker 存在性确认后消失的容器名称；从状态缓存的删除队列取出后在快照批次之前推送；这是增量事件，不替代全量状态对账。入队后若同名新代开始创建或重新出现，Node MUST 丢弃旧候选，不得以旧代消失事实报告新代删除。Docker 采集失败或尚处创建过渡态时 MUST NOT 发送删除帧。

#### Scenario: 状态缓存报告某容器删除

- **WHEN** 状态缓存确认某个已知代际容器在 Docker 中消失，且发送前该候选未失效
- **THEN** 先发送该 `container_name` 的 `delete` 事件，再发送本轮快照批次

#### Scenario: 排队后同名新建

- **WHEN** 某名称的删除候选已排队，但同名新代在发送前开始创建或重新出现在 Docker 中
- **THEN** Node 丢弃旧候选，本轮不发送该名称的 `delete` 事件

#### Scenario: Docker 采集不可判定

- **WHEN** 本轮列表或单容器核实失败，无法确认容器是否消失
- **THEN** Node 发送采集错误状态，不发送该容器的 `delete` 事件

来源：[network/wss.py](../../../../../network/wss.py)、[docker_operates/status_cache.py](../../../../../docker_operates/status_cache.py)。
