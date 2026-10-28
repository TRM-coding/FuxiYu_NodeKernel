# Test Plan

## backend--container-creation

### Requirement: 恢复挂载来源只由入参决定 [services/container_service.py]

#### Scenario: 恢复沿用原目录

- Test/check:
  - [X] tests/test_create_container.py::test_create_container_restore_reuses_existing_mount
  - [X] tests/test_anvil_creation_credentials.py::test_restore_mount_source_independent_of_image_and_name
  - [X] tests/test_anvil_creation_credentials.py::test_restore_valid_historical_subdir_still_recovers
- Assertion scope: 既有用例断言恢复结果和 Docker `mounts[0]["Source"]` 都与历史目录 `samefile`；补测在 base 自身含 `containers` 段时使用一个已存在的历史子目录，断言只调用一次 Docker create、挂载来源仍是该子目录，且不创建按新容器名推导的目录。

#### Scenario: 改名不改变数据位置

- Test/check:
  - [X] tests/test_create_container.py::test_create_container_restore_reuses_existing_mount
  - [X] tests/test_anvil_creation_credentials.py::test_restore_mount_source_independent_of_image_and_name
  - [X] tests/test_anvil_creation_credentials.py::test_restore_valid_historical_subdir_still_recovers
- Assertion scope: 同一历史目录配不同 `config.name` 和镜像时，两次挂载来源都为该目录；补测的新名称与历史目录名不同，断言没有按新名建立目录。

#### Scenario: 越界或缺失的挂载入参被拒绝

- Test/check:
  - [X] tests/test_create_container.py::test_create_container_restore_rejects_mount_outside_base
  - [X] tests/test_anvil_creation_credentials.py::test_restore_mount_path_requires_containers_segment_and_existing_dir
- Assertion scope: 越界、缺 `containers` 段、目录不存在和 symlink 逃逸均抛 `RuntimeError`，且 fake `containers.run_calls == []`；有效子目录仍允许。

#### Scenario: 恢复源等于当前公共根被拒绝

- Test/check:
  - [X] tests/test_anvil_creation_credentials.py::test_restore_mount_base_itself_is_rejected
- Assertion scope: 将 `NODE_CONTAINERS_BASE` 设为自身路径含 `containers` 段的目录，参数化或表驱动覆盖真实根路径、带 `.`/尾随分隔符的 realpath 别名、同根 symlink 别名，以及“旧单容器目录后来被设为当前公共根”的路径；每次都抛 `RuntimeError`，消息含稳定子串 `restore mount path equals containers base`，`containers.run_calls == []`，并且没有创建按新名推导的目录。同根 symlink 参数在 WSL 必跑，Windows 是否运行不作强制，不加 skip。

#### Scenario: 名字被占用即拒绝

- Test/check:
  - [X] tests/test_create_container.py::test_error_path_container_exist
  - [X] tests/test_anvil_creation_credentials.py::test_occupied_name_rejected_without_run_or_mount_change
- Assertion scope: 同名容器已存在时直接报错，容器名不被追加随机后缀，`run_calls == []`，不替换挂载来源。
