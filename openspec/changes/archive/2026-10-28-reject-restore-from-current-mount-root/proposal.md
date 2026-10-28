# Proposal

## Why

`restore_mount_path` 的 realpath 恰好等于当前 `NODE_CONTAINERS_BASE` 时，现有门禁把公共根也当作合法恢复源；当旧的单容器目录后来被配置成新的公共根时，这会把共享根挂入容器，而不是沿用该容器的历史目录。需要只收紧这一处等值边界。

## What Changes

- 恢复源经 realpath 规范化后，若恰好等于当前 `NODE_CONTAINERS_BASE`，本次创建 SHALL 拒绝。
- 普通恢复继续使用请求携带的历史单容器目录，保留既有越界、`containers` 段和目录存在检查，不按本次容器名推导路径。
- 在既有 `tests/test_anvil_creation_credentials.py` 中新增两个测试：参数化的 `test_restore_mount_base_itself_is_rejected` 覆盖根等值、realpath 别名等值和历史目录后来成为公共根；`test_restore_valid_historical_subdir_still_recovers` 覆盖有效历史子目录仍可恢复。两者都断言不创建按新名推导的目录，拒绝分支还断言不调用 Docker create。
- 不改变表结构、API 契约、其他路径逻辑、Ctrl/Web/Global 仓库或归档历史。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--container-creation`: 明确恢复源 realpath 不得等于当前公共挂载根，同时保留历史单容器目录的正常恢复。

## Impact

仅影响 Node 的 `services/container_service.py` 恢复挂载校验及其最小回归测试；不新增依赖，不影响正常历史子目录恢复或接口形状。
