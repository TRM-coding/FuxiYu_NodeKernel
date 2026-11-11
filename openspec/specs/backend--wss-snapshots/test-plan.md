# backend--wss-snapshots Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: delete-event 数据契约 [network/wss.py]

#### Scenario: 状态缓存报告某容器删除

- Test/check:
  - [X] `tests/test_cache_collectors.py::test_ctrl_link_sends_deleted_frames_before_snapshot`
  - [X] `tests/test_prevent_vanished.py::test_external_delete_queues_once_and_wss_sends_delete_before_snapshot`
- Assertion scope: 确认删除候选后先发 `{"type": "delete", "container_name": "ghost-1/old"}`，再发 `snapshot_batch`；候选只取一次。

#### Scenario: 未知状态参与消失核实

- Test/check:
  - [X] `tests/test_prevent_vanished.py::test_failed_create_unknown_without_id_is_confirmed_absent`
  - [X] `tests/test_prevent_vanished.py::test_failed_create_unknown_kept_when_confirmation_fails`
  - [X] `tests/test_prevent_vanished.py::test_failed_create_unknown_kept_when_docker_object_exists`
  - [X] `tests/test_prevent_vanished.py::test_in_flight_create_is_not_cleared_by_empty_list`
  - [X] `tests/test_prevent_vanished.py::test_action_started_during_absence_confirmation_preserves_cache`
  - [X] `tests/test_prevent_vanished.py::test_same_name_create_during_enumeration_invalidates_old_delete_candidate`
- Assertion scope: 创建失败且无 Docker ID 的 unknown 在 NotFound 后清除并排队；确认失败时保留 unknown 并报告采集错误；存在但状态不认识时保留 unknown；创建中、新动作与同名换代均不得被消失对账清除。

#### Scenario: 排队后同名新建

- Test/check:
  - [X] `tests/test_runtime_guard.py::test_delete_candidate_dropped_when_same_name_reappears_before_send`
  - [X] `tests/test_prevent_vanished.py::test_same_name_create_during_enumeration_invalidates_old_delete_candidate`
  - [X] `tests/test_prevent_vanished.py::test_create_acceptance_cancels_queued_delete_candidate`
- Assertion scope: 候选排队后同名新代出现/受理 create，发送前复核丢弃候选，本轮不发送该名称 delete。

#### Scenario: Docker 采集不可判定

- Test/check:
  - [X] `tests/test_prevent_vanished.py::test_failed_confirmation_keeps_candidate_and_collect_error`
  - [X] `tests/test_prevent_vanished.py::test_delete_candidates_are_held_while_collect_error_is_set`
  - [X] `tests/test_cache_collectors.py::test_wss_status_snapshot_sends_collect_error_shape`
- Assertion scope: 单容器确认失败时保留候选并置 collect_error；`take_confirmed_deleted()` 在 collect_error 下返回空，不发送 delete；真实 `build_status_snapshot()` 在 collect_error 下发送 `{"collect_error": "collect_failed"}` 帧，而不是空表或伪正常。

### Requirement: snapshot-batch 数据契约 [network/wss.py]

#### Scenario: 建立有效身份的 WSS 链接

- Test/check:
  - [X] `tests/test_cache_collectors.py::test_wss_snapshot_batch_reads_all_cache_views`
  - [X] `tests/test_cache_collectors.py::test_ctrl_link_accepts_matching_uid_and_pushes_snapshot`
  - [X] `tests/test_cache_collectors.py::test_lifespan_starts_caches_without_outbound_pusher`
  - [X] `tests/test_anvil_storage_snapshots.py::test_lifespan_has_no_outbound_connection_attempt`
- Assertion scope: 批次 `type == "snapshot_batch"`、`node_uid` 为持久化身份 uid，payload 依次四帧 container_status/last_ssh/disk_usage/sys_snapshot；Ctrl 拨入 `/ws/ctrl` 后首帧即整批快照；lifespan 只启动缓存，清空 Ctrl 目标地址类环境变量后仍能启动，且没有 socket/asyncio/websocket 出站连接尝试。
- Coverage note: 既有 lifespan 用例只断言缓存 start/stop 的调用列表，不能证明无出站 attempt；规划用例以连接入口记录器补该断言，同时覆盖“不要求 Node 配置 Ctrl 目标地址”。

### Requirement: snapshot-container-status 数据契约 [network/wss.py]

#### Scenario: 动作失败但容器实际运行

- Test/check:
  - [X] `tests/test_runtime_guard.py::test_action_failure_does_not_change_runtime_and_last_action_is_separate`
  - [X] `tests/test_action_contracts.py::test_soft_failure_wire_keeps_online_and_failed_only_in_last_action`
  - [X] `tests/test_anvil_storage_snapshots.py::test_unpause_soft_failure_keeps_online_wss_frame`
- Assertion scope: 既有 pause 用例断言动作 failed 时真实运行态仍 online、failed 只在 `last_action.phase`；规划用例用真实 `ContainerStatusCache` 受理 unpause 后将其终结为 failed，再调用真实 `build_status_snapshot()`，断言 payload 的 status 为 online、`last_action.action == "unpause"`、`last_action.phase == "failed"`，且不出现 `unpause_failed` 或容器 status=failed。
- Coverage note: WHEN 明确是 unpause；既有两条 `[X]` 都是 pause，不能替代。规划行补真实 unpause 软失败的 WSS 帧断言。

#### Scenario: pause 软失败但实际 online

- Test/check:
  - [X] `tests/test_runtime_guard.py::test_api_pause_soft_failure_keeps_online_and_exposes_last_action_failed`
  - [X] `tests/test_action_contracts.py::test_soft_failure_wire_keeps_online_and_failed_only_in_last_action`
- Assertion scope: pause 软失败后状态查询/WSS 条目 status 为 online、`last_action.action == "pause"`、`last_action.phase == "failed"`，两者原子分离，不把条目 status 改成 failed。

#### Scenario: 无动作记录仍保留字段

- Test/check:
  - [X] `tests/test_runtime_guard.py::test_wss_status_entry_explicit_last_action_null_and_failed_plus_online`
  - [X] `tests/test_runtime_guard.py::test_cold_start_rebuilds_running_created_exited_dead_and_last_action_null`
  - [X] `tests/test_runtime_guard.py::test_api_status_unknown_explicit_last_action_null`
- Assertion scope: 新 Node 冷启动/无动作记录的容器条目显式含 `last_action: null`，JSON 序列化仍保留；旧 Node 可缺字段。

#### Scenario: 只有硬阻塞发送 failed

- Test/check:
  - [X] `tests/test_runtime_guard.py::test_hard_block_classification_is_bounded`
  - [X] `tests/test_runtime_guard.py::test_read_priority_hard_block_gate_transition_unknown`
  - [X] `tests/test_runtime_guard.py::test_pause_unpause_offline_dead_never_report_success`
  - [X] `tests/test_anvil_storage_snapshots.py::test_wss_status_snapshot_failed_and_unknown_frames`
- Assertion scope: 既有 cache/API 用例断言 created/dead 等硬阻塞与 sshd 硬阻塞发 failed 并保留有界 failed_reason，普通动作软失败不把 status 改 failed；规划用例调用真实 `build_status_snapshot()`，断言硬阻塞条目 payload 的 `status == "failed"`、`failed_reason` 为有界原因，不由 last_action 或普通采集遮掉。
- Coverage note: 既有行停在 cache/API 状态层；真实 WSS payload 的 failed 帧由此前未覆盖，由规划行承担。

#### Scenario: 无法判定时发送 unknown

- Test/check:
  - [X] `tests/test_runtime_guard.py::test_read_priority_hard_block_gate_transition_unknown`
  - [X] `tests/test_runtime_guard.py::test_reconcile_per_container_inspect_failure_marks_unknown_and_keeps_last_known`
  - [X] `tests/test_runtime_guard.py::test_api_status_unknown_explicit_last_action_null`
  - [X] `tests/test_anvil_storage_snapshots.py::test_wss_status_snapshot_failed_and_unknown_frames`
- Assertion scope: 既有 cache/API 用例断言不可判定时 status 为 unknown、status_source/unknown_since 保留、last_known_status 留内部；规划用例调用真实 `build_status_snapshot()`，断言 WSS payload 中该条目的 `status == "unknown"`、`status_source` 与 `unknown_since` 非空，last_known 不冒充当前实态。
- Coverage note: 既有行没有真实 WSS unknown 帧断言；规划行补 payload 字段。

#### Scenario: Docker 状态采集失败

- Test/check:
  - [X] `tests/test_cache_collectors.py::test_wss_status_snapshot_sends_collect_error_shape`
  - [X] `tests/test_cache_collectors.py::test_status_cache_reconcile_failure_sets_collect_error`
- Assertion scope: collect_error 置位时 payload 恰为 `{"collect_error": "collect_failed"}`，不发送空表或伪 online；Ctrl 可区分采集失败与机器没有容器。

### Requirement: snapshot-disk-usage 数据契约 [network/wss.py]

#### Scenario: 读取磁盘快照

- Test/check:
  - [X] `tests/test_cache_collectors.py::test_disk_usage_cache_collects_overlay_bind_and_snapshot`
  - [X] `tests/test_verify_bind_mount.py::test_http_and_wss_share_same_disk_usage_fields`
  - [X] `tests/test_anvil_storage_snapshots.py::test_wss_disk_usage_distinguishes_zero_missing_and_measuring`
- Assertion scope: 既有用例断言快照含机器磁盘、overlay/bind 字节、业务路径、resolved 状态、真实 measured_at 与 total；HTTP/WSS 同一模型字段一致。规划用例构造三个容器：真实 0 字节成功项（bytes/total 为 0 且 measured_at 非空）、测量中项（total None、bind_source 为 measuring、measured_at None）、无缓存容器（payload 不出现），断言三者不混为同一状态。
- Coverage note: 既有用例覆盖正常正数用量与 HTTP/WSS 一致性，未固定“真实 0/测量中/无缓存”三者区分。

#### Scenario: 路径 unresolved 但同路径测量有效

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_unresolved_with_existing_path_and_valid_measurement_stays_total`
  - [X] `tests/test_verify_bind_mount.py::test_lightweight_path_diagnostic_updates_snapshot_without_touching_measurement`
- Assertion scope: unresolved/not_running 但既有业务路径未变、测量成功且 measured_at 真实时 total 保持有效；路径诊断不阻断业务，也不改写成测量失败。

#### Scenario: 路径变更后的旧样本

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_path_change_drops_old_sample_until_new_path_measured`
  - [X] `tests/test_verify_bind_mount.py::test_snapshot_does_not_publish_cached_path_bytes_under_new_path`
  - [X] `tests/test_verify_barriers.py::test_disk_barrier_trace_keeps_old_du_out_of_new_path`
- Assertion scope: A→B 后缓存 A 的字节不作为 B 的 total，快照发布 B 并等待重测；旧 du 晚到只写 A 的缓存；屏障轨迹断言 B 的 total 232 与 A 的 111 隔离。

#### Scenario: 旧协议缺少真实测量时间

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_container_disk_usage_model_only_has_current_fields_and_null_round_trip`
  - [X] `tests/test_anvil_storage_snapshots.py::test_old_usage_without_measured_at_is_not_current`
- Assertion scope: 旧 usage 缺 measured_at 时模型字段为 None，不推断目录身份；真实缓存读面不把此类旧样本发布为当前 total，不用接收/读取时间补齐为真实测量。
- Coverage note: “消费方按既有接收时间兼容”属 Ctrl 接收侧契约；Node 侧只断言旧样本不被当前化。

#### Scenario: 无 bind 与 overlay-only

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_docker_confirmed_no_bind_clears_paths`
  - [X] `tests/test_verify_bind_mount.py::test_unreadable_mounts_are_unresolved_not_no_bind`
  - [X] `tests/test_verify_bind_mount.py::test_ctrl_compat_fixture_update_preserve_clear_and_old_node`
  - [X] `../FuxiYu_CtrKernel/test/container/test_cross_repo_protocol_replay.py::test_node_no_bind_payload_clears_path_and_uses_overlay_only`
  - [X] `tests/test_anvil_storage_snapshots.py::test_bind_presence_blocks_overlay_only_and_no_bind_composes_overlay`
- Assertion scope: 成功确认无 `/root` bind 时 `bind_mount_path is None`、status 为 no_bind，overlay 有效时 total 等于 overlay；异常/不可读 Mounts 不被当作 no_bind；Node 本地消费方契约夹具对 no_bind 清空当前活跃业务路径；Ctrl 仓库真实消费测试 `test_node_no_bind_payload_clears_path_and_uses_overlay_only` 断言清空 `bind_mount_path`/`disk_bind_mount_bytes`、`disk_total_bytes == 400` 且 `disk_checked_at` 取帧内 `measured_at`。
- Coverage note: Node 本地夹具是独立契约回放；Ctrl 测试是跨仓只读定位，未修改对方 test。规划用例补 no_bind 的 overlay-only total 与有 bind 缺测量的负分支。

#### Scenario: unresolved 不清空路径

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_lightweight_path_diagnostic_updates_snapshot_without_touching_measurement`
  - [X] `tests/test_verify_bind_mount.py::test_inspect_failure_does_not_become_no_bind`
  - [X] `tests/test_verify_bind_mount.py::test_unreadable_mounts_are_unresolved_not_no_bind`
- Assertion scope: unresolved/not_running、inspect/Source 不可读、Mounts 形状损坏均保留既有 `bind_mount_path`；只有明确 no_bind 才置空。

#### Scenario: 相同样本被多次推送

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_repeated_wss_json_does_not_refresh_measured_at`
- Assertion scope: 同一测量周期内两次 WSS 读取保持 measured_at/total 不变，发送/接收时间不变成新测量。

### Requirement: snapshot-last-ssh 数据契约 [network/wss.py]

#### Scenario: 某容器本轮没有真实 SSH 时间

- Test/check:
  - [X] `tests/test_anvil_storage_snapshots.py::test_last_ssh_empty_output_returns_none_and_serializes_updated_at`
  - [ ] `tests/test_anvil_storage_snapshots.py::test_last_ssh_non_running_old_value_returns_none_q77`
- Assertion scope: 独立行断言 `LastSshCache.collect()` 对命令成功但空输出的 running 容器写入 `value=None`；`list_last_ssh()`/`build_last_ssh_snapshot()` 返回 `last_ssh_connect_time=None`，不用采集当前时间冒充登录时间；`updated_at` 为不带时区后缀的 `YYYY-MM-DDTHH:MM:SS`。Q77 行按主 spec 断言：先在 running 时采集真实旧值，随后容器转非 running，`list_last_ssh()`/`build_last_ssh_snapshot()` 仍应返回 `last_ssh_connect_time=None`，不得把缓存旧值当规范期望。Q77 行依赖 Global Q77，保持 `[ ]`、未创建、不 skip/xfail；独立行不依赖该修复，可先补测。
- Coverage note: 既有 `/api/container_last_ssh_time` 成功/404 用例只覆盖有值/缺条目，未断言 None 形状与 updated_at 序列化。Global Q77（607bbfd / 现 6392692）已由父登记：当前 `LastSshCache.collect()` 对非运行态跳过并保留旧缓存值，`list_last_ssh()` 直接回传旧值，与主 spec 的 None 不一致。本计划不改实现、不改历史保留策略、不改主 spec；Q77 依赖断言单独作为暂缓 locator，待 Q77 修复后再实现，且不阻塞其余 26 个独立 planned tests。

### Requirement: snapshot-static-hardware 数据契约 [network/wss.py]

#### Scenario: Ctrl 首连获取硬件画像

- Test/check:
  - [X] `tests/test_anvil_storage_snapshots.py::test_static_hardware_profile_uses_bind_mount_and_cache_expiry`
- Assertion scope: `SysSnapshotCache.collect_static()` 的静态 payload 含 hostname/platform/cpu.cores/memory.total_gb/gpu/disk.total_gb；`disk.total_gb` 取 bind_mount 分区容量而非 docker_data；静态缓存在 `STATIC_TTL_SEC` 内复用，到期后重新采集并更新。
- Coverage note: 既有用例只断言 static 的 cpu/gpu 形状，未断言 disk.total_gb 来源与静态缓存到期重采。

### Requirement: snapshot-sys 数据契约 [network/wss.py]

#### Scenario: 两个数据目录位于不同分区

- Test/check:
  - [X] `tests/test_anvil_storage_snapshots.py::test_sys_snapshot_collects_bind_and_docker_data_partitions`
- Assertion scope: 设置不同 `NODE_CONTAINERS_BASE` 与 `NODE_DOCKER_DATA_ROOT`，真实 `_collect_disk()` 对两个路径分别调用 `shutil.disk_usage`，快照返回 bind_mount/docker_data 各自的 path/total/used/free/percent；两者不互相覆盖，返回值只用于显示。
- Coverage note: 既有 sys 用例把 `_collect_disk` 整体替身，未验证两个路径的分别采集；容器限额与创建流程不在本用例范围。

### Requirement: Ctrl 拨入链路端点与身份门禁 [network/wss.py]

#### Scenario: 复用既有端口与证书

- Test/check:
  - [X] `tests/test_blueprint_api.py::test_ctrl_link_endpoint_registered_on_same_app`
  - [X] `tests/test_blueprint_api.py::test_node_self_signed_certificate_is_valid_pin_anchor`
  - [X] `tests/test_cache_collectors.py::test_ctrl_ca_trust_file_bootstraps_public_ca`
- Assertion scope: `/ws/ctrl` 与操作/身份端点注册在同一 FastAPI app，常量字面量为 `/ws/ctrl`；Node 自签证书可解析且含 server/client auth EKU；配置 Ctrl CA 信任文件时能 bootstrap 公共 CA。
- Coverage note: WSS 握手的客户端证书校验由 `run.py` uvicorn `ssl_ca_certs`/`CERT_REQUIRED` 启动配置承担，单元测试不建立真实 TLS；这里断言同一 app/证书与 CA 信任文件就绪。

#### Scenario: uid 不符则拒绝

- Test/check:
  - [X] `tests/test_cache_collectors.py::test_ctrl_link_rejects_uid_mismatch`
  - [X] `tests/test_cache_collectors.py::test_ctrl_link_rejects_missing_uid`
- Assertion scope: 连接 uid 与本机身份牌不一致或缺失时，`handle_ctrl_ws` 不 accept、close code 为 4403、frames 为空，在推送任何帧之前关闭。

#### Scenario: 身份牌未就绪不推送

- Test/check:
  - [X] `tests/test_cache_collectors.py::test_ctrl_link_rejects_when_identity_not_initialized`
- Assertion scope: `load_node_identity()` 为 None 时 close 4404、不 accept、不建推送循环、frames 为空。

#### Scenario: 无入站连接时不产生出站流量

- Test/check:
  - [X] `tests/test_cache_collectors.py::test_lifespan_starts_caches_without_outbound_pusher`
  - [X] `tests/test_anvil_storage_snapshots.py::test_lifespan_has_no_outbound_connection_attempt`
- Assertion scope: 既有 lifespan 用例只断言采集缓存的 start/stop 调用；无出站 attempt 由规划测试断言：清空 Ctrl 目标地址类环境变量后运行 lifespan，用 `socket.create_connection`、`socket.socket.connect`、`asyncio.open_connection`、`websockets.connect`（若可导入）的记录器确认全部未被调用。既有 calls 列表本身不证明无出站。
- Coverage note: 函数名与 calls 列表本身不能证明无出站 attempt；规划行把连接入口是否被调用作为决定性断言。

### Requirement: 状态快照与旧 Ctrl 收敛

#### Scenario: 旧 Ctrl 忽略动作诊断

- Test/check:
  - [X] `tests/test_runtime_guard.py::test_old_ctrl_mapping_ignores_action_fields_and_recovers_status`
- Assertion scope: 旧消费方只读 status/source/status_source 时仍映射 online；last_action 留在 JSON 中但不改变旧 Ctrl 映射结果。

#### Scenario: 旧 Ctrl 收到恢复后的 online

- Test/check:
  - [X] `tests/test_runtime_guard.py::test_old_ctrl_mapping_ignores_action_fields_and_recovers_status`
  - [X] `tests/test_runtime_guard.py::test_action_failure_does_not_change_runtime_and_last_action_is_separate`
  - [X] `tests/test_cache_collectors.py::test_cold_start_running_container_waits_for_sshd_probe`
- Assertion scope: 动作失败后真实运行态仍 online，旧 Ctrl 只按 status 收敛，可恢复此前被 failed pending 覆盖的状态；冷启动 running 经 ready probe 后进入 online，不需要读 last_action/action_ref。

#### Scenario: 旧 Node 缺字段

- Test/check:
  - [X] `tests/test_action_contracts.py::test_mixed_version_missing_optional_fields_and_restart_epoch`
  - [X] `tests/test_runtime_guard.py::test_old_ctrl_mapping_ignores_action_fields_and_recovers_status`
- Assertion scope: 旧 Node 帧/响应缺 action_ref/last_action 时，使用动作绑定的消费方按自身 timeout 降级；不使用动作绑定的消费方只按真实状态处理，不要求 Node 补发回执。

#### Scenario: 可选动作诊断缺失

- Test/check:
  - [X] `tests/test_action_contracts.py::test_mixed_version_missing_optional_fields_and_restart_epoch`
  - [X] `tests/test_runtime_guard.py::test_old_ctrl_mapping_ignores_action_fields_and_recovers_status`
- Assertion scope: 只读既有 status/source/status_source 的消费方在 last_action 缺失时仍收敛运行态；动作诊断缺失不影响状态判断。

#### Scenario: 不依赖新 DB 字段

- Test/check:
  - [X] `tests/test_action_contracts.py::test_soft_failure_wire_keeps_online_and_failed_only_in_last_action`
  - [X] `tests/test_runtime_guard.py::test_wss_status_entry_explicit_last_action_null_and_failed_plus_online`
- Assertion scope: WSS 条目/JSON 包含既有 status/source/status_source/last_action 字段，运行态与 unknown/硬阻塞语义仍可解释；Node 不依赖新 DB 列。
- Coverage note: Ctrl DB 是否存在新列不在 Node 仓库；Node 侧断言快照包含既有状态字段且不读取/输出 DB 列，DB 消费不在 Node 测试范围。

### Requirement: pause 终态与 Ctrl 确认边界

#### Scenario: pause 软失败但容器仍在运行

- Test/check:
  - [X] `tests/test_runtime_guard.py::test_api_pause_soft_failure_keeps_online_and_exposes_last_action_failed`
  - [X] `tests/test_action_contracts.py::test_soft_failure_wire_keeps_online_and_failed_only_in_last_action`
- Assertion scope: 软失败后 WSS/状态查询 status 为 online、`last_action.phase == "failed"`；不发送 status=failed，也不把动作 ref 终结当作实际 paused。

#### Scenario: 终态 paused 才确认

- Test/check:
  - [X] `tests/test_runtime_guard.py::test_pause_preserves_ready_identity_and_unpause_reuses_it`
- Assertion scope: 真实 pause 动作使容器状态到 paused 才 confirmed；快照 status 为 paused，ready identity 保留；unpause 后回 online。

#### Scenario: online 不得被当作 pause_failed

- Test/check:
  - [X] `tests/test_runtime_barriers.py::test_sylvan_timeline_real_slow_list_and_stats_does_not_rollback`
  - [X] `tests/test_action_contracts.py::test_soft_failure_wire_keeps_online_and_failed_only_in_last_action`
- Assertion scope: 慢 list/stats 交错后容器仍 online，last_action 为 idempotent_confirmed，`unpause_failed` 不出现；online 本身不被解释为 pause 成功/失败，实际暂停仍等 paused。
- Coverage note: 消费方如何解释 online 不在 Node 仓库；Node 侧断言快照保持 online 与 last_action 分离，paused 终态由真实 pause 用例覆盖。

#### Scenario: 缺 ref 或字段

- Test/check:
  - [X] `tests/test_action_contracts.py::test_mixed_version_missing_optional_fields_and_restart_epoch`
  - [X] `tests/test_action_contracts.py::test_consumer_rejects_old_ref_wrong_direction_and_unknown_phase_without_failed`
- Assertion scope: 旧 Node 帧无 last_action 时消费方按自身 timeout 降级；无 ref/未知 phase 时 Node 不伪造 failed，实际 pause 只按真实 paused 确认。

#### Scenario: confirmed 但运行态反向

- Test/check:
  - [X] `tests/test_anvil_storage_snapshots.py::test_confirmed_pause_last_action_keeps_online_snapshot`
- Assertion scope: 在真实 `ContainerStatusCache` 上受理 pause 并把 last_action 终结为 confirmed，但 Docker 实态仍 running/not paused；构造 WSS 快照后断言条目 status 为 online、`last_action.phase == "confirmed"`、未出现 paused，Node 不用动作 phase 覆盖运行态。
- Coverage note: 消费方不得仅凭 phase 写 paused；Node 侧可断言快照保持 online 与 last_action 分离。

#### Scenario: 真实 Docker 故障仍可失败

- Test/check:
  - [X] `tests/test_runtime_guard.py::test_pause_unpause_offline_dead_never_report_success`
  - [X] `tests/test_runtime_guard.py::test_hard_block_classification_is_bounded`
  - [X] `tests/test_cache_collectors.py::test_cold_start_created_container_marks_failed`
- Assertion scope: dead/created 等硬故障发 failed 并保留 failed_reason（如 docker_dead）；pause/unpause 对 offline/dead 不报成功；failed 表示运行态故障而非 pause_failed。

### Requirement: 动作引用与 Ctrl 过渡终结

#### Scenario: ACK 先到

- Test/check:
  - [X] `tests/test_action_contracts.py::test_ack_first_and_wss_first_close_exact_ref_without_ack_forced_failure`
- Assertion scope: HTTP ACK 先到、WSS 同 ref accepted 不结束过渡；同 ref confirmed 到达后才结束；运行态仍按实际状态。

#### Scenario: WSS 终结先到

- Test/check:
  - [X] `tests/test_action_contracts.py::test_ack_first_and_wss_first_close_exact_ref_without_ack_forced_failure`
- Assertion scope: WSS 终结帧先到时消费方按 ref 有界暂存，ACK 到达并精确匹配后应用；Node 不因等 ACK 伪造 failed，回执丢失保持 unconfirmed。

#### Scenario: 旧 ref 或未知 phase

- Test/check:
  - [X] `tests/test_action_contracts.py::test_consumer_rejects_old_ref_wrong_direction_and_unknown_phase_without_failed`
- Assertion scope: 旧/未知 ref、错误方向、未知 phase 均不结束消费方过渡，也不让 Node 伪造 failed；消费方只按自身 timeout 降级。

#### Scenario: Node 重启 epoch 失效

- Test/check:
  - [X] `tests/test_action_contracts.py::test_mixed_version_missing_optional_fields_and_restart_epoch`
  - [X] `tests/test_runtime_guard.py::test_wipe_old_epoch_and_last_action_after_restart`
- Assertion scope: 新 `ContainerStatusCache` 的 node_epoch 与旧对象不同，旧 ref finish 返回 False，新 Node 无动作记录输出 `last_action: null`；旧 ref 永不匹配。

#### Scenario: 非 pause 动作不误匹配

- Test/check:
  - [X] `tests/test_action_contracts.py::test_consumer_rejects_old_ref_wrong_direction_and_unknown_phase_without_failed`
- Assertion scope: 同一 ref 下消费方 ACK 的 action 为 start、WSS last_action.action 为 pause 时，方向不匹配，过渡不结束；只有 action 方向匹配的 ref 可参与终结。

### Requirement: 路径控制与测量字段作用域

#### Scenario: 路径控制字段缺失

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_container_disk_usage_model_only_has_current_fields_and_null_round_trip`
  - [X] `tests/test_verify_bind_mount.py::test_ctrl_compat_fixture_update_preserve_clear_and_old_node`
- Assertion scope: 旧 usage 缺 mount_path_status 时模型默认 unresolved；已有 bind_mount_path 仍可使用，不推断目录身份；旧 Ctrl 夹具对缺失 status 保留既有路径。

#### Scenario: 测量字段缺失

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_container_disk_usage_model_only_has_current_fields_and_null_round_trip`
  - [X] `tests/test_verify_bind_mount.py::test_ctrl_compat_fixture_update_preserve_clear_and_old_node`
  - [X] `tests/test_anvil_storage_snapshots.py::test_old_usage_without_measured_at_is_not_current`
- Assertion scope: 旧 usage 缺 measured_at 时模型为 None；真实缓存读面不把旧 total 当前化，不用接收时间冒充测量时间；消费方契约夹具按缺失/未验证处理。

#### Scenario: HTTP 与 WSS 一致

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_http_and_wss_share_same_disk_usage_fields`
- Assertion scope: 同一容器用量经 HTTP `/api/check_disk_usage` 与 WSS `disk_usage` 返回时，bind_mount_path/mount_path_status/measured_at/overlay/bind/total/source/error 全相等。

#### Scenario: 路径纠正只体现为业务路径

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_source_matches_actual_resolved_without_wire_identity`
  - [X] `tests/test_verify_bind_mount.py::test_mismatched_source_unique_candidate_corrects_business_path`
  - [X] `tests/test_verify_bind_mount.py::test_container_disk_usage_model_only_has_current_fields_and_null_round_trip`
  - [X] `tests/test_verify_bind_mount.py::test_guard_runtime_identity_fields_are_not_disk_protocol`
- Assertion scope: 路径纠正结果只改 bind_mount_path，内部 Source/configured_mount_path/observed_at 不进入线路；模型字段集合无 docker_id/bind_identity/measurement_identity；诊断由 mount_path_status 表达。

#### Scenario: 禁止新增测量协议字段

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_http_and_wss_share_same_disk_usage_fields`
  - [X] `tests/test_verify_bind_mount.py::test_guard_runtime_identity_fields_are_not_disk_protocol`
  - [X] `tests/test_verify_bind_mount.py::test_container_disk_usage_model_only_has_current_fields_and_null_round_trip`
- Assertion scope: usage 字段集合不存在 disk_protocol_version/collector_epoch/observation_seq/measurement_status/measurement_mount_path/measurement_reason；模型与 WSS JSON 均无这些字段，也没有第二套测量状态/排序协议。
