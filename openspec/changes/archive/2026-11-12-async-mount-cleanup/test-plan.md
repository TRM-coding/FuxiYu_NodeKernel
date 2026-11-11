# Test Plan

本计划中 `[ ]` 行均为待创建或待确认的规划定位，不代表测试已存在或已执行；`[X]` 行只表示已核对现有测试的断言映射。跨仓 Ctrl/Web 场景本仓库只能验证 Node 提供的事实，消费端落账、oplog 与页面展示需在 Ctrl/Web 独立变更验收。

## backend--storage-and-mounts

### Requirement: 有界去重、并发与失败冷却

#### Scenario: 并发 singleflight

- Test/check:
  - [X] tests/test_mount_usage_cache.py::test_singleflight_duplicate_aliases_share_one_du_and_keep_all_items
- Assertion scope: 同批/并发别名只启动一个 `du`，所有路径项都保留并返回 pending；本 MODIFIED 仅要求测量能力不得借去重修改 `clean_mount`，该断言不覆盖清理锁，清理锁由本变更 ADDED 需求承担。

#### Scenario: 大批量有界并发

- Test/check:
  - [X] tests/test_mount_usage_cache.py::test_hundred_paths_run_at_most_four_du_and_http_returns_pending
  - [X] tests/test_mount_usage_cache.py::test_cross_request_batches_share_global_four_worker_limit
- Assertion scope: 100 个路径整批立即 pending，同时运行的 `du` 不超过 4；跨请求共享同一全局上限，不建设通用队列。

#### Scenario: 失败冷却

- Test/check:
  - [X] tests/test_mount_usage_cache.py::test_failure_cooldown_blocks_retry_then_allows_after_sixty_seconds
- Assertion scope: 失败后 59 秒内返回稳定错误且不重启 `du`，60 秒后才允许重试；冷却行为不修改 `clean_mount`。

#### Scenario: 冷却不伪造成功

- Test/check:
  - [X] tests/test_mount_usage_cache.py::test_failure_cooldown_blocks_retry_then_allows_after_sixty_seconds
  - [X] tests/test_mount_usage_cache.py::test_failure_keeps_last_success_internally_but_never_projects_it
- Assertion scope: 冷却期 `bytes` 仍为 null，不因缓存或重复请求返回 0/最后成功值。

### Requirement: 清理后目录检查与旧缓存失效

#### Scenario: 缓存命中后目录被清理

- Test/check:
  - [X] tests/test_mount_usage_cache.py::test_cached_success_is_dropped_after_directory_removal
  - [X] tests/test_mount_usage_api.py::test_cache_hit_then_cleanup_returns_not_found_without_du
- Assertion scope: 目录被清理后下一次查询先检查存在性、丢弃缓存并返回 `not_found`，不启动 `du`。

#### Scenario: 测量期间目录被清理

- Test/check:
  - [X] tests/test_mount_usage_cache.py::test_measurement_during_cleanup_with_query_drops_late_success
  - [X] tests/test_mount_usage_cache.py::test_late_success_without_intervening_query_is_not_published
  - [X] tests/test_mount_usage_cache.py::test_old_result_cannot_publish_after_path_recreated
- Assertion scope: 清理期间/之后晚到的成功结果不发布，路径重建时旧结果也不能覆盖新任务。

#### Scenario: 已清理路径不扫描

- Test/check:
  - [X] tests/test_anvil_storage_snapshots.py::test_mount_usage_does_not_enumerate_parent_or_scan
- Assertion scope: 已清理/不存在路径只做存在性检查，不枚举父目录、不找替代、不扫全盘、不返回旧缓存。

#### Scenario: clean_mount 行为不变

- Test/check:
  - [ ] tests/test_clean_mount.py::test_accepts_legitimate_container_mount_dir
  - [ ] tests/test_clean_mount.py::test_rm_failure_surfaces_stderr
  - [X] tests/test_mount_usage_api.py::test_query_has_no_cleanup_docker_or_wss_side_effects
- Assertion scope: 统计能力不向 `clean_mount` 注入缓存/回调；旧服务测试迁移到 launcher 接缝后仍断言参数数组、30 秒超时、stderr 上界和失败不假成功。`clean_mount` 的路径互斥/异步生命周期由本变更 ADDED 需求承担，不属于统计能力。
- Coverage note: 前两行是待迁移的旧 `subprocess.run` 替身，尚未完成 launcher 接缝迁移，保持未确认；查询端点零清理副作用由既有 `test_query_has_no_cleanup...` 覆盖。旧测试迁移的完整行见“旧同步成功/错误”场景。

### Requirement: 详情与既有行为兼容

#### Scenario: 旧 Ctrl 不调用

- Test/check:
  - [X] tests/test_mount_usage_api.py::test_existing_check_disk_usage_contract_unchanged
  - [X] tests/test_verify_bind_mount.py::test_http_and_wss_share_same_disk_usage_fields
- Assertion scope: 旧 Ctrl 只走既有磁盘读面时响应/WSS 字段不变；本 MODIFIED 仅排除 `clean_mount` 的统计修改禁令，不改变这些字段。

#### Scenario: 旧 Node 无端点

- Test/check:
  - [X] tests/test_mount_usage_api.py::test_old_node_fallback_shapes_are_404_or_405
- Assertion scope: 旧 Node 不提供 `/api/check_mount_usage` 时返回既有 404/405，不伪造 0 或成功。

#### Scenario: 详情无 Node 参与

- Test/check:
  - [X] tests/test_mount_usage_api.py::test_query_has_no_cleanup_docker_or_wss_side_effects
- Assertion scope: 统计查询不触发清理/Docker/容器读取，也不向 `clean_mount` 注入详情或缓存行为。

#### Scenario: 不改变恢复/清理/冻结资格

- Test/check:
  - [X] tests/test_mount_usage_api.py::test_query_has_no_cleanup_docker_or_wss_side_effects
  - [X] tests/test_verify_bind_mount.py::test_path_diagnostic_never_gates_measurement_or_q72_fixture
- Assertion scope: 统计查询结果不写资格、不调用清理；`clean_mount` 的互斥由本变更单独授权，不改变 Ctrl 的业务资格。

#### Scenario: 无数据库迁移

- Test/check:
  - [X] tests/test_mount_usage_api.py::test_query_has_no_cleanup_docker_or_wss_side_effects
  - [X] tests/test_mount_usage_api.py::test_real_http_du_pending_success_cache_hit_then_not_found
- Assertion scope: 统计端点不产生持久化副作用；仓库无新增数据库迁移，回滚只失去统计能力。

### Requirement: 异步清理启动与状态线路契约

#### Scenario: 启动清理只返回受理和任务标识

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_start_returns_acceptance_and_task_id
- Assertion scope: 合法路径 POST 返回 HTTP 200，响应键恰为 `success`、`task_id`，`success==1`；不包含 `state`、`succeeded`、`mount_path` 或目录内容。用阻塞的删除替身证明响应在删除完成前返回，受理不等于清理成功。

#### Scenario: 查询运行中的任务

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_status_reports_running_task
- Assertion scope: 查询已受理且删除替身被阻塞的任务，返回 HTTP 200、`success==1`、同一 `task_id`、`state=="running"`、`error_reason is None`，响应无目录内容或 stderr。

#### Scenario: 查询成功的任务

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_status_reports_succeeded_task
- Assertion scope: 删除替身以 0 退出后，查询返回同一 `task_id`、`state=="succeeded"`、`error_reason is None`，HTTP 200 且 `success==1`。

#### Scenario: 查询失败的任务

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_status_failed_task_is_query_success
- Assertion scope: 删除替身以非零退出后，状态查询仍为 HTTP 200、`success==1`，但任务 `state=="failed"`、`error_reason` 非空且稳定；响应不被改成 `success==0`，也不泄漏 stderr。

### Requirement: 异步清理错误与未知任务语义

#### Scenario: 非法路径不建立任务

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_invalid_path_returns_400_without_task
- Assertion scope: 越界、缺 `containers` 段等路径返回 400、`success==0`、`error_reason=="invalid_path"`；任务表无新 id、删除替身零调用、目标目录仍存在。

#### Scenario: 重复清理返回冲突

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_duplicate_cleanup_returns_409_with_one_spawn
- Assertion scope: 首个任务保持 `running` 时第二次启动返回 409、`error_reason=="cleanup_in_progress"`；只生成一个 `task_id`，删除子进程启动次数为 1，首个任务状态不变。

#### Scenario: 清理遇到恢复预登记返回冲突

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_cleanup_conflicts_with_restore_reservation
- Assertion scope: 先登记恢复预留，再启动同路径清理，返回 409、`error_reason=="restore_in_progress"`；不创建清理任务、不启动 `rm`，恢复预留仍保持。

#### Scenario: 未知或过期任务不可伪造结果

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_unknown_task_returns_404_not_success
- Assertion scope: 随机 id 和已淘汰 id 都返回 HTTP 404、`success==0`、`error_reason=="not_found"`；不返回 `running`、`succeeded` 或任何终态字段。

#### Scenario: 未预期异常不伪装成任务结果

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_internal_failure_returns_500_not_success
- Assertion scope: 让登记器或查询抛出未预期异常，端点返回 500、`success==0`、`error_reason=="internal_error"`，不建立成功任务，也不调用删除子进程。

### Requirement: Node 权威路径规范化与原子互斥

#### Scenario: 同一真实目录的路径别名共享一把锁

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_path_aliases_share_one_canonical_lock
- Assertion scope: 以含 `..` 的等价路径和目录 symlink 请求同一真实目录；首个任务运行中，其余请求都归一到同一键并返回 409，删除子进程只启动一次。非 Linux 不能创建 symlink 时 skip symlink 参数，`..` 参数仍执行。

#### Scenario: 并发启动只有一个登记成功

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_concurrent_start_only_one_registration
- Assertion scope: 用线程 Barrier 同时发起两个同路径启动；结果恰有一个 200 和一个 409 `cleanup_in_progress`，登记器只有一个任务，删除子进程启动一次。

#### Scenario: 校验失败不占用路径

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_invalid_path_does_not_leave_reservation
- Assertion scope: 先以非法路径请求并得到 400，再创建合法目录并请求清理；第二次可正常取得新 `task_id`，证明前一次拒绝没有留下任务或路径占用。

#### Scenario: 终态释放路径后允许重试

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_terminal_releases_path_for_new_task
- Assertion scope: 首个任务进入 `succeeded` 或 `failed` 后，同路径再次启动返回 200 和新 `task_id`；旧终态仍可查询，但不再阻塞新任务。

#### Scenario: 互斥只作用于本 Node 机器

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_two_manager_instances_have_independent_locks
- Assertion scope: 两个独立登记器实例（模拟两台 Node 进程）对同一规范化路径都能登记自己的任务，互不返回 409；各自任务 id 和状态互不共享。
- Coverage note: 以两个 manager 实例做进程级代理验证，未做真实双机网络集成；跨机器区分另由 Ctrl 的 `machine_id` 键覆盖。

### Requirement: 进程内有界任务状态与重启语义

#### Scenario: 终态任务有界淘汰

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_terminal_tasks_evict_by_count_and_age
- Assertion scope: 用缩小的数量和 TTL 上限制造终态记录，超过上限后最旧终态被淘汰并返回 404 `not_found`；保留的记录仍可查询，活动任务不参与淘汰。

#### Scenario: 活动任务不被淘汰

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_active_tasks_are_not_evicted
- Assertion scope: 终态记录达到上限时仍有 `running` 任务，淘汰后该运行任务和路径占用仍存在，状态查询仍为 `running`。

#### Scenario: 终态不被晚到结果改写

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_terminal_state_is_not_overwritten_by_late_result
- Assertion scope: 任务已写入 `succeeded`/`failed` 后再次提交相反结果，终态和 `error_reason` 保持不变；路径占用不会被重新建立。

#### Scenario: Node 重启丢失任务

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_restart_drops_old_task_and_returns_404
- Assertion scope: 旧登记器任务存在时创建新登记器模拟重启；用旧 `task_id` 查询返回 404 `not_found`，不重建任务、不返回旧成功，目录存在性不改变结果。

#### Scenario: 重启后任务标识不复用

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_new_epoch_never_reuses_old_task_id
- Assertion scope: 两个登记器分别创建任务；新任务 id 的进程纪元与旧 id 不同，字符串不相等，旧 id 在新登记器中不可查询。

#### Scenario: 目录不存在不等于成功

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_missing_directory_does_not_create_success
- Assertion scope: 用从未登记/已淘汰的 `task_id` 查询，而对应目录不存在；返回 404 `not_found`，不生成 `succeeded`，不写成功记录；目录存在性不进入任务终态判定。

#### Scenario: 不持久化任务状态

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_task_lifecycle_does_not_write_db_wss_or_files
- Assertion scope: 启动、查询、淘汰与重启期间不写数据库/文件、不新增 WSS topic/字段或推送；用 WSS 构建/发送替身和文件系统 sentinel 断言零调用或零变化。

### Requirement: 异步删除子进程与关闭生命周期

#### Scenario: 退出码 0 才算成功

- Test/check:
  - [ ] tests/test_mount_cleanup_process.py::test_exit_zero_marks_succeeded
  - [ ] tests/test_mount_cleanup_process.py::test_rm_uses_argument_list_without_shell
- Assertion scope: 假 launcher/`Popen` 以 0 退出后任务为 `succeeded`、`error_reason is None`；启动参数为不含 shell 的参数列表，目标路径作为独立参数传入。

#### Scenario: 非零退出为失败

- Test/check:
  - [ ] tests/test_mount_cleanup_process.py::test_nonzero_exit_marks_failed_with_rm_failed
- Assertion scope: 假删除进程退出 1 后任务为 `failed`、`error_reason=="rm_failed"`；查询响应不包含 stderr，任务不进入成功。

#### Scenario: 慢删除不被固定超时截断

- Test/check:
  - [ ] tests/test_mount_cleanup_process.py::test_slow_rm_stays_running_without_fixed_timeout
- Assertion scope: 删除替身被事件阻塞，worker 等待时不传固定 timeout，超时终止/`timeout` 失败路径零调用，任务保持 `running`；释放事件后按真实退出码收敛。
- Coverage note: 不实际等待 31 秒；用阻塞替身和无 timeout 等待证明不按固定 30 秒截断，覆盖“慢删除不失败”的关键行为。

#### Scenario: 启动或执行异常落为失败

- Test/check:
  - [ ] tests/test_mount_cleanup_process.py::test_spawn_or_worker_exception_marks_internal_error
- Assertion scope: launcher 启动失败或 worker 抛异常时任务为 `failed`、`error_reason=="internal_error"`；不留永久 `running` 记录，不返回成功。

#### Scenario: Linux 强杀 Node 不遗留删除子进程

- Test/check:
  - [ ] tests/test_mount_cleanup_linux_parent_death.py::test_sigkill_parent_kills_rm_via_pdeathsig
  - [ ] tests/test_mount_cleanup.py::test_restart_drops_old_task_and_returns_404
- Assertion scope: Linux 下由子 Node 进程通过显式注入的假 `rm_path` 启动一个阻塞的假 `rm`，测试对 Node 发 `SIGKILL`；轮询真实子进程的 `/proc/<pid>/stat`，只断言进程不存在或状态为 `Z`（已死亡而非运行中）且 sentinel 未被后续删除。强杀后不查询、不声称可观察已死进程内的任务状态；旧 `task_id` 不可复用由另起新登记器（模拟重启）返回 404 的既有计划用例单独断言。
- Coverage note: 仅 Linux 运行；非 Linux 跳过并明确不承诺父死亡语义。强杀结果按未知处理，不把“无成功侧效应”伪造成进程内终态；测试不替代断电/内核 panic 场景。

#### Scenario: 父死亡信号启动竞态不启动 rm

- Test/check:
  - [ ] tests/test_mount_cleanup_linux_parent_death.py::test_launcher_parent_mismatch_exits_without_exec_rm
- Assertion scope: 通过登记器的显式 `rm_path` 注入，直接以不匹配的预期父 PID 启动 launcher；launcher 在 exec 前非零退出，假 `rm` 的 sentinel 不存在，证明 Node 在设置父死亡信号前消失时不会留下删除进程。
- Coverage note: 仅 Linux launcher 可执行；非 Linux 用 skip。注入只用于测试，线路协议不增加删除程序路径字段。

#### Scenario: Node 关闭终止子进程

- Test/check:
  - [ ] tests/test_mount_cleanup_process.py::test_shutdown_terminates_children_and_marks_shutdown
- Assertion scope: 正常关闭时登记器先拒绝新登记，再终止/回收已登记子进程；运行任务变成 `failed`/`shutdown`，不变成成功，关闭调用等待回收完成。

#### Scenario: 关闭期间拒绝新任务

- Test/check:
  - [ ] tests/test_mount_cleanup_process.py::test_shutdown_rejects_new_cleanup_and_restore
- Assertion scope: 登记器进入关闭状态后，新的清理启动和恢复预留都被拒绝，删除子进程零启动，不生成成功任务。

#### Scenario: 部分删除不伪装成功

- Test/check:
  - [ ] tests/test_mount_cleanup_process.py::test_partial_deletion_after_failure_is_not_success
- Assertion scope: 假删除先删除临时目录中的一个文件再非零退出；任务为 `failed`，剩余文件仍可能保留，Node 不检查目录是否消失来改写成 `succeeded`。

### Requirement: 旧同步清理与旧客户端兼容

#### Scenario: 旧同步成功保持原形状

- Test/check:
  - [X] tests/test_blueprint_api.py::test_clean_mount_success
  - [X] tests/test_anvil_storage_snapshots.py::test_clean_mount_wire_models
  - [ ] tests/test_clean_mount.py::test_accepts_legitimate_container_mount_dir
  - [ ] tests/test_mount_cleanup_sync_compat.py::test_old_sync_waits_for_exit_zero
- Assertion scope: 既有端点用例断言合法请求把 `mount_path` 交给服务并返回 `{"success":1}`，旧请求/响应模型无额外字段。迁移后的服务用例仍断言无 shell 的 `rm` 参数数组 `["rm","-rf",realpath]`、30 秒等待、捕获 stderr 和 realpath；计划端点用例断言 HTTP 在退出 0 后才返回且不返回 `task_id`。
- Coverage note: `test_accepts_legitimate_container_mount_dir` 仍替身 `subprocess.run`，迁移到 launcher/`rm_path` 接缝前保持 `[ ]`；不得删除其 30 秒/参数/stderr 断言后冒充通过。

#### Scenario: 旧同步错误保持可辨识

- Test/check:
  - [X] tests/test_blueprint_api.py::test_clean_mount_invalid_path_400
  - [X] tests/test_blueprint_api.py::test_clean_mount_rm_failure_500
  - [ ] tests/test_clean_mount.py::test_rm_failure_raises
  - [ ] tests/test_clean_mount.py::test_rm_failure_surfaces_stderr
  - [ ] tests/test_clean_mount.py::test_rm_failure_truncates_huge_stderr
  - [ ] tests/test_clean_mount.py::test_rejects_traversal_paths
  - [ ] tests/test_clean_mount.py::test_rejects_symlink_escaping_base
  - [ ] tests/test_mount_cleanup_sync_compat.py::test_old_sync_timeout_remains_500_timeout_with_30_seconds
- Assertion scope: 既有端点用例断言非法路径仍是 400 `invalid_path`、删除失败仍是 500 `success=0`。迁移后的服务用例仍断言失败抛错并带 `--- rm output ---`、stderr 仅保留 10 行且截断行数明确、越界/symlink 逃逸不执行删除。计划用例用可控慢删除跨过 30 秒边界，断言先终止/回收再返回 500 `timeout`。
- Coverage note: 五条 `tests/test_clean_mount.py` 行是待迁移的旧 `subprocess.run` 替身；迁移保留 30 秒/参数/stderr 断言，当前不宣称已确认。

#### Scenario: 旧同步遇到活动任务返回冲突

- Test/check:
  - [ ] tests/test_mount_cleanup_sync_compat.py::test_old_sync_conflicts_with_async_and_restore
- Assertion scope: 参数化活动异步清理和恢复预留；旧端点都返回 409，原因分别为 `cleanup_in_progress`/`restore_in_progress`，删除替身零调用。

#### Scenario: 两个旧同步请求不并发删除

- Test/check:
  - [ ] tests/test_mount_cleanup_sync_compat.py::test_two_old_sync_requests_only_one_rm
- Assertion scope: 两个线程用同一路径同时调用旧端点；恰一个删除并返回 200，另一个返回 409，删除子进程启动次数为 1。

#### Scenario: 旧客户端继续使用同步端点

- Test/check:
  - [ ] tests/test_mount_cleanup_sync_compat.py::test_old_endpoint_remains_old_client_compatible
- Assertion scope: 无活动占用时旧端点仍返回原同步成功/失败形状，不返回 `task_id`，旧客户端不需要创建新任务或持久状态。

#### Scenario: 当前 Ctrl 三类清理走异步

- Test/check:
  - [ ] tests/test_mount_cleanup_sync_compat.py::test_new_ctrl_three_cleanup_paths_use_async_contract
- Assertion scope: Node 同时提供异步启动/状态端点和旧同步端点；测试规划断言新客户端三类流程所需的 `task_id`/轮询字段存在，旧端点不回退为这三类流程的实现路径。
- Coverage note: 当前 Ctrl 的手动、定时与磁盘升级路由在 Ctrl 仓实现；本行只规划 Node 契约，实际三类路由切换需跨仓验收。

### Requirement: Ctrl/Web 受理、后台轮询与入口互斥

#### Scenario: Web 只等待受理

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_start_returns_acceptance_and_task_id
- Assertion scope: Node 启动响应在删除完成前返回且只含受理字段；Web 在 Ctrl 受理后不再等待的具体行为不在本仓执行。
- Coverage note: Web 的等待与页面状态在 Web 仓实现，本行只证明 Node 提供了“可立即返回的受理事实”，不能替代 Web 验收。

#### Scenario: Ctrl 后台轮询

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_status_reports_running_then_terminal_sequence
- Assertion scope: Node 对同一 `task_id` 先返回 `running`，删除替身结束后返回 `succeeded`，字段和 id 保持一致；Ctrl 的轮询调度本身不在本仓执行。
- Coverage note: Ctrl 轮询器、间隔与后台生命周期在 Ctrl 仓实现，本行只验证 Node 状态序列可供轮询消费。

#### Scenario: Ctrl 阻止同路径重复操作

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_duplicate_cleanup_returns_409_with_one_spawn
- Assertion scope: Node 对同路径第二次清理返回 409 且只启动一个删除进程；Ctrl 在本地活动状态存在时拒绝第二次操作的入口行为不在本仓执行。
- Coverage note: Ctrl 的本地入口拦截需在 Ctrl 仓验收；本行证明即使 Ctrl 漏拦，Node 也不会重复删除。

#### Scenario: Node 是规范化路径的最终门禁

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_path_aliases_share_one_canonical_lock
- Assertion scope: 不同文本路径归一到同一 realpath 后返回 409，Node 只保留一个任务；Ctrl 是否使用相同路径键不在本仓执行。
- Coverage note: Ctrl 的路径键与 Node 规范化路径可能不同，跨仓展示一致性需在 Ctrl/Web 验收；Node 的 409 是安全兜底。

#### Scenario: 不新增数据库或持久工作流

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_task_lifecycle_does_not_write_db_wss_or_files
- Assertion scope: Node 任务生命周期不写数据库/文件、不新增 WSS topic/字段；Ctrl/Web 的 schema 与持久工作流不在本仓执行。
- Coverage note: “Ctrl/Web 不新增 schema”需在 Ctrl/Web 仓做迁移与代码审查；本行只证明 Node 侧不新增持久化。

### Requirement: 清理成功、失败与未知落账边界

#### Scenario: 明确成功才标记已清理

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_start_returns_acceptance_and_task_id
  - [ ] tests/test_mount_cleanup.py::test_status_reports_succeeded_task
- Assertion scope: 启动受理不返回 `succeeded`，只有删除退出 0 后状态才为 `succeeded`；Ctrl/Web 的已清理标记和成功 oplog 写入不在本仓执行。
- Coverage note: “仅 succeeded 才标记已清理并写成功 oplog”属于 Ctrl/Web 消费逻辑，需跨仓验收；Node 侧只保证可信终态事实。

#### Scenario: 明确失败只写失败 oplog

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_status_failed_task_is_query_success
  - [ ] tests/test_mount_cleanup_process.py::test_nonzero_exit_marks_failed_with_rm_failed
- Assertion scope: 非零退出产生 `state="failed"` 和非空 `error_reason`，查询本身仍成功；Ctrl 的失败 oplog、未标已清理不在本仓执行。
- Coverage note: 失败 oplog 与“不写成功 oplog”需在 Ctrl 仓验收；本行只证明 Node 不会把失败报成成功。

#### Scenario: 轮询超时为未知

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_unknown_task_returns_404_not_success
- Assertion scope: Node 对未知/淘汰任务返回 404 而非成功；Ctrl 如何计时、超时后如何标记未知不在本仓执行。
- Coverage note: 轮询预算、超时判定和未知展示在 Ctrl/Web 仓实现；Node 没有固定 30 秒删除超时可被 Ctrl 当作结果截止时间。

#### Scenario: Node 重启丢结果为未知

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_restart_drops_old_task_and_returns_404
- Assertion scope: 重启后旧任务查询 404，Node 不重建成功；Ctrl 将 404/失联映射为未知的行为不在本仓执行。
- Coverage note: 跨仓未知映射需在 Ctrl 仓验收；Node 只保证旧 id 不可复用且不伪造终态。

#### Scenario: 失败可能部分删除

- Test/check:
  - [ ] tests/test_mount_cleanup_process.py::test_partial_deletion_after_failure_is_not_success
- Assertion scope: 删除一部分后非零退出仍为 `failed`，剩余文件可能存在，Node 不把部分删除报成功；Ctrl/Web 如何提示部分删除不在本仓执行。
- Coverage note: 用户可见的“可能不完整”提示在 Ctrl/Web 仓实现；Node 只保证不伪造成功。

### Requirement: Ctrl 重启与目录缺失的展示边界

#### Scenario: Ctrl 重启不补成功

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_restart_drops_old_task_and_returns_404
- Assertion scope: Node 重启后旧任务不可查询、不提供成功事实；Ctrl 重启丢轮询、不补写成功的行为不在本仓执行。
- Coverage note: Ctrl 重启后的无回填策略需在 Ctrl 仓验收；Node 侧不提供可补写的旧成功记录。

#### Scenario: 目录不存在正常显示

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_missing_directory_does_not_create_success
- Assertion scope: 目录不存在不会生成 `succeeded` 任务；列表是否正常展示、如何显示缺失目录不在本仓执行。
- Coverage note: 列表展示在 Ctrl/Web 仓实现；本行仅证明 Node 不把目录缺失当作清理成功。

#### Scenario: 恢复入口重新开放

- Test/check:
  - [ ] tests/test_mount_cleanup_restore.py::test_cleanup_failure_releases_path_for_restore
- Assertion scope: 清理失败后路径占用释放，保留的目录可以再次登记恢复预留；按钮/入口重新开放的 UI 行为不在本仓执行。
- Coverage note: 恢复按钮的可用性与提示在 Ctrl/Web 仓实现；Node 侧只保证失败终态不永久占用路径。

#### Scenario: Node 活动锁覆盖 Ctrl 丢失的状态

- Test/check:
  - [ ] tests/test_mount_cleanup.py::test_duplicate_cleanup_returns_409_with_one_spawn
  - [ ] tests/test_mount_cleanup_restore.py::test_restore_rejected_when_cleanup_running
- Assertion scope: Node 对活动清理的重复清理和恢复都返回 409，即使调用方没有本地状态；Ctrl 丢失活动状态后的提示不在本仓执行。
- Coverage note: 跨仓恢复入口与状态提示需在 Ctrl/Web 验收；Node 的路径锁是最终一致门禁。

## backend--container-creation

### Requirement: 恢复创建的原子校验与路径预登记

#### Scenario: 合法恢复先登记后受理

- Test/check:
  - [ ] tests/test_mount_cleanup_restore.py::test_restore_reserves_path_before_accepting
- Assertion scope: 合法恢复请求返回受理前登记恢复预留；用阻塞后台创建证明预留已存在，同路径清理此时返回 409。请求返回 200 后才进入后台创建。
- Coverage note: 既有 `test_blueprint_api.py::test_create_container_restore_payload_passes_mount_and_accounts` 使用不存在的 `/tmp/...` 路径，实现前移校验后需改为临时真实目录；本计划不把该旧用例当作已验证映射。

#### Scenario: 清理进行中拒绝恢复

- Test/check:
  - [ ] tests/test_mount_cleanup_restore.py::test_restore_rejected_when_cleanup_running
- Assertion scope: 同路径清理任务保持 `running` 时，恢复请求返回 409 `cleanup_in_progress`；不返回创建受理，后台 create 零调用，删除子进程不启动。

#### Scenario: 两个恢复争用同一路径只受理一个

- Test/check:
  - [ ] tests/test_mount_cleanup_restore.py::test_two_restore_requests_only_one_reservation
- Assertion scope: 两个恢复请求用 Barrier 同时争用同一真实目录；恰一个 200 并取得预留，另一个 409 `restore_in_progress`，后台创建只执行一次。

#### Scenario: 恢复路径非法时不留状态

- Test/check:
  - [ ] tests/test_mount_cleanup_restore.py::test_invalid_restore_path_rejected_before_accept
  - [X] tests/test_anvil_creation_credentials.py::test_restore_mount_path_requires_containers_segment_and_existing_dir
- Assertion scope: 越界、缺 `containers` 段、公共根、不存在或非目录的恢复路径返回 400 `invalid_path`；不进入后台、无 Docker 调用、无残留预留。既有服务层用例断言缺段/不存在/symlink 逃逸被拒且 `containers.run` 零调用。

#### Scenario: 普通新建不受路径锁影响

- Test/check:
  - [ ] tests/test_mount_cleanup_restore.py::test_normal_create_does_not_take_restore_reservation
- Assertion scope: 不携带 `restore_mount_path` 的创建不登记恢复预留；同路径清理不会被该创建阻塞，普通新建仍进入既有后台创建流程。

### Requirement: 恢复关键阶段的预留持有与释放

#### Scenario: 恢复创建期间清理被拒绝

- Test/check:
  - [ ] tests/test_mount_cleanup_restore.py::test_cleanup_rejected_during_restore_background
- Assertion scope: 恢复后台仍阻塞时，同路径异步清理和旧同步清理都返回 409，删除替身零调用；恢复预留直到后台终态才释放。

#### Scenario: 恢复与清理的并发窗口只允许一方

- Test/check:
  - [ ] tests/test_mount_cleanup_restore.py::test_restore_cleanup_race_allows_one_winner
- Assertion scope: 用 Barrier 同时发起恢复和清理；只有一个取得路径占用，另一个得到 409；不允许恢复受理后又并行启动删除。

#### Scenario: 创建成功后释放预留

- Test/check:
  - [ ] tests/test_mount_cleanup_restore.py::test_restore_reservation_released_after_success
- Assertion scope: 恢复后台进入成功终态后预留被释放；同路径后续清理/恢复不再收到本变更的恢复占用冲突，后续仍受既有授权和容器状态约束。

#### Scenario: 创建失败后释放并允许重试

- Test/check:
  - [ ] tests/test_mount_cleanup_restore.py::test_restore_reservation_released_after_failure
- Assertion scope: 恢复后台失败后 `finally` 释放预留；同路径清理或第二次恢复可重新登记，旧失败不永久占锁。

#### Scenario: Node 重启丢失预留

- Test/check:
  - [ ] tests/test_mount_cleanup_restore.py::test_restart_drops_restore_reservation
- Assertion scope: 旧登记器的恢复预留存在时创建新登记器模拟重启；新登记器可为同一路径取得恢复预留，旧预留不恢复；允许恢复可能看到部分删除的数据。

#### Scenario: 部分删除目录在重启后可恢复

- Test/check:
  - [ ] tests/test_mount_cleanup_restore.py::test_partial_cleanup_survives_restart_and_restore_is_accepted
- Assertion scope: 先留下部分删除但仍存在的目录，再以新登记器执行恢复预检；断言目录被接受、无需旧任务或旧预留、恢复受理不要求目录完整。
- Coverage note: 部分目录恢复是用户明确接受的边界；测试只断言预检接受现存部分目录并登记/受理，不保证恢复出的数据完整。
