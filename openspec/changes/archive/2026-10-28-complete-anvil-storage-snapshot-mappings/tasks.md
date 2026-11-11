# Tasks

## 1. 数据契约与线路模型

- [x] 1.1 实现 `test_check_disk_usage_message_request_validation`、`test_machine_disk_usage_defaults_and_null_capacity`、`test_container_disk_usage_rejects_invalid_status_and_types`、`test_disk_usage_response_alias_preserves_wire_contract`；验证方式：WSL fuxi python 运行 `tests/test_anvil_storage_snapshots.py` 对应 4 个用例，断言真实 Pydantic 缺省/必填/非法 Literal 与别名线路形状。
- [x] 1.2 实现 `test_check_disk_usage_response_contract_reads_shared_cache`、`test_clean_mount_wire_models`；验证方式：`TestClient(create_app())` 走真实 `/api/check_disk_usage` 并注入共享缓存，断言缺省、必填、字段集合与无容器采集副作用；CleanMountConfig/Message/Response 真实模型校验。
- [x] 1.3 实现 `test_old_usage_without_measured_at_is_not_current`；验证方式：真实 `DiskUsageCache.snapshot()` 读取旧 total/bind 且 `measured_at=None` 的缓存，断言不当前化、不补接收时间、保留同路径。

## 2. 路径、测量与清理边界

- [x] 2.1 实现 `test_path_correction_has_no_docker_or_directory_mutation`、`test_path_correction_scoped_to_active_container`；验证方式：真实 `DiskUsageCache.verify_mount_path`/`collect_container`，fake Docker 仅替换外部容器对象，断言只读调用、目录不变、c2/历史条目不变。
- [x] 2.2 实现 `test_resolved_path_du_failure_publishes_no_total`、`test_paused_container_keeps_path_and_measurement`、`test_bind_presence_blocks_overlay_only_and_no_bind_composes_overlay`；验证方式：真实缓存组合逻辑，fake `du`/Docker 边界；断言 resolved 失败不发布 total、paused 保留测量、有 bind 缺测量不得 overlay-only、明确 no_bind 才允许 overlay-only。
- [x] 2.3 实现 `test_path_measurement_does_not_authorize_cleanup`；验证方式：在 resolved+有效测量前置下，记录 service/API `clean_mount`、`rm`、容器 remove 零调用；范围外路径 ValueError 仅作附加检查。

## 3. `check_mount_usage` 路径门禁、缓存与 HTTP 边界

- [x] 3.1 实现 `test_mount_usage_zero_bytes_is_real_success`、`test_mount_usage_path_gate_accepts_case_insensitive_containers_segment`；验证方式：受控 `du` 返回 0 走真实 `read_mount_usage`；真实 `_validate_mount_path` 接受 `Containers`/`CONTAINERS` 段。
- [x] 3.2 实现 `test_mount_usage_does_not_enumerate_parent_or_scan`、`test_mount_usage_cache_is_empty_after_process_restart`；验证方式：`os.scandir`、`_dir_identity`、Docker、`collect_machine_disk` 记录器零调用；新建 cache 后首次查询 pending 且不恢复旧样本。
- [x] 3.3 实现 `test_check_mount_usage_browser_surface_has_no_cors`、`test_lifespan_has_no_outbound_connection_attempt`；验证方式：真实 FastAPI/TestClient 无 CORS 许可；lifespan 在清空 Ctrl 目标地址 env 后运行，socket/asyncio/websocket 连接入口零调用。

## 4. WSS 状态、磁盘与 LastSsh

- [x] 4.1 实现 `test_unpause_soft_failure_keeps_online_wss_frame`、`test_confirmed_pause_last_action_keeps_online_snapshot`；验证方式：真实 `ContainerStatusCache` 动作终结 + 真实 `build_status_snapshot()`，断言 unpause/confirmed pause 不覆盖 online 运行态。
- [x] 4.2 实现 `test_wss_status_snapshot_failed_and_unknown_frames`；验证方式：真实 status cache 的硬阻塞与 unknown 状态经真实 `build_status_snapshot()` 输出 failed/unknown 帧，断言 `status`、`failed_reason`、`status_source`、`unknown_since`。
- [x] 4.3 实现 `test_wss_disk_usage_distinguishes_zero_missing_and_measuring`、`test_last_ssh_empty_output_returns_none_and_serializes_updated_at`；验证方式：真实 disk WSS 快照区分 0/measuring/无缓存；真实 `LastSshCache` 空输出 → None 且 `updated_at` 无后缀。Q77 非运行态 locator 不创建、不执行、不 skip/xfail。
- [x] 4.4 实现 `test_static_hardware_profile_uses_bind_mount_and_cache_expiry`、`test_sys_snapshot_collects_bind_and_docker_data_partitions`；验证方式：真实 `SysSnapshotCache.collect_static/_collect_disk`，仅 fake 外部 psutil/du 读取；断言 bind_mount disk 来源、静态缓存到期重采、两个数据目录分别采集。

## 5. 定向验证与全默认回归

- [x] 5.1 从 repo root 用 WSL fuxi python 显式环境变量运行新文件 26 个独立用例，保存 raw stdout/退出码到 `E:/AI/Fuxi_audit_artifacts/anvil-rollout-2026-10-28/node-batch-4/`；确认无 Q77 locator、无 skip/xfail。
- [x] 5.2 从 repo root 执行一次完整默认 pytest（不附 tests/ 路径，包含 `scripts/ci/tests`），保存 raw stdout/退出码与 collect 数量；按实际参数化 counts 核对，不跑无必要重跑。
- [x] 5.3 运行 official verify advisory，不创建 `verify.md`；记录 advisory 通过/非阻塞项，若有真实业务差异仅报父 Global Q77，不顺手修业务。

## Workflow follow-up

- 官方 sync 两能力 delta 到 main spec；核对 Node 10 个 main spec SHA 保持。
- 按 `anvil-test-plan` 维护 `backend--storage-and-mounts`、`backend--wss-snapshots` 两个 canonical sidecar；保留 Q77 `[ ]` 与真实 notes，实施状态一致。
- 官方 archive 本 change 到 2026-10-28（北京时间）；不 commit/push，由父统一 git。
