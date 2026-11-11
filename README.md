# 伏羲 · Fuxi-Yu

Fuxi-Yu 是面向高校与实验室算力管理场景的容器化平台。NodeKernel 是伏羲平台的节点服务，部署在算力机器上，负责镜像构建、容器生命周期、协作者账号、挂载清理与运行状态采集。

当前版本使用 FastAPI 提供 HTTPS 操作接口，使用 Docker 执行容器操作。Ctrl 主动连接 Node 的 `/ws/ctrl` 获取状态快照，Node 无需配置 Ctrl 的地址。

## 快速上手

### 1. 安装依赖

节点运行环境为 Linux，需要可访问的 Docker daemon。运行用户须有 Docker 操作权限及容器挂载目录的读写权限；本地开发可使用 WSL。

在仓库根目录安装 Python 依赖：

```bash
pip install -r requirements.txt
```

### 2. 配置环境

可参考 `.env.example` 创建 `.env`。常用配置：

```bash
NODE_PORT=5789
NODE_CTRL_CA_FILE=certs/ctrl_ca.pem
NODE_CONTAINERS_BASE=/home
```

`NODE_CONTAINERS_BASE` 是容器数据挂载根目录。非 root 开发环境需改为可写路径。容器宿主端口默认从 20000–29999 分配，可通过 `NODE_PORT_RANGE_START` 和 `NODE_PORT_RANGE_END` 调整；防火墙应放行实际使用的范围。

镜像构建需要代理时，在 `.env` 中设置 `HTTP_PROXY` / `HTTPS_PROXY`。环境配置在启动时加载，修改后需重启服务。

### 3. 配置节点信任

将 Ctrl 的 CA 公共证书放到 `NODE_CTRL_CA_FILE` 指定位置。该文件用于验证 Ctrl 客户端证书，启动时找到有效信任文件后会启用双向 TLS 校验。

Node 默认使用 `certs/node_cert.pem` 与 `certs/node_key.pem`，启动时按实现生成或校验默认自签证书；自备证书可通过 `NODE_TLS_CERT_FILE` / `NODE_TLS_KEY_FILE` 指定。

节点在 Ctrl 注册后接收持久化 uid，默认保存到 `.node_identity.json`。Ctrl 负责后续连接与重连。

### 4. 启动服务

```bash
python run.py
```

默认监听地址：

```text
https://0.0.0.0:5789
```

在 Ctrl 的机器管理中填写该节点的实际 IP 与端口。HTTPS 操作接口和 WSS 快照端点共用同一监听端口。

Swagger 文档路径为 `/docs`；启用双向 TLS 后，访问客户端也需携带受信任的证书。

### 5. 运行测试

默认测试排除需要真实 Docker daemon 的集成用例：

```bash
pip install pytest
pytest
```

需要验证真实 Docker 链路时，再单独运行：

```bash
pytest -m docker
```

测试以 Linux 环境为准，包含 POSIX 路径与命令假设；Windows 本地验证可在 WSL 中执行。

## 目录结构

```text
network/             # FastAPI 操作接口、节点身份与 WSS 快照
schemas/             # 请求、响应及公共类型
services/            # 镜像、容器、账号与挂载操作
docker_operates/      # Docker 状态采集、缓存与端口分配
utils/               # 日志及通用工具
tests/               # 单元测试与 Docker 集成测试
openspec/specs/      # 按 8 个能力单元组织的行为与类型契约
config.py            # 网络、端口及运行配置
extensions.py        # Docker 客户端与采集缓存
run.py               # HTTPS 启动入口
```

## 开发约定

接口层负责请求校验与响应转换，业务操作放在 services 层，Docker 采集与缓存逻辑放在 docker_operates 中。身份由 Ctrl 颁发，节点状态由 Node 采集；修改操作或快照字段时，应同时核对 Ctrl 的消费契约。

当前行为与完整类型契约见 [OpenSpec](openspec/specs/)。跨仓库已知问题统一记录在 [Global QUESTIONS](../FuxiYu_Global/QUESTIONS.md)，旧文档保留在 Global 的 bak 中。
