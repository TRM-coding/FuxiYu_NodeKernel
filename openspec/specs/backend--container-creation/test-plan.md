# backend--container-creation Test Plan

Spec: [spec.md](spec.md)

## Current Mapping


### Requirement: ContainerConfig 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_blueprint_api.py::test_create_container_invalid_config_422
  - [X] tests/test_anvil_creation_credentials.py::test_container_config_defaults_and_ge_bounds
- Assertion scope: 既有：`port="not-a-port"` 经 `/api/create_container` 得到 422（类型违反的输入不作为有效实例）。补测：不传 `gpu_list` 得到 `[]`；`cpu_number`/`memory`/`shared_memory` 取 0、`port` 取 0、65535 边界通过；`cpu_number=-1`、`memory=-1`、`shared_memory=-1`、`port=65536`、缺 `image` 均抛 `ValidationError`。
- Coverage note: 既有断言只覆盖 port 类型错误与最终 422 状态；缺省值与 ge/le 边界由补测覆盖。正文约束分两部分：`port` 仍保留在线路模型由本 Scenario 的模型测试覆盖；生产端口由 Node 分配并显式绑定由 `tests/test_create_container.py::test_all_exposed_ports_get_an_explicit_host_port` 覆盖，本行不把后者伪装成字段校验断言。

### Requirement: ImageBuildConfig 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_anvil_creation_credentials.py::test_image_build_config_defaults_and_empty_build_rejected
- Assertion scope: 补测：`ImageBuildConfig()` 的 `dockerfile_text` 与 `image_tag` 默认均为 `""`；显式提供时原样保存。同一测试还断言非法类型被拒绝：`ImageBuildConfig(dockerfile_text=123, image_tag="x")` 与 `ImageBuildConfig(dockerfile_text="FROM x", image_tag=["x"])` 均抛 `ValidationError`。空正文/空标签在 `build_image` 上失败：`build_image({"dockerfile_text": "", "image_tag": "fuxi/x:1"})` 与 `build_image({"dockerfile_text": "FROM x", "image_tag": ""})` 均抛 `RuntimeError`（消息分别含 `missing dockerfile_text` / `missing image_tag`），fake 的 `images.build` 与 `containers.run` 调用次数均为 0（未退回按运行标签启动）。
- Coverage note: 本能力既有测试未构造该模型，缺省值、非法类型与空构建拒绝无既有断言；正文“正文或标签为空时构建失败，不静默退回运行标签”由同一补测承担。非空文本的落盘内容由“未命中则现场构建”下的 `test_build_image_uses_exact_dockerfile_text_and_new_tag` 覆盖。

### Requirement: RestoreAccountConfig 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_password_contracts.py::test_restore_account_password_contract
  - [X] tests/test_anvil_creation_credentials.py::test_restore_account_defaults_and_password_retention
- Assertion scope: 既有：`role="admin"` 被接受、`role` 保持 `"admin"`；`repr()` 与 `model_dump()` 序列化不含明文；缺 `password` 抛 `ValidationError`；7 类非法密码抛 `ValidationError`。补测：不传 `role` 时默认 `"collaborator"`；长度 8 与 128 的密码被接受；`role="root"`/`"ADMIN"`、缺 `user_name`、`password=123`/`None` 均抛 `ValidationError`；`password` 仍是 `SecretStr`，只有 `get_secret_value()` 取明文。
- Coverage note: 既有断言未覆盖 `role` 缺省值、非法 role、缺必填与长度边界（8/128），由补测覆盖。

#### Scenario: 恢复协作者携带瞬时密码

- Test/check:
  - [X] tests/test_blueprint_api.py::test_create_container_restore_payload_passes_mount_and_accounts
  - [X] tests/test_password_services.py::test_add_collaborator_uses_password
  - [X] tests/test_anvil_creation_credentials.py::test_restore_account_password_absent_from_snapshot_wss_cache_and_logs
- Assertion scope: 既有：恢复账号的明文经 `get_secret_value()` 传入 `add_collaborator(container_name, user_name, ROLE.COLLABORATOR, password=...)`；该 helper 的 exec 命令文本不含 `chpasswd` 与明文，密码只出现在 `api.started[0]["socket"].sent == b"u1:Role#Password9\n"`。补测：一次带 `restore_accounts` 的真实 `/api/create_container` 后，`extensions.status_cache.list_states()`、`get_state(name)["last_action"]`、`wss.build_status_snapshot()`、响应体、`caplog`+`capsys` 均不含明文与 `credentials`。
- Coverage note: 既有两行覆盖“按既有规则重建 + stdin 设密”，未覆盖 THEN 后半段“不进入 snapshot/WSS/action 缓存/日志/响应”，由补测覆盖。

#### Scenario: 恢复协作者缺少 password

- Test/check:
  - [X] tests/test_anvil_creation_credentials.py::test_restore_account_missing_password_422_not_accepted
- Assertion scope: 补测：`POST /api/create_container` 携带 `restore_accounts=[{"user_name":"alice","role":"collaborator"}]` 时返回 422；响应体不含 `input`/`ctx`/`alice123`，响应头 `Cache-Control: no-store`；以唯一容器名断言 `extensions.status_cache.list_states()` 不含该名（未登记 building/creating）；fake 的 `containers.run_calls == []` 且未调用 `add_collaborator`。
- Coverage note: 既有 `test_restore_account_password_contract` 只断言模型层 `ValidationError`，未涉及 HTTP 422、未受理与不回退 `<user_name>123`；上述 HTTP 断言由补测覆盖。

#### Scenario: 恢复密码设置失败

- Test/check:
  - [X] tests/test_password_api.py::test_create_restore_password_failure
  - [X] tests/test_anvil_creation_credentials.py::test_restore_account_password_absent_from_snapshot_wss_cache_and_logs
- Assertion scope: 既有：`add_collaborator` 返回 False 时创建按失败处理（`status_cache.get_state(name)["last_action"]["phase"] == "failed"`、`error_reason == "create_failed"`），响应体不含 `root_password` 与协作者密码。补测：同一失败路径下 `caplog`+`capsys` 无明文，`list_states()` 投影、`wss.build_status_snapshot()` 与 `last_action` 不含密码字段或 `credentials`。
- Coverage note: “错误与日志不含密码，不写入 snapshot”只有响应与状态部分被既有断言覆盖；日志、缓存投影与 WSS 由补测覆盖。

### Requirement: CreateContainerMessage 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_password_contracts.py::test_create_message_root_password_contract
  - [X] tests/test_anvil_creation_credentials.py::test_create_message_optional_field_defaults
  - [X] tests/test_anvil_creation_credentials.py::test_public_key_installed_without_private_key_material
- Assertion scope: 既有：`root_password.get_secret_value()` 取明文、`repr()` 与 `model_dump()` 无明文；缺 `root_password` 抛 `ValidationError`；7 类非法 `root_password` 抛 `ValidationError`。补测：`public_key`、`image_build`、`restore_mount_path` 默认 `None`，`restore_accounts` 默认 `[]` 且两个实例不共享同一 list 对象；另一正文约束用例在创建请求中附加 `private_key`/`id_rsa` 等未知字段，经真实 `POST` 创建后 fake Docker 的 `containers.run` 参数、exec 命令、stdout/caplog 均不含私钥内容，只出现 `public_key` 的 `authorized_keys` 安装命令。
- Coverage note: 既有断言集中于 `root_password`，可选字段缺省值未覆盖。正文“公开 SSH 公钥只用于安装，不记录私钥”没有独立 Scenario，由补测在真实请求边界验证；纯模型层断言不足以证明这一点。

#### Scenario: 创建请求携带 root_password

- Test/check:
  - [X] tests/test_password_contracts.py::test_create_message_root_password_contract
  - [X] tests/test_blueprint_api.py::test_create_container_success
- Assertion scope: 既有：模型保存为 `SecretStr`，`repr()` 与 `model_dump()` 序列化只见掩码，`get_secret_value()` 才得明文；API 层后台任务收到的 `root_password.get_secret_value() == "Root#Password9"`，说明后台可读取明文用于 stdin。

#### Scenario: 缺少 root_password

- Test/check:
  - [X] tests/test_password_api.py::test_password_routes_no_store
  - [X] tests/test_anvil_creation_credentials.py::test_missing_root_password_422_not_accepted
- Assertion scope: 既有：创建请求不带 `root_password` 时返回 422 且响应头 `Cache-Control: no-store`。补测：同请求响应体不含 `input`/`ctx`/`admin123`；以唯一容器名断言 `status_cache.list_states()` 不含该名；fake `containers.run_calls == []`。
- Coverage note: 既有断言只到 422 与 no-store，未断言“未登记 building/creating”与“不执行 Docker 创建、不回退 `<owner_name>123`”。

#### Scenario: root_password 非法

- Test/check:
  - [X] tests/test_password_contracts.py::test_create_message_root_password_contract
  - [X] tests/test_anvil_creation_credentials.py::test_create_root_password_invalid_422_redacted
- Assertion scope: 既有：模型层对空、短、超长、全空白、含 `:`、含 LF、含 NUL 的 `root_password` 抛 `ValidationError`。补测：空、短、超长、全空白、含 `:`、含 CR、含 LF、含 NUL 与对象类型分别经 `POST /api/create_container` 返回 422，`detail` 每项键集恰为 `type`/`loc`/`msg`（无 `input`/`ctx`/`url`），响应体与 `caplog`+`capsys` 不含原值，头为 `no-store`，且 `status_cache.list_states()` 不含该容器名。
- Coverage note: 既有断言停在模型层，未验证 HTTP 响应字段形状、日志与“创建未被受理”。

### Requirement: CreateContainerResponse 数据契约 [schemas/container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_anvil_creation_credentials.py::test_create_response_defaults_and_accepted_alias_wire_shape
- Assertion scope: 补测：`CreateContainerResponse(container_status="creating", container_name="c1")` 的 `success` 默认为 1、`action_ref` 默认为 `None`；`container_status="online"` 抛 `ValidationError`；`CreateContainerResponse(container_name="c1")`（缺 `container_status`）与 `CreateContainerResponse(container_status="creating")`（缺 `container_name`）均抛 `ValidationError`；`action_ref={"node_epoch":"e","generation":-1,"seq":1}` 抛 `ValidationError`（ActionRef 的 ge=0）；同输入构造别名后 `model_dump()` 键值与原模型完全一致。
- Coverage note: 该模型只在动作契约测试中被显式构造（`action_ref` 值），缺省值、非法 Literal、缺必填字段与 ActionRef 边界无既有断言；由补测覆盖。

#### Scenario: 创建受理返回动作引用

- Test/check:
  - [X] tests/test_runtime_guard.py::test_api_create_visible_before_background_thread_finishes
  - [X] tests/test_action_contracts.py::test_mixed_version_missing_optional_fields_and_restart_epoch
  - [X] tests/test_anvil_creation_credentials.py::test_create_response_action_ref_matches_create_generation_and_seq
- Assertion scope: 既有：受理响应的 `action_ref.node_epoch == cache.node_epoch`，后台未完成时快照已为 `creating`；`CreateContainerResponse` 接受含 `generation`/`seq` 的 `action_ref`，旧帧缺该字段时消费方按自身 timeout 降级且不伪造 failed。补测：受理响应的 `action_ref` 与 `status_cache.get_state(name)["last_action"]["ref"]` 完全相等；新名称首次 create 的 `generation == 1`、`seq == 1`，且 `action_ref` 在响应返回前已存在。
- Coverage note: 既有未锁定“响应 ref 与缓存 last_action ref 相等”及新名称的 generation/seq 初值，由补测覆盖。

### Requirement: CreateContainerAcceptedResponse 数据契约 [schemas/container.py]

#### Scenario: 使用声明值域

- Test/check:
  - [X] tests/test_anvil_creation_credentials.py::test_create_response_defaults_and_accepted_alias_wire_shape
- Assertion scope: 补测：别名的 `model_dump()` 与 `CreateContainerResponse` 同输入下键值一致；`container_status` 只接受 `building`/`creating`（`"starting"`、`"online"` 抛 `ValidationError`）；序列化键集恰为 `success`/`container_status`/`container_name`/`action_ref`，不多出未声明字段。
- Coverage note: 与“CreateContainerResponse 字段校验与缺省值”共用同一补测；本行只锁值域、别名形状与键集，不重复缺省值部分。

### Requirement: Container 数据契约 [utils/Container.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] tests/test_anvil_creation_credentials.py::test_legacy_container_dto_maps_config_values
- Assertion scope: 补测：`Container(gpu_list=[1], cpu_number=2, memory=4, shared_memory=1, name="c1", image="ubuntu:22.04", port=2233)` 暴露 `GPU_LIST`/`CPU_NUMBER`/`MEMORY`/`SHARED_MEMORY`/`NAME`；`get_config()` 返回含 `gpu_list`/`cpu_number`/`memory`/`shared_memory`/`name`/`port`/`image` 七键的字典且值等于构造值；`set_port(2234)` 后 `port` 同步，`set_port(1023)`/`set_port(49152)` 抛 `ValueError`。
- Coverage note: 该 legacy DTO 目前只作为 `create_container` 的入参被间接使用，成员映射、`get_config()` 与 `set_port` 边界无直接断言；由补测覆盖。

### Requirement: Container.Config_info 数据契约 [utils/Container.py]

#### Scenario: 字段校验与缺省值

- Test/check:
  - [X] tests/test_anvil_creation_credentials.py::test_legacy_config_info_accepts_values_new_schema_rejects
- Assertion scope: 补测：`Container.Config_info(gpu_list=[], cpu_number=-1, memory=-1, shared_memory=-1, name="c1", port=70000, image="x")` 构造成功（legacy 无 ge/le 边界）；同输入构造 `schemas.container.ContainerConfig` 抛 `ValidationError`；两者缺 `name`/`image` 均抛 `ValidationError`。
- Coverage note: 既有 `create_container` 用例只用合法 `Container.Config_info`，未断言该类型本身没有新版边界；该边界由补测覆盖。

### Requirement: CreateContainerReturn 数据契约 [services/container_service.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] tests/test_create_container.py::test_create_container_restore_reuses_existing_mount
  - [X] tests/test_anvil_creation_credentials.py::test_create_container_return_fields_from_docker_facts
- Assertion scope: 既有：`create_container` 返回 `CreateContainerReturn`，其 `bind_mount_path` 与本次宿主目录 `os.path.samefile`。补测：`CreateContainerReturn("cid", "c1")` 的 `port`/`port_mappings`/`bind_mount_path` 均为 `None`；假容器 `attrs["NetworkSettings"]["Ports"]` 为 `{"22/tcp":[{"HostPort":"21000"}], "8080/tcp":[{"HostPort":"21001"}]}` 时返回值 `port == 21000`、`port_mappings` 为 `[{"container_port":22,"host_port":21000,"protocol":"tcp"},{"container_port":8080,"host_port":21001,"protocol":"tcp"}]`（顺序沿用 docker 返回），且 `container_id`/`container_name` 等于 docker 对象字段。
- Coverage note: 既有断言只覆盖 `bind_mount_path`；默认值、端口映射的真实 dict 形状与名称字段由补测覆盖。

### Requirement: 构建段命中本机标签即跳过构建 [services/container_service.py]

#### Scenario: 命中即跳过构建

- Test/check:
  - [X] tests/test_create_container.py::test_build_image_uses_cached_image_tag
- Assertion scope: `images.get(tag)` 命中时 `build_image` 返回该 tag，且 `images.build` 调用次数为 0。

#### Scenario: 未命中则现场构建

- Test/check:
  - [X] tests/test_create_container.py::test_build_image_builds_missing_tag
  - [X] tests/test_anvil_creation_credentials.py::test_build_image_uses_exact_dockerfile_text_and_new_tag
- Assertion scope: 既有：`ImageNotFound` 时调用 `images.build(tag=构建段声明的 tag, dockerfile="Dockerfile")`，不传 `decode`，返回构建段声明的 tag；既有用例未断言 `path`/`rm`/`forcerm` 与 Dockerfile 内容。补测：在 fake `images.build` 内读取临时目录的 `Dockerfile`，断言内容与 `dockerfile_text` 逐字一致，且同一 tag 第二次调用直接命中、不再 build。
- Coverage note: 既有只锁 tag、dockerfile 名与不传 decode；未锁构建文本落盘与内容，由补测覆盖。

#### Scenario: 构建段缺文本时失败而非降级

- Test/check:
  - [X] tests/test_anvil_creation_credentials.py::test_image_build_config_defaults_and_empty_build_rejected
- Assertion scope: 补测：`build_image({"dockerfile_text": "", "image_tag": "fuxi/x:1"})` 与 `build_image({"dockerfile_text": "FROM x", "image_tag": ""})` 均抛 `RuntimeError`（消息分别含 `missing dockerfile_text` / `missing image_tag`），fake 的 `images.build` 与 `containers.run` 调用次数均为 0（未退回按运行标签启动）。
- Coverage note: 既有构建用例只走成功/失败构建路径，无“空正文”断言；本行的空正文/空标签由补测覆盖。

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
- Assertion scope: 既有：旧 tag 已存在、新 tag 未命中时按新 tag 构建（`build_calls` 的 tag 依次为 `tag_v1`、`tag_v2`），`images.remove` 从未被调用（旧制品保留）；同一 tag 即使 Dockerfile 文本变化仍命中缓存，证明缓存键是 tag 而不是文本。既有用例两次构建使用同一段 Dockerfile 文本。补测：两次构建分别使用不同文本，fake `images.build` 读取并断言 v1/v2 的 Dockerfile 内容不同，旧 tag 仍不 remove。
- Coverage note: 既有只证明新 tag 触发构建、旧制品保留与文本不参与缓存键，未证明“不同 Dockerfile”与旧标签共存；由补测覆盖。Node 没有“外部派发记录”输入，正文所说“不因外部派发记录跳过”在本仓只能以“缓存键仅为本机 tag”范围验证。

#### Scenario: 新版本再次派发

- Test/check:
  - [X] tests/test_create_container.py::test_build_image_rebuilds_when_the_tag_changes
- Assertion scope: 同一新 tag 第二次派发时 `len(build_calls)` 仍为 2 并直接返回该 tag（命中复用、不再构建），`images.remove` 从未被调用（旧制品保留）。

### Requirement: 普通新建挂载目录的本地时间戳命名与序号后缀

#### Scenario: 普通新建使用本地时间戳基名

- Test/check:
  - [X] tests/test_create_container.py::test_create_container_new_mount_uses_local_timestamp_name
- Assertion scope: 固定本地时间，校验目录、Docker Source 与返回路径一致。

#### Scenario: 时间戳取本地时间而非 UTC

- Test/check:
  - [X] tests/test_create_container.py::test_create_container_new_mount_uses_local_timestamp_name
- Assertion scope: 固定 `datetime.now()` 的值，校验目录名使用该值；未单独模拟跨时区转换。

#### Scenario: 历史目录保留且不参与新路径

- Test/check:
  - [X] tests/test_create_container.py::test_create_container_new_mount_collision_uses_fresh_suffix
- Assertion scope: 预置旧目录及内容，验证新建后旧数据不变。

### Requirement: 普通新建目录碰撞的原子有界避让

#### Scenario: 基名碰撞追加 _1

- Test/check:
  - [X] tests/test_create_container.py::test_create_container_new_mount_same_second_gets_distinct_suffix
- Assertion scope: 同秒两次创建取得基名和 `_1`。

#### Scenario: 连续碰撞按序递增

- Test/check:
  - [X] tests/test_create_container.py::test_create_container_new_mount_collision_uses_fresh_suffix
- Assertion scope: 基名和 `_1` 已存在时取得 `_2`，保留旧数据。

#### Scenario: 并发创建只占用一个候选

- Test/check:
  - [ ] 尚无并发测试。
- Assertion scope: 顺序碰撞测试不证明并发交错；实现使用 `exist_ok=False` 独占创建叶目录。

#### Scenario: 100 个候选耗尽不降级复用

- Test/check:
  - [X] tests/test_create_container.py::test_create_container_new_mount_retry_is_bounded
- Assertion scope: 所有候选被占用时失败，未调用 Docker 创建。

#### Scenario: 非碰撞错误不当作碰撞重试

- Test/check:
  - [ ] 尚无针对目录权限错误的专门测试。
- Assertion scope: 实现只捕获 `FileExistsError`，其他错误向上返回。

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

#### Scenario: 恢复不生成时间戳目录

- Test/check:
  - [X] tests/test_create_container.py::test_create_container_restore_reuses_existing_mount
- Assertion scope: 复用原目录，未额外创建新目录。

#### Scenario: 恢复与当前时刻的普通新建候选同名

- Test/check:
  - [ ] 尚无该名称形式的独立测试。
- Assertion scope: 恢复分支直接使用给定路径；已有恢复测试覆盖历史目录。

### Requirement: 创建时由 Ctrl 下发的密码设置 root 账号 [services/container_service.py]

#### Scenario: 用下发密码设置 root

- Test/check:
  - [X] tests/test_password_services.py::test_create_uses_root_password_and_no_fallback
  - [X] tests/test_create_container.py::test_create_container_writes_proxy_into_container
  - [X] tests/test_anvil_creation_credentials.py::test_root_password_set_before_sshd_gate
- Assertion scope: 既有：`create_container` 使 `api.started[0]["socket"].sent == b"root:Root#Password9\n"`（密码只进 stdin），且 `client.api.created[0]["cmd"] == ["chpasswd"]`（argv 不含密码）；代理写入事件先于 `chpasswd` 事件。补测：在统一事件序列中断言 `chpasswd` 事件先于 `/usr/sbin/sshd` 启动事件。
- Coverage note: 既有未断言“设置成功后才继续 sshd 守门”的顺序；由补测覆盖。

#### Scenario: 密码设置失败时不回退

- Test/check:
  - [X] tests/test_password_services.py::test_create_uses_root_password_and_no_fallback
  - [X] tests/test_anvil_creation_credentials.py::test_create_password_failure_logs_redacted_without_fallback
- Assertion scope: 既有：exec 退出码 1 时 `create_container` 抛 `RuntimeError`，异常文本不含明文、也不含 `owner123`（未尝试 `<owner_name>123`）；成功路径 stdout 同样不含二者；失败路径 stdout/caplog 未在该用例中断言。补测：通过真实 `/api/create_container`（fake Docker）触发 chpasswd 失败后，响应仍为受理，`last_action.phase == "failed"`/`error_reason == "create_failed"`，stdout+caplog+异常/响应不含密码或 `owner123`，且 fake `api.created` 只记录一次 `chpasswd`（不自动重试）。
- Coverage note: 既有只覆盖异常文本与成功路径 stdout；失败路径日志、状态映射与不重试由补测覆盖。

#### Scenario: 创建响应不携带凭据

- Test/check:
  - [X] tests/test_password_api.py::test_responses_no_credentials
  - [X] tests/test_anvil_creation_credentials.py::test_create_response_exact_fields_no_credentials
- Assertion scope: 既有：创建/新增协作者/更新角色/重置四条路由的响应文本均不含 `credentials` 与明文。补测：创建受理响应 JSON 键集恰为 `{"success","container_status","container_name","action_ref"}`，无 `root_password`/`credentials`/`password`，响应头 `Cache-Control: no-store`。
- Coverage note: 既有只检查“不含 credentials/明文”，未锁定“只含这四个键”。

#### Scenario: 既有创建日志不重复

- Test/check:
  - [X] tests/test_password_api.py::test_no_duplicate_password_audit
  - [X] tests/test_anvil_creation_credentials.py::test_create_logs_carry_no_password_or_credential_entry
- Assertion scope: 既有：`add_collaborator` 与 `reset_container_password` 各受理一次后，stdout+caplog 不含明文与 `password=`。补测：一次完整创建（fake Docker）后 caplog 中既有的 `create_container called`/后台开始/服务完成日志仍在，且不存在消息含密码明文、`root_password`、`credentials`、`chpasswd` 的新增记录。
- Coverage note: 既有断言覆盖新增与重置路由，创建链路的日志条目不重复由补测覆盖。
