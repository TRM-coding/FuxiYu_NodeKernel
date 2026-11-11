# Design

## Context

`create_container` 先把 `NODE_CONTAINERS_BASE` 和 `restore_mount_path` 分别 realpath 规范化，再允许 `mount_norm == base_norm`，随后才检查 `containers` 段与目录存在（`services/container_service.py:284-300`）。当公共根自身含 `containers` 段时，等于根的历史路径会穿过现有门禁。

## Goals / Non-Goals

**Goals:**

- 只增加“realpath 后恰好等于当前公共根即拒绝”的一处等值判断。
- 普通恢复继续使用请求携带的历史单容器目录，既有越界、`containers` 段、目录存在和同名拒绝行为不变。
- 用两个最小源路径测试覆盖：参数化 `test_restore_mount_base_itself_is_rejected` 验证根等值、realpath 别名等值、历史目录后来成为公共根；`test_restore_valid_historical_subdir_still_recovers` 验证有效历史子目录仍可恢复且不按新名建目录。

**Non-Goals:**

- 不修改表结构、API、Docker 创建参数或 Ctrl/Web/Global。
- 不新增通用路径框架，不按新容器名推导历史路径，不改动其他路径校验。
- 不默认拒绝所有旧挂载，也不把旧挂载改写成新目录。

## Decisions

1. 在现有 `base_norm` / `mount_norm` 计算之后、越界和 `containers` 段检查之前，增加显式 `mount_norm == base_norm` 拒绝。这样复用同一套 realpath 规范化，尾随分隔符、`.` 和指向同根的 symlink 别名都会被识别。
2. 使用独立的错误信息，而不是把等值并入“outside containers base”；等值不是越界，独立信息便于测试断言，也避免改变既有越界错误语义。错误文本固定包含稳定子串 `restore mount path equals containers base`，其他越界/缺段/不存在文案不变。
3. 测试不新建生产路径：参数化拒绝用例断言 `containers.run_calls == []` 和按新名可能推导的目录不存在；`test_restore_valid_historical_subdir_still_recovers` 只复用已存在的历史子目录，断言只调用一次 Docker create、挂载 Source 与该目录 samefile，且不按新名建目录。

## Risks / Trade-offs

- 仅比较规范化字符串，不新增大小写归一或其他平台规则；这是对现有门禁的最小补充，不扩大路径语义。
- 正常数据库中历史路径是单容器子目录，新增判断不会影响正常恢复；只有路径确实等于当前公共根时才拒绝。
