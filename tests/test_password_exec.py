from __future__ import annotations

import socket
import threading
import time

import pytest
from pydantic import SecretStr

from FuxiYu_NodeKernel import extensions
from FuxiYu_NodeKernel.services.container_service import (
    _exec_chpasswd_stdin,
    _set_account_password,
)

from .password_fakes import PasswordFakeContainer, install_password_docker


class _SocketAPI:
    def __init__(self, sock, *, exit_code=0, running=False):
        self.sock = sock
        self.exit_code = exit_code
        self.running = running
        self.created = []

    def exec_create(self, container_id, cmd, **kwargs):
        self.created.append({"container_id": container_id, "cmd": cmd, "kwargs": kwargs})
        return {"Id": "exec-real"}

    def exec_start(self, _exec_id, **_kwargs):
        return self.sock

    def exec_inspect(self, _exec_id):
        return {"ExitCode": self.exit_code, "Running": self.running}


class _Container:
    id = "c1"


def _install_api(monkeypatch, api):
    monkeypatch.setattr(extensions, "docker_client", type("_Client", (), {"api": api})())


def test_chpasswd_stdin_argv(monkeypatch):
    container = PasswordFakeContainer("c1")
    client = install_password_docker(monkeypatch, container)
    password = SecretStr("P@ss;word$`\"'\\9")

    assert _exec_chpasswd_stdin(container, "u1", password) == 0
    created = client.api.created[0]
    assert created["cmd"] == ["chpasswd"]
    assert created["kwargs"]["stdin"] is True
    assert created["kwargs"]["tty"] is False
    assert created["kwargs"]["user"] == "root"
    sock = client.api.started[0]["socket"]
    assert sock.sent == f"u1:{password.get_secret_value()}\n".encode()
    assert sock.write_shutdown is True
    assert password.get_secret_value() not in repr(created)


def test_chpasswd_stdin_real_socketio(monkeypatch, capsys):
    """Real socketpair + socket.SocketIO wrapper: write, EOF, read, close."""
    server, client_sock = socket.socketpair()
    received = []
    done = threading.Event()

    def peer():
        try:
            data = b""
            while b"\n" not in data:
                chunk = server.recv(4096)
                if not chunk:
                    break
                data += chunk
            received.append(data)
        finally:
            server.close()
            done.set()

    thread = threading.Thread(target=peer, daemon=True)
    thread.start()
    wrapper = socket.SocketIO(client_sock, "rw")
    api = _SocketAPI(wrapper)
    _install_api(monkeypatch, api)
    password = SecretStr("Real#Socket9")

    assert _exec_chpasswd_stdin(_Container(), "u1", password) == 0
    assert done.wait(2)
    thread.join(2)
    assert received == [b"u1:Real#Socket9\n"]
    assert password.get_secret_value() not in capsys.readouterr().out


def test_chpasswd_write_failure_not_success(monkeypatch):
    class _BadSock:
        def settimeout(self, _timeout):
            pass

        def sendall(self, _data):
            raise OSError("closed")

        def shutdown(self, _how):
            pass

        def recv(self, _size):
            return b""

        def close(self):
            pass

    class _Wrapper:
        _sock = _BadSock()

        def close(self):
            pass

    api = _SocketAPI(_Wrapper(), exit_code=0)
    _install_api(monkeypatch, api)
    assert _exec_chpasswd_stdin(_Container(), "u1", SecretStr("Write#Failure9")) == 1


def test_chpasswd_read_timeout_not_success(monkeypatch):
    class _TimeoutSock:
        def settimeout(self, _timeout):
            pass

        def sendall(self, _data):
            pass

        def shutdown(self, _how):
            pass

        def recv(self, _size):
            raise socket.timeout("no EOF")

        def close(self):
            pass

    class _Wrapper:
        _sock = _TimeoutSock()

        def close(self):
            pass

    api = _SocketAPI(_Wrapper(), exit_code=0)
    _install_api(monkeypatch, api)
    assert _exec_chpasswd_stdin(_Container(), "u1", SecretStr("Read#Timeout9")) == 1


def test_chpasswd_failure_sanitized(monkeypatch):
    container = PasswordFakeContainer("c1")
    install_password_docker(monkeypatch, container, exit_code=1)
    password = SecretStr("P@ssw0rd-1234")

    assert _exec_chpasswd_stdin(container, "u1", password) == 1
    with pytest.raises(RuntimeError) as excinfo:
        _set_account_password(container, "u1", password)
    assert password.get_secret_value() not in str(excinfo.value)
