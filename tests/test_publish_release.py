import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "packaging" / "publish_release.py"
SPEC = importlib.util.spec_from_file_location("publish_release", SCRIPT_PATH)
assert SPEC and SPEC.loader
publish_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publish_release)


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")


def test_publish_release_sends_atomic_manifest(tmp_path, monkeypatch):
    installer = tmp_path / "E2DM2-Setup-1.2.3.exe"
    installer.write_bytes(b"installer contents")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["token"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse(captured["payload"])

    monkeypatch.setattr(publish_release.urllib.request, "urlopen", fake_urlopen)

    publish_release.publish_release(
        "1.2.3",
        installer,
        "release-secret",
        "https://example.supabase.co/functions/v1/release-metadata",
    )

    assert captured["token"] == "Bearer release-secret"
    assert captured["timeout"] == 30
    assert captured["payload"] == {
        "version": "1.2.3",
        "download_url": (
            "https://github.com/Gendire123/E2DM2-Releases/releases/download/"
            "v1.2.3/E2DM2-Setup-1.2.3.exe"
        ),
        "sha256": "eef523368dce718bb9a2cb6df91baa07ef1669cdc6aee2e3525a0bb2e5b5a55f",
        "virustotal_url": (
            "https://www.virustotal.com/gui/file/"
            "eef523368dce718bb9a2cb6df91baa07ef1669cdc6aee2e3525a0bb2e5b5a55f"
        ),
        "file_size_bytes": 18,
    }
