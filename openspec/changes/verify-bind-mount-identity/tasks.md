# Tasks

## 1. 路径核对与业务路径纠正

- [ ] 1.1 用 Docker `/root` bind Source 与运行/暂停容器 `/proc/<pid>/root/root` 的实际目录对象做内部路径核对；`(st_dev, st_ino)` 仅用于本次定位和调试，不进入 HTTP/WSS 业务身份字段。用 Source 一致、错位、Source 改名后原路径缺失但 actual 可读、目录替换、proc 不可读、无 PID、paused 和 Docker 明确 no_bind 测试验证 `resolved/unresolved/not_running/no_bind`。
- [ ] 1.2 实现有界候选定位：只检查 `NODE_CONTAINERS_BASE` 带 `containers` 段的 Source 父目录直接子项、最后确认路径父目录直接子项及已有业务路径；Source 缺失时仍用最后确认/已有路径的允许父目录作为起点，不递归、不遍历 symlink 目录、不返回 `/proc` 路径。用 Source 改名后新路径唯一、唯一匹配、多个匹配、无匹配、候选越界和全盘目录不被访问的测试验证只有唯一匹配才修正 `bind_mount_path`。
- [ ] 1.3 只有 actual 不可读、允许范围内无可命名路径、无匹配/歧义或 proc 不可读时才标 `unresolved`；Source 缺失本身不得直接 unresolved。无法唯一确认时保留原有/最后确认业务路径，无已有路径则 null；不猜目录、不改目录/Docker 配置/不重挂载。用 Source 改名唯一新路径、无候选、unlink、inspect 失败和竞争更新的测试验证。
- [ ] 1.4 增加 `configured_mount_path`、`mount_path_status`、`mount_path_observed_at` 的模型和采集；用 UTC 时间格式、默认 unresolved、旧 Node 缺字段、null round-trip 测试验证诊断字段不是业务路径、不是测量时间。
- [ ] 1.5 路径核对发布前在 Node 内部复核当前活跃容器/Docker ID/PID 与路径核对序号；旧定位晚回丢弃，不得改写新对象/新活跃容器路径。用容器换代、路径核对晚回、并发更新测试验证；该 token 只保护路径纠正，不参与采样/测量/业务门禁。
- [ ] 1.6 明确 no_bind 契约：Docker 成功确认无 bind 时 `bind_mount_path=null`、`measurement_mount_path=null`、overlay-only；unresolved/not_running/不可读不得清空既有路径。用 no_bind、inspect 失败、unresolved 保留路径的测试验证。

## 2. 按业务路径测量与缓存

- [ ] 2.1 将 bind du 改为按当前业务 `bind_mount_path` 执行，并在 `measurement_mount_path` 记录实际路径；bind 缓存按规范化业务路径为键，不按 inode/PID/旧身份命中。用路径 A→B、旧 A 的 du 晚返回、B 重新测量、同名路径重建的受控交错验证旧字节数不会改贴 B。
- [ ] 2.2 路径变更时使旧路径测量失效并触发新测量；`measurement_mount_path` 与当前 `bind_mount_path` 不一致时 total 为空。用路径修正、回退、unresolved 保留旧路径、Source 改名后新路径唯一、no_bind 置空 bind/measurement 路径且 overlay-only、重新测量完成前后的测试验证 total 只跟随当前路径。
- [ ] 2.3 保留真实 `measured_at`（组成中较早完成时间）、`collector_epoch`、`observation_seq` 和 `measurement_status`；同 epoch 旧序号/旧连接被拒绝，同序号只作心跳，Node 重启换 epoch 且旧字节数不复用。用乱序、重复样本、重启和假时钟测试验证测量时间不被接收/发送时间刷新。
- [ ] 2.4 保留独立测量失败语义：非零 du（即使 stdout 有数字）、空/不可解析输出、超时、权限、路径不存在和缺组成均不得当 0 或成功；最后成功值只作诊断。用每类失败测试验证 `measurement_status=error/stale/unverified` 与 `total_bytes=None`，不把路径诊断 unresolved 改写成 measurement_error。

## 3. 线路、Ctrl 持久化与业务边界

- [ ] 3.1 重写 `ContainerDiskUsage` delta 与实现计划：保留 `disk_protocol_version=1`、`collector_epoch`、`observation_seq`、`measurement_status`、`measured_at`、`measurement_mount_path`、`measurement_reason`、路径诊断和既有 bytes 字段；删除 `bind_identity`、`measurement_identity`、`docker_id` 等磁盘身份字段。用模型字段总表、旧负载缺省、JSON round-trip 和 HTTP/WSS 共用测试验证。
- [ ] 3.2 更新 WSS `disk_usage` 快照：携带业务路径/configured 路径/路径状态/核对时间/测量路径/测量状态/真实测量时间，不携带目录身份；`mount_path_status` 不参与 total 有效性。用 unresolved+已有路径+有效测量、路径变更旧样本失效、旧 Node 缺 measured_at 标 unverified、无 identity 字段的帧测试验证。
- [ ] 3.3 对齐 Ctrl 持久化计划：`disk_measurement_status`、`disk_measured_at`、`disk_received_at`、`disk_observation` 保存协议/会话排序/测量路径/路径诊断；移除 `disk_identity_status`、`disk_identity_checked_at`、`disk_identity`。用隔离 fixture 验证仅当前认证机器/活跃容器中 `mount_path_status=resolved` 的修正写入 `containers.bind_mount_path`；no_bind 清空当前活跃业务 bind 路径（不保留旧路径再判同路径）；unresolved/not_running 不清空；不凭 inode 批改历史快照/旧清理记录，固定 8 字段 long_term_eligibility 不变。
- [ ] 3.4 验证诊断不门禁：`mount_path_status`、`configured_mount_path`、`mount_path_observed_at` 不作为恢复、长期资格、冻结、删除、清理或测量有效性前置；已存在有效业务 mount_path 且本次测量成功时 unresolved 不阻断业务；路径不存在/du 实际失败仍按原测量错误处理。用业务资格/处置契约回放和独立失败用例验证。

## 4. 受控回归、Q72 与部署边界

- [ ] 4.1 建立可注入屏障的真实交错测试：Docker inspect、Source/actual 读取、候选枚举、du 启动/返回、路径更新、缓存回填、WSS 读取和消费方处理之间设 barrier；覆盖 daity 等价错位、Source 改名后原路径缺失但新路径唯一、候选歧义、proc 不可读、no PID、no_bind、路径 A→B 与在途 du、旧路径核对晚回。用交错日志验证稳定复现，不靠 sleep。
- [ ] 4.2 保留 Q72 联合验收：采集盲区不额外补偿、累计继续；异常/无效测量不删除、不新增顺延；恢复可信高用量按原累计有效冻结天数判断；机器不可用 deferral 与人工宽限保留；不新增 `review_required` 阻挡；固定 8 字段 long_term_eligibility 不变。用隔离策略回放验证路径诊断不改变 Q72 判断。
- [ ] 4.3 验证 mixed-version 与拆分边界：旧 Node 缺 measured_at/measurement_mount_path 按测量未验证，不能说成缺目录身份；旧 Ctrl 忽略新字段/移除 identity 门禁后不要求 resolved；新 Node 不要求 Ctrl 新身份列。用字段缺失、旧快照、回滚和 WSS 重连测试验证。
- [ ] 4.4 核对部署/回滚与协议收窄：Node 路径核对/测量先行或与 Ctrl 字段变更同批，Ctrl 只持久化 `mount_path_status=resolved` 的修正；回滚 Node 不回落旧字节数执行删除，保留正式 specs/archive 不动。用发布清单、字段版本检查和隔离回滚演练验证；不修改 guard 的 runtime DockerID/ready_identity/action_ref/对象防旧写；不新增 Node restore preflight/API/门禁。

## Workflow follow-up

- Q72 已由用户决定：异常期不新增顺延，恢复可信高用量按原累计有效冻结天数判断；机器不可用 deferral 与人工宽限保留，无 `review_required` 阻挡。
- Q70 的跨进程删除授权不由本变更提供；路径纠正、inode/PID 和路径诊断不得作为删除/清理授权。
- 本阶段只完成待执行变更提案，不修改正式 specs/archive、不写业务代码、不 SSH/生产、不 commit/push。
