# Proposal

## Why

已删除容器的挂载目录清理目前同步执行：Web/Ctrl 请求要等 `rm -rf` 结束，Node 重启时也没有可查询的异步任务结果。清理与恢复还可能在同一目录上交错，导致恢复刚登记的目录被并发删除，或者重复清理同时启动。

## What Changes

- Node 新增 `POST /api/start_clean_mount`：校验并原子登记清理任务，立即返回 `success=1` 与 `task_id`；同一机器上同一规范化路径已有清理或恢复占用时返回冲突，不启动新的删除。
- Node 新增 `POST /api/get_clean_mount_status`：按 `task_id` 返回 `running`、`succeeded`、`failed` 与稳定的 `error_reason`。查询成功只表示查询完成，任务是否清理成功只由 `state` 表达。
- 新增进程内有界任务表与路径互斥登记：任务只活在当前 Node 进程；终态记录有数量/时间上限；Node 重启后旧任务不可查询，也不复用旧 `task_id`。
- 路径规范化以 Node 为准：`realpath`、`NODE_CONTAINERS_BASE` 边界、`containers` 路径段和现有路径白名单共同决定唯一键；异步清理、旧同步清理和恢复创建共用同一把按路径的进程内锁。
- 恢复创建携带 `restore_mount_path` 时，在返回受理前完成规范化、存在性校验、清理占用检查与恢复预登记；预登记覆盖后台创建的关键阶段，清理请求在预登记期间返回冲突。
- 异步删除使用可终止、可等待的子进程，不设置固定删除超时；成功只在 `rm` 退出码为 0 时成立，非零和启动/执行异常都落为失败。Node 正常关闭时终止并回收在跑子进程；Linux 下另用父死亡信号覆盖 `SIGKILL`/异常终止，避免 Node 消失后遗留 `rm`，绝不把中断写成成功。
- 旧 `POST /api/clean_mount` 保持同步请求/响应形状、30 秒超时和既有错误语义，但接入同一路径互斥；与进行中的异步清理或恢复冲突时返回失败，不并发删除。旧端点只保留给旧客户端/旧调用方兼容；当前 Ctrl 的手动清理、定时清理和磁盘升级清理均走新异步协议。
- 主规格中原先“本统计能力不得修改 `clean_mount`”的三处 Requirement 通过 MODIFIED delta 收窄为“不得借统计/缓存修改”，明确本变更授权的路径互斥与子进程生命周期，避免归档后规则冲突。
- Ctrl/Web 侧按外部协作协议消费：Web 只等待 Ctrl 受理；Ctrl 在后台轮询任务结果，只有明确 `succeeded` 才标记已清理并写成功 oplog，明确 `failed` 写失败 oplog，轮询超时、Node 重启丢任务等一律为未知，不得伪造成功。Ctrl 重启可丢失轮询且不补成功记录；目录不存在正常展示，不据此回填成功。
- 明确接受：删除失败或中断可能留下部分删除的目录，恢复按钮重新开放后可能恢复出不完整数据；不新增数据库结构、不引入持久工作流、不新增 WSS topic/字段，也不建设通用队列框架。

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `backend--storage-and-mounts`: 增加异步清理任务端点、Node 权威路径规范化、按路径原子互斥、进程内有界任务状态、删除子进程生命周期、旧同步端点仅向旧客户端兼容，以及当前 Ctrl 三类清理走异步的外部契约；同时 MODIFIED 三处旧 `clean_mount` 禁止修改约束，使其只限制统计/缓存能力。
- `backend--container-creation`: 增加恢复创建在受理前的原子校验与固定规范化路径预登记，以及与清理任务的串行互斥和关键阶段保护。

## Impact

- Node API：`network/api.py` 新增两个端点；既有 `/api/clean_mount` 保留并接入互斥。
- Node 模型：`schemas/container.py` 增加启动/状态请求响应模型与任务状态值，不新增持久化 schema。
- Node 服务：`services/container_service.py` 的路径规范化与删除执行被清理任务共享；新增进程内任务/锁模块并在应用 lifespan 关闭阶段停止。
- Node 生命周期：`__init__.py` 关闭顺序加入任务管理器停止；Linux 异步删除子进程带父死亡信号，正常关闭与强制终止都不遗留删除进程。
- 测试：新增异步清理、并发冲突、恢复串行、任务表边界、慢删除不截断、Linux 强杀子进程回收、正常关闭和旧端点 30 秒超时回归测试；旧 `tests/test_clean_mount.py` 的参数数组、30 秒超时和 stderr 上界断言迁移到 launcher 接缝，不删除。
- 跨仓：Ctrl/Web 按本协议接入受理、后台轮询、成功/失败/未知落账和列表状态；当前 Ctrl 的手动、定时和磁盘升级清理均切到异步协议，旧同步端点只向旧客户端保留。当前仓库只落 Node 侧契约与实现计划，不改 Ctrl/Web 仓库。
- 数据库与部署：无数据库结构变动、无迁移、无持久任务恢复；Node/Ctrl 重启的已知结果丢失由未知态和重新开放恢复入口承担。
