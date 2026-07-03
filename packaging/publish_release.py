import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_RELEASE_API_URL = (
    "https://kzozxeyktwxcsukkheah.supabase.co/functions/v1/release-metadata"
)


def get_sha256(filepath: Path) -> str:
    digest = hashlib.sha256()
    with filepath.open("rb") as installer:
        for chunk in iter(lambda: installer.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def publish_release(version: str, installer_path: Path, token: str, api_url: str) -> None:
    file_hash = get_sha256(installer_path)
    payload = {
        "version": version,
        "download_url": (
            "https://github.com/Gendire123/E2DM2-Releases/releases/download/"
            f"v{version}/E2DM2-Setup-{version}.exe"
        ),
        "sha256": file_hash,
        "virustotal_url": f"https://www.virustotal.com/gui/file/{file_hash}",
        "file_size_bytes": installer_path.stat().st_size,
    }
    request = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "E2DM2-BuildAutomation",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            published = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Release metadata API returned HTTP {error.code}: {details}"
        ) from error

    print(
        "Published release metadata for "
        f"E2DM2 {published['version']} (SHA-256: {published['sha256']})"
    )


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: publish_release.py <version> <installer_path>")
        sys.exit(1)

    version = sys.argv[1].removeprefix("v")
    installer_path = Path(sys.argv[2])
    if not installer_path.is_file():
        print(f"Installer path not found: {installer_path}")
        sys.exit(1)

    token = os.environ.get("SUPABASE_RELEASE_PUBLISH_TOKEN")
    if not token:
        print("SUPABASE_RELEASE_PUBLISH_TOKEN is not set.")
        sys.exit(1)

    api_url = os.environ.get("E2DM2_RELEASE_API_URL", DEFAULT_RELEASE_API_URL)
    try:
        publish_release(version, installer_path, token, api_url)
    except Exception as error:
        print(f"Could not publish release metadata: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
