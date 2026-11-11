# Tasks

## 1. 回归测试

- [x] 1.1 在 `tests/test_anvil_creation_credentials.py` 新增参数化 `test_restore_mount_base_itself_is_rejected` 和 `test_restore_valid_historical_subdir_still_recovers`，覆盖 `backend--container-creation` / `恢复挂载来源只由入参决定` 的 `恢复源等于当前公共根被拒绝` 与 `恢复沿用原目录` 场景；参数至少含真实根、`.` 别名、尾随分隔符、同根 symlink 和“历史目录后来设为公共根”，正常子目录测试断言 samefile、只创建一次且不按新名建目录。删除文件顶部“故意暂缓 Q75”的过时说明，并以 `pytest --collect-only` 确认两个测试可收集。
- [x] 1.2 在修复前用 WSL Python 运行 `test_restore_mount_base_itself_is_rejected`，把日志写到外部审计目录；确认退出码为非 0 且失败原因是根等值未被拒绝，不是 fixture、权限或 symlink 环境问题。

## 2. 等值门禁

- [x] 2.1 在 `services/container_service.py` 的 realpath 规范化之后增加唯一一处 `mount_norm == base_norm` 拒绝，消息固定含 `restore mount path equals containers base`；保持既有越界、`containers` 段、目录存在和同名拒绝逻辑不变。用 diff 核对只新增该 guard。
- [x] 2.2 用 WSL Python 运行两个新增测试和既有恢复相关测试，确认 `恢复源等于当前公共根被拒绝`、`恢复沿用原目录`、`改名不改变数据位置` 场景通过；symlink 参数必须实际执行，不允许 skip/xfail。
- [x] 2.3 用 WSL Python 分别运行 `tests/test_create_container.py` 与 `tests/test_anvil_creation_credentials.py` 整个文件，日志写入外部审计目录并记录明确退出码；两者均须为 0。
- [x] 2.4 核对实际测试断言后把 `test-plan.md` 中两个新增 locator 的 `[ ]` 更新为 `[X]`，随后运行 `openspec validate reject-restore-from-current-mount-root --strict`；不修改 Assertion scope、Coverage note、主 spec 或其他 artifact。

## Workflow follow-up

- 主 spec 同步、测试计划侧车和归档由父代理按已授权的完整工作流继续完成。
