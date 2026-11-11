"""本机代理配置：构建期 Dockerfile 注入与运行期容器环境。

代理是机器的事实（同一份模板，有的机器要代理、有的直连正常），来源统一为
Node 进程环境变量；本模块只做读取、过滤和命令/文本生成，不访问 Docker。
"""
import os


# 代理注入（构建期与运行期）只取这两个键；读的时候大小写都认，写出去统一成小写。
#
# ⚠ **刻意不含 `no_proxy`**：它进到构建里几乎只会帮倒忙。实测（2026-09）：某台机器上
# `archive.ubuntu.com` 解析到内网地址，而 `NO_PROXY` 里写着 `10.0.0.0/8,192.168.0.0/16`
# ——于是 apt 绕开代理直连，被校园网拦下，报的却是 `Clearsigned file isn't valid, got
# 'NOSPLIT'`，一路查不出原因。构建里的请求本来就该走代理出去；真要放行某个内部地址，
# 在模板的 dockerfile_body 里显式写 `ENV no_proxy=...`，别让进程级的 NO_PROXY 偷偷生效。
# 运行期同理：容器里的请求也该走代理出去，理由和踩过的坑是同一个。
_PROXY_ENV_KEYS = ("http_proxy", "https_proxy")


def _clean_proxy_value(value: str) -> str:
    """只接受干净的代理 URL——它要被**直接拼进 Dockerfile 文本**，所以必须挡掉
    空格、换行、引号、反引号、`$` 这些能在 Dockerfile 里变出第二条指令的字符。"""
    value = (value or "").strip()
    if value.startswith(("http://", "https://")) and not any(
        c in value for c in " \t\n\r'\"`$"
    ):
        return value
    return ""


def _inject_build_proxy(dockerfile_text: str) -> str:
    """把本机配置的代理以 `ARG` 形式写进 `FROM` 之后；没配就**原样返回**。

    ★ 为什么不用 docker-py 的 `buildargs`：源码里可查——它把参数塞进 **URL 的 query**
    （`params.update({'buildargs': json.dumps(buildargs)})`），而 CLI / BuildKit 走的是
    **body**。某些 daemon 的构建路径不读 query，于是出现"手动 `docker build --build-arg`
    就通、平台走 SDK 就不通"，而且两侧日志长得一模一样，差异完全不可见（2026-09 实测，
    为此绕了很久）。`use_config_proxy=True` 走的是同一条 query 路径，同样不可靠。

    ★ 为什么是 `ARG` 而不是 `ENV`：`ARG` 只在构建期存在，**不落进运行中的容器**
    （实测：构建完 `docker run … echo $http_proxy` 是空的）。`ENV` 会把代理地址烤进
    每一个容器——代理是构建期的环境，不是镜像的内容。

    ★ 为什么由 Node 注入：**代理是机器的事实**（同一份模板，有的机器要代理、有的直连正常），
    而 Ctrl 的设置是全局的。放本机 .env 里，一台机器一个样，不会波及别的机器。

    ★ 位置只能是 `FROM` 之后：Dockerfile 里 `FROM` 之前只允许注释与 `ARG`，做不了别的；
    而注入的 ARG 必须赶在平台注入段那次 `apt-get` 之前生效。
    """
    args = []
    for name in _PROXY_ENV_KEYS:
        value = _clean_proxy_value(
            os.environ.get(name) or os.environ.get(name.upper()) or ""
        )
        if value:
            args.append(f"ARG {name}={value}")
    if not args:
        return dockerfile_text

    snippet = (
        "# fuxi: 本机构建代理（见 docker_operates.proxy_config._inject_build_proxy）\n"
        + "\n".join(args)
    )
    lines = dockerfile_text.splitlines()
    for idx, line in enumerate(lines):
        if line.strip().upper().startswith("FROM "):
            lines.insert(idx + 1, snippet)
            return "\n".join(lines)
    return dockerfile_text


def _runtime_proxy_env() -> dict[str, str]:
    """本机给**容器内**用的代理环境变量（大小写各一份）；没配就是空 dict。

    与构建期同一个来源（Node 进程的 .env）——代理是机器的事实。两处的差别只在
    "送到哪里"：构建期写进 Dockerfile 的 `ARG`，运行期写进容器。

    ★ 为什么运行期也得给：学生 SSH 进去之后的 apt / pip / git / curl 出外网走的就是它。
    2026-09 学生报"容器内网络不通"，根因就是这段在 create_container 瘦身时跟着
    "容器内装 sshd"一起被删掉了（38de262）——那段注入不只服务于装包，它同时是
    容器出外网的唯一入口。
    """
    env: dict[str, str] = {}
    for name in _PROXY_ENV_KEYS:
        value = _clean_proxy_value(
            os.environ.get(name) or os.environ.get(name.upper()) or ""
        )
        if value:
            env[name] = value
            env[name.upper()] = value
    return env


def _runtime_proxy_setup_command(proxy_env: dict[str, str]) -> str:
    """把代理落到容器文件系统：`/etc/environment`（SSH 会话靠 PAM 读它）+ apt 配置。

    ★ 为什么非写 `/etc/environment` 不可：`docker run -e` 那套环境变量**进不了 SSH 会话**
    ——sshd 会清空环境另起一套，只从 PAM（`pam_env` 读 `/etc/environment`）等来源取值。
    学生是 SSH 进去用的，这个文件才是他们真正吃到代理的地方（两边都写：`-e` 覆盖
    容器主进程与 `docker exec`，`/etc/environment` 覆盖 SSH 会话）。

    ★ 为什么是**合并**而不是覆盖：旧实现用 `>` 直接覆盖，会把镜像自带的 PATH 一起干掉
    ——2026-09 在学生的容器里实测看到 `/etc/environment` 只剩一行 PATH，那行是镜像的；
    覆盖式写入会让 SSH 会话连 PATH 都没有。这里先删掉自己写的代理行再追加，幂等。

    ★ apt 配置只在 apt 系镜像上写（`/etc/apt/apt.conf.d` 存在时），其它基底不塞垃圾文件。
    """
    lines = "".join(f"{key}={value}\\n" for key, value in proxy_env.items())
    http_url = proxy_env.get("http_proxy") or proxy_env.get("https_proxy") or ""
    apt = ""
    if http_url:
        apt = (
            "if [ -d /etc/apt/apt.conf.d ]; then "
            f"printf 'Acquire::http::Proxy \"{http_url}\";\\n"
            f"Acquire::https::Proxy \"{http_url}\";\\n' > /etc/apt/apt.conf.d/99proxy; "
            "fi"
        )
    return (
        "touch /etc/environment; "
        "sed -i -E '/^[[:space:]]*(http_proxy|https_proxy|HTTP_PROXY|HTTPS_PROXY)=/d' "
        "/etc/environment; "
        f"printf '{lines}' >> /etc/environment; "
        + apt
    )
