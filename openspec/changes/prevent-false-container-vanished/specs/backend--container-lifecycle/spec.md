# Spec Delta

## ADDED Requirements

### Requirement: 创建过渡态先于受理响应可见

Node SHALL 在返回创建受理成功响应前，将对应名称的 `building` 或 `creating` 过渡态放入状态快照可见的缓存；后台任务尚未开始或尚未创建 Docker 对象时，快照 MUST NOT 将该受理中的容器表现为缺席。未完成的创建过渡态 MUST 阻止消失判定，且消失路径不得清除它。

#### Scenario: 受理响应快于后台线程

- **WHEN** Node 已返回创建受理成功，而后台线程尚未开始创建 Docker 对象
- **THEN** 容器状态快照包含该名称的 `building` 或 `creating` 状态，不产生删除候选

### Requirement: 对账观察边界

Node SHALL 只将本轮 Docker 观察开始前已存在的缓存代际作为本轮消失候选；本轮进行中新增或更换代际的缓存条目 MUST NOT 因缺席本轮列表而被删除或排入删除队列。构建及创建过渡态不能单独证明 Docker 对象曾经存在。本地代际仅用于 Node 缓存对账，MUST NOT 被解释为 Docker 对象身份或 Q70 的跨进程操作代际；删除帧仍只携带名称，不能宣称严格跨进程代际隔离。该本地代际同时作为动作结束与观察发布的共享边界；经共享观察票校验的有效新鲜观察确认同名 Docker ID 更换时，旧代动作票、旧观察和旧删除候选 MUST 失效；旧代晚到观察 MUST NOT 再次推进代际或取消新 pending。`guard-runtime-state-reconciliation` 在同一代际内消费动作序号，MUST NOT 另造第二套代际。普通指标更新不推进代际。

#### Scenario: 创建与慢速枚举交错

- **WHEN** 一轮 Docker 枚举开始后，新容器进入缓存，且该容器不在本轮较早取得的 Docker 列表中
- **THEN** Node 保留新容器状态，本轮不产生该容器的消失候选或删除帧

#### Scenario: 同名新代替换旧代

- **WHEN** 旧代容器在本轮观察中缺席，同时同名新建开始并取代缓存代际
- **THEN** 旧代的消失候选不能清除新代状态或进入面向新代的删除队列

#### Scenario: 同名 Docker ID 更换

- **WHEN** 经共享观察票校验的有效新鲜观察发现某名称的 Docker ID 与缓存旧代不同
- **THEN** 该名称按新代处理，旧代动作票、旧观察和旧删除候选失效；新代重新分类，不继承旧代状态

#### Scenario: 旧代观察晚到

- **WHEN** 旧代 A 的观察延迟返回并看到同名 Docker ID B，而当前已是 B 代
- **THEN** 该观察不得再次推进代际、取消 B 的 pending 或把 B 当替换；只有有效当前代观察才能驱动更换

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

Node SHALL 从 Docker 实际事件中识别已声明的状态动作并交给状态缓存的统一观察入口；事件只有 `Action` 或只有历史兼容 `status` 字段时均能识别。事件回调 MUST NOT 直接以事件文本覆盖运行态；`guard-runtime-state-reconciliation` 落地后状态事件只触发新鲜 inspect 并记录轨迹。噪声事件 SHALL 被忽略，未知动作 SHALL 留下可诊断记录，不能被当作消失证据。`exec_create: ...`、`exec_start: ...` 等带冒号后缀的动作 SHALL 按 `exec_*` 噪声处理，MUST NOT 因后缀误报为未知状态事件。

#### Scenario: 事件只有 Action

- **WHEN** Docker 发送只有 `Action=start`、且包含容器名称的状态事件
- **THEN** Node 识别为 start 状态事件并交给统一观察入口（由 guard 变更触发新鲜 inspect），记录状态轨迹，不以事件文本直接覆盖运行态

#### Scenario: 事件不直接写运行态

- **WHEN** 状态事件到达但新鲜 inspect 尚未完成或不可判定
- **THEN** 事件不直接改运行态，保留最后已知并记录采集诊断；只有新鲜观察票校验通过后才发布状态

#### Scenario: exec 动作带冒号后缀

- **WHEN** Docker 发送 `Action=exec_start: /bin/sh` 等带冒号后缀的 exec 动作
- **THEN** Node 按 `exec_*` 噪声忽略，不更新缓存或事件轨迹，也不误报未知状态事件

#### Scenario: 未知事件

- **WHEN** Docker 发送未声明动作或缺少可用动作字段
- **THEN** Node 记录未知动作，不清除该容器状态，也不排队删除
