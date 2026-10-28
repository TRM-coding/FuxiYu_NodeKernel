# Test Plan

映射范围：`backend--storage-and-mounts`（24 Requirement / 79 Scenario）与 `backend--wss-snapshots`（12 Requirement / 45 Scenario），共 36 Requirement、124 Scenario。本文件只记录 Scenario 到 Test/check 的映射与断言范围，不记录执行结果、统计数字、时间戳或完成状态。

`[X]` 表示该 locator 是已存在的测试/检查且其断言已按测试源码逐段核对；`[ ]` 表示真实缺口行，locator 是规划到 `tests/test_anvil_storage_snapshots.py` 的测试名，具体断言范围由同一 Scenario 的 Assertion scope/Coverage note 说明。checkbox 不是执行、通过或全 Scenario 覆盖声明。

Global Q77 已登记 non-running `LastSshCache` 保留旧值与主 spec 的 None 口径差异；依赖 Q77 修复的 LastSsh locator 在对应 Scenario 中单独列出并标注未创建，其余独立 locator 不受该缺陷阻塞。

## backend--storage-and-mounts

### Requirement: CheckDiskUsageMessage 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_anvil_storage_snapshots.py::test_check_disk_usage_message_request_validation`
- Assertion scope: 构造 `CheckDiskUsageMessage(config={})`，断言嵌套 `ContainerNameConfig` 的 `container_name`/`name` 缺省为 None；缺 `config` 或 `config` 类型错误被 `ValidationError` 拒绝。经 `TestClient` 向 `/api/check_disk_usage` 提交缺失 `config` 的请求，断言 422，且服务读取未被调用。
- Coverage note: Requirement 正文的“端点请求外层对象、嵌套 config 使用对应配置类型、FastAPI 在进入操作服务前校验”由同一规划用例的端点分支承担；既有 `test_check_disk_usage_success` 只走合法请求成功路径。

### Requirement: MachineDiskUsage 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_anvil_storage_snapshots.py::test_machine_disk_usage_defaults_and_null_capacity`
- Assertion scope: `MachineDiskUsage()` 的 total_gb/used_gb/free_gb/percent 全为 None，容量缺失不解释为 0 GB；四项完整合法数值原样保留；非数值输入被 `ValidationError` 拒绝。

### Requirement: ContainerDiskUsage 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_container_disk_usage_model_only_has_current_fields_and_null_round_trip`
  - [X] `tests/test_anvil_storage_snapshots.py::test_container_disk_usage_rejects_invalid_status_and_types`
- Assertion scope: 既有用例断言模型字段集合恰为 9 个既有字段、默认 `mount_path_status == "unresolved"`、显式 null 经 `model_dump` 保留、旧载荷缺 `measured_at` 时补 None 且不出现 banned 字段。规划用例补充非法 `mount_path_status` 与错误字段类型被 `ValidationError` 拒绝，证明声明的类型/Literal 边界不被接受为有效实例。
- Coverage note: 字段集合、缺省与 null round-trip 已有断言；非法 Literal/类型拒绝此前无断言，由规划行承担。`ContainerDiskUsage` 的字节字段未声明 `ge=0`，因此本行不断言负数字节被拒。

#### Scenario: 旧 Node 缺少测量时间

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_container_disk_usage_model_only_has_current_fields_and_null_round_trip`
  - [X] `tests/test_anvil_storage_snapshots.py::test_old_usage_without_measured_at_is_not_current`
- Assertion scope: 既有用例断言旧载荷（无 `measured_at`）构造后 `measured_at is None`、`mount_path_status` 回落 unresolved 且不出现目录身份字段。规划用例在真实缓存读面写入只有旧 total/bind 字节、`measured_at=None` 的样本，断言 `snapshot()` 不把旧总量发布为当前有效值（total/bind 为 None），不用读取时间补齐测量时间，并保留同一业务路径。
- Coverage note: “消费方按既有接收时间兼容”属于 Ctrl 接收侧契约；Node 侧只断言缺真实测量时间的旧样本不被当前化，接收时间不回填为真实测量。

#### Scenario: unresolved 但有同路径有效测量

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_unresolved_with_existing_path_and_valid_measurement_stays_total`
- Assertion scope: 构造 `mount_path_status="unresolved"`、既有业务路径、新鲜 bind 测量与 overlay，断言快照 `total_bytes == 5120`、`error is None`、路径保持；unresolved 未清空同路径测量。

#### Scenario: 路径变更后的旧样本

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_snapshot_does_not_publish_cached_path_bytes_under_new_path`
  - [X] `tests/test_verify_bind_mount.py::test_path_change_drops_old_sample_until_new_path_measured`
- Assertion scope: 两条用例分别断言：缓存 usage 路径为 A、当前业务路径为 B 时快照发布 B，且 bind 字节/总量/measured_at 全为 None；路径核对从 A 改到 B、新 du 未完成时同样不把 A 的字节贴到 B。

#### Scenario: 缺组成或非零 du

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_every_du_failure_is_not_zero`
  - [X] `tests/test_cache_collectors.py::test_disk_usage_cache_overlay_failure_keeps_total_pending`
- Assertion scope: 参数化非零退出、空输出、解析失败、超时、权限、du 缺失六种失败，断言 bind 条目 bytes/measured_at 不更新且错误为稳定原因；overlay 组成缺失时总用量为 None、error 为 inspect_size_failed，不把缺组成当 0。

#### Scenario: null 字段序列化

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_container_disk_usage_model_only_has_current_fields_and_null_round_trip`
  - [X] `tests/test_verify_bind_mount.py::test_http_not_collected_is_none_not_zero`
- Assertion scope: 模型显式 null 经 `model_dump` 保留；HTTP 未采集响应中 `total_bytes`/`measured_at` 为 null、`error == "not_collected"`，字段未丢失或改名为成功值。

### Requirement: CheckDiskUsageResponse 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_mount_usage_api.py::test_existing_check_disk_usage_contract_unchanged`
  - [X] `tests/test_anvil_storage_snapshots.py::test_check_disk_usage_response_contract_reads_shared_cache`
- Assertion scope: 既有用例断言 HTTP 200、`success == 1`、`container.total_bytes` 原样透出且无 `mounts`。规划用例断言 `success` 缺省 1、`machine_disk`/`container` 必填缺失被拒、线路字段集合不变，并注入已填充的 `DiskUsageCache` 后调用 `/api/check_disk_usage`，断言容器用量来自共享缓存，未调用 `collect_container` 或 Docker，宿主磁盘只做一次轻量 `collect_machine_disk` 读取。
- Coverage note: Requirement 正文的“读共享缓存、不为每次查询启动全量宿主扫描”由规划端点分支承担；`collect_machine_disk` 是单次 `shutil.disk_usage`，不属于容器全量扫描。

### Requirement: CleanMountConfig 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_clean_mount.py::test_accepts_legitimate_container_mount_dir`
  - [X] `tests/test_clean_mount.py::test_rejects_traversal_paths`
  - [X] `tests/test_clean_mount.py::test_rejects_symlink_escaping_base`
  - [X] `tests/test_anvil_storage_snapshots.py::test_clean_mount_wire_models`
- Assertion scope: 既有服务用例断言合法 `/containers/` 目录经 realpath 规范化后执行 `rm -rf`；越界、`../` 穿越、前缀伪装、符号链接逃逸全部抛 ValueError 且不执行 rm。规划用例断言 `CleanMountConfig.mount_path` 必填、缺失/错误类型被拒。
- Coverage note: Requirement 正文的“服务规范化 realpath 并约束 /containers/ 路径”由既有服务用例承担；模型必填/类型由规划行承担。

### Requirement: CleanMountMessage 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_blueprint_api.py::test_clean_mount_success`
  - [X] `tests/test_anvil_storage_snapshots.py::test_clean_mount_wire_models`
- Assertion scope: 既有端点用例断言 `POST /api/clean_mount` 接受外层 `config`、把 `mount_path` 交给服务并返回 `success == 1`。规划用例断言缺 `config` 的 `CleanMountMessage` 被 `ValidationError` 拒绝，嵌套错误类型同样被拒。
- Coverage note: 正文“端点请求外层对象、嵌套 config 使用对应配置类型”由既有成功路径与规划缺省/非法分支共同覆盖。

### Requirement: CleanMountResponse 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] `tests/test_blueprint_api.py::test_clean_mount_success`
  - [X] `tests/test_blueprint_api.py::test_clean_mount_rm_failure_500`
- Assertion scope: 成功响应经 response_model 输出 `success == 1`；rm 失败返回 500 且 `success == 0`。两条真实端点响应证明该类型继承公共 success 字段并保留错误信封。
- Coverage note: 模型本身无必填字段；缺省与序列化由真实端点响应承担。

### Requirement: DiskUsageResponse 数据契约 [schemas/container.py]

#### Scenario: 使用声明值域

- Test/check:
  - [X] `tests/test_anvil_storage_snapshots.py::test_disk_usage_response_alias_preserves_wire_contract`
- Assertion scope: 断言 `DiskUsageResponse` 与 `CheckDiskUsageResponse` 是同一模型别名；用真实 `model_validate`/`model_dump` 验证 `success`、`machine_disk`、`container` 的字段形状与 `CheckDiskUsageResponse` 一致，且不出现未声明的新协议字段。
- Coverage note: 该类型是兼容别名、无独立字段；规划用例只验证别名不改变既有线路值域，不新增字段。

### Requirement: 业务路径的确认与有界纠正

#### Scenario: Source 与实际挂载一致

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_source_matches_actual_resolved_without_wire_identity`
- Assertion scope: Docker Source 可解析且与 `/proc/<pid>/root/root` 对象一致时，返回 `mount_path_status == "resolved"`、`bind_mount_path` 为 Source，结果不含 `configured_mount_path`/`mount_path_observed_at`。

#### Scenario: 错位且候选唯一

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_mismatched_source_unique_candidate_corrects_business_path`
  - [X] `tests/test_anvil_storage_snapshots.py::test_path_correction_has_no_docker_or_directory_mutation`
- Assertion scope: 既有用例断言 Source 指向 A、actual 指向 B 且 B 唯一匹配时 resolved，业务路径修正为 B 且不等于 A。规划用例在记录型 Docker 替身上断言纠正过程只做 get/reload 读取，未调用 start/stop/pause/restart/remove；A/B 目录内容未变；快照线路不含 Source/内部字段。
- Coverage note: “Source 只留在 Node 内部日志、不修改目录/Docker 配置”此前只有路径结果断言，由规划行的副作用与线路断言承担。

#### Scenario: 候选歧义或无匹配

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_ambiguous_candidates_unresolved_and_preserve_existing`
  - [X] `tests/test_verify_bind_mount.py::test_no_candidate_unresolved_and_no_business_path`
  - [X] `tests/test_verify_bind_mount.py::test_bounded_search_only_scans_allowed_parents`
- Assertion scope: 多候选时 unresolved、保留既有路径、reason 为 `ambiguous_candidates`；无候选时 unresolved、路径为 None、reason 为 `no_candidate`；有界搜索只扫描允许根下的父目录直接子项，不进入越界父目录。

#### Scenario: Source 改名后原路径缺失但新路径唯一

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_renamed_source_missing_still_finds_unique_new_path`
- Assertion scope: Source 已消失、actual 可读且允许父目录中只有一个对象匹配时 resolved，业务路径修正为该唯一新路径；不因 Source 缺失直接 unresolved。
- Coverage note: 不修改目录/Docker 配置的副作用与错位场景共享 `test_path_correction_has_no_docker_or_directory_mutation`；本场景行只承担路径定位断言。

#### Scenario: Source 缺失但无命名候选

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_no_candidate_unresolved_and_no_business_path`
  - [X] `tests/test_verify_bind_mount.py::test_bounded_search_only_scans_allowed_parents`
- Assertion scope: Source 消失、actual 可读但无可命名唯一匹配时 unresolved、无既有路径时为 None、reason 为 `no_candidate`；搜索不递归、不越界。

#### Scenario: 无 PID 或 proc 不可读

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_no_pid_not_running_and_preserves_path`
  - [X] `tests/test_verify_bind_mount.py::test_proc_unreadable_unresolved_preserves_existing_path`
  - [X] `tests/test_verify_bind_mount.py::test_lightweight_path_diagnostic_updates_snapshot_without_touching_measurement`
- Assertion scope: 无稳定 PID 时 `not_running` 并保留既有业务路径；proc 不可读时 unresolved、保留路径、reason 为 `actual_unreadable`；诊断变化只改 `mount_path_status`，不触发 du、不清有效测量，返回路径为既有业务路径而非 `/proc` 临时路径。

#### Scenario: 旧路径核对晚回

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_late_path_check_result_is_dropped_by_check_sequence`
  - [X] `tests/test_verify_bind_mount.py::test_late_path_result_dropped_when_active_object_changes`
- Assertion scope: 旧核对在新核对或容器换代后返回时被 `check_seq` 或活跃 DockerID/PID 复核丢弃并返回 None；状态与路径保持新对象结果，旧结果没有进入后续路径发布。
- Coverage note: 该保护在用例中只体现在路径状态/返回 None；测量与业务门禁的独立性由“路径诊断不构成业务门禁”场景覆盖，不把路径核对序列当成测量排序协议。

### Requirement: 路径诊断不构成业务门禁

#### Scenario: unresolved 但既有路径测量成功

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_unresolved_with_existing_path_and_valid_measurement_stays_total`
  - [X] `tests/test_verify_bind_mount.py::test_lightweight_path_diagnostic_updates_snapshot_without_touching_measurement`
- Assertion scope: unresolved/not_running 但同业务路径 du 成功、组成完整且 measured_at 有效时，快照仍保留路径与 total 5120、error None；诊断变化不改测量。
- Coverage note: 恢复/长期/冻结/删除/清理是 Ctrl 业务；Node 侧只断言路径诊断不使测量失败，未在 Node 断言 Ctrl 资格。

#### Scenario: 路径诊断失败但测量独立成功

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_lightweight_path_diagnostic_updates_snapshot_without_touching_measurement`
- Assertion scope: actual 不可读导致 unresolved 时，已有 bind 测量与 measured_at 保持，total 仍 5120；路径诊断失败未被写成测量失败。

#### Scenario: resolved 但测量失败

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_every_du_failure_is_not_zero`
  - [X] `tests/test_anvil_storage_snapshots.py::test_resolved_path_du_failure_publishes_no_total`
- Assertion scope: 既有参数化用例断言各类 du 失败不产生字节、错误为稳定原因。规划用例先建立 resolved 路径与上一成功样本，再让 du 非零退出，断言快照 `mount_path_status` 仍 resolved、`total_bytes`/`bind_mount_bytes`/`measured_at` 均 None、`error` 为真实失败原因；内部最后成功值只作诊断。
- Coverage note: “resolved 不能因路径成功而发布数字”此前没有同时固定 resolved 状态与失败测量的断言，由规划行承担。

#### Scenario: 路径修正只作用于当前活跃容器

- Test/check:
  - [X] `tests/test_anvil_storage_snapshots.py::test_path_correction_scoped_to_active_container`
- Assertion scope: 为 c1/c2 分别建立路径状态与缓存用量，只对 c1 做路径纠正/核对，断言 c1 路径更新，而 c2 的 `bind_mount_path`、字节、`mount_path_status`、measured_at 全部不变；历史 `_container_cache` 条目未被批量改写。
- Coverage note: Node 只返回当前活跃容器的校正路径；Ctrl 的存储模型与资格 DTO 不在 Node 断言范围。

### Requirement: 按业务路径测量与路径变更失效

#### Scenario: 业务路径 A 修正为 B

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_path_change_drops_old_sample_until_new_path_measured`
  - [X] `tests/test_verify_bind_mount.py::test_old_path_du_late_does_not_become_new_path_total`
  - [X] `tests/test_verify_barriers.py::test_disk_barrier_trace_keeps_old_du_out_of_new_path`
- Assertion scope: A→B 后新测量未完成时 total/bind/measured_at 为空；A 的晚到 du 只写 A 的缓存，不成为 B 的 total；屏障轨迹断言旧 du 返回发生在新路径发布之后，B 的 total 232 不被 A 的 111 污染。

#### Scenario: 缓存用量路径与当前路径不一致

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_snapshot_does_not_publish_cached_path_bytes_under_new_path`
  - [X] `tests/test_verify_bind_mount.py::test_path_change_drops_old_sample_until_new_path_measured`
- Assertion scope: 缓存 usage 的 `bind_mount_path` 为 A、当前业务路径为 B 时发布 B，bind/total/measured_at 全 None，必须按 B 重测；不把 A 的字节标成 B。

#### Scenario: 路径未变但测量独立失败

- Test/check:
  - [X] `tests/test_anvil_storage_snapshots.py::test_resolved_path_du_failure_publishes_no_total`
- Assertion scope: 同一路径保持 resolved、上一成功样本仍存在时，后续 du 非零/超时/空输出失败，快照 total 为空、error 为真实原因、最后成功字节只留内部诊断，不用 0 或旧值冒充当前测量。
- Coverage note: 与“resolved 但测量失败”共享同一规划用例的两个分支；既有 `test_every_du_failure_is_not_zero` 从空条目开始，未固定“路径未变 + 最后成功值”的分支。

### Requirement: 测量有效性、组成与真实时间

#### Scenario: unresolved 路径的同一路径测量有效

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_unresolved_with_existing_path_and_valid_measurement_stays_total`
- Assertion scope: unresolved 但业务路径未变、overlay/bind 组成完整、measured_at 为真实完成时间且测量路径一致时 total 有效，不因 unresolved 或 inode 未验证清空。

#### Scenario: overlay-only 非 no_bind

- Test/check:
  - [X] `tests/test_anvil_storage_snapshots.py::test_bind_presence_blocks_overlay_only_and_no_bind_composes_overlay`
- Assertion scope: 容器存在 `/root` bind 但 bind 测量尚未完成/缺失时，即使 overlay 数字可得也发布 `total_bytes=None`、`bind_mount_bytes=None`，不把 bind 缺失当 0；同一用例另一分支用成功 Docker inspect 确认无 bind 时，断言 overlay-only total 等于 overlay 且 `mount_path_status == "no_bind"`。
- Coverage note: 明确 no_bind 的 overlay-only 合法分支同时服务 wss-snapshots 的“无 bind 与 overlay-only”；异常/不可读 Mounts 仍走 unresolved，由既有 `test_unreadable_mounts_are_unresolved_not_no_bind` 承担。

#### Scenario: 真实测量时间已旧

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_measured_at_uses_earlier_component_when_bind_sample_is_newer`
  - [X] `tests/test_verify_bind_mount.py::test_lightweight_path_diagnostic_updates_snapshot_without_touching_measurement`
  - [X] `tests/test_verify_bind_mount.py::test_repeated_wss_json_does_not_refresh_measured_at`
- Assertion scope: measured_at 取 overlay/bind 较早真实完成时间，bind 样本时间在未来时不得成为合计时间；路径核对只改诊断，快照与重复 WSS 读取都不刷新 measured_at。
- Coverage note: WSS 侧未单独构造“旧但未过期”的 measured_at；读取不刷新由重复推送/路径核对用例承担，端点 TTL 旧样本由 `test_ttl_hit_reuses_original_measured_at_without_du` 承担。

#### Scenario: 重复推送同一缓存结果

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_repeated_wss_json_does_not_refresh_measured_at`
- Assertion scope: 同一测量周期内两次构造 disk_usage WSS 帧，`measured_at`/`total_bytes` 保持完全一致，发送/读取时间未变成新测量。

### Requirement: 采集失败不伪造零

#### Scenario: 非零 du 仍输出数字

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_every_du_failure_is_not_zero`
  - [X] `tests/test_verify_bind_mount.py::test_du_failure_keeps_last_success_diagnostic_but_publishes_no_total`
- Assertion scope: 非零退出时即使 stdout 有 `123` 也不采纳，entry 保留上一成功 bytes/measured_at，测量读面返回 bytes None、error 为 `non_zero_exit`，不更新成功时间。

#### Scenario: HTTP 未采集

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_http_not_collected_is_none_not_zero`
- Assertion scope: `/api/check_disk_usage` 对无缓存容器返回 200、`total_bytes=None`、`error == "not_collected"`、`mount_path_status == "unresolved"`、`measured_at=None`，不返回 0。

#### Scenario: 失败不覆盖最后成功值

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_du_failure_keeps_last_success_diagnostic_but_publishes_no_total`
  - [X] `tests/test_mount_usage_cache.py::test_failure_keeps_last_success_internally_but_never_projects_it`
- Assertion scope: 磁盘缓存失败后 entry 仍保留旧 bytes/measured_at 作诊断，读面不发布旧值；按路径端点失败后也保留内部最后成功值，但投影为 bytes None、error 为稳定原因。

### Requirement: 轻量路径核对独立于重型测量

#### Scenario: du 阻塞时路径核对仍推进

- Test/check:
  - [X] `tests/test_verify_barriers.py::test_disk_barrier_trace_keeps_old_du_out_of_new_path`
- Assertion scope: 在真实 `subprocess.run` 边界阻塞 A 的 du，路径核对/新路径测量仍完成并发布 B；轨迹顺序证明 du 未阻塞路径核对，测量有效性仍由组成、measured_at、路径一致决定。

#### Scenario: 路径核对超时

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_inspect_failure_does_not_become_no_bind`
  - [X] `tests/test_verify_bind_mount.py::test_proc_unreadable_unresolved_preserves_existing_path`
  - [X] `tests/test_verify_bind_mount.py::test_unreadable_mounts_are_unresolved_not_no_bind`
- Assertion scope: inspect 失败、proc 不可读、Mounts 形状不可读分别走 unresolved 并保留业务路径，未被解释为 no_bind 或测量失败；超时与失败共用同一异常归类路径。
- Coverage note: 现有用例以 RuntimeError/PermissionError/坏 Mounts 覆盖失败分类，没有单独伪造超时异常；超时不会进入不同业务分支。

### Requirement: 运行状态与 no_bind 边界

#### Scenario: paused 容器路径可核对

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_paused_with_pid_is_verified_like_running`
  - [X] `tests/test_anvil_storage_snapshots.py::test_paused_container_keeps_path_and_measurement`
- Assertion scope: paused 且 PID/根挂载可读时路径核对与 running 相同，返回 resolved 并保留业务路径；规划用例在 paused 容器上预置同路径 bind 测量后执行真实采集，断言 `total_bytes`/`measured_at` 仍有效、路径未被清空，暂停不自动清测量。
- Coverage note: 既有用例断言 paused 的路径核对；暂停下测量保留此前没有独立断言，由规划行承担。

#### Scenario: stopped/restarting 无稳定 PID

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_no_pid_not_running_and_preserves_path`
  - [X] `tests/test_verify_bind_mount.py::test_lightweight_path_diagnostic_updates_snapshot_without_touching_measurement`
- Assertion scope: 无稳定 PID 时 `not_running` 并保留最后业务路径；容器转 exited 后快照只更新诊断，不清已有路径或测量。

#### Scenario: Docker 明确 no_bind

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_docker_confirmed_no_bind_clears_paths`
  - [X] `tests/test_verify_bind_mount.py::test_ctrl_compat_fixture_update_preserve_clear_and_old_node`
  - [X] `tests/test_anvil_storage_snapshots.py::test_bind_presence_blocks_overlay_only_and_no_bind_composes_overlay`
- Assertion scope: 成功 inspect 确认没有 `/root` bind 时 `mount_path_status == "no_bind"`、`bind_mount_path is None`，状态路径清空、path_version 递增；规划用例断言明确 no_bind 时 overlay-only total 等于 overlay；Ctrl 接收端清空当前活跃业务路径的消费方契约由既有本地夹具的 no_bind 分支断言。
- Coverage note: Node 侧断言状态清空与 no_bind 的 overlay-only total；Ctrl 清空活跃路径是 Node 帧的消费方契约，由既有本地夹具覆盖，不是 Node 写库。

#### Scenario: Docker inspect 失败

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_inspect_failure_does_not_become_no_bind`
  - [X] `tests/test_verify_bind_mount.py::test_unreadable_mounts_are_unresolved_not_no_bind`
- Assertion scope: inspect 抛错或 Mounts 不可读/形状损坏时 unresolved、保留旧路径、状态标 unresolved，不推断 no_bind。

#### Scenario: unresolved 不清空路径

- Test/check:
  - [X] `tests/test_verify_bind_mount.py::test_lightweight_path_diagnostic_updates_snapshot_without_touching_measurement`
  - [X] `tests/test_verify_bind_mount.py::test_inspect_failure_does_not_become_no_bind`
- Assertion scope: unresolved/not_running 保留既有 `bind_mount_path`；只有成功确认 no_bind 才置空。

### Requirement: 路径与测量不构成删除清理授权

#### Scenario: 路径匹配也不能授权清理

- Test/check:
  - [X] `tests/test_anvil_storage_snapshots.py::test_path_measurement_does_not_authorize_cleanup`
- Assertion scope: 规划用例先建立 resolved 路径与有效测量事实，再执行路径核对/快照/查询，以记录型替身断言 `services.container_service.clean_mount`、`network.api.clean_mount`、`rm` 与容器 remove 全部零调用，这是本测试的决定性断言：测量事实没有自动进入清理/删除路径。范围外路径调用 `clean_mount` 仍抛 ValueError 只作为附加的路径白名单检查，不单独证明授权边界。
- Coverage note: 既有路径/测量结果没有以“resolved + 有效测量”为前提断言不授权清理；`clean_mount` 没有独立授权参数，不能把路径白名单当成授权证明，因此规划测试以 no-call 为决定性断言。

#### Scenario: 同名新容器与旧帧

- Test/check:
  - [X] `tests/test_prevent_vanished.py::test_same_name_create_during_enumeration_invalidates_old_delete_candidate`
  - [X] `tests/test_prevent_vanished.py::test_create_acceptance_cancels_queued_delete_candidate`
  - [X] `tests/test_runtime_guard.py::test_delete_candidate_dropped_when_same_name_reappears_before_send`
- Assertion scope: 同名新建/受理会作废旧 delete 候选；发送前同名对象重新出现时 `take_confirmed_deleted()` 不返回该名称。路径/测量事实未参与该代际判断。
- Coverage note: Q70 的跨进程同名代际协议独立于本变更；本场景只映射 Node 既有候选失效行为，不把路径事实当新代证明。

### Requirement: Node 批量路径用量请求契约

#### Scenario: 合法批量请求

- Test/check:
  - [X] `tests/test_mount_usage_api.py::test_valid_batch_preserves_order_duplicates_and_mixed_states`
  - [X] `tests/test_mount_usage_api.py::test_endpoint_uses_cache_bridge_for_pending_to_success`
  - [X] `tests/test_mount_usage_models.py::test_mount_paths_accepts_one_to_hundred_items`
- Assertion scope: 1～100 条字符串路径整批接受：模型用例显式接受 1 条与 100 条；API 用例断言响应 `mounts` 与请求等长同序、`path` 原样回显（含重复项）、`success == 1`，每项字段恰为 path/bytes/measured_at/pending/error。

#### Scenario: 超过上限或空批次

- Test/check:
  - [X] `tests/test_mount_usage_api.py::test_shape_errors_return_422_before_any_measurement`
  - [X] `tests/test_mount_usage_models.py::test_mount_paths_rejects_empty_or_over_limit`
- Assertion scope: 空数组、101 条、非字符串数组、缺 config/mount_paths 在启动测量前返回 422，服务未被调用、响应无 mounts；模型层同样拒绝空/超限。

#### Scenario: 单条路径非法不拖垮同批

- Test/check:
  - [X] `tests/test_mount_usage_api.py::test_endpoint_uses_cache_bridge_for_pending_to_success`
  - [X] `tests/test_mount_usage_cache.py::test_invalid_not_found_and_permission_never_start_du`
- Assertion scope: 同批含越界路径时仅该项返回 `invalid_path`，其余合法项仍返回 pending/成功，整批 HTTP 200、`success == 1`；不存在/权限失败返回逐项稳定错误并按项收集，不升级为批次级失败。

#### Scenario: 不携带删除记录身份

- Test/check:
  - [X] `tests/test_mount_usage_api.py::test_identity_fields_inside_or_outside_config_are_422_and_not_measured`
  - [X] `tests/test_mount_usage_models.py::test_config_forbids_extra_identity_fields`
  - [X] `tests/test_mount_usage_models.py::test_message_forbids_outer_extra_identity_fields`
- Assertion scope: 请求只含 `config.mount_paths`；deleted_id/machine_id/container_name/role 位于 config 内或外层均 422 且不启动测量，模型 `extra="forbid"`；Node 不要求/解释这些身份字段。

### Requirement: 逐路径结果状态与真实字节

#### Scenario: 成功返回逻辑字节

- Test/check:
  - [X] `tests/test_mount_usage_api.py::test_real_http_du_pending_success_cache_hit_then_not_found`
  - [X] `tests/test_mount_usage_cache.py::test_real_du_on_local_temp_directory`
  - [X] `tests/test_mount_usage_models.py::test_response_wire_fields_are_exact`
  - [X] `tests/test_anvil_storage_snapshots.py::test_mount_usage_zero_bytes_is_real_success`
- Assertion scope: 真实本地 tmp 目录真实 du 成功时 `bytes >= 2048`（逻辑字节而非物理 blocks）、`measured_at` 形如 UTC `YYYY-MM-DDTHH:MM:SSZ`、`pending == False`、`error is None`；规划用例在受控 `du` 边界返回 `0` 并走真实 `read_mount_usage()`，断言该项 `bytes == 0`、`pending == False`、`error is None` 且有真实 `measured_at`，把 0 与缺失/失败区分开。
- Coverage note: 既有模型用例只构造 0 值线路对象，真实目录 du 用例只覆盖非空目录；执行路径上的 0 样本由规划行承担。

#### Scenario: 测量中

- Test/check:
  - [X] `tests/test_mount_usage_cache.py::test_read_returns_pending_immediately_and_uses_six_hundred_second_timeout`
  - [X] `tests/test_mount_usage_api.py::test_real_http_du_pending_success_cache_hit_then_not_found`
- Assertion scope: 无成功样本时立即返回 `bytes=None`、`measured_at=None`、`pending=True`、`error=None`，HTTP 不等待 du；du 启动超时为 600 秒。

#### Scenario: 测量失败

- Test/check:
  - [X] `tests/test_mount_usage_cache.py::test_stable_error_mapping`
  - [X] `tests/test_mount_usage_cache.py::test_failure_keeps_last_success_internally_but_never_projects_it`
- Assertion scope: 非零退出/权限/空输出/解析失败/超时/du 缺失/未知异常映射为稳定 error，`bytes=None`、`measured_at=None`、`pending=False`，stdout 数字不采纳；失败不投影旧成功值。

#### Scenario: 批次含逐项错误

- Test/check:
  - [X] `tests/test_mount_usage_api.py::test_valid_batch_preserves_order_duplicates_and_mixed_states`
  - [X] `tests/test_mount_usage_api.py::test_endpoint_uses_cache_bridge_for_pending_to_success`
- Assertion scope: 同批成功/pending/error 混合时顶层仍 `success == 1`、`mounts` 等长同序，逐项状态独立；`success == 1` 只表示批次受理。

#### Scenario: 重复路径保持映射

- Test/check:
  - [X] `tests/test_mount_usage_api.py::test_valid_batch_preserves_order_duplicates_and_mixed_states`
  - [X] `tests/test_mount_usage_cache.py::test_singleflight_duplicate_aliases_share_one_du_and_keep_all_items`
- Assertion scope: 同路径/规范化别名重复出现时每项各有一项结果并原样回显 path，允许共享一次后台 du，不少返回项。

### Requirement: 受限路径与不扫描边界

#### Scenario: 允许目录

- Test/check:
  - [X] `tests/test_mount_usage_cache.py::test_path_gate_accepts_allowed_directory_and_normalized_aliases`
  - [X] `tests/test_anvil_storage_snapshots.py::test_mount_usage_path_gate_accepts_case_insensitive_containers_segment`
- Assertion scope: 绝对路径 realpath 位于 base 内、含 `containers` 段且最终对象是现存非 symlink 目录时通过校验；尾随斜杠/`.`/`..` 别名规范化为同一缓存键；规划用例在 `NODE_CONTAINERS_BASE` 下建立 `Containers`/`CONTAINERS` 路径段，断言真实 `_validate_mount_path` 通过且规范化键一致，覆盖正文的大小写不敏感约束。
- Coverage note: 既有路径门禁用例只使用小写 `containers`；大小写不敏感分支由规划行承担。

#### Scenario: 越界或非绝对路径

- Test/check:
  - [X] `tests/test_mount_usage_cache.py::test_path_gate_rejects_out_of_scope_relative_missing_segment_file_and_missing`
  - [X] `tests/test_mount_usage_cache.py::test_invalid_not_found_and_permission_never_start_du`
- Assertion scope: 相对路径、等于 base、base 外、缺 `containers` 段返回 `invalid_path`，且不启动 du；门禁只处理请求值。
- Coverage note: 不枚举相邻目录由规划 `test_mount_usage_does_not_enumerate_parent_or_scan` 承担；既有行只断言不启动 du。

#### Scenario: symlink 或普通文件

- Test/check:
  - [X] `tests/test_mount_usage_cache.py::test_path_gate_rejects_symlink_and_dangling_symlink`
  - [X] `tests/test_mount_usage_cache.py::test_path_gate_rejects_out_of_scope_relative_missing_segment_file_and_missing`
  - [X] `tests/test_mount_usage_cache.py::test_queued_symlink_replacement_is_not_measured`
- Assertion scope: 最终对象是 symlink、悬空链接或普通文件时返回 `invalid_path`，不跟随执行 du；排队期间变成 symlink 的任务也被丢弃。

#### Scenario: 已清理或不存在

- Test/check:
  - [X] `tests/test_mount_usage_cache.py::test_path_gate_rejects_out_of_scope_relative_missing_segment_file_and_missing`
  - [X] `tests/test_mount_usage_cache.py::test_cached_success_is_dropped_after_directory_removal`
- Assertion scope: 允许范围内不存在/已清理返回 `not_found`，返回前不启动 du；已有缓存被丢弃。
- Coverage note: 返回前不枚举父目录/不查找替代目录由规划 `test_mount_usage_does_not_enumerate_parent_or_scan` 承担；既有行断言不启动 du 且丢弃缓存。

#### Scenario: 不做全盘或全局统计

- Test/check:
  - [X] `tests/test_anvil_storage_snapshots.py::test_mount_usage_does_not_enumerate_parent_or_scan`
- Assertion scope: 对合法路径和已清理路径调用真实 `read_mount_usage()`，同时用 `os.scandir`、`cache._dir_identity`、Docker client、`collect_machine_disk`/`shutil.disk_usage` 的记录器断言：没有父目录枚举、没有容器/目录身份读取、没有全局统计；只做请求路径的 stat/realpath 与单路径后台 du。
- Coverage note: 既有路径门禁用例只断言不启动 du，未断言不枚举父目录/全局统计；规划行把目录身份、Docker/宿主统计入口也纳入零调用断言，避免只靠 `os.scandir` 替身证明过多否定条件。

### Requirement: 按路径内存缓存与后台测量

#### Scenario: TTL 内命中

- Test/check:
  - [X] `tests/test_mount_usage_cache.py::test_ttl_hit_reuses_original_measured_at_without_du`
  - [X] `tests/test_mount_usage_api.py::test_real_http_du_pending_success_cache_hit_then_not_found`
- Assertion scope: 年龄小于 900 秒的成功样本原样返回 bytes/measured_at、不重启 du；HTTP 命中后 du 调用数不增加，测量时间早于请求时间仍如实展示。

#### Scenario: 无样本或 TTL 到期

- Test/check:
  - [X] `tests/test_mount_usage_cache.py::test_expired_success_returns_pending_and_never_old_bytes`
  - [X] `tests/test_mount_usage_api.py::test_endpoint_uses_cache_bridge_for_pending_to_success`
- Assertion scope: 无成功样本或年龄达到 900 秒时启动一次后台测量并立即返回 `pending=True`，不返回旧 bytes，HTTP 不阻塞。

#### Scenario: 慢 du

- Test/check:
  - [X] `tests/test_mount_usage_cache.py::test_read_returns_pending_immediately_and_uses_six_hundred_second_timeout`
- Assertion scope: du 持续运行且接近 600 秒超时时查询仍立即返回 pending，不等待进程结束；超时配置为 600 秒。

#### Scenario: 最后成功值不被失败覆盖

- Test/check:
  - [X] `tests/test_mount_usage_cache.py::test_failure_keeps_last_success_internally_but_never_projects_it`
  - [X] `tests/test_verify_bind_mount.py::test_du_failure_keeps_last_success_diagnostic_but_publishes_no_total`
- Assertion scope: 失败不更新 entry 的成功 bytes/measured_at；查询投影为 pending/error，内部最后成功值只作诊断，不伪装成当前测量。

#### Scenario: 进程重启

- Test/check:
  - [X] `tests/test_anvil_storage_snapshots.py::test_mount_usage_cache_is_empty_after_process_restart`
- Assertion scope: 新建 `DiskUsageCache` 代表进程重启后缓存为空：`_bind_cache`/`_container_cache`/`_path_state` 均无旧条目；同一路径首次查询返回 pending 并重新启动 du，不恢复旧样本。
- Coverage note: 既有 TTL/过期用例复用同一 cache 实例，没有断言新进程缓存为空。

### Requirement: 有界去重、并发与失败冷却

#### Scenario: 并发 singleflight

- Test/check:
  - [X] `tests/test_mount_usage_cache.py::test_singleflight_duplicate_aliases_share_one_du_and_keep_all_items`
- Assertion scope: 两个并发请求/同批别名包含同一规范化路径且无成功样本时只启动一个 du，两个响应都返回 pending，所有请求项保留。

#### Scenario: 大批量有界并发

- Test/check:
  - [X] `tests/test_mount_usage_cache.py::test_hundred_paths_run_at_most_four_du_and_http_returns_pending`
  - [X] `tests/test_mount_usage_cache.py::test_cross_request_batches_share_global_four_worker_limit`
- Assertion scope: 100 个不同合法路径整批立即返回 pending，同时运行 du 不超过 4；跨请求批次也共享全局 4 worker 上限。

#### Scenario: 失败冷却

- Test/check:
  - [X] `tests/test_mount_usage_cache.py::test_failure_cooldown_blocks_retry_then_allows_after_sixty_seconds`
- Assertion scope: 失败后 59 秒内重复查询返回上次稳定错误、`pending=False`、不启动新 du；60 秒后才允许重试。

#### Scenario: 冷却不伪造成功

- Test/check:
  - [X] `tests/test_mount_usage_cache.py::test_failure_cooldown_blocks_retry_then_allows_after_sixty_seconds`
  - [X] `tests/test_mount_usage_cache.py::test_failure_keeps_last_success_internally_but_never_projects_it`
- Assertion scope: 冷却期内 bytes 仍 None，不因缓存存在/请求重复返回 0 或最后成功值。

### Requirement: 清理后目录检查与旧缓存失效

#### Scenario: 缓存命中后目录被清理

- Test/check:
  - [X] `tests/test_mount_usage_cache.py::test_cached_success_is_dropped_after_directory_removal`
  - [X] `tests/test_mount_usage_api.py::test_cache_hit_then_cleanup_returns_not_found_without_du`
- Assertion scope: 缓存命中后目录被删除，下一次查询先检查存在性、丢弃缓存并返回 `not_found`，不返回旧成功样本或启动 du。

#### Scenario: 测量期间目录被清理

- Test/check:
  - [X] `tests/test_mount_usage_cache.py::test_measurement_during_cleanup_with_query_drops_late_success`
  - [X] `tests/test_mount_usage_cache.py::test_late_success_without_intervening_query_is_not_published`
  - [X] `tests/test_mount_usage_cache.py::test_old_result_cannot_publish_after_path_recreated`
- Assertion scope: 后台 du 启动后目录被删除，晚到成功结果不发布（bytes None、status 非 ok）；无新查询也照样丢弃；路径重建时旧结果不能覆盖新任务。

#### Scenario: 已清理路径不扫描

- Test/check:
  - [X] `tests/test_anvil_storage_snapshots.py::test_mount_usage_does_not_enumerate_parent_or_scan`
- Assertion scope: 已清理/不存在路径只做存在性检查并返回 `not_found`；不枚举父目录、不查找替代目录、不扫描全盘、不返回旧缓存。
- Coverage note: 与“不做全盘/全局统计”共享同一规划用例；既有清理用例只断言不启动 du/不返回旧值，未断言不枚举父目录。

#### Scenario: clean_mount 行为不变

- Test/check:
  - [X] `python -m pytest tests/test_clean_mount.py tests/test_mount_usage_api.py::test_query_has_no_cleanup_docker_or_wss_side_effects -q`
  - [X] `tests/test_mount_usage_api.py::test_query_has_no_cleanup_docker_or_wss_side_effects`
- Assertion scope: 既有 clean_mount 安全/超时/错误/删除语义由该套件覆盖；新端点查询期间不调用 clean_mount、不执行 rm、不改 cache 的容器/路径状态，清理入口保持原行为。

### Requirement: 只读、无周期 WSS 扩展与权限边界

#### Scenario: 查询不产生持久化

- Test/check:
  - [X] `tests/test_mount_usage_api.py::test_query_has_no_cleanup_docker_or_wss_side_effects`
  - [X] `tests/test_mount_usage_api.py::test_real_http_du_pending_success_cache_hit_then_not_found`
- Assertion scope: 端点成功/pending/错误只更新进程内 bind 缓存；不写快照/清理记录，不改目录/容器；测试断言 `_container_cache`/`_path_state` 为空、无 docker_init/clean_mount/rm。
- Coverage note: Node 无 DB 写入面；这里以真实端点不产生持久化副作用（cache 容器/路径状态为空、无清理/Docker 调用）承担“不写数据库”，不把 Ctrl DB 纳入 Node 断言。

#### Scenario: 不扩 WSS

- Test/check:
  - [X] `tests/test_mount_usage_api.py::test_query_has_no_cleanup_docker_or_wss_side_effects`
  - [X] `tests/test_verify_bind_mount.py::test_http_and_wss_share_same_disk_usage_fields`
  - [X] `tests/test_verify_bind_mount.py::test_guard_runtime_identity_fields_are_not_disk_protocol`
- Assertion scope: 查询期间不调用 `build_disk_usage_snapshot`/`build_snapshot_batch`，不建新 topic/字段/频率；既有 disk_usage WSS 字段仍与 HTTP 共用同一模型，无 `disk_protocol_version`/`collector_epoch`/`observation_seq`。

#### Scenario: 权限不另设门禁

- Test/check:
  - [X] `tests/test_mount_usage_api.py::test_identity_fields_inside_or_outside_config_are_422_and_not_measured`
  - [X] `tests/test_mount_usage_models.py::test_config_forbids_extra_identity_fields`
- Assertion scope: 合法请求只需 `config.mount_paths`；携带 machine 角色/用户角色/deleted_id 等身份字段被 422 拒绝，Node 不以 deleted_id 做授权，也没有新增角色字段。

#### Scenario: 不向浏览器开放路径参数

- Test/check:
  - [X] `tests/test_anvil_storage_snapshots.py::test_check_mount_usage_browser_surface_has_no_cors`
- Assertion scope: 真实 FastAPI app 对带 Origin 的 OPTIONS/POST 不返回 `access-control-allow-origin` 等 CORS 许可；端点只注册在既有 `/api/check_mount_usage`、无新公网别名；任意宿主路径仍被路径白名单拒绝为 `invalid_path`。
- Coverage note: mTLS 客户端证书校验在 `run.py` 的 uvicorn 启动层，TestClient 不建立 TLS；规划用例只断言 Node 未新增 CORS/公网入口与路径白名单仍生效，控制通道认证由既有启动配置承担。

### Requirement: 详情与既有行为兼容

#### Scenario: 旧 Ctrl 不调用

- Test/check:
  - [X] `tests/test_mount_usage_api.py::test_existing_check_disk_usage_contract_unchanged`
  - [X] `tests/test_verify_bind_mount.py::test_http_and_wss_share_same_disk_usage_fields`
- Assertion scope: 旧 Ctrl 只走既有 `/api/check_disk_usage`/WSS 时行为不变：响应仍为 machine_disk+container、无 mounts 新字段；disk WSS 字段与 HTTP 共用既有模型。

#### Scenario: 旧 Node 无端点

- Test/check:
  - [X] `tests/test_mount_usage_api.py::test_old_node_fallback_shapes_are_404_or_405`
- Assertion scope: `GET /api/check_mount_usage` 返回 405，未知路径 404；Node 不返回伪造 0/成功，Ctrl 由自身映射 node_unsupported。

#### Scenario: 详情无 Node 参与

- Test/check:
  - [X] `tests/test_mount_usage_api.py::test_query_has_no_cleanup_docker_or_wss_side_effects`
- Assertion scope: 查询端点不调用 `list_container_status`/`verify_mount_path`/`collect_container`，也不因详情展示执行测量；Node 没有容器详情读面，查询只返回路径统计结果。
- Coverage note: Node 仓库没有容器详情端点/字段；本场景可观察的 Node 侧断言限于查询不触发容器读取，Ctrl/Web 的详情展示与“未记录”文案不在 Node 测试范围。

#### Scenario: 不改变恢复/清理/冻结资格

- Test/check:
  - [X] `tests/test_mount_usage_api.py::test_query_has_no_cleanup_docker_or_wss_side_effects`
  - [X] `tests/test_verify_bind_mount.py::test_path_diagnostic_never_gates_measurement_or_q72_fixture`
- Assertion scope: 查询结果不触发 clean_mount/verify/collect/WSS；本地策略夹具只按 `total_bytes` 是否存在消费测量事实，不读取路径诊断作门禁，Node 侧不写资格状态。
- Coverage note: Q72 的累计/补偿/宽限策略与 Ctrl 资格实现不在 Node 仓库；这里断言 Node 不写业务状态、不把诊断当门禁，资格判定本身不在 Node 测试范围。

#### Scenario: 无数据库迁移

- Test/check:
  - [X] `tests/test_mount_usage_api.py::test_query_has_no_cleanup_docker_or_wss_side_effects`
  - [X] `tests/test_mount_usage_api.py::test_real_http_du_pending_success_cache_hit_then_not_found`
- Assertion scope: 端点只更新进程内 bind 缓存；测试断言容器/路径状态不落缓存、无 docker/clean_mount/rm 副作用；Node 仓库无新增表/列/迁移，回滚只失去按需统计。
- Coverage note: Node 无 DB 写入面；“无迁移”由真实端点不产生持久化副作用与仓库无迁移文件共同承担，不把 Ctrl DB 纳入 Node 断言。

## backend--wss-snapshots

### Requirement: delete-event 数据契约 [network/wss.py]

#### Scenario: 状态缓存报告某容器删除

- Test/check:
  - [X] `tests/test_cache_collectors.py::test_ctrl_link_sends_deleted_frames_before_snapshot`
  - [X] `tests/test_prevent_vanished.py::test_external_delete_queues_once_and_wss_sends_delete_before_snapshot`
- Assertion scope: 确认删除候选后先发 `{"type": "delete", "container_name": "ghost-1/old"}`，再发 `snapshot_batch`；候选只取一次。

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
