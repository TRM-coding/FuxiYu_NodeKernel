# Tasks

## 1. 命名与碰撞

- [x] 1.1 在 `services/container_service.py` 保持 `_MAX_NEW_MOUNT_ATTEMPTS = 100` 与 `_create_timestamped_mount_dir(...)`：普通新建生成 `<name>_<YYYYMMDD_HHMMSS>` 基名，碰撞时按 `_1` 至 `_99` 顺序以 `os.makedirs(..., exist_ok=False)` 尝试；仅非恢复分支调用，并将实际路径用于 Docker `Mount` 与 `bind_mount_path`。验证：运行 `pytest -q tests/test_create_container.py::test_create_container_new_mount_uses_local_timestamp_name`，断言基名、挂载 Source 与返回值一致。
- [x] 1.2 保持 100 个候选上限：仅 `FileExistsError` 推进下一序号，耗尽后抛错且不调用 Docker，不复用既有目录。验证：运行 `pytest -q tests/test_create_container.py::test_create_container_new_mount_same_second_gets_distinct_suffix tests/test_create_container.py::test_create_container_new_mount_collision_uses_fresh_suffix tests/test_create_container.py::test_create_container_new_mount_retry_is_bounded`，断言 `_1`/`_2`、100 上限与旧目录不变。

## 2. 恢复

- [x] 2.1 恢复分支不调用新目录分配逻辑，直接使用 `restore_mount_path`，历史目录不改名。验证：运行 `pytest -q tests/test_create_container.py::test_create_container_restore_reuses_existing_mount tests/test_anvil_creation_credentials.py::test_restore_mount_source_independent_of_image_and_name tests/test_anvil_creation_credentials.py::test_restore_mount_base_itself_is_rejected tests/test_anvil_creation_credentials.py::test_restore_valid_historical_subdir_still_recovers tests/test_anvil_creation_credentials.py::test_restore_mount_path_requires_containers_segment_and_existing_dir tests/test_anvil_creation_credentials.py::test_occupied_name_rejected_without_run_or_mount_change`，断言挂载 Source 与 `bind_mount_path` 均为历史目录。

## 3. 定向验证

- [x] 3.1 运行 `openspec validate timestamped-container-mount-directory --strict`，确认 change 有效。
