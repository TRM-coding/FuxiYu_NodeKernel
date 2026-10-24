"""Low-level Docker account/password operations.

These helpers only handle container account existence, exec transport and
stdin ``chpasswd``. Business permissions, role rules and response shapes stay
in ``services.container_service``.
"""

from __future__ import annotations

import socket

from pydantic import SecretStr

from .. import extensions
from ..utils import sanitizer as _sanitizer


def _container_user_exists(container, user_name: str) -> bool:
    result = container.exec_run(
        ["/bin/sh", "-c", f"id -u {user_name} >/dev/null 2>&1"],
        user="root",
    )
    exit_code = getattr(result, "exit_code", None)
    if exit_code is None:
        try:
            exit_code = int(result[0])
        except Exception:
            exit_code = 1
    return exit_code == 0


def _docker_exec_api(container):
    api = getattr(getattr(container, "client", None), "api", None)
    if api is None:
        api = getattr(extensions.docker_client, "api", None)
    if api is None:
        raise RuntimeError("docker exec API unavailable")
    return api


def _exec_socket_target(sock):
    """Return a socket-like object with sendall/recv/shutdown.

    docker-py may return a raw socket or a ``socket.SocketIO`` wrapper whose
    underlying socket lives at ``_sock``. Keep the original wrapper alive and
    use the underlying socket for I/O when necessary.
    """

    underlying = getattr(sock, "_sock", None)
    for candidate in (underlying, sock):
        if candidate is not None and all(
            hasattr(candidate, name) for name in ("sendall", "recv", "shutdown")
        ):
            return candidate
    return None


def _exec_chpasswd_stdin(
    container,
    login_name: str,
    password: SecretStr,
    timeout_sec: int = 30,
) -> int:
    """Set one account password with chpasswd over Docker exec stdin.

    The password is never placed in argv, shell text, environment variables,
    temporary files, logs or exception messages. An unconfirmed write/EOF/read
    is a failure, even if the exec inspect reports exit code 0.
    """

    _sanitizer.validate_username(login_name)
    if not isinstance(password, SecretStr):
        raise ValueError("password must be SecretStr")
    payload = f"{login_name}:{password.get_secret_value()}\n".encode("utf-8")

    api = _docker_exec_api(container)
    response = api.exec_create(
        container.id,
        ["chpasswd"],
        stdin=True,
        stdout=True,
        stderr=True,
        tty=False,
        user="root",
    )
    exec_id = response["Id"]
    sock = api.exec_start(exec_id, socket=True)
    target = _exec_socket_target(sock)
    write_ok = eof_ok = read_ok = False
    try:
        if target is not None:
            try:
                target.settimeout(timeout_sec)
            except Exception:
                pass
            target.sendall(payload)
            write_ok = True
            target.shutdown(socket.SHUT_WR)
            eof_ok = True
            while target.recv(4096):
                pass
            read_ok = True
    except (BrokenPipeError, socket.timeout, OSError, AttributeError):
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass

    try:
        inspection = api.exec_inspect(exec_id) or {}
    except Exception:
        return 1
    if not (write_ok and eof_ok and read_ok):
        return 1
    if inspection.get("Running"):
        return 1
    exit_code = inspection.get("ExitCode")
    return int(exit_code) if isinstance(exit_code, int) else 1


def _set_account_password(container, login_name: str, password: SecretStr) -> None:
    if _exec_chpasswd_stdin(container, login_name, password) != 0:
        raise RuntimeError("chpasswd failed")
