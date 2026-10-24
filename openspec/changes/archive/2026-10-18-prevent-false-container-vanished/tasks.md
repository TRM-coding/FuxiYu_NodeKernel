# Tasks

## 1. 对账观察边界

- [x] 1.1 在创建受理成功响应前登记快照可见的 `building`/`creating`，并让后台线程沿用它；用后台线程未启动即收快照的测试验证名称可见且不会误删。
- [x] 1.2 为缓存创建、同名重建、忘记旧代和经共享观察票校验的有效新鲜观察确认的同名 Docker ID 更换维护同一本地代际令牌，并在对账开始时截取候选快照；该令牌同时供 `guard-runtime-state-reconciliation` 的动作/观察边界复用，不另造第二套代际。用受控交错测试验证枚举中创建的新容器不会被判 `vanished`，在途创建不会被清除，有效当前代观察触发的同名 ID 更换会作废旧代动作/观察/删除候选，旧代晚到观察不会二次换代或取消新 pending。
- [x] 1.3 对旧代差集候选执行 Docker 单容器存在性确认，并在确认前后复核代际和创建过渡态；用找到对象、明确 NotFound、查询异常三类测试验证只有明确消失才排队，异常会保留缓存并置采集错误。

## 2. 删除推送与事件通道

- [x] 2.1 让删除队列携带本地代际，在 WSS 发送前核实候选仍有效且 Docker 对象未重现；用排队后同名创建、候选失效、确认失败及正常删除的测试验证删帧与快照顺序。
- [x] 2.2 归一化 Docker 事件的 `Action` 与兼容 `status` 字段，保留 ready-check 守卫，并把 `exec_create: ...`/`exec_start: ...` 等带冒号后缀的动作按 `exec_*` 噪声处理；状态事件交给统一观察入口，事件回调不得新增直接写运行态路径（`guard-runtime-state-reconciliation` 落地后只触发新鲜 inspect）。用状态事件、噪声事件、带冒号 exec 事件、未知事件和 inspect 不可判定测试验证识别、轨迹与唯一入口。

## 3. 跨路径回归

- [x] 3.1 用 jyz/test2 等价时序的模拟：Docker 创建成功、慢速逐容器采集、缓存回填及 WSS 推送交错，验证不产生误删帧，真实外部删除仍产生一次删帧；与 Ctrl `guard-container-vanish-deletion` 的快照缺席用例联合验收，运行 Node 安全默认测试套件并记录结果。（本地只读联合验收：Ctrl `d2ba7be` 的 `test/container/test_cross_repo_protocol_replay.py` 使用实际 Node 帧构造器 + Ctrl SQLite 回放，日志 `crossrepo-2.log` 为 13 passed；覆盖 creating、snapshot_missing、collect_error、delete+snapshot、磁盘 payload。未部署。）
- [ ] 3.2 核对部署顺序与回滚：先部署 Ctrl `guard-container-vanish-deletion` 防护，再用旧 Node 名称线索验证 Ctrl 只标待核实、不软删；随后部署 Node 对账修复。与 `guard-runtime-state-reconciliation` 联合验收事件运行态唯一入口，确保事件只触发新鲜 inspect、不与旧直写路径双写。回滚 Node 时保留 Ctrl 防护，不单独回滚 Ctrl。

> 归档警告：3.2 的生产部署顺序、旧 Node 名称线索验证与生产回滚演练**未执行**；本阶段只有本地清单和跨仓本地回放，不表示已上线。生产发布仍按 `docs/rollout-rollback-checklist.md` 后续执行。

## Workflow follow-up

- 若需要旧删除帧对跨进程同名新建具备严格代际隔离，先决策 Global `QUESTIONS.md` 的 Q70，再另立 Ctrl/协议变更。
