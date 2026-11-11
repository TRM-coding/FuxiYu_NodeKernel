from __future__ import annotations

import json

import pytest
from pydantic import SecretStr, ValidationError
from fastapi.encoders import jsonable_encoder

from FuxiYu_NodeKernel.schemas import (
    AddCollaboratorConfig,
    CreateContainerMessage,
    ResetContainerPasswordConfig,
    RestoreAccountConfig,
    UpdateRoleConfig,
    UpdateRoleResponse,
)

VALID_CFG = {
    "gpu_list": [],
    "cpu_number": 2,
    "memory": 4,
    "shared_memory": 0,
    "name": "c1",
    "port": 2233,
    "image": "ubuntu:22.04",
}
PW = SecretStr("Correct#Horse9Battery")
BAD_PASSWORDS = ["", "short", "x" * 129, "abc:defgh", "abc\ndefgh", "abc\x00defgh", "        "]


def create_message(**overrides):
    payload = {
        "owner_name": "admin",
        "config": VALID_CFG,
        "root_password": PW,
    }
    payload.update(overrides)
    return CreateContainerMessage(**payload)


def test_create_message_root_password_contract():
    msg = create_message()
    assert msg.root_password.get_secret_value() == PW.get_secret_value()
    assert PW.get_secret_value() not in repr(msg)
    assert PW.get_secret_value() not in json.dumps(msg.model_dump(), default=str)

    with pytest.raises(ValidationError):
        CreateContainerMessage(owner_name="admin", config=VALID_CFG)

    for bad in BAD_PASSWORDS:
        with pytest.raises(ValidationError):
            create_message(root_password=SecretStr(bad))


def test_restore_account_password_contract():
    account = RestoreAccountConfig(user_name="u1", role="admin", password=PW)
    assert account.role == "admin"
    assert PW.get_secret_value() not in repr(account)
    assert PW.get_secret_value() not in json.dumps(account.model_dump(), default=str)

    with pytest.raises(ValidationError):
        RestoreAccountConfig(user_name="u1", role="admin")

    for bad in BAD_PASSWORDS:
        with pytest.raises(ValidationError):
            RestoreAccountConfig(user_name="u1", role="admin", password=SecretStr(bad))


def test_add_collaborator_contract():
    cfg = AddCollaboratorConfig(container_name="c1", user_name="u1", role="admin", password=PW)
    assert PW.get_secret_value() not in repr(cfg)
    assert PW.get_secret_value() not in json.dumps(cfg.model_dump(), default=str)

    with pytest.raises(ValidationError):
        AddCollaboratorConfig(container_name="c1", user_name="u1", role="admin")

    for bad in BAD_PASSWORDS:
        with pytest.raises(ValidationError):
            AddCollaboratorConfig(
                container_name="c1", user_name="u1", role="admin", password=SecretStr(bad)
            )


def test_update_role_password_contract():
    root = UpdateRoleConfig(
        container_name="c1", user_name="u1", updated_role="root", root_password=PW
    )
    assert PW.get_secret_value() not in repr(root)
    assert PW.get_secret_value() not in json.dumps(root.model_dump(), default=str)

    admin = UpdateRoleConfig(
        container_name="c1", user_name="old_root", updated_role="admin", password=PW
    )
    assert PW.get_secret_value() not in repr(admin)

    plain = UpdateRoleConfig(container_name="c1", user_name="u1", updated_role="admin")
    assert plain.password is None and plain.root_password is None

    with pytest.raises(ValidationError):
        UpdateRoleConfig(container_name="c1", user_name="u1", updated_role="root")

    with pytest.raises(ValidationError):
        UpdateRoleConfig(
            container_name="c1",
            user_name="u1",
            updated_role="root",
            root_password=PW,
            password=PW,
        )
    with pytest.raises(ValidationError):
        UpdateRoleConfig(
            container_name="c1", user_name="u1", updated_role="admin", root_password=PW
        )
    with pytest.raises(ValidationError):
        UpdateRoleConfig(
            container_name="c1", user_name="u1", updated_role="collaborator", password=PW
        )

    for bad in BAD_PASSWORDS:
        with pytest.raises(ValidationError):
            UpdateRoleConfig(
                container_name="c1", user_name="u1", updated_role="root", root_password=SecretStr(bad)
            )


def test_secretstr_masking_across_models():
    values = [
        create_message(),
        RestoreAccountConfig(user_name="u1", password=PW),
        AddCollaboratorConfig(container_name="c1", user_name="u1", role="collaborator", password=PW),
        UpdateRoleConfig(container_name="c1", user_name="u1", updated_role="root", root_password=PW),
        ResetContainerPasswordConfig(container_name="c1", user_name="root", password=PW),
    ]
    for model in values:
        encoded = jsonable_encoder(model)
        assert PW.get_secret_value() not in repr(model)
        assert PW.get_secret_value() not in json.dumps(encoded, default=str)


def test_restore_password_not_in_snapshot():
    account = RestoreAccountConfig(user_name="u1", password=PW)
    dumped = account.model_dump()
    assert dumped["password"] == "**********" or str(dumped["password"]) == "**********"
    assert PW.get_secret_value() not in json.dumps(dumped, default=str)
    assert PW.get_secret_value() not in account.model_dump_json()


def test_update_role_response_plain_shape():
    response = UpdateRoleResponse(success=1, decrypted_message={"container_name": "c1", "user_name": "u1"})
    assert response.success == 1
    assert response.decrypted_message["container_name"] == "c1"
