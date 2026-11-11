# Tasks

## 1. 构建版本消费

- [x] 1.1 验证 Node 按 Ctrl 下发的准确标签查缓存，旧标签不替代新配方；通过模拟 Docker 的新旧标签构建和重复复用测试核验，并同步容器创建规格。

## 2. 整体验证

- [x] 2.1 完成 Node 无 Docker 测试及 OpenSpec 严格校验，核实旧镜像和已有容器不受新版本构建影响。

## Workflow follow-up

- 将 delta 吸收进主规格并归档，遵守仓库 hook 提交。
