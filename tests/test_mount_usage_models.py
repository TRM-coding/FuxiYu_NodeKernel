"""check_mount_usage 线路模型测试。"""
import pytest
from pydantic import ValidationError

from FuxiYu_NodeKernel.schemas import (
    CheckDiskUsageResponse,
    CheckMountUsageConfig,
    CheckMountUsageMessage,
    CheckMountUsageResponse,
    ContainerDiskUsage,
    MountUsageItem,
)


def test_mount_paths_accepts_one_to_hundred_items():
    assert CheckMountUsageConfig(mount_paths=["/home/a/containers/c1"]).mount_paths == [
        "/home/a/containers/c1"
    ]
    paths = [f"/home/a/containers/c{i}" for i in range(100)]
    assert len(CheckMountUsageConfig(mount_paths=paths).mount_paths) == 100


@pytest.mark.parametrize(
    "paths",
    [
        [],
        [f"/home/a/containers/c{i}" for i in range(101)],
    ],
)
def test_mount_paths_rejects_empty_or_over_limit(paths):
    with pytest.raises(ValidationError):
        CheckMountUsageConfig(mount_paths=paths)


@pytest.mark.parametrize(
    "paths",
    [
        "not-a-list",
        [1],
        ["/home/a/containers/c1", 2],
        None,
    ],
)
def test_mount_paths_rejects_non_string_array(paths):
    with pytest.raises(ValidationError):
        CheckMountUsageConfig(mount_paths=paths)


def test_message_requires_config_and_mount_paths():
    with pytest.raises(ValidationError):
        CheckMountUsageMessage()
    with pytest.raises(ValidationError):
        CheckMountUsageMessage(config={})
    assert CheckMountUsageMessage(
        config={"mount_paths": ["/home/a/containers/c1"]}
    ).config.mount_paths == ["/home/a/containers/c1"]


@pytest.mark.parametrize("field", ["deleted_id", "machine_id", "container_name", "role"])
def test_config_forbids_extra_identity_fields(field):
    """身份字段由 Ctrl 负责，Node 请求模型必须拒绝而不是忽略。"""

    with pytest.raises(ValidationError):
        CheckMountUsageConfig(mount_paths=["/home/a/containers/c1"], **{field: "x"})


@pytest.mark.parametrize("field", ["deleted_id", "machine_id", "container_name", "role"])
def test_message_forbids_outer_extra_identity_fields(field):
    with pytest.raises(ValidationError):
        CheckMountUsageMessage(
            config={"mount_paths": ["/home/a/containers/c1"]},
            **{field: "x"},
        )


def test_mount_item_allows_null_optional_fields():
    pending = MountUsageItem(path="/home/a/containers/c1", pending=True)
    assert pending.bytes is None
    assert pending.measured_at is None
    assert pending.error is None

    error = MountUsageItem(
        path="/home/a/containers/c1",
        bytes=None,
        measured_at=None,
        pending=False,
        error="not_found",
    )
    assert error.error == "not_found"


def test_mount_item_rejects_negative_bytes():
    with pytest.raises(ValidationError):
        MountUsageItem(path="/home/a/containers/c1", bytes=-1, pending=False)


def test_response_wire_fields_are_exact():
    response = CheckMountUsageResponse(
        mounts=[
            {
                "path": "/home/a/containers/c1",
                "bytes": 0,
                "measured_at": "2026-10-20T08:00:00Z",
                "pending": False,
                "error": None,
            },
            {
                "path": "/home/a/containers/c2",
                "bytes": None,
                "measured_at": None,
                "pending": True,
                "error": None,
            },
            {
                "path": "/home/a/containers/c3",
                "bytes": None,
                "measured_at": None,
                "pending": False,
                "error": "permission_denied",
            },
        ]
    )

    payload = response.model_dump()
    assert set(payload) == {"success", "mounts"}
    assert [item["path"] for item in payload["mounts"]] == [
        "/home/a/containers/c1",
        "/home/a/containers/c2",
        "/home/a/containers/c3",
    ]
    for item in payload["mounts"]:
        assert set(item) == {"path", "bytes", "measured_at", "pending", "error"}


def test_existing_disk_wire_model_unchanged():
    assert list(ContainerDiskUsage.model_fields) == [
        "container_name",
        "overlay_rw_bytes",
        "bind_mount_bytes",
        "bind_mount_path",
        "mount_path_status",
        "bind_mount_source",
        "total_bytes",
        "error",
        "measured_at",
    ]
    assert set(CheckDiskUsageResponse.model_fields) == {
        "success",
        "machine_disk",
        "container",
    }
