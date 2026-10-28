# backend--container-lifecycle Test Plan

Spec: [spec.md](spec.md)

## Current Mapping


### Requirement: ContainerNameConfig 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_remove_container_missing_name_400
  - [X] tests/test_anvil_lifecycle_contracts.py::test_name_config_alias_and_field_validation
- Assertion scope: 现有测试证明空 config 能通过 ContainerNameConfig 并在端点返回 missing_container_name；断言：两个字段默认 None、name 别名可单独赋值、非字符串输入被 Pydantic 拒绝，且 _container_name 在两者同时设置时优先 container_name、仅 name 时回退、两者皆空返回 None。

### Requirement: ContainerOperationAcceptedResponse 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_start_container_success_accepts_with_action_ref
  - [X] tests/test_anvil_lifecycle_contracts.py::test_container_response_models_default_success_and_optional_fields
- Assertion scope: 现有测试经真实端点构造受理响应并断言 container_status=starting、action_ref.node_epoch 与 seq；断言：最小构造时 success 缺省为 1、action_ref 缺省 None、缺 container_status/container_name 时 ValidationError。
- Coverage note: 既有测试未断言 success 缺省与必填字段拒绝；补齐测试覆盖这些模型断言。旧 Node 缺 action_ref 时 Ctrl 侧如何降级属跨仓行为，Node 测试不验证。

#### Scenario: 动作受理返回引用

- Test/check:
  - [X] tests/test_blueprint_api.py::test_pause_container_success_accepts_with_action_ref
  - [X] tests/test_action_contracts.py::test_ack_first_and_wss_first_close_exact_ref_without_ack_forced_failure
- Assertion scope: 端点测试断言 pause 受理响应在过渡态下返回 action_ref；动作契约测试断言 HTTP ACK 的 ref 与后续 WSS last_action.ref 完全一致。

### Requirement: ContainerStatusMessage 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_container_status_online
  - [X] tests/test_anvil_lifecycle_contracts.py::test_container_message_models_require_config
- Assertion scope: 现有测试经端点提交 config 并断言 container_status=online；断言：ContainerStatusMessage 缺 config 时 ValidationError、嵌套 ContainerNameConfig 默认字段保留。

### Requirement: ContainerStatusResponse 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_action_contracts.py::test_mixed_version_missing_optional_fields_and_restart_epoch
  - [X] tests/test_anvil_lifecycle_contracts.py::test_container_response_models_default_success_and_optional_fields
  - [X] tests/test_anvil_lifecycle_contracts.py::test_status_response_hard_block_fields
- Assertion scope: 现有测试构造最小 ContainerStatusResponse，断言 last_action 显式为 None、container_status 保持 online、不含 action_ref；断言：success 缺省 1、cache_updated_at/error/error_reason/failed_* 等可选字段缺省 None、非法 status 被拒绝，并断言硬阻塞响应 success=0 且保留 error/error_reason/failed_reason/failed_detail，软失败 success=1、仅 last_action.failed 且 failed_* 为 None。

#### Scenario: 运行态与动作诊断同响应

- Test/check:
  - [X] tests/test_action_contracts.py::test_soft_failure_wire_keeps_online_and_failed_only_in_last_action
- Assertion scope: 构造 last_action.phase=failed、error_reason=state_mismatch 的响应，断言运行态仍为 online，且 HTTP/WSS wire 中 failed 只出现在 last_action。

### Requirement: ContainerLastSshTimeMessage 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_container_last_ssh_time_success
  - [X] tests/test_anvil_lifecycle_contracts.py::test_container_message_models_require_config
- Assertion scope: 现有端点测试提交 config 并断言 last_ssh_connect_time；断言：ContainerLastSshTimeMessage 缺 config 时 ValidationError。

### Requirement: ContainerLastSshTimeResponse 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_container_last_ssh_time_success
  - [X] tests/test_anvil_lifecycle_contracts.py::test_container_response_models_default_success_and_optional_fields
  - [X] tests/test_anvil_lifecycle_contracts.py::test_last_ssh_wss_allows_none
- Assertion scope: 现有端点测试断言 last_ssh_connect_time 值；断言：最小响应 success 缺省 1、缺 container_name/last_ssh_connect_time 时 ValidationError；WSS 全量 last_ssh 快照允许 last_ssh_connect_time=None 且不丢失该条目。
- Coverage note: 既有测试未断言 success 缺省、必填字段拒绝和 WSS last_ssh 的 None 值；补齐测试覆盖这些断言。Ctrl 没有新观察时保留旧值属跨仓读策略，Node 测试不验证。

### Requirement: MachineStatusMessage 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_machine_status_online
  - [X] tests/test_anvil_lifecycle_contracts.py::test_container_message_models_require_config
- Assertion scope: 现有端点测试以 config={} 调用并断言 machine_status=online；断言：MachineStatusMessage() 默认使用 EmptyConfig，且空 config 可序列化为 {}。

### Requirement: MachineStatusResponse 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_machine_status_online
  - [X] tests/test_anvil_lifecycle_contracts.py::test_container_response_models_default_success_and_optional_fields
- Assertion scope: 现有端点测试断言 machine_status=online；断言：最小响应 success 缺省 1，非法 machine_status 被 Literal 拒绝。

### Requirement: RemoveContainerMessage 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_remove_container_missing_name_400
  - [X] tests/test_anvil_lifecycle_contracts.py::test_container_message_models_require_config
- Assertion scope: 现有测试证明空 config 可通过模型并由端点返回 missing_container_name；断言：RemoveContainerMessage 缺 config 时 ValidationError。

### Requirement: RemoveContainerResponse 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_remove_container_success
- Assertion scope: 端点测试断言删除成功响应 success=1，证明 RemoveContainerResponse 的缺省 success 在真实响应中生效。

### Requirement: StartContainerMessage 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_start_container_success_accepts_with_action_ref
  - [X] tests/test_anvil_lifecycle_contracts.py::test_container_message_models_require_config
- Assertion scope: 现有端点测试提交 config 并断言受理状态；断言：StartContainerMessage 缺 config 时 ValidationError。

### Requirement: StartContainerResponse 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_start_container_success_accepts_with_action_ref
  - [X] tests/test_anvil_lifecycle_contracts.py::test_container_response_models_default_success_and_optional_fields
- Assertion scope: 现有测试断言 container_status=starting、action_ref 存在；断言：最小响应 success 缺省 1、必填字段缺失时 ValidationError。

### Requirement: StopContainerMessage 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_stop_container_success_accepts_with_action_ref
  - [X] tests/test_anvil_lifecycle_contracts.py::test_container_message_models_require_config
- Assertion scope: 现有端点测试提交 config 并断言 container_status=stopping；断言：StopContainerMessage 缺 config 时 ValidationError。

### Requirement: StopContainerResponse 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_stop_container_success_accepts_with_action_ref
  - [X] tests/test_anvil_lifecycle_contracts.py::test_container_response_models_default_success_and_optional_fields
- Assertion scope: 现有测试断言 container_status=stopping、action_ref.seq>=1；断言：最小响应 success 缺省 1、必填字段缺失时 ValidationError。

### Requirement: RestartContainerMessage 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_restart_container_success_accepts_with_action_ref
  - [X] tests/test_anvil_lifecycle_contracts.py::test_container_message_models_require_config
- Assertion scope: 现有端点测试提交 config 并断言 container_status=restarting；断言：RestartContainerMessage 缺 config 时 ValidationError。

### Requirement: RestartContainerResponse 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_restart_container_success_accepts_with_action_ref
  - [X] tests/test_anvil_lifecycle_contracts.py::test_container_response_models_default_success_and_optional_fields
- Assertion scope: 现有测试断言 container_status=restarting、action_ref.node_epoch 与 cache 一致；断言：最小响应 success 缺省 1、必填字段缺失时 ValidationError。

### Requirement: PauseContainerConfig 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_anvil_lifecycle_contracts.py::test_pause_config_default_and_literal_rejection
- Assertion scope: 断言：PauseContainerConfig(container_name='c1') 的 action 缺省为 'pause'，显式 'pause'/'unpause' 均可接受，'resume' 被 Literal 拒绝。

### Requirement: PauseContainerMessage 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_pause_container_success_accepts_with_action_ref
  - [X] tests/test_anvil_lifecycle_contracts.py::test_container_message_models_require_config
- Assertion scope: 现有端点测试提交 config 并断言受理状态；断言：PauseContainerMessage 缺 config 时 ValidationError。

### Requirement: PauseContainerResponse 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_pause_container_success_accepts_with_action_ref
  - [X] tests/test_anvil_lifecycle_contracts.py::test_container_response_models_default_success_and_optional_fields
- Assertion scope: 现有测试断言 container_status=pausing、action_ref 存在；断言：最小响应 success 缺省 1、必填字段缺失时 ValidationError。

### Requirement: ContainerStatus 数据契约 [schemas/container.py]

#### Scenario: 使用声明值域

- Test/check:
  - [X] tests/test_blueprint_api.py::test_container_status_online
  - [X] tests/test_blueprint_api.py::test_container_status_pending
  - [X] tests/test_blueprint_api.py::test_container_status_miss_unknown
  - [X] tests/test_runtime_guard.py::test_api_create_visible_before_background_thread_finishes
  - [X] tests/test_anvil_lifecycle_contracts.py::test_container_status_literal_domain
- Assertion scope: 现有端点/运行时测试分别断言 online、starting、unknown、creating 等线路值；断言：参数化覆盖 13 个声明值均可构造，'sleeping' 被 Literal 拒绝。

### Requirement: PauseAction 数据契约 [schemas/container.py]

#### Scenario: 使用声明值域

- Test/check:
  - [X] tests/test_blueprint_api.py::test_pause_container_success_accepts_with_action_ref
  - [X] tests/test_blueprint_api.py::test_unpause_container_success_accepts_with_action_ref
  - [X] tests/test_anvil_lifecycle_contracts.py::test_pause_config_default_and_literal_rejection
- Assertion scope: 现有端点测试分别接受 action=pause 与 action=unpause；断言：非法 'resume' 被拒绝，并与 pause 缺省值场景共用参数化。

### Requirement: ContainerNameMessage 数据契约 [schemas/container.py]

#### Scenario: 使用声明值域

- Test/check:
  - [X] tests/test_anvil_lifecycle_contracts.py::test_wire_alias_models_preserve_shapes
- Assertion scope: 断言：直接用 ContainerNameMessage 构造 config，断言 container_name/name 的序列化形状与 ContainerStatusMessage 一致，缺 config 时 ValidationError。

### Requirement: LastSshTimeResponse 数据契约 [schemas/container.py]

#### Scenario: 使用声明值域

- Test/check:
  - [X] tests/test_anvil_lifecycle_contracts.py::test_wire_alias_models_preserve_shapes
- Assertion scope: 断言：直接用 LastSshTimeResponse 构造最小响应，断言 success 缺省 1、container_name/last_ssh_connect_time 必填，序列化与 ContainerLastSshTimeResponse 一致。

### Requirement: MachineStatus 数据契约 [constant.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] tests/test_anvil_lifecycle_contracts.py::test_internal_enums_and_remove_result_contracts
  - [X] tests/test_anvil_lifecycle_contracts.py::test_machine_status_type_boundary
- Assertion scope: 断言：MachineStatus 成员值 online/offline/maintenance 可用于内部数据传递；MachineStatusResponse 接受字符串 'online' 而拒绝 MachineStatus.ONLINE 枚举成员，证明运行层枚举与 schemas Literal 分别维护。

### Requirement: MachineTypes 数据契约 [constant.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] tests/test_anvil_lifecycle_contracts.py::test_internal_enums_and_remove_result_contracts
- Assertion scope: 断言：MachineTypes 成员值 GPU/CPU，并验证这些枚举成员可用于内部数据传递。

### Requirement: ContainerStatus 数据契约 [constant.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] tests/test_runtime_guard.py::test_hard_block_classification_is_bounded
  - [X] tests/test_runtime_guard.py::test_pause_unpause_offline_dead_never_report_success
  - [X] tests/test_anvil_lifecycle_contracts.py::test_internal_enum_type_boundary
- Assertion scope: 现有测试断言 ContainerStatus.ONLINE/OFFLINE/RESTARTING/FAILED 的 .value 参与运行态分类与断言；断言：逐一覆盖 10 个成员值，并断言 ContainerStatusResponse 接受字符串值而拒绝 constant 枚举成员，证明两套同名类型分别维护。

### Requirement: RemoveContinaerReturn 数据契约 [services/container_service.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] tests/test_remove_container.py::test_error_path_container_not_exist
  - [X] tests/test_remove_container.py::test_error_path_invalid_config
  - [X] tests/test_anvil_lifecycle_contracts.py::test_internal_enums_and_remove_result_contracts
- Assertion scope: 现有服务测试断言 NOTFOUND(1) 与 FAILED(2)；断言：SUCCESS(0) 常量，并用 fake Docker 走通删除成功后第二次 get 抛 NotFound 的 SUCCESS 路径。

### Requirement: 创建过渡态先于受理响应可见

#### Scenario: 受理响应快于后台线程

- Test/check:
  - [X] tests/test_runtime_guard.py::test_api_create_visible_before_background_thread_finishes
  - [X] tests/test_prevent_vanished.py::test_in_flight_create_is_not_cleared_by_empty_list
- Assertion scope: API 测试在后台线程阻塞时断言快照已含 creating 且不 vanish；reconcile 测试在空列表下断言 building 与 action_ref 保留、无删除候选。

### Requirement: 对账观察边界

#### Scenario: 创建与慢速枚举交错

- Test/check:
  - [X] tests/test_prevent_vanished.py::test_create_during_enumeration_is_not_vanished
- Assertion scope: 枚举过程中新建的容器被加入缓存后，断言状态为 creating 且 take_deleted() 为空。

#### Scenario: 同名新代替换旧代

- Test/check:
  - [X] tests/test_prevent_vanished.py::test_same_name_create_during_enumeration_invalidates_old_delete_candidate
  - [X] tests/test_prevent_vanished.py::test_create_acceptance_cancels_queued_delete_candidate
- Assertion scope: 同名 create 受理/枚举交错时断言旧删除候选被清空、新 create 过渡态保留；create 受理本身也取消已排队候选。

#### Scenario: 同名 Docker ID 更换

- Test/check:
  - [X] tests/test_runtime_guard.py::test_valid_current_observation_drives_identity_change_and_supersedes_old_action
  - [X] tests/test_runtime_guard.py::test_old_generation_late_observation_cannot_replace_again_or_cancel_new_pending
  - [X] tests/test_anvil_lifecycle_contracts.py::test_identity_change_invalidates_old_delete_candidate
- Assertion scope: 当前代、当前 action_seq 的观察返回新 Docker ID 时，断言 generation 递增、docker_id 更新、旧 last_action 置 superseded 且运行态按新对象重新门禁；旧 observation ticket 由 test_old_generation_late_observation... 断言被拒绝；断言：预置旧删除候选后换代，候选队列为空。

#### Scenario: 旧代观察晚到

- Test/check:
  - [X] tests/test_runtime_guard.py::test_old_generation_late_observation_cannot_replace_again_or_cancel_new_pending
- Assertion scope: 旧代观察晚到看到新 ID 时断言 publish_observed 返回 False，generation/docker_id 不变，新 create pending 不被取消。

#### Scenario: 本地代际不跨进程

- Test/check:
  - [X] tests/test_action_contracts.py::test_mixed_version_missing_optional_fields_and_restart_epoch
  - [X] tests/test_prevent_vanished.py::test_external_delete_queues_once_and_wss_sends_delete_before_snapshot
- Assertion scope: 动作契约测试断言 Node 重启生成不同 node_epoch、旧 ref 终结被拒绝；WSS 测试断言 delete 帧只含 type/container_name。
- Coverage note: Node 侧只能证明本地代际与 delete 帧形状；Ctrl 的待核实/Q70 跨进程隔离不在本仓库，未宣称验证。

### Requirement: 消失须经 Docker 再确认

#### Scenario: Docker 对象仍存在

- Test/check:
  - [X] tests/test_prevent_vanished.py::test_docker_still_exists_keeps_cache_and_does_not_queue
- Assertion scope: 列表漏报但单容器 get 仍找到对象时，断言缓存保留且 take_deleted() 为空。

#### Scenario: Docker 查询失败

- Test/check:
  - [X] tests/test_prevent_vanished.py::test_failed_confirmation_keeps_candidate_and_collect_error
  - [X] tests/test_runtime_guard.py::test_reconcile_vanished_candidate_requires_notfound_and_generation_check
- Assertion scope: 单容器确认抛异常时断言缓存保留、collect_error=collect_failed、无删除候选；明确 NotFound 后才进入删除候选。

### Requirement: Docker 状态事件兼容

#### Scenario: 事件只有 Action

- Test/check:
  - [X] tests/test_runtime_guard.py::test_event_action_field_only_triggers_fresh_inspect
  - [X] tests/test_anvil_lifecycle_contracts.py::test_event_positive_trace_and_unknown_diagnostic
- Assertion scope: 现有测试断言仅 Action 字段事件会触发 containers.get 并收敛为 starting；断言：捕获 event_log.record，start 事件在 inspect 前记录状态轨迹。

#### Scenario: 事件不直接写运行态

- Test/check:
  - [X] tests/test_runtime_guard.py::test_event_inspect_failure_keeps_last_known
  - [X] tests/test_runtime_guard.py::test_event_action_field_only_triggers_fresh_inspect
  - [X] tests/test_anvil_lifecycle_contracts.py::test_event_inspect_failure_keeps_last_known_with_diagnostic
- Assertion scope: 事件后 inspect 失败时断言保留 online；事件到达且 inspect 成功时断言按新鲜事实收敛，而不是按事件文本直接覆盖；断言：inspect 失败时 caplog 记录含容器名和失败原因的 WARNING，且状态仍为最后已知。

#### Scenario: exec 动作带冒号后缀

- Test/check:
  - [X] tests/test_runtime_guard.py::test_event_exec_colon_is_noise_and_unknown_not_delete
- Assertion scope: exec_start:/bin/sh、exec_create:/bin/sh 事件被忽略：断言运行态不变、event_log.record 未被调用。

#### Scenario: 未知事件

- Test/check:
  - [X] tests/test_cache_collectors.py::test_status_cache_unrecognized_event_ignored_without_pollution
  - [X] tests/test_runtime_guard.py::test_event_exec_colon_is_noise_and_unknown_not_delete
  - [X] tests/test_anvil_lifecycle_contracts.py::test_event_positive_trace_and_unknown_diagnostic
- Assertion scope: 现有测试断言未知事件不改变运行态且不写事件轨迹；断言：caplog WARNING 包含容器名与未知 action，形成可诊断记录，同时 take_deleted()/take_delete_candidates() 为空，不排队删除。

### Requirement: 动作受理与完成确认分离

#### Scenario: 受理后由实态确认

- Test/check:
  - [X] tests/test_runtime_guard.py::test_api_repeated_unpause_is_idempotent_with_new_ref
  - [X] tests/test_runtime_guard.py::test_start_same_ready_process_is_idempotent
- Assertion scope: 重复 unpause 端点测试断言新鲜实态 running/not paused 时 last_action 为 idempotent_confirmed、运行态 online；start 幂等测试断言已 ready 同进程不重新 start。

#### Scenario: start 受理但就绪门禁未通过

- Test/check:
  - [X] tests/test_runtime_guard.py::test_api_start_running_without_ready_does_not_bypass_gate
- Assertion scope: start 已 running 但无 ready 证明时，断言 start_calls=0、状态保持 starting 且 ready_check=true，不因 Docker running 直接 online。

#### Scenario: 动作失败但实际仍在运行

- Test/check:
  - [X] tests/test_action_contracts.py::test_soft_failure_wire_keeps_online_and_failed_only_in_last_action
  - [X] tests/test_runtime_guard.py::test_api_pause_soft_failure_keeps_online_and_exposes_last_action_failed
- Assertion scope: 动作失败后新鲜实态仍 running：断言运行态 online，failed 只出现在 last_action，且 HTTP 状态响应同时返回 online 与 last_action.failed。

### Requirement: 统一动作序号与旧写抑制

#### Scenario: 旧动作完成晚于新动作受理

- Test/check:
  - [X] tests/test_runtime_guard.py::test_finish_old_ref_is_superseded_and_never_overwrites_new_ref
  - [X] tests/test_runtime_guard.py::test_blocked_old_action_side_effect_cannot_write_new_generation
- Assertion scope: 旧 ref 终结晚到时断言被拒绝且不覆盖新 ref；旧动作 Docker 调用阻塞期间换代后，断言旧观察票/端口写入不能写新代。

#### Scenario: 慢速对账在 unpause 后回写旧快照

- Test/check:
  - [X] tests/test_runtime_barriers.py::test_sylvan_timeline_real_slow_list_and_stats_does_not_rollback
- Assertion scope: 慢 list + stats 期间完成两次 unpause，断言最终 online、last_action=idempotent_confirmed、无 unpause_failed，且 stats 后按名称新鲜解析。

#### Scenario: 旧列表对象在换名后返回

- Test/check:
  - [X] tests/test_runtime_guard.py::test_reconcile_uses_fresh_name_resolution_not_stale_list_object
- Assertion scope: list 返回旧 paused 对象、按名称 get 返回新 running 对象时，断言状态 online、docker_id 为新值、无删除候选。

#### Scenario: 旧读取延迟返回

- Test/check:
  - [X] tests/test_runtime_guard.py::test_read_seq_cas_rejects_late_old_read_and_metrics_do_not_raise_sequences
- Assertion scope: R1 先取票、R2 后取票并先发布，R1 晚到：断言 read_seq CAS 拒绝 R1，状态保持 R2 的 paused。

#### Scenario: 后发观察先完成

- Test/check:
  - [X] tests/test_runtime_guard.py::test_read_seq_cas_rejects_late_old_read_and_metrics_do_not_raise_sequences
- Assertion scope: 后发观察先完成时断言发布按 read_seq 判定，完成顺序/响应时间不授予写入资格。

#### Scenario: 迟到事件不回滚新状态

- Test/check:
  - [X] tests/test_anvil_lifecycle_contracts.py::test_late_state_event_does_not_rollback_online
- Assertion scope: 断言：在新动作确认 online 后投递较早/较晚的 pause 事件，断言 Node 先取票再新鲜 inspect；实态 running 时保持 online 与最新 last_action，只有实态 paused 时才收敛 paused，不按事件文本回滚。

#### Scenario: 普通指标更新不抬代际

- Test/check:
  - [X] tests/test_runtime_guard.py::test_read_seq_cas_rejects_late_old_read_and_metrics_do_not_raise_sequences
- Assertion scope: 指标票只更新 runtime_metrics；断言 generation、action_seq、last_applied_read_seq 均不变。

### Requirement: 共享本地代际与同名对象更换

#### Scenario: 有效当前观察驱动同名更换

- Test/check:
  - [X] tests/test_runtime_guard.py::test_valid_current_observation_drives_identity_change_and_supersedes_old_action
  - [X] tests/test_runtime_guard.py::test_old_generation_late_observation_cannot_replace_again_or_cancel_new_pending
  - [X] tests/test_anvil_lifecycle_contracts.py::test_identity_change_invalidates_old_delete_candidate
- Assertion scope: 当前代有效观察返回同名新 Docker ID 时，断言进入新代、旧动作置 superseded、按新对象重新分类并进入就绪门禁；旧 observation ticket 由相邻测试断言被拒绝；断言：预置旧删除候选后换代，候选队列为空。

#### Scenario: 旧代观察晚到看到新对象

- Test/check:
  - [X] tests/test_runtime_guard.py::test_old_generation_late_observation_cannot_replace_again_or_cancel_new_pending
- Assertion scope: 旧代观察晚到看到新对象时，断言 generation 票先失败，不推进 B→C、不取消 B 的 pending，也不把 B 当替换。

#### Scenario: 当前 create 首次绑定 Docker ID

- Test/check:
  - [X] tests/test_runtime_guard.py::test_create_first_bind_and_different_id_deferred
- Assertion scope: create pending 首次确认看到 Docker ID 时，断言绑定 ID、generation 不变、create_pending 保留。

#### Scenario: create pending 期间不同 ID 推迟

- Test/check:
  - [X] tests/test_runtime_guard.py::test_create_first_bind_and_different_id_deferred
  - [X] tests/test_anvil_lifecycle_contracts.py::test_create_pending_identity_deferral_is_diagnosed
- Assertion scope: create pending 已有绑定 ID 后，普通观察看到不同 ID 时断言 publish 返回 False、docker_id/generation 不变、create_pending 保留；断言：caplog 的 identity_change_deferred 诊断含名称与两个 ID。

#### Scenario: 创建 pending 与旧删除候选交错

- Test/check:
  - [X] tests/test_prevent_vanished.py::test_create_acceptance_cancels_queued_delete_candidate
  - [X] tests/test_runtime_guard.py::test_delete_candidate_dropped_when_same_name_reappears_before_send
  - [X] tests/test_runtime_guard.py::test_blocked_old_action_side_effect_cannot_write_new_generation
- Assertion scope: create 受理时断言队列中旧删除候选被清空；发送前同名对象重新出现时断言候选被丢弃、不发送 delete；旧动作阻塞结束后断言其完成/端口写入不能覆盖新 create 过渡态。

#### Scenario: 磁盘路径与测量诊断独立

- Test/check:
  - [X] tests/test_runtime_guard.py::test_verify_bind_fields_are_independent_of_runtime_actions
  - [X] tests/test_verify_barriers.py::test_disk_barrier_trace_keeps_old_du_out_of_new_path
- Assertion scope: 运行态动作/对象代际变化后断言磁盘路径、用量、测量时间字段逐项不变；bind 屏障测试断言旧 du 不污染新路径事实。

#### Scenario: 不宣称跨进程代际

- Test/check:
  - [X] tests/test_prevent_vanished.py::test_external_delete_queues_once_and_wss_sends_delete_before_snapshot
  - [X] tests/test_action_contracts.py::test_mixed_version_missing_optional_fields_and_restart_epoch
- Assertion scope: 断言 delete 帧只含容器名、不带本地 generation；Node 重启后旧 epoch ref 不能匹配新进程。
- Coverage note: 该 Scenario 的“不宣称跨进程代际”是协议边界，Node 侧只能证明帧形状与本地 epoch 拒绝，不能证明 Ctrl/Q70 的最终处理。

### Requirement: pause 与 unpause 的新鲜实态确认

#### Scenario: 对已 running 容器重复 unpause

- Test/check:
  - [X] tests/test_runtime_guard.py::test_api_repeated_unpause_is_idempotent_with_new_ref
  - [X] tests/test_runtime_guard.py::test_unpause_is_not_paused_error_after_fresh_state_resolves_idempotent
  - [X] tests/test_anvil_lifecycle_contracts.py::test_repeated_unpause_without_ready_keeps_ready_check
- Assertion scope: 第二次 unpause 在新鲜 inspect 为 running/not paused 时断言 idempotent_confirmed、新 action_ref、运行态 online，且不产生 unpause_failed；断言：running/not paused 但无 ready_identity 时保持 starting/ready_check，不因 Docker running 绕过门禁。

#### Scenario: unpause 遇到 offline 或 dead

- Test/check:
  - [X] tests/test_runtime_guard.py::test_pause_unpause_offline_dead_never_report_success
- Assertion scope: exited/offline 与 dead 容器执行 pause/unpause：断言 phase=failed，offline 保持 offline，dead 保持 failed/docker_dead，绝不报成功或写 online。

#### Scenario: 其他 Docker 错误不得吞掉

- Test/check:
  - [X] tests/test_anvil_lifecycle_contracts.py::test_unpause_docker_error_uses_fresh_inspect
- Assertion scope: 断言：unpause 抛出权限/daemon 类 APIError、新鲜 inspect 仍为 paused 时，动作 failed/docker_api_error 且运行态保持 paused；post-inspect 不可判定时不报成功，按 unconfirmed/unknown 保留最后已知。

#### Scenario: 对已 paused 容器重复 pause

- Test/check:
  - [X] tests/test_anvil_lifecycle_contracts.py::test_repeated_pause_on_paused_is_idempotent
- Assertion scope: 断言：对已 paused 容器再次 pause 返回 idempotent_confirmed、pause_calls=0、运行态保持 paused、last_action 为该动作的幂等终结。

### Requirement: 就绪证明绑定运行进程

#### Scenario: pause 保留同一进程就绪证明

- Test/check:
  - [X] tests/test_runtime_guard.py::test_pause_preserves_ready_identity_and_unpause_reuses_it
- Assertion scope: pause 后断言 ready_verified=true 且 ready_identity 不变；unpause 后断言复用同一身份回到 online。

#### Scenario: restart 后必须重新验证

- Test/check:
  - [X] tests/test_runtime_guard.py::test_api_restart_clears_ready_until_sshd_probe
- Assertion scope: restart 受理/完成后断言 ready_verified=false、状态 starting/ready_check；probe 通过后才 online。

#### Scenario: 同 Docker ID 外部重启

- Test/check:
  - [X] tests/test_runtime_guard.py::test_ready_identity_must_match_docker_id_and_started_at
- Assertion scope: 同 Docker ID、StartedAt 变化时断言旧 ready 失效、状态 starting/ready_check、ready_verified=false。

#### Scenario: 缺少 StartedAt

- Test/check:
  - [X] tests/test_runtime_guard.py::test_ready_identity_must_match_docker_id_and_started_at
- Assertion scope: StartedAt 为空时断言 ready_verified=false，不得复用旧 ready。

### Requirement: 运行态与动作结果分离

#### Scenario: unpause 动作失败但容器实际 online

- Test/check:
  - [X] tests/test_runtime_guard.py::test_unpause_is_not_paused_error_after_fresh_state_resolves_idempotent
  - [X] tests/test_runtime_guard.py::test_sylvan_timeline_old_reconcile_cannot_rollback_after_unpause
- Assertion scope: unpause 因 is not paused 失败但新鲜实态 running/not paused 时，断言 last_action=idempotent_confirmed、运行态 online，动作失败不形成永久 failed。

#### Scenario: 正常退出

- Test/check:
  - [X] tests/test_runtime_guard.py::test_hard_block_classification_is_bounded
  - [X] tests/test_runtime_guard.py::test_stop_offline_is_idempotent_and_dead_not_success
  - [X] tests/test_anvil_lifecycle_contracts.py::test_exited_is_offline_without_hard_block
- Assertion scope: exited 容器断言 offline；stop 已 offline 断言 idempotent_confirmed；断言：exited 条目不形成 hard_block，叠加动作失败痕迹后仍为 offline，last_action.failed 不改变运行态。

#### Scenario: 历史 OOM 后恢复运行

- Test/check:
  - [X] tests/test_runtime_guard.py::test_hard_block_classification_is_bounded
- Assertion scope: 历史 OOMKilled=true 但当前 running 时断言状态按 running 进入 starting/门禁，OOM 不永久 sticky。

#### Scenario: 动作 TTL 不得清除硬阻塞

- Test/check:
  - [X] tests/test_anvil_lifecycle_contracts.py::test_hard_block_survives_action_ttl
- Assertion scope: 断言：先建立 sshd/dead 硬阻塞，再修改 accepted_at 或 expires_at 以可控推进超过 TTL（不 sleep），并断言 current_action.expires_at 已过期；读取 cache.get(name)["hard_block"] is True 且 get_state() 仍为 failed/failed_reason，TTL 不把硬阻塞抹成 online/unknown。

### Requirement: 硬阻塞边界与恢复

#### Scenario: created 半成品

- Test/check:
  - [X] tests/test_runtime_guard.py::test_create_pending_created_fact_is_not_hard_blocked_until_create_finishes
  - [X] tests/test_runtime_guard.py::test_api_create_leaves_created_object_as_hard_block
- Assertion scope: create pending 期间 created 只显示 creating、不形成硬阻塞；create 终结后对象仍 created 时断言 failed/created_half_built、hard_block=true。

#### Scenario: sshd 暂未就绪保持门禁

- Test/check:
  - [X] tests/test_runtime_guard.py::test_api_start_running_without_ready_does_not_bypass_gate
  - [X] tests/test_runtime_guard.py::test_cold_start_rebuilds_running_created_exited_dead_and_last_action_null
- Assertion scope: start 已 running 但 sshd 未就绪时断言保持 starting/ready_check；冷启动 running 同样先进入 ready_check，不直接 online。

#### Scenario: sshd 未安装或门禁终态不可用

- Test/check:
  - [X] tests/test_runtime_guard.py::test_hard_block_classification_is_bounded
  - [X] tests/test_cache_collectors.py::test_ensure_sshd_started_detects_not_installed
  - [X] tests/test_runtime_guard.py::test_probe_success_clears_sshd_hard_block_only_after_same_process_confirmation
  - [X] tests/test_anvil_lifecycle_contracts.py::test_sshd_not_installed_probe_sets_hard_block
- Assertion scope: 现有测试分别断言 set_hard_block(sshd) 保留 failed、mark_ready_verified 后解除、probe 成功且同进程确认后解除，以及 ensure 对 exit=127 返回 not_installed；断言：真实 _probe_ready_once 在 fake 容器 exec 返回 127 时落 failed/sshd_not_installed、hard_block=true、ready_identity 被清除。

#### Scenario: 当前 Docker 证明 dead

- Test/check:
  - [X] tests/test_runtime_guard.py::test_hard_block_classification_is_bounded
  - [X] tests/test_runtime_guard.py::test_pause_unpause_offline_dead_never_report_success
  - [X] tests/test_runtime_guard.py::test_hard_block_invalidates_ready_and_pause_does_not_clear_it
  - [X] tests/test_anvil_lifecycle_contracts.py::test_hard_block_survives_action_ttl
  - [X] tests/test_anvil_lifecycle_contracts.py::test_dead_hard_block_survives_event_and_stale_observation
- Assertion scope: 新鲜实态 dead 时断言 failed/docker_dead、hard_block=true；动作层 dead 不报成功；paused 事实不提供故障消失证据，硬阻塞保持；断言：超 TTL 后 cache.get(name)["hard_block"] 仍为 True，普通事件与旧观察票也不能清除 dead 硬阻塞。

#### Scenario: 硬阻塞在新实态下恢复

- Test/check:
  - [X] tests/test_runtime_guard.py::test_probe_success_clears_sshd_hard_block_only_after_same_process_confirmation
  - [X] tests/test_runtime_guard.py::test_hard_block_classification_is_bounded
  - [X] tests/test_anvil_lifecycle_contracts.py::test_hard_block_cleared_by_recreated_object
- Assertion scope: 现有测试覆盖“新鲜实态证明故障消失且门禁通过”的恢复分支；断言：预置 sshd/created/dead 硬阻塞后，同名新 Docker ID 经当前代观察进入新代，cache.get(name) 的 hard_block 被清除，状态按新对象重新进入 starting/ready_check，旧代观察/动作不能复活阻塞。

### Requirement: 未知与采集错误保留最后已知

#### Scenario: Docker 列表采集失败

- Test/check:
  - [X] tests/test_cache_collectors.py::test_status_cache_reconcile_failure_sets_collect_error
  - [X] tests/test_runtime_guard.py::test_reconcile_vanished_candidate_requires_notfound_and_generation_check
  - [X] tests/test_anvil_lifecycle_contracts.py::test_list_failure_keeps_last_known_and_reports_collect_error
- Assertion scope: 现有测试断言列表/对账异常置 collect_error=collect_failed，单容器查询失败时缓存保留且无删除候选；断言：先 seed online 再让 containers.list 抛错，最后已知 online 保留、collect_error 置位、无删除帧。

#### Scenario: 单容器观测不可判定

- Test/check:
  - [X] tests/test_runtime_guard.py::test_reconcile_per_container_inspect_failure_marks_unknown_and_keeps_last_known
  - [X] tests/test_runtime_guard.py::test_event_inspect_failure_keeps_last_known
- Assertion scope: 单容器 inspect 异常时断言 unknown、status_source=collect_error、last_known_status=online，缓存保留；事件 inspect 失败同样保留最后已知。

#### Scenario: 未知后恢复

- Test/check:
  - [X] tests/test_anvil_lifecycle_contracts.py::test_unknown_recovers_on_next_successful_observe
- Assertion scope: 断言：先制造单容器 unknown，再恢复 get 并成功 reconcile，状态回到 online、status_source/unknown_since 被清除，无需重启 Node。

### Requirement: 冷启动运行态重建

#### Scenario: 冷启动遇到 running

- Test/check:
  - [X] tests/test_runtime_guard.py::test_cold_start_rebuilds_running_created_exited_dead_and_last_action_null
  - [X] tests/test_cache_collectors.py::test_cold_start_running_container_waits_for_sshd_probe
- Assertion scope: 冷启动 running 容器断言 starting/ready_check、last_action=null；probe 通过后才 online。

#### Scenario: 冷启动遇到 exited 或 dead

- Test/check:
  - [X] tests/test_runtime_guard.py::test_cold_start_rebuilds_running_created_exited_dead_and_last_action_null
- Assertion scope: 冷启动 exited 断言 offline、dead 断言 failed，且两者 last_action 均为 null，不继承重启前动作状态。

#### Scenario: 旧 failed pending 不复活

- Test/check:
  - [X] tests/test_runtime_guard.py::test_wipe_old_epoch_and_last_action_after_restart
  - [X] tests/test_anvil_lifecycle_contracts.py::test_restart_does_not_revive_old_failed_pending
- Assertion scope: 现有测试断言新 cache 的 node_epoch 不同、last_action=null、旧 ref finish 被拒绝；断言：从旧 cache 的 unpause_failed pending 切换到新 cache，reconcile running 后为 starting/ready_check、无旧 pending/last_action。

### Requirement: 动作引用 action_ref 契约

#### Scenario: 受理前分配并保持一致

- Test/check:
  - [X] tests/test_action_contracts.py::test_ack_first_and_wss_first_close_exact_ref_without_ack_forced_failure
  - [X] tests/test_runtime_barriers.py::test_injected_barriers_cover_accept_ref_ticket_queue_docker_http_wss_delete_event
- Assertion scope: 动作契约测试断言 HTTP ACK 的 ref 与 WSS last_action.ref 完全一致；屏障测试断言 accept/ref 分配早于 queue/Docker 副作用。

#### Scenario: create 使用对象代际

- Test/check:
  - [X] tests/test_action_contracts.py::test_mixed_version_missing_optional_fields_and_restart_epoch
  - [X] tests/test_runtime_guard.py::test_old_generation_late_observation_cannot_replace_again_or_cancel_new_pending
  - [X] tests/test_runtime_guard.py::test_create_first_bind_and_different_id_deferred
- Assertion scope: CreateContainerResponse 构造断言 action_ref.generation 使用传入对象代际；status_cache create 测试断言 create 受理 ref.generation 与 cache generation 一致、首次绑定不额外换代。

#### Scenario: Node 重启 epoch 变化

- Test/check:
  - [X] tests/test_action_contracts.py::test_mixed_version_missing_optional_fields_and_restart_epoch
  - [X] tests/test_runtime_guard.py::test_wipe_old_epoch_and_last_action_after_restart
- Assertion scope: 新旧 cache 的 node_epoch 不同，旧 ref 在新进程终结被拒绝，新进程无动作时 last_action=null。

#### Scenario: 旧 Node 缺字段

- Test/check:
  - [X] tests/test_action_contracts.py::test_mixed_version_missing_optional_fields_and_restart_epoch
  - [X] tests/test_runtime_guard.py::test_api_status_unknown_explicit_last_action_null
- Assertion scope: 旧 Node 帧缺少 last_action 时本地消费方按 timeout 降级；新 Node 的状态响应显式包含 last_action:null。旧 Ctrl 仅读 status/source 时如何收敛属 Ctrl 侧行为，Node 测试未断言。
- Coverage note: 旧 Ctrl 的最终收敛不在 Node 测试范围；Node 侧只证明缺字段帧可被本地消费方 timeout 降级、旧 Ctrl 可见字段仍可被读取。

#### Scenario: 不用于跨进程授权

- Test/check:
  - [X] tests/test_prevent_vanished.py::test_external_delete_queues_once_and_wss_sends_delete_before_snapshot
  - [X] tests/test_action_contracts.py::test_mixed_version_missing_optional_fields_and_restart_epoch
- Assertion scope: delete 帧只含 container_name，不带 action_ref/generation；Node 重启后旧 ref 被拒绝。
- Coverage note: Node 侧证明 action_ref 不进入既有 delete 帧；Ctrl/Q70 是否接受该引用作为跨进程授权不在本仓库断言范围。

### Requirement: last_action 诊断与终结语义

#### Scenario: 无动作记录

- Test/check:
  - [X] tests/test_runtime_guard.py::test_api_status_unknown_explicit_last_action_null
  - [X] tests/test_runtime_guard.py::test_wss_status_entry_explicit_last_action_null_and_failed_plus_online
- Assertion scope: HTTP 状态响应显式包含 last_action:null；WSS 条目同样显式 null，经 JSON 序列化不丢失。

#### Scenario: 重复 unpause 的 online 与幂等终结

- Test/check:
  - [X] tests/test_runtime_guard.py::test_api_repeated_unpause_is_idempotent_with_new_ref
- Assertion scope: 两次 unpause 返回不同 action_ref；运行态 online，last_action 为对应 ref 的 idempotent_confirmed，无 unpause_failed。

#### Scenario: pause 软失败但实际 online

- Test/check:
  - [X] tests/test_runtime_guard.py::test_api_pause_soft_failure_keeps_online_and_exposes_last_action_failed
  - [X] tests/test_action_contracts.py::test_soft_failure_wire_keeps_online_and_failed_only_in_last_action
- Assertion scope: pause 软失败但实态 online：HTTP/WSS 原子返回 online 与 last_action.failed，运行态不被 last_action 改写。

#### Scenario: 旧 ref 晚到

- Test/check:
  - [X] tests/test_runtime_guard.py::test_finish_old_ref_is_superseded_and_never_overwrites_new_ref
  - [X] tests/test_runtime_guard.py::test_same_ref_terminal_phase_not_regressed
- Assertion scope: 较新 ref 已受理/终结后，旧 ref 的 finish 被拒绝且不覆盖最新 last_action；同一 ref 终结后旧 accepted 不回退。

#### Scenario: 对象换代保留终结诊断

- Test/check:
  - [X] tests/test_runtime_guard.py::test_valid_current_observation_drives_identity_change_and_supersedes_old_action
  - [X] tests/test_anvil_lifecycle_contracts.py::test_new_generation_rejects_old_ref
- Assertion scope: 对象换代时旧 latest action 置 superseded 且保留旧 ref；断言：旧 ref 在新代 action_generation_valid/finish 均被拒绝，新代动作使用新 ref。

#### Scenario: 未确认不是完成

- Test/check:
  - [X] tests/test_runtime_guard.py::test_unconfirmed_and_timed_out_are_non_terminal_and_can_finish_later
  - [X] tests/test_action_contracts.py::test_consumer_rejects_old_ref_wrong_direction_and_unknown_phase_without_failed
- Assertion scope: unconfirmed/timed_out 不是终结：同一 ref 后续可 confirmed，运行态不被置 failed；独立消费方对未知 phase 只 timeout，不伪造 failed。
- Coverage note: 消费方 timeout/降级是本地夹具策略，不是 Node 强制；Node 侧只证明相位非终结与运行态分离。

#### Scenario: 记录有界

- Test/check:
  - [X] tests/test_anvil_lifecycle_contracts.py::test_action_records_are_bounded
- Assertion scope: 该 locator连续受理 40 个动作，断言 cache 只保留最多 32 条原子动作记录、last_action 指向最新 ref，旧终结记录被有界裁剪。
