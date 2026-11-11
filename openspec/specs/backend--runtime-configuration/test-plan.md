# backend--runtime-configuration Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: NetConfig 数据契约 [config.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_net_config_declares_only_node_port`
- Assertion scope: 在 `with monkeypatch.context() as local:` 内先 `local.delenv("NODE_PORT", raising=False)`，再 `importlib.reload(config)`，断言 `NetConfig` 只声明 `NODE_PORT` 一项且其值为合法监听端口整数、不存在 Ctrl 地址类配置键，与"Node 只知道自己的监听端口、不要求配置 Ctrl 地址"一致；`finally` 中再 `importlib.reload(config)` 恢复，不使用 `monkeypatch.undo()`。
- Coverage note: 缺省端口的具体数值未在 spec 中声明，故只校验类型与端口范围、不固化实现默认值；类属性在导入时由 `_env_int` 求值，不做环境隔离会读到机器上的 `NODE_PORT` 而误判。

### Requirement: PortConfig 数据契约 [config.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_port_config_default_range_constants`
  - [X] `tests/test_port_allocator.py::test_ports_are_handed_out_sequentially_from_range_start`
- Assertion scope: 新增用例在 `with monkeypatch.context() as local:` 内 `local.delenv("NODE_PORT_RANGE_START", raising=False)` 与 `local.delenv("NODE_PORT_RANGE_END", raising=False)`，再 `importlib.reload(config)`，断言两项缺省为 20000 与 29999 且起止有序，`finally` 中再 reload 恢复；既有用例断言分配器从 `NODE_PORT_RANGE_START` 顺序取号，证明配置只以配置值形式被运行入口消费。
- Coverage note: 既有用例以类属性为起点推导期望值，因此不构成对缺省值本身的断言；缺省值断言必须先隔离 `NODE_PORT_RANGE_*` 环境变量，否则会读到环境值；缺省段与显式 Docker 绑定由 port_allocator 承担的部分不在本场景范围。

### Requirement: KeyConfig 数据契约 [config.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_key_config_declares_paths_without_secret_material`
- Assertion scope: 断言 `PUBLIC_KEY_PATH`/`PRIVATE_KEY_PATH`/`PUBLIC_KEY_CONTROL` 三个键存在、值为文件名路径字符串、字段内容不含 PEM 标记或私钥正文（不复制密钥）。
- Coverage note: spec 明确"是否仍被运行入口消费在 Global 问题清单中核查"，故只断言配置键与"不复制密钥"，不做消费路径行为断言。

### Requirement: AppConfig 数据契约 [config.py]

#### Scenario: 内部值传递

- Test/check:
  - [X] `tests/test_anvil_node_foundations.py::test_app_config_inherits_key_config_and_env_overrides`
- Assertion scope: 断言 `AppConfig` 继承 `KeyConfig`、`PUBLIC_KEY_PATH`/`PRIVATE_KEY_PATH` 两键同名覆盖且新增 `SECRET_KEY`；在 `with monkeypatch.context() as local:` 内 `local.setenv(...)` 后 `importlib.reload(config)`，断言读到环境值，`finally` 中再 `importlib.reload(config)` 恢复，不使用 `monkeypatch.undo()`；断言中不出现任何实际凭据值。
- Coverage note: `AppConfig` 属性在导入时求值，覆写断言必须用局部 `monkeypatch.context()`，否则 `monkeypatch.undo()` 会连同共享 fixture 注入的 patch（如 fake docker client）一起撤销；"SPEC 不记录实际凭据值"以"不断言具体值"体现。
