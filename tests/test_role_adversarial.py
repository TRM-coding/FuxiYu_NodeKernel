"""update_role 对抗回归（只测试，不修复生产代码）。

覆盖面
======
- 真实 FastAPI + Pydantic：role 大小写/None/数组/对象、密码缺失/空/超长/冒号/
  CR/LF/NUL、非字符串密码、角色与密码字段组合。
- 注入名字：shell 元字符、路径穿越、NUL；以及 ``--help`` 这类会被 id/usermod/
  userdel 当成选项的前导连字符名字。
- 目标锁定：非 ROOT 角色把 ``user_name`` 指向共享 ``root`` 时不得改 root 密码或组。
- Docker 分步异常：exec_create/exec_start/exec_inspect 抛错、inspect 未知/非整数/
  Running=true、socket sendall/shutdown/recv 失败。
- 命令分步异常：用户探测失败、建号失败、密码写失败、管理组失败、ROOT 清理
  userdel/归档步骤失败。
- 确定性重复：旧 ROOT→ADMIN、目标→ROOT 的顺序重复多轮；第二步失败不回滚第一步；
  每轮 transcript 完全一致，响应/日志/argv 不带密码。

隔离与复现
==========
全部使用 ``tests/`` 既有 ``FakeContainers``/``PasswordFakeContainer`` 与
``tests/password_fakes.py`` 的 exec API；不替换 ``update_role`` 或
``_exec_chpasswd_stdin`` 等被测逻辑，只替换 Docker 边界。不连接 Docker daemon、
数据库或网络，不启动/停止服务，不读写仓库 ``.env``。日志写到运行命令指定的
``NODE_LOG_DIR``（外部 artifact 目录）。

固定语料标识 ``SEED``：20261024。测试本身不使用随机数，重复执行顺序固定。

预期失败的缺陷复现（故意保留 fail，不用 xfail/skip）
=====================================================
1. shell 元字符名字在请求边界返回 500（而非 400/422），且要先经过 Docker lookup；
2. ``user_name=--help`` 通过校验并被执行，ADMIN/ROOT 都可能返回 success=true；
3. 非 ROOT 角色以 ``user_name=root`` 为目标时，ADMIN 带 password 会写共享 root
   密码，ADMIN/COLLABORATOR 会改 root 组。
这些断言按规格/安全性质写成期望值；实际行为见运行报告。
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from FuxiYu_NodeKernel import create_app, extensions
from FuxiYu_NodeKernel.constant import ROLE
from FuxiYu_NodeKernel.services.container_service import update_role

from .conftest import FakeContainers
from .password_fakes import FakeExecAPI, PasswordFakeContainer, PasswordFakeDockerClient

SEED = 20261024
ROUNDS = 3

PW_META = "P@ss;$(id)#9"
ROOT_PW_META = "Root;$(id)#9"
BAD_COLON = "Adv3rsarial:bad"
BAD_LONG = "x" * 129

_UNSET = object()


# ---------------------------------------------------------------------------
# 测试替身：只替换 Docker 边界，不 mock update_role / account_passwords
# ---------------------------------------------------------------------------


class _ForbiddenDocker:
    """任何访问都视为“本应在请求校验阶段被拒绝”的失败。"""

    def __getattr__(self, name):
        raise AssertionError(f"docker client must not be touched: {name}")


class _SpyContainers(FakeContainers):
    def __init__(self, existing=None):
        super().__init__(existing)
        self.get_calls = []

    def get(self, name_or_id):
        self.get_calls.append(name_or_id)
        return super().get(name_or_id)


class _LookupFailureContainers:
    def __init__(self):
        self.get_calls = []

    def get(self, name_or_id):
        self.get_calls.append(name_or_id)
        raise RuntimeError(f"lookup exploded for {name_or_id}")


class _ProbeFailureContainer(PasswordFakeContainer):
    """用户存在性探测抛异常，用于验证在写密码/改组之前中止。"""

    def exec_run(self, cmd, **kw):
        self.exec_calls.append((cmd, kw))
        text = cmd[-1] if isinstance(cmd, (list, tuple)) and cmd else str(cmd)
        if "id -u" in text and "useradd" not in text:
            raise RuntimeError("user probe exploded")
        return self.result(0)


class _AdversarialSocket:
    def __init__(self, *, fail: str | None = None, secret: str = ""):
        self.sent = b""
        self.closed = False
        self.write_shutdown = False
        self.fail = fail
        self.secret = secret

    def settimeout(self, _timeout):
        pass

    def sendall(self, data):
        if self.fail == "send":
            raise OSError(f"send failed {self.secret}")
        self.sent += data

    def shutdown(self, _how):
        if self.fail == "shutdown":
            raise OSError(f"shutdown failed {self.secret}")
        self.write_shutdown = True

    def recv(self, _size):
        if self.fail == "recv":
            raise OSError(f"recv failed {self.secret}")
        return b""

    def close(self):
        self.closed = True


class _AdversarialExecAPI(FakeExecAPI):
    """可编程 exec 通道：抛错、未知 inspect、坏 socket。"""

    def __init__(
        self,
        *,
        fail_stage: str | None = None,
        inspect_result=_UNSET,
        socket_fail: str | None = None,
        secret: str = "",
    ):
        super().__init__()
        self.fail_stage = fail_stage
        self.inspect_result = inspect_result
        self.socket_fail = socket_fail
        self.secret = secret

    def exec_create(self, container_id, cmd, **kwargs):
        if self.fail_stage == "create":
            raise RuntimeError(f"exec_create failed {self.secret}")
        return super().exec_create(container_id, cmd, **kwargs)

    def exec_start(self, exec_id, **kwargs):
        if self.fail_stage == "start":
            raise RuntimeError(f"exec_start failed {self.secret}")
        if self.socket_fail is not None:
            sock = _AdversarialSocket(fail=self.socket_fail, secret=self.secret)
            self.started.append({"id": exec_id, "kwargs": kwargs, "socket": sock})
            self.sockets[exec_id] = sock
            return sock
        return super().exec_start(exec_id, **kwargs)

    def exec_inspect(self, exec_id):
        if self.fail_stage == "inspect":
            raise RuntimeError(f"exec_inspect failed {self.secret}")
        if self.inspect_result is not _UNSET:
            return self.inspect_result
        return super().exec_inspect(exec_id)


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def _test_client():
    return TestClient(create_app())


def _payload(**overrides):
    config = {
        "container_name": "c1",
        "user_name": "u1",
        "updated_role": "admin",
    }
    config.update(overrides)
    return {"config": config}


def _post(client, **overrides):
    return client.post("/api/update_role", json=_payload(**overrides))


def _install(monkeypatch, container, *, api=None):
    client = PasswordFakeDockerClient(FakeContainers([container]))
    if api is not None:
        client.api = api
    monkeypatch.setattr(extensions, "docker_client", client)
    return client


def _install_containers(monkeypatch, containers, *, api=None):
    client = PasswordFakeDockerClient(containers)
    if api is not None:
        client.api = api
    monkeypatch.setattr(extensions, "docker_client", client)
    return client


def _commands(container):
    return [call[0][-1] for call in container.exec_calls]


def _sent(client):
    return [entry["socket"].sent for entry in client.api.started]


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _assert_no_secret(text: str, *secrets: str) -> None:
    for secret in secrets:
        if secret:
            assert secret not in text


def _assert_redacted(resp, *secrets: str) -> None:
    """422/500 固定脱敏体：无密码、无 input/ctx、no-store。"""

    _assert_no_secret(resp.text, *secrets)
    assert '"input"' not in resp.text
    assert '"ctx"' not in resp.text
    assert resp.headers.get("cache-control") == "no-store"


# ---------------------------------------------------------------------------
# 1. 真实 FastAPI/Pydantic 输入校验
# ---------------------------------------------------------------------------


INVALID_ROLES = [
    "ROOT",
    "Root",
    " root",
    "root ",
    "ROOT\n",
    "rоot",  # Cyrillic 'о'，不能当作 root 别名
    "ADMIN",
    "Admin",
    "COLLABORATOR",
    "Collaborator",
    None,
    [],
    ["root"],
    {},
    1,
    0,
    True,
    False,
]


@pytest.mark.parametrize("role", INVALID_ROLES, ids=lambda value: f"role={value!r}")
def test_invalid_role_rejected_before_docker(monkeypatch, role):
    monkeypatch.setattr(extensions, "docker_client", _ForbiddenDocker())
    resp = _post(_test_client(), updated_role=role, root_password=ROOT_PW_META)
    assert resp.status_code == 422, resp.text
    _assert_redacted(resp, ROOT_PW_META)


INVALID_PASSWORD_CASES = [
    ("root_missing", {"updated_role": "root"}, ()),
    ("root_null", {"updated_role": "root", "root_password": None}, ()),
    ("root_empty", {"updated_role": "root", "root_password": ""}, ()),
    ("root_short", {"updated_role": "root", "root_password": "short"}, ("short",)),
    ("root_long", {"updated_role": "root", "root_password": BAD_LONG}, (BAD_LONG,)),
    ("root_blank", {"updated_role": "root", "root_password": "        "}, ()),
    ("root_colon", {"updated_role": "root", "root_password": BAD_COLON}, (BAD_COLON,)),
    ("root_cr", {"updated_role": "root", "root_password": "abcdefg\rh"}, ("abcdefg\rh",)),
    ("root_lf", {"updated_role": "root", "root_password": "abcdefg\nh"}, ("abcdefg\nh",)),
    ("root_nul", {"updated_role": "root", "root_password": "abcdefg\x00h"}, ("abcdefg\x00h",)),
    ("root_int", {"updated_role": "root", "root_password": 12345678}, ("12345678",)),
    ("root_list", {"updated_role": "root", "root_password": [ROOT_PW_META]}, (ROOT_PW_META,)),
    (
        "root_object",
        {"updated_role": "root", "root_password": {"value": ROOT_PW_META}},
        (ROOT_PW_META,),
    ),
    ("admin_short", {"updated_role": "admin", "password": "short"}, ("short",)),
    ("admin_colon", {"updated_role": "admin", "password": BAD_COLON}, (BAD_COLON,)),
    ("admin_int", {"updated_role": "admin", "password": 12345678}, ("12345678",)),
    (
        "collaborator_password",
        {"updated_role": "collaborator", "password": PW_META},
        (PW_META,),
    ),
    (
        "admin_root_password",
        {"updated_role": "admin", "root_password": ROOT_PW_META},
        (ROOT_PW_META,),
    ),
    (
        "root_both_passwords",
        {"updated_role": "root", "root_password": ROOT_PW_META, "password": PW_META},
        (ROOT_PW_META, PW_META),
    ),
]


@pytest.mark.parametrize(
    "label, overrides, secrets",
    INVALID_PASSWORD_CASES,
    ids=[case[0] for case in INVALID_PASSWORD_CASES],
)
def test_invalid_password_contract_rejected_before_docker(
    monkeypatch, label, overrides, secrets
):
    monkeypatch.setattr(extensions, "docker_client", _ForbiddenDocker())
    resp = _post(_test_client(), **overrides)
    assert resp.status_code == 422, (label, resp.text)
    _assert_redacted(resp, *secrets)


def test_valid_roles_keep_secret_on_stdin(monkeypatch, capsys, caplog):
    """合法密码（含 shell 元字符）只走 stdin；响应、argv、日志不出现明文。"""

    cases = [
        (
            "root",
            {"updated_role": "root", "root_password": ROOT_PW_META},
            b"root:",
            "for g in sudo wheel",
            1,
        ),
        (
            "admin_password",
            {"updated_role": "admin", "password": PW_META},
            b"u1:",
            "usermod -aG sudo u1",
            1,
        ),
        (
            "admin_no_password",
            {"updated_role": "admin"},
            None,
            "usermod -aG sudo u1",
            0,
        ),
        (
            "collaborator",
            {"updated_role": "collaborator"},
            None,
            "deluser u1 sudo",
            0,
        ),
    ]

    for label, overrides, expected_prefix, expected_cmd, created_count in cases:
        container = PasswordFakeContainer("c1", user_exists=True)
        client = _install(monkeypatch, container)
        resp = _post(_test_client(), **overrides)

        assert resp.status_code == 200, (label, resp.text)
        assert resp.json()["success"] is True, (label, resp.json())
        _assert_no_secret(resp.text, PW_META, ROOT_PW_META)

        commands = _commands(container)
        assert any(expected_cmd in command for command in commands), (label, commands)
        assert all(PW_META not in command and ROOT_PW_META not in command for command in commands), (
            label,
            commands,
        )
        assert len(client.api.created) == created_count, (label, client.api.created)

        if expected_prefix is not None:
            sent = client.api.started[0]["socket"].sent
            assert sent.startswith(expected_prefix), (label, sent.split(b":", 1)[0])
            assert sent.endswith(b"\n"), label
            assert PW_META.encode() in sent or ROOT_PW_META.encode() in sent, label
            assert client.api.created[0]["cmd"] == ["chpasswd"], label
            assert client.api.created[0]["kwargs"]["stdin"] is True, label
            assert client.api.created[0]["kwargs"]["tty"] is False, label
        else:
            assert client.api.created == [], (label, client.api.created)

    text = capsys.readouterr().out + caplog.text
    _assert_no_secret(text, PW_META, ROOT_PW_META)


# ---------------------------------------------------------------------------
# 2. 注入名字 / 选项注入
# ---------------------------------------------------------------------------


META_NAMES = [
    "u1; id",
    "u1 && id",
    "$(id)",
    "`id`",
    "u1\nid",
    "u1\r id",
    "u1|id",
    "u1 > /tmp/pwn",
    "../root",
    "u1/../root",
    "u1\x00id",
    "u1\\id",
]


def test_shell_metacharacter_user_names_rejected_at_request_boundary(monkeypatch):
    records = []
    for name in META_NAMES:
        container = PasswordFakeContainer("c1", user_exists=True)
        _install(monkeypatch, container)
        resp = _post(_test_client(), user_name=name, updated_role="admin")
        records.append(
            {
                "name": name,
                "status": resp.status_code,
                "success": resp.json().get("success"),
                "commands": _commands(container),
            }
        )

    problems = [
        f"{record['name']!r}: status={record['status']} commands={len(record['commands'])}"
        for record in records
        if record["status"] != 422 or record["commands"]
    ]
    assert not problems, "invalid user names must be rejected by request validation:\n" + "\n".join(problems)

    # 请求模型被绕过时，service 入口也必须在 Docker lookup 前拒绝同一输入。
    service_spy = _SpyContainers([])
    _install_containers(monkeypatch, service_spy)
    for container_name, user_name, role in (
        ("c1", "u1; id", ROLE.ADMIN),
        ("c1; id", "u1", ROLE.ADMIN),
        ("c1", "root", ROLE.ADMIN),
    ):
        with pytest.raises(ValueError):
            update_role(container_name, user_name, role)
    assert service_spy.get_calls == []


def test_shell_metacharacter_container_names_rejected_before_docker_lookup(monkeypatch):
    records = []
    for name in META_NAMES:
        container = PasswordFakeContainer(name, user_exists=True)
        containers = _SpyContainers([container])
        _install_containers(monkeypatch, containers)
        resp = _post(
            _test_client(),
            container_name=name,
            user_name="u1",
            updated_role="admin",
        )
        records.append(
            {
                "name": name,
                "status": resp.status_code,
                "get_calls": list(containers.get_calls),
                "commands": _commands(container),
            }
        )

    problems = [
        f"{record['name']!r}: status={record['status']} get_calls={record['get_calls']} "
        f"commands={len(record['commands'])}"
        for record in records
        if record["status"] != 422 or record["get_calls"] or record["commands"]
    ]
    assert not problems, (
        "invalid container names must be rejected before Docker lookup:\n" + "\n".join(problems)
    )


def test_option_like_user_names_cannot_false_succeed(monkeypatch):
    """``--help`` 会被 id/usermod/userdel 当成选项并退出 0，不能因此返回成功。"""

    records = []
    for role, extra in (
        ("admin", {}),
        ("root", {"root_password": ROOT_PW_META}),
    ):
        container = PasswordFakeContainer("c1", user_exists=True)
        client = _install(monkeypatch, container)
        resp = _post(
            _test_client(),
            user_name="--help",
            updated_role=role,
            **extra,
        )
        _assert_no_secret(resp.text, PW_META, ROOT_PW_META)
        records.append(
            {
                "role": role,
                "status": resp.status_code,
                "success": resp.json().get("success"),
                "commands": _commands(container),
                "created": len(client.api.created),
            }
        )

    problems = [
        f"role={record['role']}: status={record['status']} success={record['success']} "
        f"created={record['created']} commands={record['commands']}"
        for record in records
        if record["status"] not in (400, 422)
        or record["commands"]
        or record["created"]
    ]
    assert not problems, "option-like names must not reach shell commands:\n" + "\n".join(problems)


# ---------------------------------------------------------------------------
# 3. 非 ROOT 角色不得触碰共享 root
# ---------------------------------------------------------------------------


def test_non_root_roles_must_not_touch_shared_root(monkeypatch):
    """ADMIN/COLLABORATOR 的 password/组操作不得落到共享 root 账号上。"""

    records = []
    for label, extra in (
        ("admin_password", {"updated_role": "admin", "password": PW_META}),
        ("admin_no_password", {"updated_role": "admin"}),
        ("collaborator", {"updated_role": "collaborator"}),
    ):
        container = PasswordFakeContainer("c1", user_exists=True)
        client = _install(monkeypatch, container)
        resp = _post(_test_client(), user_name="root", **extra)
        _assert_no_secret(resp.text, PW_META, ROOT_PW_META)
        sent = _sent(client)
        records.append(
            {
                "case": label,
                "status": resp.status_code,
                "success": resp.json().get("success"),
                "commands": _commands(container),
                "sent_logins": [payload.split(b":", 1)[0] for payload in sent],
            }
        )

    problems = []
    for record in records:
        safe = (record["status"] in (400, 422)) or (record["success"] in (False, 0))
        if not safe or record["commands"] or b"root" in record["sent_logins"]:
            problems.append(
                f"{record['case']}: status={record['status']} success={record['success']} "
                f"sent_logins={record['sent_logins']} commands={record['commands']}"
            )
    assert not problems, (
        "non-ROOT roles must not write shared root password or change root groups:\n"
        + "\n".join(problems)
    )


# ---------------------------------------------------------------------------
# 4. Docker 分步异常：密码写失败 / exec 未知
# ---------------------------------------------------------------------------


TRANSPORT_FAILURES = [
    ("exec_create", {"fail_stage": "create"}),
    ("exec_start", {"fail_stage": "start"}),
    ("exec_inspect", {"fail_stage": "inspect"}),
    ("inspect_none", {"inspect_result": None}),
    ("inspect_empty", {"inspect_result": {}}),
    ("inspect_missing_exit_code", {"inspect_result": {"Running": False}}),
    ("inspect_string_exit_code", {"inspect_result": {"ExitCode": "0", "Running": False}}),
    ("inspect_still_running", {"inspect_result": {"ExitCode": 0, "Running": True}}),
    ("inspect_nonzero", {"inspect_result": {"ExitCode": 1, "Running": False}}),
    ("socket_send", {"socket_fail": "send"}),
    ("socket_shutdown", {"socket_fail": "shutdown"}),
    ("socket_recv", {"socket_fail": "recv"}),
]


def test_admin_password_transport_failures_never_false_success(monkeypatch, capsys, caplog):
    failures = []
    for label, options in TRANSPORT_FAILURES:
        container = PasswordFakeContainer("c1", user_exists=True)
        api = _AdversarialExecAPI(secret=PW_META, **options)
        _install(monkeypatch, container, api=api)
        result = update_role("c1", "u1", ROLE.ADMIN, password=SecretStr(PW_META))
        commands = _commands(container)
        if result is not False or any("usermod" in command for command in commands):
            failures.append((label, result, commands))

    text = capsys.readouterr().out + caplog.text
    _assert_no_secret(text, PW_META)
    assert not failures, failures


def test_root_password_transport_failures_raise_and_skip_cleanup(monkeypatch, capsys, caplog):
    failures = []
    for label, options in TRANSPORT_FAILURES:
        container = PasswordFakeContainer("c1", user_exists=True)
        api = _AdversarialExecAPI(secret=ROOT_PW_META, **options)
        _install(monkeypatch, container, api=api)
        commands = []

        try:
            update_role("c1", "target", ROLE.ROOT, root_password=SecretStr(ROOT_PW_META))
        except RuntimeError as exc:
            _assert_no_secret(str(exc), ROOT_PW_META)
        else:
            failures.append((label, "did not raise"))
            continue

        commands = _commands(container)
        if any("for g in sudo wheel" in command for command in commands):
            failures.append((label, "ran cleanup after password failure", commands))

    text = capsys.readouterr().out + caplog.text
    _assert_no_secret(text, ROOT_PW_META)
    assert not failures, failures


# ---------------------------------------------------------------------------
# 5. 命令分步异常 / 顺序
# ---------------------------------------------------------------------------


def test_admin_user_probe_exception_aborts_before_any_write(monkeypatch, capsys, caplog):
    container = _ProbeFailureContainer("c1", user_exists=True)
    client = _install(monkeypatch, container)

    with pytest.raises(RuntimeError) as excinfo:
        update_role("c1", "u1", ROLE.ADMIN, password=SecretStr(PW_META))

    assert client.api.created == []
    assert not any("usermod" in command for command in _commands(container))
    _assert_no_secret(str(excinfo.value), PW_META)
    _assert_no_secret(capsys.readouterr().out + caplog.text, PW_META)


def test_admin_create_failure_stops_before_password_write(monkeypatch):
    container = PasswordFakeContainer("c1", user_exists=False)
    container.command_codes["useradd -M -d /root/.collaborators/old_root"] = 1
    client = _install(monkeypatch, container)

    assert update_role("c1", "old_root", ROLE.ADMIN, password=SecretStr(PW_META)) is False

    commands = _commands(container)
    assert any("useradd -M -d /root/.collaborators/old_root" in command for command in commands)
    assert client.api.created == []
    assert not any("usermod" in command for command in commands)


def test_admin_password_failure_after_create_is_false_with_partial_account(monkeypatch):
    container = PasswordFakeContainer("c1", user_exists=False)
    api = _AdversarialExecAPI(fail_stage="start", secret=PW_META)
    client = _install(monkeypatch, container, api=api)

    assert update_role("c1", "old_root", ROLE.ADMIN, password=SecretStr(PW_META)) is False

    commands = _commands(container)
    assert any("useradd -M -d /root/.collaborators/old_root" in command for command in commands)
    assert len(client.api.created) == 1
    assert client.api.started == []
    assert not any("usermod" in command for command in commands)


def test_admin_group_failure_after_password_is_false_no_rollback(monkeypatch):
    container = PasswordFakeContainer("c1", user_exists=True)
    container.command_codes["usermod -aG sudo u1"] = 1
    client = _install(monkeypatch, container)

    assert update_role("c1", "u1", ROLE.ADMIN, password=SecretStr(PW_META)) is False

    commands = _commands(container)
    assert any("usermod -aG sudo u1" in command for command in commands)
    assert len(client.api.created) == 1
    assert not any("userdel" in command for command in commands)
    assert not any("deluser" in command for command in commands)


def test_root_userdel_failure_is_false_after_root_password_set(monkeypatch):
    container = PasswordFakeContainer("c1", user_exists=True)
    container.command_codes["userdel target || deluser target"] = 1
    client = _install(monkeypatch, container)

    assert (
        update_role("c1", "target", ROLE.ROOT, root_password=SecretStr(ROOT_PW_META))
        is False
    )

    sent = _sent(client)
    assert len(sent) == 1
    assert sent[0].startswith(b"root:") and sent[0].endswith(b"\n")
    commands = _commands(container)
    assert any("for g in sudo wheel" in command and "userdel target" in command for command in commands)
    assert not any("old_root" in command for command in commands)


def test_root_archive_step_failure_is_false_after_root_password_set(monkeypatch):
    """归档阶段所在的 exec 失败时不得假成功；mv 单独失败的 best-effort 语义见下一测试。"""

    container = PasswordFakeContainer("c1", user_exists=True)
    container.command_codes[".legacy_target_"] = 1
    client = _install(monkeypatch, container)

    assert (
        update_role("c1", "target", ROLE.ROOT, root_password=SecretStr(ROOT_PW_META))
        is False
    )

    sent = _sent(client)
    assert len(sent) == 1
    assert sent[0].startswith(b"root:")
    commands = _commands(container)
    assert any(".legacy_target_" in command for command in commands)
    assert not any("old_root" in command for command in commands)


def test_root_cleanup_command_shape_is_idempotent_and_best_effort_archive(monkeypatch):
    container = PasswordFakeContainer("c1", user_exists=True)
    client = _install(monkeypatch, container)

    assert (
        update_role("c1", "target", ROLE.ROOT, root_password=SecretStr(ROOT_PW_META))
        is True
    )

    command = next(command for command in _commands(container) if "for g in sudo wheel" in command)
    assert 'deluser target "$g"' in command
    assert "grep -qx" in command
    assert "mv /root/.collaborators/target /root/.collaborators/.legacy_target_" in command
    assert "2>/dev/null || true" in command
    assert "userdel target || deluser target" in command
    assert "rm -f /home/target" in command
    assert ROOT_PW_META not in command
    assert len(_sent(client)) == 1


def test_container_lookup_failure_aborts_without_exec(monkeypatch, capsys, caplog):
    containers = _LookupFailureContainers()
    client = _install_containers(monkeypatch, containers)

    with pytest.raises(RuntimeError) as excinfo:
        update_role("c1", "u1", ROLE.ADMIN)

    assert containers.get_calls == ["c1"]
    assert client.api.created == []
    _assert_no_secret(str(excinfo.value), PW_META)
    _assert_no_secret(capsys.readouterr().out + caplog.text, PW_META)


def test_root_missing_password_and_root_identity_rejected_before_exec(monkeypatch):
    cases = [
        ("missing_password", "u1", {}),
        ("target_is_root", "root", {"root_password": SecretStr(ROOT_PW_META)}),
    ]
    for label, user_name, kwargs in cases:
        container = PasswordFakeContainer("c1", user_exists=True)
        client = _install(monkeypatch, container)
        with pytest.raises(ValueError):
            update_role("c1", user_name, ROLE.ROOT, **kwargs)
        assert client.api.created == [], label
        assert container.exec_calls == [], label


# ---------------------------------------------------------------------------
# 6. API 映射：失败不伪装成功、不泄密
# ---------------------------------------------------------------------------


def test_api_admin_transport_failure_reports_false(monkeypatch, capsys, caplog):
    container = PasswordFakeContainer("c1", user_exists=True)
    api = _AdversarialExecAPI(fail_stage="start", secret=PW_META)
    _install(monkeypatch, container, api=api)

    resp = _post(_test_client(), updated_role="admin", password=PW_META)

    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] in (False, 0), resp.json()
    _assert_redacted(resp, PW_META)
    assert not any("usermod" in command for command in _commands(container))
    _assert_no_secret(capsys.readouterr().out + caplog.text, PW_META)


def test_api_root_transport_failure_is_500_redacted(monkeypatch, capsys, caplog):
    container = PasswordFakeContainer("c1", user_exists=True)
    api = _AdversarialExecAPI(fail_stage="start", secret=ROOT_PW_META)
    _install(monkeypatch, container, api=api)

    resp = _post(_test_client(), user_name="target", updated_role="root", root_password=ROOT_PW_META)

    assert resp.status_code == 500, resp.text
    assert resp.json()["error_reason"] == "internal_error"
    _assert_redacted(resp, ROOT_PW_META)
    assert not any("for g in sudo wheel" in command for command in _commands(container))
    _assert_no_secret(capsys.readouterr().out + caplog.text, ROOT_PW_META)


def test_api_root_userdel_failure_reports_false(monkeypatch, capsys, caplog):
    container = PasswordFakeContainer("c1", user_exists=True)
    container.command_codes["userdel target || deluser target"] = 1
    client = _install(monkeypatch, container)

    resp = _post(_test_client(), user_name="target", updated_role="root", root_password=ROOT_PW_META)

    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] in (False, 0), resp.json()
    _assert_redacted(resp, ROOT_PW_META)
    sent = _sent(client)
    assert len(sent) == 1 and sent[0].startswith(b"root:")
    _assert_no_secret(capsys.readouterr().out + caplog.text, ROOT_PW_META)


# ---------------------------------------------------------------------------
# 7. 确定性重复顺序 / 不漏密码 / 不回滚
# ---------------------------------------------------------------------------


def _record(resp):
    return {
        "status": resp.status_code,
        "json": resp.json(),
        "cache": resp.headers.get("cache-control"),
    }


def _successful_round(monkeypatch, app_client):
    container = PasswordFakeContainer("c1", user_exists=False)
    client = _install(monkeypatch, container)
    responses = []

    responses.append(_record(_post(app_client, user_name="old_root", updated_role="admin", password=PW_META)))
    container.user_exists = True
    responses.append(
        _record(
            _post(
                app_client,
                user_name="target",
                updated_role="root",
                root_password=ROOT_PW_META,
            )
        )
    )
    responses.append(_record(_post(app_client, user_name="old_root", updated_role="admin", password=PW_META)))

    return {
        "seed": SEED,
        "responses": responses,
        "commands": _commands(container),
        "sent_sha256": [_digest(payload) for payload in _sent(client)],
        "created": len(client.api.created),
    }


def test_repeated_handover_sequence_is_deterministic_and_redacted(monkeypatch, capsys, caplog):
    app_client = _test_client()
    transcripts = []
    response_texts = []

    for _ in range(ROUNDS):
        transcripts.append(_successful_round(monkeypatch, app_client))
        response_texts.extend(item["json"] for item in transcripts[-1]["responses"])

    assert len(transcripts) == ROUNDS
    assert transcripts[1:] == transcripts[:-1], transcripts

    for transcript in transcripts:
        assert [item["status"] for item in transcript["responses"]] == [200, 200, 200]
        assert [item["json"]["success"] for item in transcript["responses"]] == [True, True, True]
        assert transcript["created"] == 3
        assert len(transcript["sent_sha256"]) == 3

    _assert_no_secret(str(response_texts), PW_META, ROOT_PW_META)
    _assert_no_secret(capsys.readouterr().out + caplog.text, PW_META, ROOT_PW_META)


def test_second_step_failure_does_not_rollback_first_and_repeats(monkeypatch, capsys, caplog):
    app_client = _test_client()
    transcripts = []

    for _ in range(ROUNDS):
        container = PasswordFakeContainer("c1", user_exists=False)
        api = _AdversarialExecAPI()
        client = _install(monkeypatch, container, api=api)

        first = _post(app_client, user_name="old_root", updated_role="admin", password=PW_META)
        container.user_exists = True
        first_commands = list(_commands(container))
        first_sent_sha = [_digest(payload) for payload in _sent(client)]

        api.fail_stage = "start"
        second = _post(
            app_client,
            user_name="target",
            updated_role="root",
            root_password=ROOT_PW_META,
        )
        second_commands = _commands(container)[len(first_commands):]

        assert first.status_code == 200 and first.json()["success"] is True
        assert second.status_code == 500 and second.json()["error_reason"] == "internal_error"
        assert not any("old_root" in command for command in second_commands), second_commands
        assert not any("userdel" in command for command in second_commands), second_commands
        assert not _sent(client)[len(first_sent_sha):], "root stdin must not be sent on exec_start failure"

        transcripts.append(
            {
                "seed": SEED,
                "first": _record(first),
                "second": _record(second),
                "first_commands": first_commands,
                "second_commands": second_commands,
                "first_sent_sha256": first_sent_sha,
                "created": len(client.api.created),
            }
        )

    assert transcripts[1:] == transcripts[:-1], transcripts
    _assert_no_secret(capsys.readouterr().out + caplog.text, PW_META, ROOT_PW_META)


# ---------------------------------------------------------------------------
# 8. 额外字段 / 只处理单目标 / 日志脱敏
# ---------------------------------------------------------------------------


def test_transfer_root_extra_field_is_ignored_and_no_scan(monkeypatch):
    container = PasswordFakeContainer("c1", user_exists=True)
    client = _install(monkeypatch, container)
    app_client = _test_client()

    resp = app_client.post(
        "/api/update_role",
        json={
            "config": {
                "container_name": "c1",
                "user_name": "target",
                "updated_role": "root",
                "root_password": ROOT_PW_META,
                "transfer_root": "old_root",
                "owner_name": "old_root",
                "other_user": "old_root",
            }
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    commands = "\n".join(_commands(container))
    assert "target" in commands
    assert "old_root" not in commands
    assert ROOT_PW_META not in commands
    assert len(_sent(client)) == 1


def test_validation_and_internal_errors_do_not_log_secret(monkeypatch, capsys, caplog):
    monkeypatch.setattr(extensions, "docker_client", _ForbiddenDocker())
    app_client = _test_client()

    rejected = _post(app_client, updated_role="root", root_password=BAD_COLON)
    assert rejected.status_code == 422
    _assert_redacted(rejected, BAD_COLON)

    container = PasswordFakeContainer("c1", user_exists=True)
    api = _AdversarialExecAPI(fail_stage="start", secret=PW_META)
    _install(monkeypatch, container, api=api)
    failed = _post(app_client, updated_role="admin", password=PW_META)
    assert failed.status_code == 200
    assert failed.json()["success"] in (False, 0)

    text = capsys.readouterr().out + caplog.text
    _assert_no_secret(text, BAD_COLON, PW_META)
