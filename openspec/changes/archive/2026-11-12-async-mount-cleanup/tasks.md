# Tasks

## 1. 清理核心与线路

- [x] 1.1 实现共享路径规范化、进程内路径互斥登记与有界任务记录（任务 id、单向终态、活动不淘汰、终态 64 条/600 秒），并补 `tests/test_mount_cleanup.py` 的别名、并发、终态释放、淘汰、重启与机器隔离测试；覆盖 `backend--storage-and-mounts / Node 权威路径规范化与原子互斥` 和 `进程内有界任务状态与重启语义`。
- [x] 1.2 增加 start/status 请求响应模型与 `/api/start_clean_mount`、`/api/get_clean_mount_status` 路由，落实 `success=1` 仅表示受理/查询成功、409/400/404/500 稳定原因与不泄漏 stderr；用 `tests/test_mount_cleanup.py` 覆盖线路、错误、未知任务和字段集合。
- [x] 1.3 在 `extensions.py` 注册进程级任务管理器并在应用 lifespan 中接入启动/关闭生命周期；验证测试中重复导入与 TestClient 生命周期不产生跨实例共享任务。

## 2. 异步删除与子进程

- [x] 2.1 实现 `services/mount_modules/cleanup_launcher.py` 的 Linux 父死亡 launcher 与可注入 `rm_path`：`PR_SET_PDEATHSIG`、设置后父 PID 校验、参数数组执行 `rm -rf`、捕获有界 stderr、无固定超时；补 `tests/test_mount_cleanup_process.py` 的成功、非零、慢删除不截断、spawn/exec 异常和启动失败回滚测试。
- [x] 2.2 实现后台 worker 与任务终态收尾：仅退出码 0 成功、非零 `rm_failed`、异常 `internal_error`，路径占用在 finally 释放；测试覆盖 `backend--storage-and-mounts / 异步删除子进程与关闭生命周期` 的成功/失败/部分删除场景。
- [x] 2.3 实现正常关闭：停止受理、终止并回收所有 launcher/rm、运行任务落 `failed`/`shutdown`、拒绝新登记；用 `tests/test_mount_cleanup_process.py` 和 TestClient lifespan 测试验证。
- [x] 2.4 增加 Linux 专用 `tests/test_mount_cleanup_linux_parent_death.py`：用真实子 Node 进程、注入的阻塞假 `rm` 和 `SIGKILL` 断言子进程不存在或为僵尸、sentinel 未被删除；父 PID 不匹配时 launcher 在 exec 前退出。非 Linux skip，不查询强杀后进程内任务状态。

## 3. 旧同步端点兼容

- [x] 3.1 将 `clean_mount` 接入同一路径锁和 launcher，保留旧同步语义、30 秒超时、参数数组、stderr 上界与失败不假成功；与活动异步/恢复冲突返回 409 且不删除。
- [x] 3.2 迁移 `tests/test_clean_mount.py` 到 launcher/`rm_path` 接缝，保留 30 秒、参数、stderr 和路径拒绝断言；补 `tests/test_mount_cleanup_sync_compat.py` 的旧成功/错误/409/两个同步请求只删除一次测试。
- [x] 3.3 验证旧客户端同步形状、`error_reason=="internal_error"`、`timeout`/`invalid_path` 稳定原因，以及当前 Ctrl 三类清理所需异步端点仍与旧端点为并存关系；按 `backend--storage-and-mounts / 旧同步清理与旧客户端兼容` 记录跨仓边界。

## 4. 恢复与清理原子互斥

- [x] 4.1 在创建受理前实现 `restore_mount_path` 共享规范化、存在性校验、锁内占用检查与恢复预留；失败返回 400/409、不启动后台或 Docker、无残留预留。测试覆盖 `backend--container-creation / 恢复创建的原子校验与路径预登记`。
- [x] 4.2 将预检规范化路径传入后台 `create_container`，保留服务层既有 realpath/base/`containers`/存在性校验；预留覆盖镜像构建到恢复账号重建，成功/失败 finally 释放。补 `tests/test_mount_cleanup_restore.py` 的串行、并发和关键阶段测试。
- [x] 4.3 补重启恢复边界测试：清理中断留下现存部分目录后，新登记器可重新登记恢复预留并受理，不依赖旧 task/预留；覆盖 `部分删除目录在重启后可恢复`。

## 5. 回归与收尾

- [x] 5.1 运行聚焦套件 `python -m pytest tests/test_mount_cleanup.py tests/test_mount_cleanup_process.py tests/test_mount_cleanup_linux_parent_death.py tests/test_mount_cleanup_sync_compat.py tests/test_mount_cleanup_restore.py -q`（Linux 父死亡用例在非 Linux 按计划 skip），修复实现问题。
- [x] 5.2 运行既有清理/创建/API 回归（至少 `tests/test_clean_mount.py tests/test_blueprint_api.py tests/test_create_container.py tests/test_anvil_creation_credentials.py`），确认旧端点兼容与恢复受理变化均有断言。
- [x] 5.3 运行 `openspec validate async-mount-cleanup --strict` 与 `git diff --check`，确认仅 Node 实现/测试和本 change 工件变化；不修改已批准 test-plan，不提交、不推送。

## Workflow follow-up

- 实现完成后按官方 `openspec-verify-change` 工作流验证；不创建 Anvil verify 工件。
- 本次不归档、不提交、不推送。
