# Design

## Context

Node 现有 `POST /api/clean_mount` 是同步端点：`services/container_service.clean_mount()` 先做 `NODE_CONTAINERS_BASE`/`containers` 白名单校验，再以 `rm -rf` 删除，HTTP 请求要等删除结束。`POST /api/create_container` 虽只返回受理，但恢复路径的校验发生在后台 `create_container()` 内，且与清理之间没有共享的路径占用状态；两个请求可以同时通过校验，随后一个恢复创建、一个删除同一目录。

Node 没有数据库，任务状态只能放在进程内；`run.py` 以单进程运行 FastAPI，lifespan 目前只在退出时停止系统缓存。Ctrl/Web 不在本仓库，但本变更需要把受理、轮询、成功/失败落账和未知结果写成跨仓协议约束，供 Ctrl/Web 的独立变更实现。用户已明确接受：Node 重启会丢失任务，删除可能只完成一部分，恢复入口重新开放后可能看到不完整数据；Ctrl 重启会丢失轮询且不得补写成功。

主规格已有三处“本统计能力不得修改 `clean_mount`”的旧约束（去重/冷却、缓存失效、详情兼容）。这些约束属于上一变更的统计/缓存范围，不能继续禁止本次授权的路径互斥和子进程生命周期；本 delta 用 MODIFIED Requirement 将其限定为“不得借统计/缓存修改”，并明确异步清理是唯一例外。

本设计以 [proposal.md](proposal.md) 的动机和 `specs/` 的行为契约为准，不描述逐行实现。

## Goals / Non-Goals

**Goals:**

- 为已删除容器目录提供“受理—后台删除—轮询终态”的异步清理流程，HTTP 不等待 `rm`。
- 以 Node 的路径规范化为唯一互斥键，在异步清理、旧同步清理和恢复创建之间建立同一把按路径的进程内锁。
- 让恢复创建的“校验 + 占用检查 + 预留登记”原子化，并让预留覆盖后台创建的关键阶段。
- 让任务状态只在进程内有界保存，终态可查询、可淘汰，重启后不伪造结果。
- 让异步删除不设固定超时，慢清理可一直保持 `running`；成功只由退出码 0 决定。
- 让删除子进程在正常关闭时终止并回收，在 Linux `SIGKILL`/异常终止时由父死亡信号终止，两种情况都不遗留存活的 `rm`。
- 保持旧同步端点对旧客户端/旧调用方可用，并明确当前 Ctrl 手动、定时与磁盘升级清理走异步，以及 Ctrl/Web 的成功、失败、未知边界。

**Non-Goals:**

- 不在本仓库修改 Ctrl/Web，也不在 Node 增加数据库、迁移、持久队列或 WSS 推送。
- 不建设通用任务框架、通用锁服务或跨机器分布式锁；互斥范围就是单 Node 进程所代表的一台机器。
- 不改变普通新建的目录命名、Docker 创建步骤、容器运行态、删除容器接口或恢复账号的业务规则。
- 不把路径锁延长到容器整个生命周期；恢复成功释放后，清理仍由既有 Ctrl 授权和资格判定负责。
- 不提供删除进度百分比、逐文件结果、断点续删、重启恢复或自动补偿。
- 不给异步删除设置固定超时；旧同步端点的 30 秒超时保持不变。
- 不改变 `clean_mount` 的路径白名单；本变更只共享校验实现并增加互斥。

## Decisions

### 1. 线路协议与“成功”的含义

Node 保留现有请求外层 `config` 风格，新增：

```json
POST /api/start_clean_mount
{"config": {"mount_path": "/home/alice/containers/c1"}}

200 {"success": 1, "task_id": "<node_epoch>:<seq>"}
```

```json
POST /api/get_clean_mount_status
{"config": {"task_id": "<node_epoch>:<seq>"}}

200 {
  "success": 1,
  "task_id": "<node_epoch>:<seq>",
  "state": "running|succeeded|failed",
  "error_reason": null
}
```

`start_clean_mount` 的 `success=1` 只表示“已登记并开始受理”，不表示目录已删除。`get_clean_mount_status` 的 `success=1` 只表示“查询成功”；任务失败时 HTTP 仍为 200，由 `state="failed"` 和非空 `error_reason` 表达。旧同步端点的 `success=1` 仍表示删除完成。三处 `success` 含义不同，Ctrl 不得用启动受理或查询成功代替清理成功。

错误沿用 `{"success":0,"error":...,"error_reason":...}`，稳定原因包括：`invalid_path`（400）、`cleanup_in_progress`/`restore_in_progress`（409）、`not_found`（404）、`internal_error`（500）。异步任务失败原因只使用 `rm_failed`、`shutdown`、`internal_error`；旧同步端点仍保留 `timeout`。不把 stderr、绝对路径内容或子进程输出放进状态响应。

替代方案是在启动响应中直接返回 `state` 或等待首次 `rm` 结果。两者都会让“已受理”和“已删除”混淆，拒绝。

### 2. 单一进程内任务/路径登记器

新增一个服务层模块（例如 `services/mount_cleanup.py`），在 `extensions.py` 中放一个进程级单例，由 API、旧同步服务和恢复创建共享。它只持有一个 `threading.RLock()`，同时保护：

- `active_by_key`：规范化路径键到当前占用（清理或恢复）的映射；
- `tasks`：`task_id` 到任务记录的有界映射；
- `processes`：运行中的删除子进程句柄；
- `accepting`：关闭时拒绝新登记；
- `node_epoch` 与递增序号：生成不会跨重启复用的任务标识。

锁只在内存中；不读写数据库、不写文件锁、不依赖 Docker label。模块不承担容器运行态或业务授权，只负责目录路径的占用与删除任务。

替代方案是使用文件锁或 Docker label 做跨进程互斥。它们会引入持久化和清理残留，且本项目 Node 是单进程，拒绝。

### 3. Node 权威路径规范化

清理和恢复共用同一规范化函数：

1. 拒绝空值、NUL 或不可转成路径文本的输入；不做 `~` 展开。
2. 对输入做 `os.path.realpath()`，得到绝对的真实路径。
3. 对 `NODE_CONTAINERS_BASE` 做同样规范化；真实路径必须位于其下且不得等于根目录。
4. 真实路径必须含大小写不敏感的 `containers` 路径段。
5. realpath 指向 base 外、伪装前缀、缺段或其它白名单失败都返回 `invalid_path`。
6. 比较与键使用 `os.path.normcase(realpath)`；删除和挂载仍使用 realpath 本身，避免在大小写不敏感平台上误用小写路径执行。

恢复额外要求真实路径存在且为目录；清理允许目录已经不存在，因为 `rm -rf` 对不存在目标仍可成功。任务键是规范化路径；因为登记器只属于一个 Node 进程，机器维度由进程隐含保证。Ctrl 的键另带 `machine_id`，见决策 8。

没有给请求增加 `machine_id`、`normalized_path` 或路径指纹字段。Node 不把规范化路径回传给 Ctrl；Ctrl 对路径别名的漏拦由 Node 的 409 最终兜底。

### 4. 清理启动的原子校验与登记

`start_clean_mount` 的顺序是：

1. 在锁内完成路径规范化、白名单校验、活动占用检查和任务记录登记；三者之间不得释放锁，也不得先查后登。
2. 如果没有占用，生成 `task_id`，写入 `running` 任务，并把 `active_by_key[key]` 标记为该清理任务。
3. 记录提交后再启动后台线程；线程启动失败时在同一把锁内删除任务和占用，向请求返回 500，不能留下永远 `running` 的任务。
4. 已有同键清理返回 409 `cleanup_in_progress`；已有恢复预留返回 409 `restore_in_progress`；被拒请求不生成任务、不启动子进程。

校验中的 `realpath`/`isdir` 是本地快速调用，允许在锁内执行；不得在锁内做 Docker、网络、磁盘扫描或等待子进程。实际 `rm` 必须在后台、锁外执行。

替代方案是“先校验、后登记”，这会在两步之间留下恢复或第二个清理插入的窗口，直接违背用户要求，拒绝。

### 5. 恢复创建的预登记与关键阶段

携带 `restore_mount_path` 的创建请求在返回受理前执行一次恢复预检：

1. 在同一个登记器锁内，用共享规范化函数校验路径；额外要求存在且是目录。
2. 检查 `active_by_key[key]`：有清理则返回 409 `cleanup_in_progress`，有另一个恢复则返回 409 `restore_in_progress`。
3. 通过后立即写入恢复预留，拿到一次性 token 和预检得到的规范化 `reserved_path`，再把二者交给既有后台创建流程。
4. 容器名冲突、后台线程提交失败或其它在受理前发生的失败，必须在错误返回前释放 token。
5. 请求一旦受理，token 和 `reserved_path` 随 `_bg_create` 闭包进入 `try/finally`，覆盖镜像构建、`create_container(reserved_path)` 的既有 realpath/存在性安全校验、Docker `/root` bind 建立、sshd 门禁和恢复账号重建；后台流程终止（成功或失败）才释放。

`create_container()` 接收预检固定下来的 `reserved_path`，并保留既有 realpath、base/`containers` 和存在性安全校验；不新增路径别名专用复验机制。

恢复正常路径后再释放预留，路径重新可被清理或恢复；容器生命周期内的“该不该清理”仍由 Ctrl 的资格/授权负责，Node 不新增容器存在性门禁。

这个顺序把不存在/非法 `restore_mount_path` 从“先受理、后台失败”前移为“受理前 400”；这是原子登记的必要代价，既有使用不存在路径的 API 测试需要先创建真实目录或改为断言 400。

替代方案是让服务层在 `create_container` 开始时自行加锁。那样 API 受理到后台开始之间仍有窗口，且后台失败后锁的释放责任不清，拒绝。

### 6. 有界任务状态、标识与淘汰

- `task_id = f"{node_epoch}:{seq}"`。`node_epoch` 每次 Node 进程启动重新生成，`seq` 在锁内递增；重启前 id 不会再次出现。
- 任务状态只允许 `running -> succeeded` 或 `running -> failed`；终态写入必须幂等，晚到结果不能覆盖已写终态。
- 活动任务永不淘汰，也不因数量上限被丢弃。
- 终态记录上限为 64 条、保留时间 600 秒；超过任一上限时按 `finished_at` 最旧优先淘汰。淘汰只在终态集合中执行，清理失败/成功的任务记录都可能被淘汰。
- 查询未命中（从不存在、已淘汰或重启前）统一返回 404 `not_found`。Node 不在目录不存在时生成“成功”任务，也不写盘补记录。
- 任务记录不持久化、不写 WSS、不进 Docker label、不写数据库。Ctrl 侧按决策 8 的轮询规则把 404/失联解释为未知。

选择 64 条/600 秒只用于约束已终结任务的历史：异步删除没有固定超时，可能运行超过 600 秒，活动任务永不淘汰；终态保留 10 分钟给 Ctrl 正常轮询，超过后返回 404 并按未知处理。数字是 Node 内部常量，不进入线路协议，也不是删除结果截止时间。替代方案是无限保留，会让进程内存随清理次数增长，拒绝。

### 7. 删除子进程、无固定超时与关闭/强杀生命周期

后台线程不使用 `subprocess.run`，因为拿不到可终止的句柄，也无法在父进程被强杀时约束子进程：

1. Linux 生产环境在 `services/mount_modules/cleanup_launcher.py` 使用一个极小的独立 launcher 作为直接子进程。删除程序路径 `rm_path` 由登记器作为显式依赖解析（生产默认 `shutil.which("rm")`；测试注入一个可控的假可执行文件），launcher 只执行传入的绝对路径，不在内部重新做 PATH 查找。Node 传入自己的 PID、任务 token 和 realpath；launcher 在任何删除前调用 libc `prctl(PR_SET_PDEATHSIG, SIGKILL)`，然后用 `os.getppid()` 与预期 PID 比较：不一致说明 Node 已在设置信号前消失，launcher 直接非零退出，不 exec 删除程序；一致则 `os.execv(rm_path, ["rm", "-rf", realpath])`。PDEATHSIG 对普通非 setuid 的 `rm` 跨 `exec` 保留；`rm_path` 缺失或不可执行时失败关闭，不退回 shell。
2. 选择独立 launcher 而不是 `preexec_fn`：Node 是多线程进程，fork 后运行 Python 回调有死锁风险；launcher 在独立进程早期完成 `prctl`，父 PID 校验关闭“Node 在 prctl 之前消失”的竞态。`prctl` 不可用或设置失败时，launcher 不执行删除，任务落 `failed`/`internal_error`，即失败关闭而不是无保护删除。
3. launcher 在锁内启动并登记 PID，然后释放锁等待；stdout/stderr 捕获，日志只保留既有有界尾部，状态响应只放稳定原因。正常关闭时向 launcher/rm 的进程组发送终止信号，等待有界时间后强制终止并回收。旧同步端点使用同一 launcher 和同一个可注入 `rm_path`，但等待上限保留为 30 秒。
4. 异步删除不设置固定超时：后台线程一直等待子进程退出，任务保持 `running`；不得因为超过 30 秒或任何固定时长而主动终止、写 `timeout` 或截断删除。只有退出码 0 才写 `succeeded`；非零写 `failed`/`rm_failed`；启动、launcher 或执行异常写 `failed`/`internal_error`。
5. Node 正常关闭时，登记器先把 `accepting` 置为 false，拒绝新清理/恢复登记；然后终止并回收在跑子进程；运行中的任务写 `failed`/`shutdown`，未完成结果绝不改写成成功。
6. Node 被 `SIGKILL` 或异常终止时，Python 已无法执行收尾；Linux 内核在父进程消失后向 launcher/rm 发送 `SIGKILL`，因此删除子进程不会继续存活。任务状态和结果随 Node 进程丢失为未知，目录可能已部分删除；这是明确接受的结果。
7. lifespan 的 `finally` 调用登记器关闭，并等待正常关闭流程结束再让进程退出。POSIX 使用独立进程组/会话，正常关闭可终止整组；本地 Windows 测试环境不承诺 Linux 父死亡语义，相关测试用假 launcher/`Popen` 或显式 skip 的非 Linux 集成测试。

替代方案 `shutil.rmtree` 随 Node 线程死亡而停止，但无法满足“删除子进程必须结束”和可终止回收要求；替代方案 `preexec_fn` 在多线程进程里不安全；两者都拒绝。

### 8. Ctrl/Web 消费协议

Node 只提供事实；当前 Ctrl 的手动清理、定时清理和磁盘升级清理都通过这套协议消费。以下 Ctrl/Web 行为是外部协作契约，不在本仓实现，Node 验收只覆盖任务事实与 409。

- **受理**：Ctrl 在本地先建立 `(machine_id, path)` 活动记录，调用 `start_clean_mount` 收到 200 后向 Web 返回“已受理”，Web 立刻展示清理中，不再等待。Ctrl 的路径键取自己已保存的业务路径；Node 的规范化键可能与之不同，因此 Ctrl 只做第一层拦截，Node 的 409 是最终门禁。若 Node 在返回 `task_id` 前拒绝或启动请求失败，Ctrl 移除本地待受理记录并返回失败，不写成功/失败执行 oplog；若无法确定 Node 是否已受理，后续同路径请求的 409 仍由 Node 兜底。
- **轮询**：Ctrl 在后台按有界间隔持续查询 `task_id`；Node 不设固定删除超时，`state=running` 可以持续任意长时间。`running` 继续；`succeeded` 才进入成功分支；`failed` 进入失败分支。Ctrl 自己的轮询预算/超时只是消费端策略，超过后判未知，不等同于 Node 终止任务。
- **成功**：仅当返回的 `task_id` 与本地记录一致且 `state="succeeded"`，Ctrl 才在既有结构中标记已清理并写成功 oplog。启动成功、查询成功、目录缺失、HTTP 200 都不够。
- **失败**：`state="failed"` 写失败 oplog，不标记已清理；失败任务可能已部分删除，列表/恢复文案不得把它显示成“已清理”。
- **未知**：轮询超时、Node 重启后 404、连接不可用、响应无法解析等无法确认终态的情况，Ctrl 判为未知；不标记已清理，不写成功 oplog。未知只存在 Ctrl 进程内，不要求新增持久结构。
- **重启**：Ctrl 重启可丢失活动记录和轮询；不得从目录不存在、日志或旧记录回填成功。若 Node 仍有同路径任务，新的清理/恢复会收到 409，Ctrl 必须按“仍在进行/未知”处理，而不是成功。
- **列表**：列表状态来自 Ctrl 进程内清理记录；目录不存在属于正常展示状态，不是错误，也不是自动成功。未知、失败或 Ctrl 重启后恢复按钮重新开放。
- **权限与门禁**：Ctrl 继续使用既有 `container:manage` 等授权；Node 不新增角色门禁。路径锁不是用户授权，只是操作互斥。

### 9. 旧同步端点与旧客户端兼容

`POST /api/clean_mount` 保留同步语义和原响应形状，但内部改为调用同一个登记器的同步方法：锁内规范化、检查和登记临时清理占用，锁外执行同一个受跟踪的 launcher/`rm`，结束后释放占用。旧同步端点保留 30 秒超时：超时先终止/回收并返回既有 500 `timeout`；成功仍只在退出码 0 时返回 `{"success":1}`。底层仍以参数数组执行 `rm -rf`、不经 shell、捕获有界 stderr，失败不假成功；与活动异步清理或恢复预留冲突时新增 409，且不执行删除。

当前 Ctrl 的手动清理、定时清理和磁盘升级清理都使用新异步端点与 `task_id` 轮询；旧同步端点只保留给旧客户端/旧调用方兼容，Node 不强制旧客户端迁移，也不为当前 Ctrl 新增定时器或持久队列。旧同步与异步共享路径锁，因此旧客户端和当前 Ctrl 不会对同一目录双重删除。

既有 `tests/test_clean_mount.py` 的路径校验、参数数组、30 秒超时、stderr 上界和失败语义仍是同步端点的回归契约。测试迁移到新的 launcher/`rm_path` 接缝时保留这些断言，不删除 30 秒/参数/stderr 检查；迁移完成前在 test-plan 中保持未确认，不冒充已通过。

替代方案是让旧端点在异步任务运行时排队等待。它会改变同步端点的时延和超时语义，且需要新的等待队列，拒绝。

### 10. 不持久化、不扩 WSS、不做数据库迁移

任务表、占用表、子进程句柄、Ctrl 的轮询状态全部是进程内对象。Node 和 Ctrl 都不新增表、列、JSON 迁移、文件锁、WSS topic/字段或推送；跨重启恢复明确不做。未知结果由 Ctrl 的进程内状态表达，Ctrl 重启后自然丢失，不补写成功。

## Risks / Trade-offs

- **删除不是原子的**：`rm -rf` 可能删掉一部分后失败、随 Node 强杀/关闭中止；任务只能报失败或丢失，不能给出完整/部分边界。用户已接受恢复入口重新开放后可能恢复出不完整数据。
- **Linux 强杀保障有边界**：PDEATHSIG 覆盖 Node 进程在 Linux 上被 `SIGKILL`/异常终止的情况；断电、宿主崩溃或内核 panic 无法运行任何用户态收尾，重启后只能看到部分目录。非 Linux 生产环境不承诺同等强杀语义；launcher 或 `prctl` 失败时任务失败关闭，不执行无保护的 `rm`。
- **慢删除会长期占用路径**：异步删除不再有 30 秒上限，可能持续数分钟或更久；期间 Node 拒绝同路径重复清理/恢复。Ctrl 自己的轮询超时只会让状态变未知，不会终止 Node 任务，因此恢复可能继续被 Node 409 挡住，直到删除结束或 Node 退出。
- **Ctrl 丢失轮询不补偿**：Ctrl 重启后不会恢复旧任务，也不会扫描目录补写成功；这是“无持久工作流”的直接代价。
- **路径别名可能绕过 Ctrl 第一层**：Ctrl 不接收 Node 的规范化路径，别名可能让 Ctrl 键不同；Node 的规范化锁会返回 409，因此安全性由 Node 兜底，但 Ctrl 的本地展示可能短暂不一致。
- **恢复入参校验前移**：不存在或非法的 `restore_mount_path` 从后台失败变为受理前 400；依赖“先 200 受理、后台再失败”的调用方和测试需要适配，这是原子校验/登记的代价。
- **恢复预留会阻塞较长时间**：镜像构建和恢复账号重建也可能耗时，预留覆盖整个后台流程会暂时阻止同路径清理。这是用可用性换“创建关键阶段不被删”的安全选择。
- **旧同步调用方新增 409**：并发重复清理不再同时执行；只处理 2xx 的旧调用方会把它当失败。这是有意收紧，避免同一目录双重删除。
- **单进程假设**：进程内锁只在每台机器一个 Node 进程时成立。`run.py` 当前是单进程；若未来改成多 worker，需要独立设计跨进程锁，不能沿用本方案。
- **不同路径可并发清理**：本变更不引入全局队列或 I/O 限流，多个不同目录的 `rm` 仍可并行，可能增加磁盘压力；既有 Ctrl 调用频率和授权是当前边界。
- **旧服务测试需要迁移**：既有 `test_clean_mount.py` 对 `subprocess.run` 的替身需迁移到 launcher/`rm_path` 接缝，但 30 秒、参数数组、stderr 上界和失败语义断言必须保留；未迁移前测试计划标为待确认，不宣称已通过。
- **当前 Ctrl 已切异步**：手动、定时和磁盘升级清理都依赖新端点；旧同步只服务旧客户端，不能因为保留旧端点而让当前 Ctrl 继续走同步路径。

## Migration Plan

1. 先部署 Node：新端点上线，旧 `/api/clean_mount` 继续可用；旧客户端不调用新端点时行为不变。
2. 再部署 Ctrl/Web：当前 Ctrl 的手动、定时和磁盘升级清理开始走异步受理与轮询；旧客户端/旧 Ctrl 仍可走同步端点。
3. 若 Ctrl 先部署，新端点缺失会按现有 `node_unsupported` 类降级；不得把 404/405 当成功。
4. 回滚 Node 时，已受理的异步任务随进程消失，Ctrl 必须按未知处理；旧同步端点恢复原行为，不补写成功。
5. 无数据库迁移、无数据回填、无部署顺序要求；上线验证以 `openspec validate --strict`、新增/回归测试、慢删除不截断检查、正常关闭回收检查和 Linux `SIGKILL` 父死亡信号集成检查为准。

## Open Questions

无。任务未知、部分删除、Ctrl 重启丢失轮询和恢复入口重新开放均已作为明确产品边界接受；没有待定的 schema 或持久化方案。
