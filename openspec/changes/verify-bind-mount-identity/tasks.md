# Tasks

## 1. 身份探测与协议

- [ ] 1.1 增加 Source/actual dev+inode、Docker ID、PID starttime、boot/collector epoch 的本机探测；用同对象、不同设备同 inode、目录替换、proc 不可读、PID 复用及 paused/stopped 测试验证各状态。设备号、inode、starttime 以十进制字符串上报，附 version 1 字段说明和 JSON 大整数用例。
- [ ] 1.2 独立运行轻量探测并为观测设置最大年龄；用假时钟和阻塞探测验证重型用量 TTL 内能发现错位、探测不执行 du、du 阻塞不阻止探测、线程停滞会显式过期、WSS 读侧不执行 du，并记录批量容器探测的负载边界。
- [ ] 1.3 为 HTTP/WSS 共用磁盘模型增加 version 1 身份、测量资格、时间和发布序号；用 JSON round-trip 测试验证大于 2^53 的 inode/starttime 无损、无 bind 明确、旧负载缺字段为未验证、重复发送不刷新测量时间，补兼容文档。
- [ ] 1.4 校验 `ContainerDiskUsage` 模型 delta 与 design.md 字段总表一致：嵌套 `bind_identity`/`measurement_identity`、缺省 None、HTTP/WSS 共用、Ctrl 持久化列名与线路名映射；不随意改 `disk_protocol_version` 等协议名。

## 2. 扫描与缓存

- [ ] 2.1 在隔离 Linux 临时目录/命名空间验证 FD 传递和 du 对已固定目录的遍历；覆盖 rename/路径替换、嵌套挂载、权限失败、rc 非零和超时，确认测量入口后实现身份感知缓存，不能只测 fstat 而未验证 du。
- [ ] 2.2 为后台任务增加 generation 与缓存回填检查；用在途扫描遇到同名重建、重启、A→B→A、旧线程晚回填的受控交错验证旧 bytes 不会绑定新身份，及时释放 FD 和线程资源；缓存键同时包含 Docker ID、PID starttime、boot ID、collector epoch 和 generation。
- [ ] 2.3 检查 du 的退出码、输出和超时，保留最后数值仅作诊断；用 rc 非零有 stdout、空输出、解析失败和超时测试验证 total 不会伪有效，并说明 apparent-size 与持续写入限制。
- [ ] 2.4 新扫描完成后及时组装容器用量，保留各组成时间并按较早时间判龄；用假时钟验证不再等下一轮 sweep、测量时间与身份观测时间分离、身份恢复匹配时必须重新测量、超龄样本显式 stale。

## 3. 两端联合验收

- [ ] 3.1 与 Ctrl `gate-disk-check-on-mount-identity` 联合回放 daity 等价的目录替换、缓存恢复、WSS 重发和连接重建；验证 mismatch/unknown/过期不驱动冻结/重置/删除，不自动改目录，新测量后正常响应，记录安全套件及模拟证据。
- [ ] 3.2 按 Q72 做联合验收：异常期不动作、不新增顺延，恢复可信高用量按原累计有效冻结天数可立即升级，恢复低用量正常重置；机器不可用 deferral 与人工宽限保留，没有 `review_required` 阻挡。
- [ ] 3.3 核对部署/回滚矩阵与诊断输出：Ctrl 先部署、Node 逐机升级、旧 Node 保持未验证；用隔离环境验证字段缺失和版本回退行为，输出未验证覆盖率检查步骤。
- [ ] 3.4 核对 Q70 独立性：磁盘身份/generation 匹配不能作为跨进程删除或清理授权；记录 Q71 后续扩展边界（实际对象计量后可冻结但清理须阻断），首版不实现该扩展。

## Workflow follow-up

- Q71 的实际对象计量及错位时允许冻结是后续策略扩展；首版采用错位时停止磁盘自动处置，清理必须阻断且仅后续待选。
- Q72 已由用户决定：异常期不新增顺延，恢复可信高用量按原累计有效冻结天数判断；机器不可用 deferral 与人工宽限保留，无 `review_required` 阻挡。
- 本变更只建立磁盘采样证据，不替代 Q70 的跨进程操作代际协议，也不宣称清理路径具有原子对象身份保证。
