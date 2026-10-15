# Proposal

## Why

Ctrl 修正模板与平台注入的版本换代后，需要将“不同配方使用不同标签、同标签命中才复用”落实到 Node 的可验证消费契约，避免仅在 Ctrl 断言标签变化而漏检真正的构建入口。

## What Changes

- 用隔离 Docker 替身验证旧标签存在时，新版本标签仍触发新配方构建。
- 验证新标签构建后再次派发可复用，旧版本制品和已有容器不被清理或改写。
- 保持 Node 不推导 Ctrl 归属或版本、不依派发历史跳过本机缓存查验的职责。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--container-creation`: Ctrl 配方换代与本机镜像缓存复用的跨端契约。

## Impact

影响构建缓存的隔离测试与创建能力规格；沿用现有构建字段和本机标签查验，不要求真实 Docker 环境即可验证消费链路。
