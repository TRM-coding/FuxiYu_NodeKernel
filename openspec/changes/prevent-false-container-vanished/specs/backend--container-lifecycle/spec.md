# Spec Delta

## ADDED Requirements

### Requirement: 创建过渡态先于受理响应可见

Node SHALL 在返回创建受理成功响应前，将对应名称的 `building` 或 `creating` 过渡态放入状态快照可见的缓存；后台任务尚未开始或尚未创建 Docker 对象时，快照 MUST NOT 将该受理中的容器表现为缺席。未完成的创建过渡态 MUST 阻止消失判定，且消失路径不得清除它。

#### Scenario: 受理响应快于后台线程

- **WHEN** Node 已返回创建受理成功，而后台线程尚未开始创建 Docker 对象
- **THEN** 容器状态快照包含该名称的 `building` 或 `creating` 状态，不产生删除候选

### Requirement: 对账观察边界

Node SHALL 只将本轮 Docker 观察开始前已存在的缓存代际作为本轮消失候选；本轮进行中新增或更换代际的缓存条目 MUST NOT 因缺席本轮列表而被删除或排入删除队列。构建及创建过渡态不能单独证明 Docker 对象曾经存在。本地代际仅用于 Node 缓存对账，MUST NOT 被解释为 Docker 对象身份或 Q70 的跨进程操作代际；删除帧仍只携带名称，不能宣称严格跨进程代际隔离。

#### Scenario: 创建与慢速枚举交错

- **WHEN** 一轮 Docker 枚举开始后，新容器进入缓存，且该容器不在本轮较早取得的 Docker 列表中
- **THEN** Node 保留新容器状态，本轮不产生该容器的消失候选或删除帧

#### Scenario: 同名新代替换旧代

- **WHEN** 旧代容器在本轮观察中缺席，同时同名新建开始并取代缓存代际
- **THEN** 旧代的消失候选不能清除新代状态或进入面向新代的删除队列

#### Scenario: 本地代际不跨进程

- **WHEN** Node 已经发送只含 `container_name` 的 `delete` 帧，随后同名新容器创建
- **THEN** Node 的本地代际不能撤回在途帧或向 Ctrl 证明代际；Ctrl 只能按待核实处理，严格 Q70 隔离仍需独立协议

### Requirement: 消失须经 Docker 再确认

Node SHALL 在排入消失删除前，对候选容器作独立 Docker 存在性确认；只有明确得到不存在且缓存代际未变化时才能排队。列表采集或单容器确认失败 MUST 保留缓存、标记采集错误并等待后续对账，不得据此报告删除。

#### Scenario: Docker 对象仍存在

- **WHEN** 列表中缺少已知容器，但单容器确认仍找到该 Docker 对象
- **THEN** Node 不删除缓存、不排队删除，并在后续观察中收敛其状态

#### Scenario: Docker 查询失败

- **WHEN** Docker 列表或单容器确认抛出不可判定的异常
- **THEN** Node 保留相关缓存并报告采集错误，不向 Ctrl 发送该容器的删除事实

### Requirement: Docker 状态事件兼容

Node SHALL 从 Docker 实际事件中识别已声明的状态动作并更新缓存；事件只有 `Action` 或只有历史兼容 `status` 字段时均能识别。噪声事件 SHALL 被忽略，未知动作 SHALL 留下可诊断记录，不能被当作消失证据。

#### Scenario: 事件只有 Action

- **WHEN** Docker 发送只有 `Action=start`、且包含容器名称的状态事件
- **THEN** Node 将该事件按 start 处理并更新状态轨迹

#### Scenario: 未知事件

- **WHEN** Docker 发送未声明动作或缺少可用动作字段
- **THEN** Node 记录未知动作，不清除该容器状态，也不排队删除
