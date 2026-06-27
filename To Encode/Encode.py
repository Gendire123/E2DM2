"""Legacy console launcher for E2DM2.

The rendering implementation lives in the e2dm2 package. This launcher keeps a
simple console workflow for existing users without moving or modifying originals.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from e2dm2.catalog import FULL_LENGTH_TRACKS
from e2dm2.models import ExportSize, RenderRequest, WorkflowMode
from e2dm2.project import create_project, import_media
from e2dm2.render import create_render_plan, render


WATCH_FOLDER = Path(__file__).resolve().parent


def choose(prompt: str, maximum: int, default: int = 1) -> int:
    while True:
        value = input(prompt).strip()
        if not value:
            return default
        if value.isdigit() and 1 <= int(value) <= maximum:
            return int(value)
        print(f"Enter a number from 1 to {maximum}.")


def main() -> None:
    print("Easy Epic Drone Movie Maker (E2DM2)")
    print("1. Epic Montage 1")
    print("2. Epic Montage 2")
    print("3. Full-length video")
    mode = choose("Video type [1-3, Enter for 1]\n> ", 3)
    name = input("Project name\n> ").strip() or "Drone Project"
    project = create_project(name)
    videos = sorted(
        (path for path in WATCH_FOLDER.iterdir() if path.suffix.lower() in {".mp4", ".mov", ".m4v"}),
        key=lambda path: path.name.casefold(),
    )
    if not videos:
        print(f"No video files found in {WATCH_FOLDER}")
        return
    print(f"Copying {len(videos)} clip(s) into {project.path}...")
    import_media(project.path, project.settings, videos)
    if mode in {1, 2}:
        request = RenderRequest(
            WorkflowMode.EPIC_MONTAGE,
            [ExportSize.SOURCE],
            song_id=f"epic-montage-{mode}",
        )
    else:
        print("Choose soundtrack:")
        for index, track in enumerate(FULL_LENGTH_TRACKS, 1):
            print(f"{index}. {track.title} - {track.description}")
        track_index = choose("Soundtrack [1-4, Enter for 1]\n> ", len(FULL_LENGTH_TRACKS))
        request = RenderRequest(
            WorkflowMode.FULL_LENGTH,
            [ExportSize.SOURCE],
            full_length_track_id=FULL_LENGTH_TRACKS[track_index - 1].track_id,
        )
    plan = create_render_plan(project, request)
    result = render(
        plan,
        lambda event: print(f"{event.message}: {event.percent:.1f}%") if event.percent is not None else print(event.message),
    )
    for output in result.outputs:
        print(f"Created: {output.output_path}" if output.success else f"Failed: {output.error}")


if __name__ == "__main__":
    main()
