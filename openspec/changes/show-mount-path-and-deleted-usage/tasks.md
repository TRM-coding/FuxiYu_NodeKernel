# Tasks

## 1. 线路模型与端点

- [ ] 1.1 在 `schemas/container.py` 增加 `CheckMountUsageConfig`、`CheckMountUsageMessage`、`MountUsageItem`、`CheckMountUsageResponse`，并从 `schemas/__init__.py` 导出；用模型测试验证 `mount_paths` 为 1～100、可选字段可为 null、响应只含 `path/bytes/measured_at/pending/error`。
- [ ] 1.2 在 `network/api.py` 增加 `POST /api/check_mount_usage`，经 `services/container_service.py` 薄桥接调用缓存；用 TestClient 验证合法批次返回 HTTP 200、`success=1`、逐项状态与请求等长同序，空数组/101 项返回 422 且未触发测量，内部异常返回 500 且无部分伪造结果。

## 2. 路径校验与结果投影

- [ ] 2.1 在 `DiskUsageCache` 增加独立路径校验：绝对路径、最终对象非 symlink、存在目录、`realpath` 位于 `NODE_CONTAINERS_BASE` 内且含大小写不敏感的 `containers` 段；用 tmp 目录测试覆盖合法路径、越界、相对路径、缺段、普通文件、symlink、不存在和权限失败，并断言 `invalid_path`/`not_found`/`permission_denied` 不启动 du。
- [ ] 2.2 增加按路径读取/调度方法，按成功、pending、错误投影 `bytes/measured_at/pending/error`；用可控假时钟和假 du 验证 TTL 内返回原始测量时间、过期/无样本返回 pending、失败不写 0、不把最后成功值伪装成当前成功。

## 3. 有界后台测量与清理检查

- [ ] 3.1 为端点增加去重后的 singleflight 和固定 4 个测量 worker；用并发 barrier/调用计数验证同规范化路径只起一次 du、重复路径逐项回显不少项、100 条批次同时运行的 du 不超过 4 且 HTTP 立即返回 pending。
- [ ] 3.2 实现 600 秒 du 超时不阻塞请求、失败后 60 秒冷却和稳定错误映射；用假 du 的 timeout/非零退出/空输出/不可解析输出/权限失败验证错误字段，并验证冷却内不重复起 du、冷却后才允许重试。
- [ ] 3.3 在每次读缓存前检查目录存在性，清理/不存在时移除缓存并返回 `not_found`，用进程内单调 request id 丢弃晚到 du；用“缓存命中后删除目录”“测量期间删除目录”“旧结果晚到”测试验证不返回旧成功值，且 `clean_mount` 未修改。

## 4. 只读与兼容边界

- [ ] 4.1 核对实现只更新 Node 进程内路径缓存和执行器：不写数据库/已删 `disk_*`/快照/清理记录，不调用 `clean_mount`、Docker inspect、`verify_mount_path` 或 `/proc`；用 monkeypatch 调用记录和 WSS 帧计数验证查询不产生新 topic、字段、推送或清理副作用。
- [ ] 4.2 核对未新增 machine 角色/用户角色门禁、未改 `check_disk_usage`/`ContainerDiskUsage`/详情接口，且端点沿用既有 mTLS 控制通道；用现有 API 回归测试和字段总表验证旧 Ctrl 不调用时行为不变，旧 Node 无端点时仍为 404/405 供 Ctrl 降级。

## 5. 集成检查

- [ ] 5.1 运行本变更定向测试（模型、路径、缓存、并发、清理、端点、既有 clean/磁盘回归），确认全部通过；不重跑无关业务全量测试。
- [ ] 5.2 运行 `openspec validate show-mount-path-and-deleted-usage --strict`、`openspec status --change show-mount-path-and-deleted-usage --json`（四个 artifact 均 done）和 `git diff --check`；检查 diff 仅涉及 Node 端点/模型/缓存/服务桥及测试，不含正式 specs、archive、数据库迁移、WSS 协议或 `clean_mount` 改动。

## Workflow follow-up

- 本提案阶段只写规划文档，不实现、不运行上述业务测试、不 commit/push、不 SSH/部署。
- 归档需在实现、评审和单独授权后另行执行；本变更不修改任何正式 spec 或 archive。
