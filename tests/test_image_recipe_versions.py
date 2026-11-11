"""Ctrl 注入换代后，新文本必须按新标签构建，旧制品继续保留。"""

from pathlib import Path
from types import SimpleNamespace

import docker

from FuxiYu_NodeKernel import extensions
from FuxiYu_NodeKernel.services.container_service import build_image


def test_changed_injection_builds_new_tag_then_reuses_it(monkeypatch):
    old_tag = "fuxi/image-7:20261015T000000Z"
    new_tag = "fuxi/image-7:20261015T000001Z"
    available = {old_tag}
    builds, removals = [], []

    class Images:
        def get(self, tag):
            if tag not in available:
                raise docker.errors.ImageNotFound(tag)
            return object()

        def build(self, **kwargs):
            content = (Path(kwargs["path"]) / kwargs["dockerfile"]).read_text(encoding="utf-8")
            builds.append((kwargs["tag"], content))
            available.add(kwargs["tag"])
            return object(), []

        def remove(self, tag, **kwargs):
            removals.append(tag)

    monkeypatch.setattr(extensions, "docker_client", SimpleNamespace(images=Images()))
    payload = {
        "image_tag": new_tag,
        "dockerfile_text": "FROM ubuntu:24.04\nUSER root\nRUN echo PLATFORM_INJECTION_V2\nENTRYPOINT tail -f /dev/null\n",
    }
    assert build_image(payload) == new_tag
    assert len(builds) == 1 and builds[0][0] == new_tag
    assert "PLATFORM_INJECTION_V2" in builds[0][1]
    assert build_image(payload) == new_tag
    assert len(builds) == 1
    assert old_tag in available and new_tag in available
    assert removals == []
