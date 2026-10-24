# Design

## Context

Node 现有 build_image 先查 Ctrl 指定标签，未命中再用最终 Dockerfile 构建。Ctrl 修复版本生成后，消费端需要证明确实不会因为同模板旧标签存在而错误复用。

## Goals / Non-Goals

**Goals:** 用假 Docker 验证旧版本存在、新版本构建、再次命中及旧制品保留，测试实际 build_image 入口。

**Non-Goals:** 不更改 Ctrl 资源身份，不增加 Node 侧版本推导，不访问真实 Docker/GPU 或修改宿主容器。

## Decisions

1. 沿用 image_tag 与 dockerfile_text 两个线路字段，标签查验保持由 Node 负责。
2. Docker 替身记录查验、构建标签与临时 Dockerfile，断言两份实际内容和版本的对应关系。
3. 若现有实现已满足消费契约，仅新增回归与规格场景，不为形成代码差异而重写构建逻辑。

## Risks / Trade-offs

- 替身通过不等于真实 Docker 构建通过 → 报告限定为消费契约与控制流验证，不声称运行了真实制品构建。
