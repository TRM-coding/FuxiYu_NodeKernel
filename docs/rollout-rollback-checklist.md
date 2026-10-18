# Node 本地验收、部署顺序与回滚清单（2026-10-18）

本清单覆盖本仓三个 OpenSpec change 的**本地隔离实现与测试**：

- `prevent-false-container-vanished`
- `guard-runtime-state-reconciliation`
- `verify-bind-mount-identity`

本阶段没有执行 SSH、生产操作、部署、push、archive 或正式
`openspec/specs/` 同步；没有修改 Ctrl/Web/Global/skills，也没有修改
`.git/aborted-implementation-20261018/` 备份。本文是本地验收与发布顺序
核对记录，**不是生产联调通过证明，也不表示已经上线**。

## 1. 当前线路边界

- 六类动作（create/start/stop/restart/pause/unpause）成功受理响应可带
  `action_ref={node_epoch,generation,seq}`；`node_epoch` 是进程启动 UUID，
  `generation`/`seq` 为非负整数。旧 Node 可缺字段。
- HTTP 状态与 WSS 容器条目可带 `last_action={ref,action,phase,error_reason}`；
  新 Node 无记录时显式输出 `last_action:null`。`last_action.failed` 不等于
  容器运行态 `failed`。状态查询响应不再输出恒为 null 的 `action_ref`。
- 运行态仍使用既有状态值；只有既有 start/create 就绪门禁终态、created
  半成品和当前 Docker dead 等允许集合可形成硬阻塞 `failed`。
- 磁盘线路只使用既有字节/路径/来源字段，新增 `mount_path_status`
  （缺省 unresolved）和真实 `measured_at`。目录对象/PID/inode 只在 Node
  内部定位与调试；不进入 HTTP/WSS，不作为冻结/恢复/长期/删除/清理门禁。
- 不新增数据库表/列、WSS 必需字段、epoch/seq 连接协议或 Ctrl 四列/资格 DTO。
- `delete` 帧仍是既有 `{type:"delete", container_name}`；Node 在发送前复核
  本地代际与 Docker 名称存在性，明确 NotFound 才发送；采集错误期间不取走
  删除候选。只提供本进程名称隔离，不宣称 Q70 跨进程严格代际。

## 2. 本地验证命令与结果

环境：`E:\Miniconda3\envs\lianjue\python.exe`（Python 3.11，pytest、docker SDK、
FastAPI、Pydantic 可用），`PYTHONPATH=E:\AI\Fuxi`。本机 Docker Desktop 已启动，
仅使用本地 `desktop-linux` context（server 28.5.1），未使用 remote context；
镜像使用本机已有 `swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/alpine:latest`
（Docker Hub 当前不可达，测试会先探测本地镜像，只有 daemon/镜像确实缺失才 skip）。

```powershell
$env:PYTHONPATH='E:\AI\Fuxi'
E:\Miniconda3\envs\lianjue\python.exe -m pytest -q -p no:cacheprovider
```

结果：**331 passed, 1 skipped, 16 deselected, 24 subtests passed**。
默认套件中的 1 个 skip 是 `tests/test_clean_mount.py:80` 的
“symlink not permitted in this environment”，与 Docker/生产无关。

```powershell
E:\Miniconda3\envs\lianjue\python.exe -m pytest -q -p no:cacheprovider `
  -m docker tests/test_docker_runtime_integration.py
```

结果：**4 passed, 1 skipped**。4 项真实 Docker 通过：

1. running/not paused 的重复 unpause 为 `idempotent_confirmed`，不调用
   Docker unpause，运行态 online，WSS 帧携带同一 ref；
2. exited 容器 unpause 返回 failed/not_running，不伪造成功；
3. pause 保留同一进程 ready_identity，unpause 复用；同 Docker ID 外部
   restart 改变 StartedAt 后重新进入 ready_check；
4. 慢 stats 期间真实容器 paused→running，最终按名称新鲜解析发布 online，
   旧 list 对象不把状态回写 paused。

skip 项是“真实 dead 容器 unpause 不成功”，原因写在测试 marker 中：不能
在不破坏本机 Docker storage/宿主挂载的前提下安全制造 dead 状态；dead 的
运行态/动作映射由 `tests/test_runtime_guard.py` 的
`test_pause_unpause_offline_dead_never_report_success` 覆盖，未宣称真实
dead 集成通过。

旧 Docker 测试补充定位与修复（本变更之外，未并入上面的 4 项）：

- `tests/test_docker_status_cache.py`：原 fixture 固定使用
  `pytest_sshd_fixture`/`pytest_no_sshd` 并在启动前按名称删除同名容器；
  `apt-get update && install openssh-server` 无 timeout，本机 apt 在 25 秒
  上限时仍未完成（rc=124），`exec_run` 又无 timeout，导致整个 marker 挂起。
  已改为唯一名称/label、按本次 Docker ID 清理、容器内 `timeout` 包裹
  （探针 20s、安装 240s），安装失败才按环境前置 skip。修复后
  `pytest -m docker tests/test_docker_status_cache.py`：**6 passed in 228.16s**，
  容器已清理。
- `tests/test_create_container.py::test_happy_path`：原用例默认使用
  `ubuntu:22.04`，该镜像没有 `/usr/sbin/sshd`/`ssh-keygen`（复现：
  `docker run --rm ubuntu:22.04 sh -c 'command -v ssh-keygen || echo missing; test -x /usr/sbin/sshd || echo missing'`
  两项均 missing），create 的 sshd 门禁在 `ssh-keygen -A` 处 exit 127。
  已改为必须设置 `NODE_TEST_IMAGE` 指向带 sshd 的镜像，未设置/镜像缺失时
  作为环境前置显式 skip；同时改为唯一名称、按本次 Docker ID 清理。本机
  未提供该镜像，因此该项为 **1 skipped**，不是行为通过。
- 其余安全旧 Docker 用例（add/remove collaborator、remove container、
  update role，均唯一名称/自有对象清理）：
  `pytest -m docker ...`：**4 passed**。
- 全量 `pytest -m docker` 未合并重跑；分项结果为旧用例 10 passed + 1
  skipped、本变更专项 4 passed + 1 skipped，**不能宣称全量 Docker green**。

```powershell
openspec validate prevent-false-container-vanished --strict --json
openspec validate guard-runtime-state-reconciliation --strict --json
openspec validate verify-bind-mount-identity --strict --json
git diff --check
```

结果：三个 change 均为 `valid=true`、`issues=[]`；`git diff --check` 无输出。

主要本地证据：

| 测试文件 | 覆盖 |
| --- | --- |
| `tests/test_docker_runtime_integration.py` | 本机真实 Docker：重复 unpause、offline 不成功、pause/restart ready 失效、慢 stats、WSS 帧；唯一名称/label，仅按本次 Docker ID 清理 |
| `tests/test_prevent_vanished.py` | 枚举中创建、在途创建、同名替换、单容器 NotFound/异常、删除候选失效、collect_error 期间不取删除候选、WSS 删帧顺序 |
| `tests/test_runtime_guard.py` | 读面优先级、观察票 CAS（含旧 node_epoch、旧 unknown、metrics 票失效）、动作队列、同名换代、create 绑定/deferred 与新旧 create 所有权、硬阻塞 ready/暂停边界、创建中 created 不提前硬阻塞、旧 finish 不回写、pause/unpause 幂等、冷启动、事件唯一入口、启动失败队列清理 |
| `tests/test_runtime_barriers.py` | 受理/ref/票/队列/Docker/HTTP/WSS/删除候选屏障与 Sylvan 慢 list/stats 回放 |
| `tests/test_randomized_guard.py` | 固定种子交错、不变量、失败最小化 |
| `tests/test_action_inspect_errors.py` | pause/start/stop/restart pre-inspect 的 NotFound/APIError/连接/timeout 分类，以及 post-inspect 不确定性 |
| `tests/test_action_contracts.py` | 独立本地消费方：HTTP ACK 先到/WSS 终结先到、exact ref+方向、旧/未知 ref、缺字段、重启 epoch、状态响应不输出 action_ref |
| `tests/test_verify_barriers.py` | 路径 A→B 与在途 du、Docker/路径/候选/缓存/WSS/消费方交错日志 |
| `tests/test_verify_bind_mount.py` | Source/actual 核对、有界候选、改名/歧义/proc/no PID/no_bind/Mounts 不可读、路径晚回、A→B 在途 du、bind 样本晚于 overlay 时取较早 measured_at、失败不当 0、HTTP/WSS 共用与 Ctrl 本地夹具 |
| `tests/test_docker_status_cache.py` | 旧真实 Docker fixture 修复：唯一名称/label、按 ID 清理、apt 有界 timeout、sshd 冷启动/probe/终态；6 passed |

## 3. 发布顺序（本地清单核对，未执行）

1. **Ctrl 消失防护先落地**：Ctrl `guard-container-vanish-deletion` 的本地
   快照为 HEAD `5099cc1`、tasks 5/6、`openspec validate --strict` 通过；
   `test/container/test_vanish_guard.py` 覆盖快照缺席待核实、显式 delete
   帧、旧帧晚于同名新建、跨机同名、unknown/过渡保留、成功状态清除标记。
   该变更余 3.1 为与 Node prevent 的跨仓联合验收，尚未完成。**本地代码
   存在不等于已部署。**
2. **Node prevent 基础**：先启用创建可见过渡态、共享本地代际、对账观察边界、
   Docker 单容器存在性再确认、删除候选代际和 `Action`/`status` 事件归一化。
3. **Node guard**：再启用动作序号、读取前 observation ticket/CAS、
   `action_ref`/`last_action`、pause/unpause 幂等、ready_identity 和冷启动重建。
   本仓实现中 prevent 与 guard 共用同一 `ContainerStatusCache` 代际，不另造
   第二套 generation；事件只经 `_apply_event → issue_observation →
   _inspect_fact → publish_observed`，没有事件文本直写运行态的第二条路径。
4. **Node verify-bind**：启用业务路径核对、按业务路径 du、路径变更失效和
   两个当前线路字段；Ctrl 只按既有 `bind_mount_path`/bytes/`disk_checked_at`
   接收，不新增列。旧 Node 缺 `measured_at` 时按接收时间兼容或未验证处理。
5. **Ctrl 消费核对**：Ctrl 只消费 `bind_mount_path`/`mount_path_status`/
   `measured_at`；`resolved` 更新、`no_bind` 清空当前活跃业务路径、
   `unresolved`/`not_running` 保留。该联合核对尚未在本阶段执行。

本项 7.1 是**发布清单与依赖检查**：当前 Node 只有一套 `_meta[].generation`，
事件运行态只有统一观察入口；guard 不应单独部署在旧代际/双写事件路径上。
没有执行任何部署，不能据此声称上线。

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
| prevent 3.1 与 Ctrl `guard-container-vanish-deletion` 快照缺席用例联合验收 | Node 侧时序/删除候选测试完成；Ctrl 侧本地 guard 测试 5/6 | Ctrl 变更余 3.1 联合验收，未做跨仓联合运行 |
| prevent 3.2 实际部署顺序与旧 Node 名称线索验证/生产回滚演练 | 本文记录顺序与回滚，本地模拟完成 | 没有 Ctrl 部署权限与生产环境，未 SSH/部署 |
| guard 6.5 真实 dead 容器集成 | 4 项真实 Docker 通过；dead 显式 skip | 不能安全制造 dead 状态；dead 映射由单元测试覆盖，未伪造通过 |
| Ctrl 对磁盘新字段的接收/落库 | 仅本地独立夹具 | 不修改 Ctrl，未做跨仓联调 |
| Ctrl `guard-container-vanish-deletion` 3.1 联合验收 | Ctrl 本地 5/6 | 与 prevent 3.1 同一跨仓项 |
| 旧 `test_create_container::test_happy_path` 真实 Docker 运行 | 1 skipped（环境前置） | 本机没有带 `/usr/sbin/sshd` 的 `NODE_TEST_IMAGE`；设置后可运行完整断言，未把行为失败改 skip |

本地 Ctrl 夹具只验证字段语义，不是 Ctrl 实现，也不是端到端生产验收。
guard 7.1 只完成发布清单/依赖核对，不是部署或上线证明。

## 6. 本轮复审与修复（本地已验证）

- **硬阻塞**：`set_hard_block` 使旧 ready 证明失效；running 事实不能再凭
  旧 `ready_verified` 直接清阻塞；paused 事实保留已证实的硬阻塞，暂停不
  被当作 sshd/created/dead 条件消失。
- **create pending 与 created**：创建进行中看到 Docker `created` 只保持
  building/creating 过渡，不提前形成硬阻塞；create 终结后对象仍为 created
  才形成 `created_half_built`；create 被同代新动作取代后，后台 create 晚到
  终结会释放 `create_pending` 名称所有权，避免永久挡住绑定/换代/删除候选。
- **旧采集/旧动作回写**：删除 `ContainerStatusCache.update` 这条旧采集直写口；
  `finish_action` 只终结当前受理序号，不再直接写运行态；动作/采集运行态只能
  由新鲜 Docker 事实 + 观察票发布。无当前动作/已过期调用被忽略，不能覆盖
  新状态；测试 seed 也改用 issue/publish。
- **删除候选**：`_collect_error` 置位期间 `take_confirmed_deleted` 保留候选
  不发送，等成功对账后再复核；同名 create/旧代检查仍在发送前执行。
- **磁盘路径**：`Mounts` 缺失、形状损坏或含非 dict 项时标 unresolved/
  mounts_unreadable，不推断 no_bind、不清空已有业务路径。
- **wire**：`ContainerStatusResponse` 不再继承受理响应，不输出恒为 null 的
  `action_ref`；磁盘模型仍只有当前允许字段，无 identity/epoch/seq。
- **补测覆盖**：新增旧 `node_epoch` 观察票不能写新进程、metrics 票被
  action_seq/代际更换拒绝、旧 unknown 票不能覆盖新运行态、旧 create 终结
  不能释放新 create pending、bind 样本晚于 overlay 时 `measured_at` 仍取
  较早组件；这些边界原先只有间接覆盖。
- **测试安全**：真实 Docker 集成用例每次使用唯一名称和本次运行 label，只
  清理 `containers.run` 返回的 Docker ID；不再为先删同名容器而清理既有对象。
  旧状态缓存 fixture 的固定名称/pre-delete 与无界 apt 等待也已按同一规则
  修正；镜像/daemon/apt 环境缺失才 skip，行为断言失败不会被 skip 吞掉。
