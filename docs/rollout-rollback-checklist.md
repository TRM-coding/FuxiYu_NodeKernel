# Node 本地验收、部署顺序与回滚清单（2026-10-18）

本清单只覆盖本仓三个 OpenSpec change 的**本地隔离实现与测试**：

- `prevent-false-container-vanished`
- `guard-runtime-state-reconciliation`
- `verify-bind-mount-identity`

本阶段没有执行 SSH、生产操作、部署、commit、push、archive 或正式
`openspec/specs/` 同步；没有修改 Ctrl/Global/skills，也没有修改
`.git/aborted-implementation-20261018/` 备份。本文不是生产联调通过证明。

## 1. 当前线路边界

- 六类动作（create/start/stop/restart/pause/unpause）成功受理响应可带
  `action_ref={node_epoch,generation,seq}`；`node_epoch` 是进程启动 UUID，
  `generation`/`seq` 为非负整数。旧 Node 可缺字段。
- HTTP 状态与 WSS 容器条目可带 `last_action={ref,action,phase,error_reason}`；
  新 Node 无记录时显式输出 `last_action:null`。`last_action.failed` 不等于
  容器运行态 `failed`。
- 运行态仍使用既有状态值；只有既有 start/create 就绪门禁终态、created
  半成品和当前 Docker dead 等允许集合可形成硬阻塞 `failed`。
- 磁盘线路只使用既有字节/路径/来源字段，新增 `mount_path_status`
  （缺省 unresolved）和真实 `measured_at`。目录对象/PID/inode 只在 Node
  内部定位与调试；不进入 HTTP/WSS，不作为冻结/恢复/长期/删除/清理门禁。
- 不新增数据库表/列、WSS 必需字段、epoch/seq 连接协议或 Ctrl 四列/资格 DTO。
- `delete` 帧仍是既有 `{type:"delete", container_name}`；Node 在发送前复核
  本地代际与 Docker 名称存在性，明确 NotFound 才发送，且只提供本进程名称
  隔离，不宣称 Q70 跨进程严格代际。

## 2. 本地验证命令与结果

环境：`E:\Miniconda3\envs\lianjue\python.exe`（Python 3.11，pytest、docker SDK、
FastAPI、Pydantic 可用）。默认测试使用 Docker 替身，不启动后台常驻服务。

```powershell
$env:PYTHONPATH='E:\AI\Fuxi'
E:\Miniconda3\envs\lianjue\python.exe -m pytest -q -p no:cacheprovider
```

结果：**315 passed, 1 skipped, 13 deselected, 24 subtests passed**。
默认套件中的 1 个 skip 是 `tests/test_clean_mount.py:80` 的
“symlink not permitted in this environment”，与 Docker/生产无关。

```powershell
E:\Miniconda3\envs\lianjue\python.exe -m pytest -q -p no:cacheprovider -m docker
```

结果：**13 skipped, 316 deselected**。本机没有可用 Docker daemon；真实 Docker
集成用例按 `docker` marker 明确 skip，没有伪造通过。

```powershell
openspec validate prevent-false-container-vanished --strict --json
openspec validate guard-runtime-state-reconciliation --strict --json
openspec validate verify-bind-mount-identity --strict --json
git diff --check
```

结果：三个 change 均为 `valid=true`、`issues=[]`；`git diff --check` 无输出。
详细日志在 `.git/recovery-verification-20261018/`。

主要本地证据：

| 测试文件 | 覆盖 |
| --- | --- |
| `tests/test_prevent_vanished.py` | 枚举中创建、在途创建、同名替换、单容器 NotFound/异常、删除候选失效、WSS 删帧顺序 |
| `tests/test_runtime_guard.py` | 读面优先级、观察票 CAS、动作队列、同名换代、create 绑定/deferred、pause/unpause 幂等、就绪进程身份、冷启动、事件唯一入口、启动失败队列清理 |
| `tests/test_runtime_barriers.py` | 受理/ref/票/队列/Docker/HTTP/WSS/删除候选屏障与 Sylvan 慢 list/stats 回放 |
| `tests/test_randomized_guard.py` | 固定种子交错、不变量、失败最小化 |
| `tests/test_action_inspect_errors.py` | pause/start/stop/restart pre-inspect 的 NotFound/APIError/连接/timeout 分类，以及 post-inspect 不确定性 |
| `tests/test_action_contracts.py` | 独立本地消费方：HTTP ACK 先到/WSS 终结先到、exact ref+方向、旧/未知 ref、缺字段、重启 epoch |
| `tests/test_verify_barriers.py` | 路径 A→B 与在途 du、Docker/路径/候选/缓存/WSS/消费方交错日志 |
| `tests/test_verify_bind_mount.py` | Source/actual 核对、有界候选、改名/歧义/proc/no PID/no_bind、路径晚回、A→B 在途 du、失败不当 0、HTTP/WSS 共用与 Ctrl 本地夹具 |

## 3. 发布顺序（本地核对，未执行）

1. **Ctrl 消失防护先落地**：Ctrl 的 `guard-container-vanish-deletion` 必须先把
   显式 delete 与快照名称缺席降级为待核实，不能直接软删有效记录。该变更
   当前不在本仓，未来上线前必须先完成并核对。
2. **Node prevent 基础**：先启用创建可见过渡态、共享本地代际、对账观察边界、
   Docker 单容器存在性再确认、删除候选代际和 `Action`/`status` 事件归一化。
3. **Node guard**：再启用动作序号、读取前 observation ticket/CAS、
   `action_ref`/`last_action`、pause/unpause 幂等、ready_identity 和冷启动重建。
   本仓实现中 prevent 与 guard 共用同一 `ContainerStatusCache` 代际，不另造
   第二套 generation。
4. **Node verify-bind**：启用业务路径核对、按业务路径 du、路径变更失效和
   两个当前线路字段；Ctrl 只按既有 `bind_mount_path`/bytes/`disk_checked_at`
   接收，不新增列。旧 Node 缺 `measured_at` 时按接收时间兼容或未验证处理。
5. **Ctrl 消费核对**：Ctrl 只消费 `bind_mount_path`/`mount_path_status`/
   `measured_at`；`resolved` 更新、`no_bind` 清空当前活跃业务路径、
   `unresolved`/`not_running` 保留。该联合核对尚未在本阶段执行。

Node 对前三个 Node 变更按同一进程内共享基础验收；没有把 guard 单独部署在
旧代际/双写事件路径上的配置。

## 4. 回滚

- 回滚 Node 时保留 Ctrl 的消失防护，不单独回滚 Ctrl；Ctrl 继续把旧 Node 的
  名称线索当待核实，不直接软删。
- Node 重启后生成新 `node_epoch`；动作序号、观察票、代际、`last_action`、
  `ready_identity` 都是进程内存状态，旧 ref 永不匹配，`last_action` 为 null。
- verify-bind 回滚后旧 payload 缺 `measured_at` 时按既有接收时间或未验证处理；
  不恢复旧路径字节用于冻结/删除，不用接收时间伪造真实测量时间。
- 已发出的 Docker 副作用和在途 delete 帧不能撤回；Q70 跨进程同名身份仍需
  独立协议，本仓不提供删除授权。
- 回滚不删除已发送的 Ctrl 防护，也不恢复旧事件直写运行态路径。

## 5. 未完成项与真实限制

以下项**没有**在本阶段完成，不应勾选为已完成：

| 项 | 当前状态 | 原因 |
| --- | --- | --- |
| prevent 3.1 与 Ctrl `guard-container-vanish-deletion` 快照缺席用例联合验收 | Node 侧时序/删除候选测试完成 | Ctrl 变更未在本仓实现，未做跨仓联合验收 |
| prevent 3.2 实际部署顺序与旧 Node 名称线索验证/生产回滚演练 | 本文记录顺序与回滚，本地模拟完成 | 没有 Ctrl 部署权限与生产环境，未 SSH/部署 |
| guard 6.5 隔离本地 Docker 集成 | 13 个 docker 用例明确 skipped | 本机 Docker daemon 不可用 |
| guard 7.1 Ctrl 消失防护已落地前置 | Node prevent 基础完成 | Ctrl 防护尚未落地，无法核对发布前置 |
| Ctrl 对磁盘新字段的接收/落库 | 仅本地独立夹具 | 不修改 Ctrl，未做跨仓联调 |

本地 Ctrl 夹具只验证字段语义，不是 Ctrl 实现，也不是端到端生产验收。
