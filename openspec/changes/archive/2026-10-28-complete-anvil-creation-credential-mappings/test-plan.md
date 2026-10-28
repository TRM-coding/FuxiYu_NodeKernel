# Test Plan

<!-- Mapping only. 每条定位行有自己的 checkbox：[X] 表示该映射已核对（测试存在且断言范围已在测试代码中确认），
     [ ] 表示待建/待确认。[ ] 行给出本变更规划的新测试位置；规划测试尚不存在，不代表已运行或通过。
     正文中无独立 Scenario 的明确约束，在最近的 Scenario 下以“正文约束”写入 Coverage note，
     并给出实际测试位置或不可执行的仓库边界；不把测试意图写进 delta spec。 -->

## backend--container-creation

### Requirement: ContainerConfig 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_create_container_invalid_config_422
  - [X] tests/test_anvil_creation_credentials.py::test_container_config_defaults_and_ge_bounds
- Assertion scope: 既有：`port="not-a-port"` 经 `/api/create_container` 得到 422（类型违反的输入不作为有效实例）。计划：不传 `gpu_list` 得到 `[]`；`cpu_number`/`memory`/`shared_memory` 取 0、`port` 取 0、65535 边界通过；`cpu_number=-1`、`memory=-1`、`shared_memory=-1`、`port=65536`、缺 `image` 均抛 `ValidationError`。
- Coverage note: 既有断言只覆盖 port 类型错误与最终 422 状态；缺省值与 ge/le 边界由计划测试补齐。正文约束分两部分：`port` 仍保留在线路模型由本 Scenario 的模型测试覆盖；生产端口由 Node 分配并显式绑定由 `tests/test_create_container.py::test_all_exposed_ports_get_an_explicit_host_port` 覆盖，本行不把后者伪装成字段校验断言。

### Requirement: ImageBuildConfig 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_anvil_creation_credentials.py::test_image_build_config_defaults_and_empty_build_rejected
- Assertion scope: 计划：`ImageBuildConfig()` 的 `dockerfile_text` 与 `image_tag` 默认均为 `""`；显式提供时原样保存。同一测试还断言非法类型被拒绝：`ImageBuildConfig(dockerfile_text=123, image_tag="x")` 与 `ImageBuildConfig(dockerfile_text="FROM x", image_tag=["x"])` 均抛 `ValidationError`。空正文/空标签在 `build_image` 上失败：`build_image({"dockerfile_text": "", "image_tag": "fuxi/x:1"})` 与 `build_image({"dockerfile_text": "FROM x", "image_tag": ""})` 均抛 `RuntimeError`（消息分别含 `missing dockerfile_text` / `missing image_tag`），fake 的 `images.build` 与 `containers.run` 调用次数均为 0（未退回按运行标签启动）。
- Coverage note: 本能力既有测试未构造该模型，缺省值、非法类型与空构建拒绝无既有断言；正文“正文或标签为空时构建失败，不静默退回运行标签”由同一计划测试承担。非空文本的落盘内容由“未命中则现场构建”下的 `test_build_image_uses_exact_dockerfile_text_and_new_tag` 覆盖。

### Requirement: RestoreAccountConfig 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_password_contracts.py::test_restore_account_password_contract
  - [X] tests/test_anvil_creation_credentials.py::test_restore_account_defaults_and_password_retention
- Assertion scope: 既有：`role="admin"` 被接受、`role` 保持 `"admin"`；`repr()` 与 `model_dump()` 序列化不含明文；缺 `password` 抛 `ValidationError`；7 类非法密码抛 `ValidationError`。计划：不传 `role` 时默认 `"collaborator"`；长度 8 与 128 的密码被接受；`role="root"`/`"ADMIN"`、缺 `user_name`、`password=123`/`None` 均抛 `ValidationError`；`password` 仍是 `SecretStr`，只有 `get_secret_value()` 取明文。
- Coverage note: 既有断言未覆盖 `role` 缺省值、非法 role、缺必填与长度边界（8/128），由计划测试补齐。

#### Scenario: 恢复协作者携带瞬时密码

- Test/check:
  - [X] tests/test_blueprint_api.py::test_create_container_restore_payload_passes_mount_and_accounts
  - [X] tests/test_password_services.py::test_add_collaborator_uses_password
  - [X] tests/test_anvil_creation_credentials.py::test_restore_account_password_absent_from_snapshot_wss_cache_and_logs
- Assertion scope: 既有：恢复账号的明文经 `get_secret_value()` 传入 `add_collaborator(container_name, user_name, ROLE.COLLABORATOR, password=...)`；该 helper 的 exec 命令文本不含 `chpasswd` 与明文，密码只出现在 `api.started[0]["socket"].sent == b"u1:Role#Password9\n"`。计划：一次带 `restore_accounts` 的真实 `/api/create_container` 后，`extensions.status_cache.list_states()`、`get_state(name)["last_action"]`、`wss.build_status_snapshot()`、响应体、`caplog`+`capsys` 均不含明文与 `credentials`。
- Coverage note: 既有两行覆盖“按既有规则重建 + stdin 设密”，未覆盖 THEN 后半段“不进入 snapshot/WSS/action 缓存/日志/响应”，由计划测试补齐。

#### Scenario: 恢复协作者缺少 password

- Test/check:
  - [X] tests/test_anvil_creation_credentials.py::test_restore_account_missing_password_422_not_accepted
- Assertion scope: 计划：`POST /api/create_container` 携带 `restore_accounts=[{"user_name":"alice","role":"collaborator"}]` 时返回 422；响应体不含 `input`/`ctx`/`alice123`，响应头 `Cache-Control: no-store`；以唯一容器名断言 `extensions.status_cache.list_states()` 不含该名（未登记 building/creating）；fake 的 `containers.run_calls == []` 且未调用 `add_collaborator`。
- Coverage note: 既有 `test_restore_account_password_contract` 只断言模型层 `ValidationError`，未涉及 HTTP 422、未受理与不回退 `<user_name>123`；上述 HTTP 断言由计划测试承担。

#### Scenario: 恢复密码设置失败

- Test/check:
  - [X] tests/test_password_api.py::test_create_restore_password_failure
  - [X] tests/test_anvil_creation_credentials.py::test_restore_account_password_absent_from_snapshot_wss_cache_and_logs
- Assertion scope: 既有：`add_collaborator` 返回 False 时创建按失败处理（`status_cache.get_state(name)["last_action"]["phase"] == "failed"`、`error_reason == "create_failed"`），响应体不含 `root_password` 与协作者密码。计划：同一失败路径下 `caplog`+`capsys` 无明文，`list_states()` 投影、`wss.build_status_snapshot()` 与 `last_action` 不含密码字段或 `credentials`。
- Coverage note: “错误与日志不含密码，不写入 snapshot”只有响应与状态部分被既有断言覆盖；日志、缓存投影与 WSS 由计划测试补齐。

### Requirement: CreateContainerMessage 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_password_contracts.py::test_create_message_root_password_contract
  - [X] tests/test_anvil_creation_credentials.py::test_create_message_optional_field_defaults
  - [X] tests/test_anvil_creation_credentials.py::test_public_key_installed_without_private_key_material
- Assertion scope: 既有：`root_password.get_secret_value()` 取明文、`repr()` 与 `model_dump()` 无明文；缺 `root_password` 抛 `ValidationError`；7 类非法 `root_password` 抛 `ValidationError`。计划：`public_key`、`image_build`、`restore_mount_path` 默认 `None`，`restore_accounts` 默认 `[]` 且两个实例不共享同一 list 对象；另一正文约束用例在创建请求中附加 `private_key`/`id_rsa` 等未知字段，经真实 `POST` 创建后 fake Docker 的 `containers.run` 参数、exec 命令、stdout/caplog 均不含私钥内容，只出现 `public_key` 的 `authorized_keys` 安装命令。
- Coverage note: 既有断言集中于 `root_password`，可选字段缺省值未覆盖。正文“公开 SSH 公钥只用于安装，不记录私钥”没有独立 Scenario，由计划测试在真实请求边界验证；纯模型层断言不足以证明这一点。

#### Scenario: 创建请求携带 root_password

- Test/check:
  - [X] tests/test_password_contracts.py::test_create_message_root_password_contract
  - [X] tests/test_blueprint_api.py::test_create_container_success
- Assertion scope: 既有：模型保存为 `SecretStr`，`repr()` 与 `model_dump()` 序列化只见掩码，`get_secret_value()` 才得明文；API 层后台任务收到的 `root_password.get_secret_value() == "Root#Password9"`，说明后台可读取明文用于 stdin。

#### Scenario: 缺少 root_password

- Test/check:
  - [X] tests/test_password_api.py::test_password_routes_no_store
  - [X] tests/test_anvil_creation_credentials.py::test_missing_root_password_422_not_accepted
- Assertion scope: 既有：创建请求不带 `root_password` 时返回 422 且响应头 `Cache-Control: no-store`。计划：同请求响应体不含 `input`/`ctx`/`admin123`；以唯一容器名断言 `status_cache.list_states()` 不含该名；fake `containers.run_calls == []`。
- Coverage note: 既有断言只到 422 与 no-store，未断言“未登记 building/creating”与“不执行 Docker 创建、不回退 `<owner_name>123`”。

#### Scenario: root_password 非法

- Test/check:
  - [X] tests/test_password_contracts.py::test_create_message_root_password_contract
  - [X] tests/test_anvil_creation_credentials.py::test_create_root_password_invalid_422_redacted
- Assertion scope: 既有：模型层对空、短、超长、全空白、含 `:`、含 LF、含 NUL 的 `root_password` 抛 `ValidationError`。计划：空、短、超长、全空白、含 `:`、含 CR、含 LF、含 NUL 与对象类型分别经 `POST /api/create_container` 返回 422，`detail` 每项键集恰为 `type`/`loc`/`msg`（无 `input`/`ctx`/`url`），响应体与 `caplog`+`capsys` 不含原值，头为 `no-store`，且 `status_cache.list_states()` 不含该容器名。
- Coverage note: 既有断言停在模型层，未验证 HTTP 响应字段形状、日志与“创建未被受理”。

### Requirement: CreateContainerResponse 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_anvil_creation_credentials.py::test_create_response_defaults_and_accepted_alias_wire_shape
- Assertion scope: 计划：`CreateContainerResponse(container_status="creating", container_name="c1")` 的 `success` 默认为 1、`action_ref` 默认为 `None`；`container_status="online"` 抛 `ValidationError`；`CreateContainerResponse(container_name="c1")`（缺 `container_status`）与 `CreateContainerResponse(container_status="creating")`（缺 `container_name`）均抛 `ValidationError`；`action_ref={"node_epoch":"e","generation":-1,"seq":1}` 抛 `ValidationError`（ActionRef 的 ge=0）；同输入构造别名后 `model_dump()` 键值与原模型完全一致。
- Coverage note: 该模型只在动作契约测试中被显式构造（`action_ref` 值），缺省值、非法 Literal、缺必填字段与 ActionRef 边界无既有断言；由计划测试承担。

#### Scenario: 创建受理返回动作引用

- Test/check:
  - [X] tests/test_runtime_guard.py::test_api_create_visible_before_background_thread_finishes
  - [X] tests/test_action_contracts.py::test_mixed_version_missing_optional_fields_and_restart_epoch
  - [X] tests/test_anvil_creation_credentials.py::test_create_response_action_ref_matches_create_generation_and_seq
- Assertion scope: 既有：受理响应的 `action_ref.node_epoch == cache.node_epoch`，后台未完成时快照已为 `creating`；`CreateContainerResponse` 接受含 `generation`/`seq` 的 `action_ref`，旧帧缺该字段时消费方按自身 timeout 降级且不伪造 failed。计划：受理响应的 `action_ref` 与 `status_cache.get_state(name)["last_action"]["ref"]` 完全相等；新名称首次 create 的 `generation == 1`、`seq == 1`，且 `action_ref` 在响应返回前已存在。
- Coverage note: 既有未锁定“响应 ref 与缓存 last_action ref 相等”及新名称的 generation/seq 初值，由计划测试补齐。

### Requirement: CreateContainerAcceptedResponse 数据契约 [schemas/container.py]

#### Scenario: 使用声明值域

- Test/check:
  - [X] tests/test_anvil_creation_credentials.py::test_create_response_defaults_and_accepted_alias_wire_shape
- Assertion scope: 计划：别名的 `model_dump()` 与 `CreateContainerResponse` 同输入下键值一致；`container_status` 只接受 `building`/`creating`（`"starting"`、`"online"` 抛 `ValidationError`）；序列化键集恰为 `success`/`container_status`/`container_name`/`action_ref`，不多出未声明字段。
- Coverage note: 与“CreateContainerResponse 字段校验与缺省值”共用同一计划测试；本行只锁值域、别名形状与键集，不重复缺省值部分。

### Requirement: Container 数据契约 [utils/Container.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] tests/test_anvil_creation_credentials.py::test_legacy_container_dto_maps_config_values
- Assertion scope: 计划：`Container(gpu_list=[1], cpu_number=2, memory=4, shared_memory=1, name="c1", image="ubuntu:22.04", port=2233)` 暴露 `GPU_LIST`/`CPU_NUMBER`/`MEMORY`/`SHARED_MEMORY`/`NAME`；`get_config()` 返回含 `gpu_list`/`cpu_number`/`memory`/`shared_memory`/`name`/`port`/`image` 七键的字典且值等于构造值；`set_port(2234)` 后 `port` 同步，`set_port(1023)`/`set_port(49152)` 抛 `ValueError`。
- Coverage note: 该 legacy DTO 目前只作为 `create_container` 的入参被间接使用，成员映射、`get_config()` 与 `set_port` 边界无直接断言；由计划测试承担。

### Requirement: Container.Config_info 数据契约 [utils/Container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_anvil_creation_credentials.py::test_legacy_config_info_accepts_values_new_schema_rejects
- Assertion scope: 计划：`Container.Config_info(gpu_list=[], cpu_number=-1, memory=-1, shared_memory=-1, name="c1", port=70000, image="x")` 构造成功（legacy 无 ge/le 边界）；同输入构造 `schemas.container.ContainerConfig` 抛 `ValidationError`；两者缺 `name`/`image` 均抛 `ValidationError`。
- Coverage note: 既有 `create_container` 用例只用合法 `Container.Config_info`，未断言该类型本身没有新版边界；该边界由计划测试承担。

### Requirement: CreateContainerReturn 数据契约 [services/container_service.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] tests/test_create_container.py::test_create_container_restore_reuses_existing_mount
  - [X] tests/test_anvil_creation_credentials.py::test_create_container_return_fields_from_docker_facts
- Assertion scope: 既有：`create_container` 返回 `CreateContainerReturn`，其 `bind_mount_path` 与本次宿主目录 `os.path.samefile`。计划：`CreateContainerReturn("cid", "c1")` 的 `port`/`port_mappings`/`bind_mount_path` 均为 `None`；假容器 `attrs["NetworkSettings"]["Ports"]` 为 `{"22/tcp":[{"HostPort":"21000"}], "8080/tcp":[{"HostPort":"21001"}]}` 时返回值 `port == 21000`、`port_mappings` 为 `[{"container_port":22,"host_port":21000,"protocol":"tcp"},{"container_port":8080,"host_port":21001,"protocol":"tcp"}]`（顺序沿用 docker 返回），且 `container_id`/`container_name` 等于 docker 对象字段。
- Coverage note: 既有断言只覆盖 `bind_mount_path`；默认值、端口映射的真实 dict 形状与名称字段由计划测试补齐。

### Requirement: 构建段命中本机标签即跳过构建 [services/container_service.py]

#### Scenario: 命中即跳过构建

- Test/check:
  - [X] tests/test_create_container.py::test_build_image_uses_cached_image_tag
- Assertion scope: `images.get(tag)` 命中时 `build_image` 返回该 tag，且 `images.build` 调用次数为 0。

#### Scenario: 未命中则现场构建

- Test/check:
  - [X] tests/test_create_container.py::test_build_image_builds_missing_tag
  - [X] tests/test_anvil_creation_credentials.py::test_build_image_uses_exact_dockerfile_text_and_new_tag
- Assertion scope: 既有：`ImageNotFound` 时调用 `images.build(tag=构建段声明的 tag, dockerfile="Dockerfile")`，不传 `decode`，返回构建段声明的 tag；既有用例未断言 `path`/`rm`/`forcerm` 与 Dockerfile 内容。计划：在 fake `images.build` 内读取临时目录的 `Dockerfile`，断言内容与 `dockerfile_text` 逐字一致，且同一 tag 第二次调用直接命中、不再 build。
- Coverage note: 既有只锁 tag、dockerfile 名与不传 decode；未锁构建文本落盘与内容，由计划测试补齐。

#### Scenario: 构建段缺文本时失败而非降级

- Test/check:
  - [X] tests/test_anvil_creation_credentials.py::test_image_build_config_defaults_and_empty_build_rejected
- Assertion scope: 计划：`build_image({"dockerfile_text": "", "image_tag": "fuxi/x:1"})` 与 `build_image({"dockerfile_text": "FROM x", "image_tag": ""})` 均抛 `RuntimeError`（消息分别含 `missing dockerfile_text` / `missing image_tag`），fake 的 `images.build` 与 `containers.run` 调用次数均为 0（未退回按运行标签启动）。
- Coverage note: 既有构建用例只走成功/失败构建路径，无“空正文”断言；本行的空正文/空标签由计划测试承担。

#### Scenario: 构建结果决定运行镜像

- Test/check:
  - [X] tests/test_blueprint_api.py::test_create_container_with_image_build_reports_building
  - [X] tests/test_create_container.py::test_create_container_uses_prepared_image_and_only_runs_sshd_gate
- Assertion scope: 既有：带 `image_build` 时后台编排把构建返回值写入 `cfg.image`（`calls[0][1].image == image_build.image_tag`）；服务层 `create_container` 把传入镜像标签作为 `containers.run` 的第一个位置参数。
- Coverage note: 两行合起来证明“构建标签 → 实际运行镜像”；API 层用例用桩替换了 `create_container`，运行镜像本身由服务层用例证明。

#### Scenario: 平台注入换代而旧标签仍在

- Test/check:
  - [X] tests/test_create_container.py::test_build_image_rebuilds_when_the_tag_changes
  - [X] tests/test_create_container.py::test_build_image_cache_key_is_the_tag_not_the_dockerfile
  - [X] tests/test_anvil_creation_credentials.py::test_build_image_uses_exact_dockerfile_text_and_new_tag
- Assertion scope: 既有：旧 tag 已存在、新 tag 未命中时按新 tag 构建（`build_calls` 的 tag 依次为 `tag_v1`、`tag_v2`），`images.remove` 从未被调用（旧制品保留）；同一 tag 即使 Dockerfile 文本变化仍命中缓存，证明缓存键是 tag 而不是文本。既有用例两次构建使用同一段 Dockerfile 文本。计划：两次构建分别使用不同文本，fake `images.build` 读取并断言 v1/v2 的 Dockerfile 内容不同，旧 tag 仍不 remove。
- Coverage note: 既有只证明新 tag 触发构建、旧制品保留与文本不参与缓存键，未证明“不同 Dockerfile”与旧标签共存；由计划测试补齐。Node 没有“外部派发记录”输入，正文所说“不因外部派发记录跳过”在本仓只能以“缓存键仅为本机 tag”范围验证。

#### Scenario: 新版本再次派发

- Test/check:
  - [X] tests/test_create_container.py::test_build_image_rebuilds_when_the_tag_changes
- Assertion scope: 同一新 tag 第二次派发时 `len(build_calls)` 仍为 2 并直接返回该 tag（命中复用、不再构建），`images.remove` 从未被调用（旧制品保留）。

### Requirement: 恢复挂载来源只由入参决定 [services/container_service.py]

#### Scenario: 恢复沿用原目录

- Test/check:
  - [X] tests/test_create_container.py::test_create_container_restore_reuses_existing_mount
  - [X] tests/test_anvil_creation_credentials.py::test_restore_mount_source_independent_of_image_and_name
- Assertion scope: 既有：携带 `restore_mount_path=<base>/admin/containers/old_c` 时，返回值 `bind_mount_path` 与 `containers.run` 的 `mounts[0]["Source"]` 都 `os.path.samefile` 该目录。计划：用不同 `config.name`/`config.image` 两次调用同一 restore 目录，两个 `mounts[0]["Source"]` 仍都指向该目录，证明来源不由新名称或运行镜像推导。
- Coverage note: 既有只覆盖一个名称/镜像；正文“MUST NOT 因运行镜像来源不同而改变”由计划测试补齐。

#### Scenario: 改名不改变数据位置

- Test/check:
  - [X] tests/test_create_container.py::test_create_container_restore_reuses_existing_mount
- Assertion scope: 同一用例中 `config.name == "pytest_create_c"` 而挂载来源仍是 `old_c` 目录，证明挂载来源取 `restore_mount_path` 而非按新容器名推导。

#### Scenario: 越界或缺失的挂载入参被拒绝

- Test/check:
  - [X] tests/test_create_container.py::test_create_container_restore_rejects_mount_outside_base
  - [X] tests/test_anvil_creation_credentials.py::test_restore_mount_path_requires_containers_segment_and_existing_dir
  - [ ] tests/test_anvil_creation_credentials.py::test_restore_mount_base_itself_is_rejected
- Assertion scope: 既有：容器挂载根之外的目录抛 `RuntimeError`，消息匹配 `unsafe restore mount path`。本轮独立补测：根内但缺 `containers` 段的路径、根内 `containers` 段但目录不存在的路径、经 symlink realpath 后逃出挂载根的路径分别被拒绝，消息分别含 `without containers segment` / `does not exist` / `outside containers base`，且 fake `containers.run_calls == []`；有效子目录仍允许，调用 `containers.run` 一次且 mount source 指向该目录。暂缓定位 `test_restore_mount_base_itself_is_rejected` 的预期是：自定义根自身含 `containers` 路径段且 `restore_mount_path=str(base)` 时拒绝、无 run 调用。
- Coverage note: 当前实现放行 base 自身，违反正文“之下”的约束。用户决定本轮只记录该缺陷，暂缓 `test_restore_mount_base_itself_is_rejected` 及其业务修复；该定位保留 `[ ]`、尚未创建，不加 skip/xfail，不宣称覆盖。其余校验补测不依赖此修复，待修订计划独立获批后继续；主规格不变。

#### Scenario: 名字被占用即拒绝

- Test/check:
  - [X] tests/test_create_container.py::test_error_path_container_exist
  - [X] tests/test_anvil_creation_credentials.py::test_occupied_name_rejected_without_run_or_mount_change
- Assertion scope: 既有：同名容器已存在时 `create_container` 抛 `RuntimeError`，消息匹配 `already exists`。计划：该次调用 `containers.run_calls == []`（未创建容器），异常消息里的容器名恰为请求名（未加随机后缀改名），且同时携带合法 `restore_mount_path` 仍直接拒绝；`run_calls == []` 表明没有改用任何挂载来源启动。
- Coverage note: 既有断言只到异常文案，未断言“不自行改名、不替换挂载来源”与无 run 副作用。

### Requirement: 创建时由 Ctrl 下发的密码设置 root 账号 [services/container_service.py]

#### Scenario: 用下发密码设置 root

- Test/check:
  - [X] tests/test_password_services.py::test_create_uses_root_password_and_no_fallback
  - [X] tests/test_create_container.py::test_create_container_writes_proxy_into_container
  - [X] tests/test_anvil_creation_credentials.py::test_root_password_set_before_sshd_gate
- Assertion scope: 既有：`create_container` 使 `api.started[0]["socket"].sent == b"root:Root#Password9\n"`（密码只进 stdin），且 `client.api.created[0]["cmd"] == ["chpasswd"]`（argv 不含密码）；代理写入事件先于 `chpasswd` 事件。计划：在统一事件序列中断言 `chpasswd` 事件先于 `/usr/sbin/sshd` 启动事件。
- Coverage note: 既有未断言“设置成功后才继续 sshd 守门”的顺序；由计划测试补齐。

#### Scenario: 密码设置失败时不回退

- Test/check:
  - [X] tests/test_password_services.py::test_create_uses_root_password_and_no_fallback
  - [X] tests/test_anvil_creation_credentials.py::test_create_password_failure_logs_redacted_without_fallback
- Assertion scope: 既有：exec 退出码 1 时 `create_container` 抛 `RuntimeError`，异常文本不含明文、也不含 `owner123`（未尝试 `<owner_name>123`）；成功路径 stdout 同样不含二者；失败路径 stdout/caplog 未在该用例中断言。计划：通过真实 `/api/create_container`（fake Docker）触发 chpasswd 失败后，响应仍为受理，`last_action.phase == "failed"`/`error_reason == "create_failed"`，stdout+caplog+异常/响应不含密码或 `owner123`，且 fake `api.created` 只记录一次 `chpasswd`（不自动重试）。
- Coverage note: 既有只覆盖异常文本与成功路径 stdout；失败路径日志、状态映射与不重试由计划测试补齐。

#### Scenario: 创建响应不携带凭据

- Test/check:
  - [X] tests/test_password_api.py::test_responses_no_credentials
  - [X] tests/test_anvil_creation_credentials.py::test_create_response_exact_fields_no_credentials
- Assertion scope: 既有：创建/新增协作者/更新角色/重置四条路由的响应文本均不含 `credentials` 与明文。计划：创建受理响应 JSON 键集恰为 `{"success","container_status","container_name","action_ref"}`，无 `root_password`/`credentials`/`password`，响应头 `Cache-Control: no-store`。
- Coverage note: 既有只检查“不含 credentials/明文”，未锁定“只含这四个键”。

#### Scenario: 既有创建日志不重复

- Test/check:
  - [X] tests/test_password_api.py::test_no_duplicate_password_audit
  - [X] tests/test_anvil_creation_credentials.py::test_create_logs_carry_no_password_or_credential_entry
- Assertion scope: 既有：`add_collaborator` 与 `reset_container_password` 各受理一次后，stdout+caplog 不含明文与 `password=`。计划：一次完整创建（fake Docker）后 caplog 中既有的 `create_container called`/后台开始/服务完成日志仍在，且不存在消息含密码明文、`root_password`、`credentials`、`chpasswd` 的新增记录。
- Coverage note: 既有断言覆盖新增与重置路由，创建链路的日志条目不重复由计划测试补齐。

## backend--container-credentials

### Requirement: 密码输入使用 SecretStr 且只保持最小生命周期

#### Scenario: SecretStr 掩码

- Test/check:
  - [X] tests/test_password_contracts.py::test_secretstr_masking_across_models
  - [X] tests/test_password_contracts.py::test_create_message_root_password_contract
  - [X] tests/test_password_contracts.py::test_update_role_password_contract
- Assertion scope: 既有：创建、恢复、新增协作者、更新 ROOT、重置五个入口经 `jsonable_encoder` 与 `repr()` 后 JSON 均不含明文；`test_update_role_password_contract` 另断言更新 ADMIN 的 `password` 在 `repr()` 中同样为掩码；`root_password` 只有 `get_secret_value()` 才返回明文。
- Coverage note: `AddCollaboratorConfig`、`ResetContainerPasswordConfig` 没有独立 Scenario；由同一掩码用例覆盖，不另造场景。

#### Scenario: 创建密码不进入 Docker 运行配置

- Test/check:
  - [X] tests/test_password_services.py::test_create_password_not_in_docker_config
  - [X] tests/test_password_exec.py::test_chpasswd_stdin_argv
- Assertion scope: 既有：`containers.run` 的 args 与 kwargs（含 `environment`）整体序列化后不含明文；密码 exec 的 argv 恰为 `["chpasswd"]`，明文只出现在 exec stdin 的套接字字节流中。
- Coverage note: 正文“`restore_accounts` 的瞬时密码复用同一 helper”由 `test_add_collaborator_uses_password` 的 stdin 断言与创建编排的 `add_collaborator` 调用共同证明；没有第二条 Docker 配置注入路径。

#### Scenario: 密码不进入 WSS 或 action 缓存

- Test/check:
  - [X] tests/test_password_api.py::test_password_not_in_status_or_wss
  - [X] tests/test_anvil_creation_credentials.py::test_restore_account_password_absent_from_snapshot_wss_cache_and_logs
- Assertion scope: 既有：`CreateContainerMessage.model_dump()` 序列化不含 `root_password` 明文与 `credentials`，创建受理响应文本不含明文。计划：一次带 `restore_accounts` 的真实 `/api/create_container` 之后，`extensions.status_cache.list_states()` 与 `get_state(name)["last_action"]`、`wss.build_status_snapshot()` 全量 JSON、响应体均不含该密码、`root_password`、`password`、`credentials` 与 stdin 内容。
- Coverage note: 既有断言只到“模型 dump + 单次响应文本”，未读取 status/action 缓存投影与 WSS 快照。正文的“数据库”约束在 Node 无数据库层，本仓没有可执行断言；本行只锁 Node 缓存与 WSS。

#### Scenario: 恢复密码不进入 snapshot

- Test/check:
  - [X] tests/test_password_contracts.py::test_restore_password_not_in_snapshot
  - [X] tests/test_anvil_creation_credentials.py::test_restore_account_password_absent_from_snapshot_wss_cache_and_logs
- Assertion scope: 既有：`RestoreAccountConfig.model_dump()` 的 `password` 为掩码，`model_dump()` 与 `model_dump_json()` 均不含明文。计划：恢复成功与恢复失败（`add_collaborator` 返回 False）两条路径结束后，快照/WSS/action 缓存/响应/caplog+capsys 均无明文。
- Coverage note: “Ctrl 也不得写入持久化 snapshot”属 Ctrl 仓库，Node 侧不可断言；本行只锁 Node 侧快照、缓存、WSS、日志与响应。

#### Scenario: 不提供密码查回

- Test/check:
  - [X] tests/test_password_api.py::test_no_password_lookup_endpoint
  - [X] tests/test_anvil_creation_credentials.py::test_restore_account_password_absent_from_snapshot_wss_cache_and_logs
- Assertion scope: 既有：`/openapi.json` 中路径含 `password` 的路由方法集合只含 `post`（无查询端点）。计划：创建完成后 status 缓存与 WSS 全量载荷中检索不到该密码/`credentials`，说明 Node 没有可逆读面。
- Coverage note: “读取持久化数据取回密码”在 Node 无对应存储，只能以快照/缓存不可见间接证明。

### Requirement: 通过 stdin 安全执行 chpasswd

#### Scenario: stdin 传递密码且 argv 不含密码

- Test/check:
  - [X] tests/test_password_exec.py::test_chpasswd_stdin_argv
  - [X] tests/test_password_exec.py::test_chpasswd_stdin_real_socketio
- Assertion scope: 既有：`exec_create(container.id, ["chpasswd"], stdin=True, tty=False, user="root")`；stdin 收到 `u1:<密码>\n` 且写端 shutdown；真实 `socket.socketpair()` + `SocketIO` 场景对端收到 `b"u1:Real#Socket9\n"`，`_exec_chpasswd_stdin` 返回 0。

#### Scenario: 特殊字符按数据处理

- Test/check:
  - [X] tests/test_password_exec.py::test_chpasswd_stdin_argv
  - [X] tests/test_role_adversarial.py::test_valid_roles_keep_secret_on_stdin
- Assertion scope: 既有：`test_chpasswd_stdin_argv` 的密码含 `$`、`;`、反引号、引号、反斜杠，作为整段 stdin 字节原样送达，argv 仍为 `["chpasswd"]`；`test_valid_roles_keep_secret_on_stdin` 的 API 层合法密码含 `$`、`;`、括号，四个角色路径的所有容器命令文本均不含明文（未被 shell 拼接）。
- Coverage note: “不被任何 shell 解释”由“argv 无 shell 拼接 + stdin 字节原样”证明，未在真实容器内执行。

#### Scenario: chpasswd 非 0 时脱敏失败

- Test/check:
  - [X] tests/test_password_exec.py::test_chpasswd_failure_sanitized
  - [X] tests/test_anvil_creation_credentials.py::test_chpasswd_failure_does_not_retry
- Assertion scope: 既有：`exec_inspect` 退出码 1 时 `_exec_chpasswd_stdin` 返回 1，`_set_account_password` 抛 `RuntimeError`，异常文本不含明文。计划：失败路径 `api.exec_create` 只被调用 1 次（不自动重试），错误只含固定原因、不含 stdin 内容或原始输出。
- Coverage note: 既有断言未覆盖 THEN 中“不自动重试”这一部分。

#### Scenario: add_collaborator 日志不含初始密码

- Test/check:
  - [X] tests/test_password_services.py::test_add_collaborator_logs_no_secret
  - [X] tests/test_anvil_creation_credentials.py::test_add_collaborator_logs_no_echo_or_chpasswd_command
- Assertion scope: 既有：一次 `add_collaborator` 后 stdout+caplog 不含明文，也不含 `u1:u1123`；既有用例未断言 `echo ... | chpasswd` 或 `chpasswd` 字样。计划：同一 helper 执行后 stdout+caplog 不含 `chpasswd`、不含 `echo` 拼接密码/`u1:` 文本，密码只出现在 stdin socket 字节中。
- Coverage note: 既有只锁明文与 `u1:u1123`；`echo ... | chpasswd` 命令模式由计划测试补齐，不把既有断言扩大为命令模式断言。

#### Scenario: update_role 日志不含 ROOT/旧 owner 密码

- Test/check:
  - [X] tests/test_password_services.py::test_update_role_logs_no_secret
  - [X] tests/test_role_adversarial.py::test_api_root_transport_failure_is_500_redacted
- Assertion scope: 既有：旧 ROOT 降 ADMIN 与 ROOT 目的一次调用后 stdout+caplog 不含任一明文；API 层 ROOT 传输失败时响应与日志无明文，`error_reason == "internal_error"`，且失败后不执行清理组命令。

#### Scenario: 普通角色切换不触碰密码

- Test/check:
  - [X] tests/test_password_services.py::test_plain_role_switch_no_password
  - [X] tests/test_update_role.py::test_admin_existing_without_password_does_not_chpasswd
  - [X] tests/test_role_adversarial.py::test_valid_roles_keep_secret_on_stdin
- Assertion scope: 既有：`test_plain_role_switch_no_password` 与 `test_admin_existing_without_password_does_not_chpasswd` 在 admin/collaborator 未提供密码时 `client.api.created == []`（未实际执行 chpasswd）；`test_valid_roles_keep_secret_on_stdin` 进一步断言命令仍执行 `usermod -aG sudo u1`/`deluser u1 sudo`，且没有 `chpasswd` stdin。
- Coverage note: 前两条只锁“没有密码 exec”；组操作命令与 stdin 为空由第三条用例补齐，不新增实现。

### Requirement: 密码不得进入日志、错误、WSS、缓存与响应

#### Scenario: 日志与异常无明文

- Test/check:
  - [X] tests/test_password_services.py::test_logs_and_exceptions_no_secret
  - [X] tests/test_role_adversarial.py::test_validation_and_internal_errors_do_not_log_secret
- Assertion scope: 既有：ROOT 传输失败后 stdout+caplog 无明文；含 `:` 的 `root_password` 触发 422 与一次内部失败两条路径的日志同样无明文。
- Coverage note: 正文“Node 不写浏览器 localStorage/sessionStorage”属 Web 仓库，Node 侧没有浏览器执行面；Node 也没有数据库层，数据库约束在本仓无可执行断言。本行不伪造这两类断言。

#### Scenario: 响应不返回凭据

- Test/check:
  - [X] tests/test_password_api.py::test_add_collab_response_redacts
  - [X] tests/test_password_api.py::test_update_role_response_redacts
  - [X] tests/test_password_api.py::test_responses_no_credentials
- Assertion scope: 既有：新增协作者与更新角色成功响应包含 `success` 与 `decrypted_message`（`container_name`/`user_name`/`role` 或 `updated_role`），响应文本无明文、无 `credentials`；未逐键断言没有其他非敏感字段。新增协作者失败时 500 的 `error_reason == "add_failed"` 且无明文。
- Coverage note: 更新角色失败路径由“失败响应夹带尝试不泄漏”与“日志与异常无明文”覆盖；本行不把成功响应断言扩大为失败响应全文断言。

#### Scenario: 凭据响应禁止缓存

- Test/check:
  - [X] tests/test_password_api.py::test_password_routes_no_store
  - [X] tests/test_role_adversarial.py::test_invalid_password_contract_rejected_before_docker
- Assertion scope: 既有：创建（422）、新增协作者（200）、更新角色（200）、重置（200）四条密码路由的响应头 `Cache-Control == "no-store"`；更新角色的 19 组 422 脱敏体也带 `no-store`。
- Coverage note: “Ctrl/Web 返回 `credentials` 同样 MUST `no-store`”属 Ctrl/Web 仓库，Node 侧只能证明本仓路由。

#### Scenario: ROOT 交接逐次调用、逐项凭据

- Test/check:
  - [X] tests/test_password_services.py::test_root_handover_orchestration
  - [X] tests/test_role_adversarial.py::test_repeated_handover_sequence_is_deterministic_and_redacted
- Assertion scope: 既有：先 `update_role(old_root, ADMIN, password=...)` 再 `update_role(target, ROOT, root_password=...)` 时 stdin 内容分别出现 `b"old_root:Role#Password9\n"` 与 `b"root:Root#Password9\n"`；三轮重复交接记录完全一致（三次 200 + `success=True`、`created == 3`、三条 stdin 摘要），响应与日志无明文。
- Coverage note: THEN 中“Ctrl 返回所有旧账号 + `root` 的凭据（单旧 ROOT 2 项）”属 Ctrl 仓库；Node 侧只锁“每次只出现本次目标的一个密码字段”。

#### Scenario: 单次 ROOT 请求只带本次密码字段

- Test/check:
  - [X] tests/test_password_services.py::test_root_transfer_single_target
  - [X] tests/test_role_adversarial.py::test_transfer_root_extra_field_is_ignored_and_no_scan
  - [X] tests/test_password_contracts.py::test_update_role_password_contract
- Assertion scope: 既有：`test_root_transfer_single_target` 的 ROOT 目标调用出现 `b"root:Root#Password9\n"`，命令文本不含 `old_root`、不含 `root:target123`；`test_transfer_root_extra_field_is_ignored_and_no_scan` 中请求体附加 `transfer_root`/`owner_name`/`other_user` 被忽略（只对 target 执行、`_sent` 仅 1 条）；同时带 `root_password` 与 `password` 的模型抛 `ValidationError`。
- Coverage note: “完整交接的 Ctrl 响应包含 root 与所有旧所有者凭据”属 Ctrl 仓库。

#### Scenario: 不新增重复密码审计

- Test/check:
  - [X] tests/test_password_api.py::test_no_duplicate_password_audit
  - [X] tests/test_anvil_creation_credentials.py::test_create_logs_carry_no_password_or_credential_entry
  - [X] tests/test_anvil_creation_credentials.py::test_root_handover_no_new_password_audit
- Assertion scope: 既有：新增协作者与手动重置各一次后，stdout+caplog 不含明文，也不含 `password=`（Node 未新增密码审计行）。计划：完整创建日志无新密码/凭据条目；旧 ROOT 降 ADMIN + ROOT 目标交接后 stdout+caplog 不含 `password=`、无新增密码审计行/重复条目。
- Coverage note: 既有只覆盖新增与重置两条路由；创建与 ROOT 交接的审计断言由上述计划测试补齐。“Ctrl 沿用 `ADD_COLLABORATOR`/`UPDATE_COLLABORATOR_ROLE`、超时不得伪装成功”属 Ctrl 仓库。

#### Scenario: 非密码路由保持默认 422

- Test/check:
  - [X] tests/test_password_api.py::test_non_password_route_default_422
- Assertion scope: 既有：`/api/container_status` 的非法请求仍返回 422 且响应含 `detail`、无 `success` 字段，响应头不是 `no-store`（未被密码路由脱敏 handler 改写）；未逐键断言默认 error 形状。

#### Scenario: 失败响应夹带尝试不泄漏

- Test/check:
  - [X] tests/test_password_api.py::test_failure_response_no_secret
  - [X] tests/test_role_adversarial.py::test_api_admin_transport_failure_reports_false
- Assertion scope: 既有：重置/更新角色的服务抛含 `secret=...` 的异常时响应 500 且无明文；ADMIN 传输失败时响应 200 + `success` 为假、无明文，并满足 `_assert_redacted`（无 `input`/`ctx`、`no-store`）；失败体使用固定的 `error`/`error_reason` 文案，未逐键断言没有其他非敏感字段，响应文本不含密码。

### Requirement: 含密码请求的校验错误必须脱敏

#### Scenario: 同层字段缺失时不回显密码

- Test/check:
  - [X] tests/test_password_api.py::test_password_route_422_redaction
  - [X] tests/test_anvil_creation_credentials.py::test_password_routes_sibling_missing_422_redacted
- Assertion scope: 既有：创建请求带合法 `root_password` 但 `config` 缺必填字段时返回 422，响应文本不含明文且无 `input`/`ctx`；重置密码 `short` 非法时 422 且无回显（不是同层字段缺失）。计划：创建、新增协作者、更新角色、重置四条路由分别携带合法密码并省略一个同层必填字段，均返回 422，`detail` 键集只含 `type`/`loc`/`msg`，无 `input`/`ctx`/`url`，响应无明文、带 `no-store`，且 fake Docker 未被调用。
- Coverage note: 既有只覆盖创建的同层字段缺失与重置的非法密码；新增/更新/重置的“同层缺字段”由计划测试补齐。

#### Scenario: 密码本身非法时不回显

- Test/check:
  - [X] tests/test_role_adversarial.py::test_invalid_password_contract_rejected_before_docker
  - [X] tests/test_password_api.py::test_password_route_422_redaction
  - [X] tests/test_anvil_creation_credentials.py::test_create_root_password_invalid_422_redacted
- Assertion scope: 既有：更新角色 19 组非法/错位密码（缺失、空串、过短、超长、全空白、含 `:`、CR、LF、NUL、类型错误、双密码混用）均返回 422，响应无明文、无 `input`/`ctx`、带 `no-store`；重置密码 `short` 同样 422 且无回显。计划：创建路由的非法 `root_password`（空、超长、含 `:`、控制字符）同样 422 且不回显，并断言 `detail` 无 `url`。
- Coverage note: 创建路由缺“密码本身非法”的 HTTP 层断言，由计划测试补齐。

#### Scenario: 类型错误不携带原值

- Test/check:
  - [X] tests/test_password_api.py::test_password_route_422_redaction
  - [X] tests/test_role_adversarial.py::test_invalid_password_contract_rejected_before_docker
  - [X] tests/test_anvil_creation_credentials.py::test_create_root_password_invalid_422_redacted
- Assertion scope: 既有：重置密码传数字 `123` 返回 422、响应不含 `123`、无 `input`/`ctx`；更新角色传数字/数组/对象均 422，响应无明文、无 `input`/`ctx`、带 `no-store`。计划：创建路由传对象类型 `root_password` 同样 422 且不带原值，`detail` 键集只含 `type`/`loc`/`msg`，不含 `url`。

### Requirement: 已受理的密码任务不因客户端断开而取消

#### Scenario: 创建受理后断开

- Test/check:
  - [X] tests/test_runtime_guard.py::test_api_create_visible_before_background_thread_finishes
  - [X] tests/test_anvil_creation_credentials.py::test_create_disconnect_keeps_background_password_step
- Assertion scope: 既有：真实 `TestClient` HTTP 受理先于后台完成（响应已回、缓存状态先为 `creating`、后台完成后 `last_action.phase == "confirmed"`），只证明受理与后台解耦，未模拟断开，不覆盖本 Scenario。计划：真实 `create_app` + `httpx2.ASGITransport` 发起 `POST /api/create_container`；fake Docker 的 `containers.run` 在后台 worker 中由 `threading.Event` 阻塞；等待 worker 进入 `containers.run` 后，在受理响应已返回的时点 `aclose`/取消 ASGI client，再释放 worker；断言 `containers.run` 只 1 次、root `chpasswd` stdin 只出现一次（`api.started[0]["socket"].sent == b"root:<明文>\n"`）、`last_action.phase == "confirmed"`，无第二次创建或密码步骤。明确这是 ASGI transport 生命周期断开/取消，不声称真实 TCP 断开。
- Coverage note: 既有只证明受理先于后台；ASGI 断开由计划测试承担，不能用“响应已回”代替断开断言。创建场景的断开点是 accepted 响应已返回后的 ASGI client 关闭（不是请求处理中取消），与 spec 的“受理后断开”一致；不声称服务端收到真实 TCP FIN。

#### Scenario: 新增、重置或转移执行中断开

- Test/check:
  - [X] tests/test_password_api.py::test_sync_disconnect_continues
  - [X] tests/test_anvil_creation_credentials.py::test_sync_password_routes_survive_asgi_disconnect
- Assertion scope: 既有：仅 handler 层证据——`reset_container_password_api` 是同步函数（`inspect.iscoroutinefunction(...) is False`），直接调用会调用已打桩的 `reset_container_password` 并返回 `{"success": 1}`；未执行真实 `chpasswd`，`iscoroutinefunction` 不是断开证据，不覆盖本 Scenario。计划：真实 `create_app` + `httpx2.ASGITransport` 分别发起 add/update/reset 的 `POST`，fake `exec_create` 在服务线程由 `threading.Event` 阻塞；等待进入后取消 ASGI request task（或发送 ASGI disconnect），释放 worker；断言每条路由只执行一次 `chpasswd`、stdin 字节正确、无第二次 exec；失败路径不出现 `200`/`success`。明确这是 ASGI request 生命周期取消，不是真实 TCP，不对端到端网络断开作声明。
- Coverage note: 既有只到 handler 层；新增/重置/转移的断开语义由 ASGI 计划测试承担，不能用 `isCoroutineFunction` 或直接调用 handler 伪证。
