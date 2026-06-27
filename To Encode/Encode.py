import subprocess
import time
import shutil
import json
import re
from pathlib import Path
from datetime import datetime
from fractions import Fraction


# =========================
# CONFIGURATION
# =========================

WATCH_FOLDER = Path(r"C:\Users\Félix\Desktop\Drone\To Encode")
OUTPUT_FOLDER = Path(r"E:\Drone Footage")
ARCHIVE_FOLDER = WATCH_FOLDER / "_processed_originals"

MUSIC_OPTIONS = [
    {
        "path": Path(r"C:\Users\Félix\Desktop\Drone\dronemusic1.m4a"),
        "description": "Piano, relaxing, easy listening.",
    },
    {
        "path": Path(r"C:\Users\Félix\Desktop\Drone\dronemusic2.m4a"),
        "description": "Interstellar Theme",
    },
    {
        "path": Path(r"C:\Users\Félix\Desktop\Drone\dronemusic3.m4a"),
        "description": "Inception Theme",
    },
    {
        "path": Path(r"C:\Users\Félix\Desktop\Drone\dronemusic4.m4a"),
        "description": "Relaxing Strings Music",
    },
]

MUSIC_FILE = MUSIC_OPTIONS[0]["path"]
EPIC_MUSIC_FILE = Path(r"C:\Users\Félix\Desktop\Drone\EpicMusic.m4a")
EPIC_MUSIC_2_FILE = Path(r"C:\Users\Félix\Desktop\Drone\EpicMusic2.m4a")

PRODUCTION_MODE_DEFAULT = "default"
PRODUCTION_MODE_MONTAGE = "montage"
PRODUCTION_MODE_BOTH = "both"
PRODUCTION_MODE_MONTAGE_2 = "montage_2"

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}

QUIET_TIME_SECONDS = 1
RECURSIVE = False

TARGET_SIZE_RATIO = 0.35

AMD_QUALITY = "quality"

ADD_MUSIC = True
MUSIC_FADE_IN_SECONDS = 5
MUSIC_FADE_OUT_SECONDS = 10
MUSIC_AUDIO_BITRATE = "192k"

VIDEO_FADE_IN_SECONDS = 3
VIDEO_FADE_OUT_SECONDS = 8

MONTAGE_TOTAL_DURATION_SECONDS = 150
MONTAGE_OPENING_SECONDS = 10
MONTAGE_SEQUENCE_DURATION_SECONDS = MONTAGE_TOTAL_DURATION_SECONDS
MONTAGE_CUTS_END_SECONDS = 145
MONTAGE_FADE_OUT_SECONDS = 5
MONTAGE_MUSIC_DURATION_SECONDS = MONTAGE_TOTAL_DURATION_SECONDS
MONTAGE_ESCALATION_CUE_SECONDS = 108
MONTAGE_DARK_CUE_START_SECONDS = 92.091
MONTAGE_DARK_CUE_END_SECONDS = 97
MONTAGE_DARK_CUE_FADE_OUT_SECONDS = 1
MONTAGE_DARK_CUE_OPACITY = 0.80
MONTAGE_EPIC_FLASH_START_SECONDS = 98.127
MONTAGE_EPIC_FLASH_DURATION_SECONDS = 1
MONTAGE_EPIC_FLASH_FADE_IN_SECONDS = 0.35
MONTAGE_EPIC_FLASH_OPACITY = 0.90
MONTAGE_TRANSITION_SECONDS = 0.25
MONTAGE_HARD_CUT_THRESHOLD_SECONDS = 2
MONTAGE_CUT_TIMES_SECONDS = [
    0,
    13.427,
    24.726,
    36.035,
    47.295,
    52.967,
    58.597,
    68.478,
    68.663,
    68.993,
    69.535,
    69.906,
    81.188,
    86.832,
    87.353,
    91.082,
    91.247,
    91.611,
    92.091,
    98.127,
    109.422,
    119.303,
    119.481,
    119.824,
    120.188,
    120.690,
    126.395,
    131.995,
    143.287,
]
MONTAGE_SEGMENT_COUNT = len(MONTAGE_CUT_TIMES_SECONDS)
MONTAGE_MIN_CLIP_SECONDS = 0.1
MONTAGE_MIN_SOURCE_DURATION_SECONDS = 180

MONTAGE_2_TOTAL_DURATION_SECONDS = 227
MONTAGE_2_CUT_TIMES_SECONDS = [
    0,
    9.238882,
    17.947152,
    35.467734,
    44.280046,
    52.977912,
    61.592545,
    66.003902,
    67.314825,
    67.678970,
    67.928670,
    68.209581,
    69.603737,
    69.832628,
    70.134348,
    70.394452,
    71.455675,
    71.736587,
    72.059115,
    72.340027,
    72.558514,
    73.380442,
    73.640546,
    73.931862,
    74.212774,
    74.420857,
    74.753789,
    76.938660,
    77.500484,
    79.144339,
    79.716567,
    81.308401,
    81.870225,
    83.482868,
    84.065500,
    85.678143,
    94.448838,
    103.146704,
    111.782145,
    113.967016,
    114.570456,
    116.172695,
    116.755327,
    118.399182,
    118.877773,
    120.521628,
    121.062643,
    122.113462,
    122.820944,
    124.922582,
    125.546830,
    127.117856,
    127.679680,
    131.508406,
    140.185464,
    144.555205,
    145.075412,
    149.070604,
    153.253071,
    166.424720,
    175.143394,
    183.862069,
    196.888060,
    201.278609,
    203.505097,
    205.648351,
    209.997284,
    215.532289,
    216.094113,
    217.696352,
    218.258176,
    219.902031,
    220.463855,
    222.086901,
]

MONTAGE_PRESETS = {
    PRODUCTION_MODE_MONTAGE: {
        "name": "2:30 minutes montage",
        "output_suffix": "Montage_2m30",
        "music_file": EPIC_MUSIC_FILE,
        "total_duration": MONTAGE_TOTAL_DURATION_SECONDS,
        "opening_seconds": MONTAGE_OPENING_SECONDS,
        "sequence_duration": MONTAGE_SEQUENCE_DURATION_SECONDS,
        "cuts_end_seconds": MONTAGE_CUTS_END_SECONDS,
        "fade_out_seconds": MONTAGE_FADE_OUT_SECONDS,
        "music_duration": MONTAGE_MUSIC_DURATION_SECONDS,
        "escalation_cue_seconds": MONTAGE_ESCALATION_CUE_SECONDS,
        "dark_cue_start_seconds": MONTAGE_DARK_CUE_START_SECONDS,
        "dark_cue_end_seconds": MONTAGE_DARK_CUE_END_SECONDS,
        "dark_cue_fade_out_seconds": MONTAGE_DARK_CUE_FADE_OUT_SECONDS,
        "dark_cue_opacity": MONTAGE_DARK_CUE_OPACITY,
        "flash_start_seconds": MONTAGE_EPIC_FLASH_START_SECONDS,
        "flash_duration_seconds": MONTAGE_EPIC_FLASH_DURATION_SECONDS,
        "flash_fade_in_seconds": MONTAGE_EPIC_FLASH_FADE_IN_SECONDS,
        "flash_opacity": MONTAGE_EPIC_FLASH_OPACITY,
        "transition_seconds": MONTAGE_TRANSITION_SECONDS,
        "hard_cut_threshold_seconds": MONTAGE_HARD_CUT_THRESHOLD_SECONDS,
        "cut_times": MONTAGE_CUT_TIMES_SECONDS,
        "min_source_duration_seconds": MONTAGE_MIN_SOURCE_DURATION_SECONDS,
        "short_cut_threshold_seconds": 5,
        "short_cut_source_advance_seconds": 1,
        "heartbeat_times": [],
        "heartbeat_opacity": 0,
        "heartbeat_fade_seconds": 0,
    },
    PRODUCTION_MODE_MONTAGE_2: {
        "name": "Epic montage 2 (3:47)",
        "output_suffix": "Epic_Montage_2_3m47",
        "music_file": EPIC_MUSIC_2_FILE,
        "total_duration": MONTAGE_2_TOTAL_DURATION_SECONDS,
        "opening_seconds": 5,
        "sequence_duration": MONTAGE_2_TOTAL_DURATION_SECONDS,
        "cuts_end_seconds": 222.145,
        "fade_out_seconds": 4.855,
        "music_duration": MONTAGE_2_TOTAL_DURATION_SECONDS,
        "escalation_cue_seconds": 180.634,
        "dark_cue_start_seconds": None,
        "dark_cue_end_seconds": None,
        "dark_cue_fade_out_seconds": 0,
        "dark_cue_opacity": 0,
        "flash_start_seconds": None,
        "flash_duration_seconds": 0,
        "flash_fade_in_seconds": 0,
        "flash_opacity": 0,
        "transition_seconds": MONTAGE_TRANSITION_SECONDS,
        "hard_cut_threshold_seconds": MONTAGE_HARD_CUT_THRESHOLD_SECONDS,
        "cut_times": MONTAGE_2_CUT_TIMES_SECONDS,
        "min_source_duration_seconds": 295,
        "short_cut_threshold_seconds": 5,
        "short_cut_source_advance_seconds": 1,
        "heartbeat_times": [
            76.938660,
            77.500484,
            79.144339,
            79.716567,
            81.308401,
            81.870225,
            83.482868,
            84.065500,
            215.532289,
            216.094113,
            217.696352,
            218.258176,
            219.902031,
            220.463855,
            222.086901,
        ],
        "heartbeat_opacity": 0.20,
        "heartbeat_fade_seconds": 0.45,
    },
}

MOVE_ORIGINALS_AFTER_SUCCESS = True


# =========================
# SCRIPT LOGIC
# =========================

def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def sanitize_footage_title(text):
    text = text.strip()

    # Replace Windows-invalid filename characters with spaces
    text = re.sub(r'[<>:"/\\|?*\x00-\x1F]+', " ", text)

    # Collapse repeated spaces
    text = re.sub(r"\s+", " ", text)

    # Avoid filenames ending with periods or spaces
    text = text.strip(" ._")

    if not text:
        text = "Drone Footage"

    return text


def ask_production_mode():
    print("")
    print("What type of drone video do you want to produce?")
    print("1. Default (full length)")
    print("2. 2:30 minutes montage")
    print("3. Both default full length and 2:30 minutes montage")
    print("4. Epic montage 2 (3:47)")

    while True:
        choice = input("Video type [1-4, Enter for 1]\n> ").strip()

        if not choice or choice == "1":
            log("Production mode: Default (full length)")
            return PRODUCTION_MODE_DEFAULT

        if choice == "2":
            log("Production mode: 2:30 minutes montage")
            return PRODUCTION_MODE_MONTAGE

        if choice == "3":
            log("Production mode: Both default full length and 2:30 minutes montage")
            return PRODUCTION_MODE_BOTH

        if choice == "4":
            log("Production mode: Epic montage 2 (3:47)")
            return PRODUCTION_MODE_MONTAGE_2

        print("Please enter 1, 2, 3, or 4, or press Enter for the default.")


def ask_footage_description():
    print("")
    description = input("What is the footage about? Example: Visite de Fred\n> ")
    description = sanitize_footage_title(description)
    log(f"Footage description: {description}")
    return description


def ask_music_file():
    print("")
    print("Choose the music track:")

    for index, option in enumerate(MUSIC_OPTIONS, start=1):
        default_label = " (default)" if index == 1 else ""
        print(f"{index}. {option['description']}{default_label}")
        print(f"   {option['path']}")

    while True:
        choice = input("Music choice [1-4, Enter for 1]\n> ").strip()

        if not choice:
            selected = MUSIC_OPTIONS[0]
            break

        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(MUSIC_OPTIONS):
                selected = MUSIC_OPTIONS[index - 1]
                break

        print(f"Please enter a number from 1 to {len(MUSIC_OPTIONS)}, or press Enter for the default.")

    log(f"Music selected: {selected['description']} ({selected['path']})")
    return selected["path"]


def is_montage_mode(production_mode):
    return production_mode in MONTAGE_PRESETS or production_mode == PRODUCTION_MODE_BOTH


def montage_preset_for_mode(production_mode):
    if production_mode == PRODUCTION_MODE_BOTH:
        return MONTAGE_PRESETS[PRODUCTION_MODE_MONTAGE]

    return MONTAGE_PRESETS[production_mode]


def ensure_folders():
    WATCH_FOLDER.mkdir(parents=True, exist_ok=True)
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    ARCHIVE_FOLDER.mkdir(parents=True, exist_ok=True)


def check_tool(tool_name):
    try:
        subprocess.run(
            [tool_name, "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
        return True
    except Exception:
        return False


def check_h264_amf():
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        encoders_output = result.stdout + result.stderr
        return "h264_amf" in encoders_output

    except Exception:
        return False


def is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def get_video_files():
    pattern = "**/*" if RECURSIVE else "*"
    files = []

    for path in WATCH_FOLDER.glob(pattern):
        if not path.is_file():
            continue

        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue

        if path.name.lower().endswith(".tmp.mp4"):
            continue

        if is_inside(path, ARCHIVE_FOLDER):
            continue

        if is_inside(path, OUTPUT_FOLDER):
            continue

        files.append(path)

    files.sort(key=lambda p: p.name.lower())
    return files


def folder_signature(files):
    signature = {}

    for file in files:
        try:
            stat = file.stat()
            signature[str(file)] = (stat.st_size, stat.st_mtime)
        except FileNotFoundError:
            continue

    return signature


def wait_until_files_are_stable(video_files):
    if not video_files:
        return False

    log(f"Waiting {QUIET_TIME_SECONDS} second(s) to make sure files are stable...")

    first_signature = folder_signature(video_files)
    time.sleep(QUIET_TIME_SECONDS)
    second_signature = folder_signature(video_files)

    return first_signature == second_signature


def parse_fps(rate_text):
    if not rate_text or rate_text == "0/0":
        return 0.0

    try:
        return float(Fraction(rate_text))
    except Exception:
        return 0.0


def fps_bucket(fps):
    if 58 <= fps <= 62:
        return "60fps"

    if 28 <= fps <= 31:
        return "30fps"

    if 23 <= fps <= 25:
        return "24fps"

    if fps > 0:
        return f"{round(fps)}fps"

    return "unknownfps"


def fps_display(fps):
    if abs(fps - 29.97) < 0.05:
        return "29.97"

    if abs(fps - 59.94) < 0.05:
        return "59.94"

    if fps > 0:
        return f"{fps:.2f}"

    return "unknown"


def resolution_label(width, height):
    pixels = width * height

    if width >= 3800 or height >= 2100:
        return "4K"

    if width >= 2600 or height >= 1450:
        return "2.7K"

    if width >= 1900 or height >= 1000:
        return "1080p"

    return f"{width}x{height}"


def safe_label(text):
    text = text.replace(".", "p")
    text = re.sub(r"[^A-Za-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def get_video_info(video_file):
    command = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name,avg_frame_rate,r_frame_rate,bit_rate,duration",
        "-show_entries", "format=duration,size,bit_rate",
        "-of", "json",
        str(video_file)
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        log(f"Could not read video info: {video_file.name}")
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        log(f"Could not parse video info: {video_file.name}")
        return None

    streams = data.get("streams", [])
    if not streams:
        log(f"No video stream found: {video_file.name}")
        return None

    stream = streams[0]
    fmt = data.get("format", {})

    width = int(stream.get("width", 0))
    height = int(stream.get("height", 0))

    fps = parse_fps(stream.get("avg_frame_rate"))
    if fps <= 0:
        fps = parse_fps(stream.get("r_frame_rate"))

    try:
        duration = float(fmt.get("duration", 0))
    except Exception:
        duration = 0.0

    try:
        size_bytes = int(fmt.get("size", video_file.stat().st_size))
    except Exception:
        size_bytes = video_file.stat().st_size

    codec = stream.get("codec_name", "unknown")

    label = resolution_label(width, height)
    fps_label = fps_bucket(fps)

    return {
        "path": video_file,
        "width": width,
        "height": height,
        "fps": fps,
        "fps_display": fps_display(fps),
        "fps_bucket": fps_label,
        "duration": duration,
        "size_bytes": size_bytes,
        "codec": codec,
        "resolution_label": label,
        "group_key": f"{width}x{height}_{fps_label}"
    }


def group_videos_by_type(video_files):
    groups = {}

    for video_file in video_files:
        info = get_video_info(video_file)

        if info is None:
            continue

        key = info["group_key"]

        if key not in groups:
            groups[key] = []

        groups[key].append(info)

    return groups


def get_encoding_limits(first_info):
    width = first_info["width"]
    height = first_info["height"]
    fps = first_info["fps"]

    pixels = width * height

    if pixels >= 8_000_000 and fps > 50:
        return 25000, 60000

    if pixels >= 8_000_000:
        return 18000, 45000

    if pixels >= 3_500_000 and fps > 50:
        return 16000, 40000

    if pixels >= 3_500_000:
        return 12000, 30000

    if pixels >= 1_900_000 and fps > 50:
        return 8000, 22000

    if pixels >= 1_900_000:
        return 6000, 16000

    return 3000, 10000


def calculate_target_bitrate_kbps(video_infos):
    total_size_bytes = sum(info["size_bytes"] for info in video_infos)
    total_duration_seconds = sum(info["duration"] for info in video_infos)

    if total_duration_seconds <= 0:
        log("Could not calculate duration. Using fallback bitrate: 25000k.")
        return 25000

    original_bitrate_kbps = (total_size_bytes * 8) / total_duration_seconds / 1000
    target_bitrate_kbps = int(original_bitrate_kbps * TARGET_SIZE_RATIO)

    min_kbps, max_kbps = get_encoding_limits(video_infos[0])

    unclamped_target = target_bitrate_kbps
    target_bitrate_kbps = max(min_kbps, target_bitrate_kbps)
    target_bitrate_kbps = min(max_kbps, target_bitrate_kbps)

    log(f"Estimated original average bitrate: {int(original_bitrate_kbps)} kbps")
    log(f"Target size ratio: {int(TARGET_SIZE_RATIO * 100)}%")
    log(f"Initial target bitrate: {unclamped_target} kbps")
    log(f"Final target H.264 bitrate: {target_bitrate_kbps} kbps")

    return target_bitrate_kbps


def write_concat_file(video_infos, concat_file):
    with concat_file.open("w", encoding="utf-8") as f:
        for info in video_infos:
            video = info["path"]
            safe_path = str(video.resolve()).replace("\\", "/").replace("'", "\\'")
            f.write(f"file '{safe_path}'\n")


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent

    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def move_originals_to_archive(video_infos):
    for info in video_infos:
        original = info["path"]
        destination = unique_path(ARCHIVE_FOLDER / original.name)
        shutil.move(str(original), str(destination))

    log("Original files for this group moved to archive folder.")


def build_video_filter(video_duration):
    fade_in = VIDEO_FADE_IN_SECONDS
    fade_out = VIDEO_FADE_OUT_SECONDS

    if video_duration <= 0:
        video_duration = 1

    fade_out_start = max(video_duration - fade_out, 0)

    if video_duration < fade_in + fade_out:
        fade_in = min(fade_in, video_duration / 3)
        fade_out = min(fade_out, video_duration / 3)
        fade_out_start = max(video_duration - fade_out, 0)

    return (
        f"fade=t=in:st=0:d={fade_in:.3f},"
        f"fade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f},"
        f"format=yuv420p"
    )


def build_audio_filter(video_duration):
    fade_in = MUSIC_FADE_IN_SECONDS
    fade_out = MUSIC_FADE_OUT_SECONDS

    if video_duration <= 0:
        video_duration = 1

    fade_out_start = max(video_duration - fade_out, 0)

    if video_duration < fade_in + fade_out:
        fade_in = min(fade_in, video_duration / 3)
        fade_out = min(fade_out, video_duration / 3)
        fade_out_start = max(video_duration - fade_out, 0)

    return (
        f"[1:a]"
        f"atrim=0:{video_duration:.3f},"
        f"asetpts=N/SR/TB,"
        f"afade=t=in:st=0:d={fade_in:.3f},"
        f"afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}"
        f"[musicout]"
    )


def build_ffmpeg_command(concat_file, temp_output_file, target_bitrate_kbps, video_info, video_duration):
    maxrate_kbps = target_bitrate_kbps
    bufsize_kbps = int(target_bitrate_kbps * 2.0)

    fps = video_info["fps"]

    if fps > 0:
        gop_size = int(round(fps * 2))
    else:
        gop_size = 60

    video_filter = build_video_filter(video_duration)

    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",

        "-fflags", "+genpts",
        "-analyzeduration", "200M",
        "-probesize", "200M",

        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
    ]

    if ADD_MUSIC:
        command.extend([
            "-stream_loop", "-1",
            "-i", str(MUSIC_FILE),
        ])

    command.extend([
        "-map", "0:v:0",
        "-sn",
        "-dn",

        "-vf", video_filter,

        "-c:v", "h264_amf",
        "-quality", AMD_QUALITY,

        "-profile:v", "high",
        "-level", "5.2",

        "-rc", "cbr",
        "-b:v", f"{target_bitrate_kbps}k",
        "-maxrate", f"{maxrate_kbps}k",
        "-bufsize", f"{bufsize_kbps}k",

        "-g", str(gop_size),

        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
    ])

    if ADD_MUSIC:
        audio_filter = build_audio_filter(video_duration)

        command.extend([
            "-filter_complex", audio_filter,
            "-map", "[musicout]",
            "-c:a", "aac",
            "-b:a", MUSIC_AUDIO_BITRATE,
            "-shortest",
        ])
    else:
        command.extend([
            "-an"
        ])

    command.append(str(temp_output_file))

    return command


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def ffmpeg_fps_value(fps):
    if abs(fps - 29.97) < 0.05:
        return "30000/1001"

    if abs(fps - 59.94) < 0.05:
        return "60000/1001"

    if fps > 0:
        return f"{fps:.3f}"

    return "30"


def montage_zoom_filter(width, height, zoom):
    if zoom <= 1:
        return None

    zoom_width = int(round((width * zoom) / 2) * 2)
    zoom_height = int(round((height * zoom) / 2) * 2)

    return f"scale={zoom_width}:{zoom_height},crop={width}:{height}"


def montage_color_filters(style):
    if style == "sepia":
        return [
            "colorchannelmixer=rr=.393:rg=.769:rb=.189:gr=.349:gg=.686:gb=.168:br=.272:bg=.534:bb=.131",
        ]

    return []


def build_montage_segment_plan(video_duration, preset):
    segment_count = len(preset["cut_times"])
    transition_count = segment_count - 1
    cut_times = preset["cut_times"] + [preset["sequence_duration"]]
    visible_durations = [
        cut_times[index + 1] - cut_times[index]
        for index in range(segment_count)
    ]
    transition_durations = []
    output_durations = []

    for index in range(segment_count):
        if index < transition_count:
            adjacent_short_clip = (
                visible_durations[index] < preset["hard_cut_threshold_seconds"]
                or visible_durations[index + 1] < preset["hard_cut_threshold_seconds"]
            )
            transition_duration = 0 if adjacent_short_clip else preset["transition_seconds"]
        else:
            transition_duration = 0

        transition_durations.append(transition_duration)
        output_durations.append(visible_durations[index] + transition_duration)

    if min(output_durations) < MONTAGE_MIN_CLIP_SECONDS:
        raise ValueError("Montage clip timing produced a clip shorter than the configured minimum.")

    visible_starts = []
    visible_cursor = 0.0

    for index, duration in enumerate(output_durations):
        visible_starts.append(visible_cursor)
        visible_cursor += duration - transition_durations[index]

    cue_time_in_montage = preset["escalation_cue_seconds"]
    cue_index = min(
        range(segment_count),
        key=lambda index: abs(
            visible_starts[index] + (output_durations[index] / 2) - cue_time_in_montage
        )
    )

    plan = []
    color_styles = ["natural", "natural", "natural", "natural", "sepia", "natural", "natural", "natural", "natural", "natural"]
    speed_pattern = [1.0, 1.0, 1.0, 1.15, 1.0, 1.0, 1.0, 1.0, 1.0, 1.25, 1.0, 1.0]
    source_durations = [
        output_duration * speed_pattern[index % len(speed_pattern)]
        for index, output_duration in enumerate(output_durations)
    ]
    total_source_clip_duration = sum(source_durations)
    short_cut_threshold = preset["short_cut_threshold_seconds"]
    short_source_advance = preset["short_cut_source_advance_seconds"]
    fixed_gap_count = 0

    if short_cut_threshold is not None:
        fixed_gap_count = sum(
            1
            for index in range(segment_count - 1)
            if visible_durations[index] < short_cut_threshold
        )

    fixed_gap_time = fixed_gap_count * (short_source_advance or 0)
    flexible_gap_count = max((segment_count - 1) - fixed_gap_count, 0)
    available_gap_time = max(video_duration - total_source_clip_duration - fixed_gap_time - 0.5, 0)
    source_gap = available_gap_time / max(flexible_gap_count, 1)
    source_cursor = 0.0

    for index, output_duration in enumerate(output_durations):
        progress = index / max(segment_count - 1, 1)
        source_duration = source_durations[index]
        source_start = source_cursor
        source_end = source_start + source_duration

        if source_end > video_duration:
            raise ValueError(
                "Montage source timing reached the end of the available footage before all cuts were planned. "
                "Add more source footage or reduce the montage duration."
            )

        speed = source_duration / output_duration

        if index == cue_index:
            speed = min(speed, 1.15)

        plan.append({
            "index": index,
            "source_start": source_start,
            "source_duration": source_duration,
            "output_duration": output_duration,
            "speed": speed,
            "style": color_styles[index % len(color_styles)],
            "zoom": 1.045 if index % 3 != 1 else 1.0,
            "flash": False,
            "motion_blur": progress > 0.45 and index % 5 == 0,
            "cue": index == cue_index,
            "visible_start": visible_starts[index],
            "visible_duration": visible_durations[index],
            "transition_after": transition_durations[index],
        })

        if index == segment_count - 1:
            source_cursor = source_end
        elif short_cut_threshold is not None and visible_durations[index] < short_cut_threshold:
            source_cursor = source_end + short_source_advance
        else:
            source_cursor = source_end + source_gap

    return plan


def build_montage_filter_script(video_info, video_duration, filter_script_file, preset):
    width = video_info["width"]
    height = video_info["height"]
    fps_value = ffmpeg_fps_value(video_info["fps"])
    segment_plan = build_montage_segment_plan(video_duration, preset)

    split_labels = [f"[v{segment['index']}]" for segment in segment_plan]

    filters = [
        f"[0:v]split={len(split_labels)}{''.join(split_labels)}"
    ]

    for segment in segment_plan:
        segment_filters = [
            f"[v{segment['index']}]trim=start={segment['source_start']:.3f}:duration={segment['source_duration']:.3f}",
            f"setpts=(PTS-STARTPTS)/{segment['speed']:.3f}",
            f"fps={fps_value}",
            "settb=AVTB",
        ]

        zoom_filter = montage_zoom_filter(width, height, segment["zoom"])
        if zoom_filter:
            segment_filters.append(zoom_filter)

        segment_filters.extend(montage_color_filters(segment["style"]))

        if segment["motion_blur"]:
            segment_filters.append("tmix=frames=3:weights='1 2 1'")

        segment_filters.extend([
            "setsar=1",
            "format=yuv420p",
        ])

        filters.append(
            ",".join(segment_filters)
            + f"[s{segment['index']}]"
        )

    current_label = "s0"
    current_duration = segment_plan[0]["output_duration"]

    for segment in segment_plan[1:]:
        previous_segment = segment_plan[segment["index"] - 1]
        transition_duration = previous_segment["transition_after"]
        output_label = f"x{segment['index']}"

        if transition_duration > 0:
            offset = max(current_duration - transition_duration, 0)

            filters.append(
                f"[{current_label}][s{segment['index']}]"
                f"xfade=transition=fade:"
                f"duration={transition_duration:.3f}:"
                f"offset={offset:.3f}"
                f",settb=AVTB"
                f"[{output_label}]"
            )
        else:
            filters.append(
                f"[{current_label}][s{segment['index']}]"
                f"concat=n=2:v=1:a=0,"
                f"settb=AVTB"
                f"[{output_label}]"
            )

        current_duration += segment["output_duration"] - transition_duration
        current_label = output_label

    filters.append(
        f"[{current_label}]"
        f"fade=t=in:st=0:d={preset['opening_seconds']:.3f},"
        f"fade=t=out:st={preset['cuts_end_seconds']:.3f}:d={preset['fade_out_seconds']:.3f},"
        f"format=yuv420p"
        f"[basevideo]"
    )

    video_label = "basevideo"

    if preset["dark_cue_start_seconds"] is not None:
        dark_cue_fade_out_start = preset["dark_cue_end_seconds"]
        dark_cue_end = preset["dark_cue_end_seconds"] + preset["dark_cue_fade_out_seconds"]

        filters.append(
            f"color=c=black@{preset['dark_cue_opacity']:.2f}:s={width}x{height}:d={preset['total_duration']:.3f},"
            f"format=yuva420p,"
            f"fade=t=in:st={preset['dark_cue_start_seconds']:.3f}:d={preset['dark_cue_end_seconds'] - preset['dark_cue_start_seconds']:.3f}:alpha=1,"
            f"fade=t=out:st={dark_cue_fade_out_start:.3f}:d={preset['dark_cue_fade_out_seconds']:.3f}:alpha=1"
            f"[darkcue]"
        )

        filters.append(
            f"[{video_label}][darkcue]"
            f"overlay=shortest=1:enable='between(t\\,{preset['dark_cue_start_seconds']:.3f}\\,{dark_cue_end:.3f})'"
            f"[darkvideo]"
        )
        video_label = "darkvideo"

    for heartbeat_index, heartbeat_time in enumerate(preset["heartbeat_times"]):
        heartbeat_label = f"heartbeat{heartbeat_index}"
        heartbeat_video_label = f"heartbeatvideo{heartbeat_index}"
        heartbeat_end = heartbeat_time + preset["heartbeat_fade_seconds"]

        filters.append(
            f"color=c=black@{preset['heartbeat_opacity']:.2f}:s={width}x{height}:d={preset['total_duration']:.3f},"
            f"format=yuva420p,"
            f"fade=t=out:st={heartbeat_time:.6f}:d={preset['heartbeat_fade_seconds']:.3f}:alpha=1"
            f"[{heartbeat_label}]"
        )

        filters.append(
            f"[{video_label}][{heartbeat_label}]"
            f"overlay=shortest=1:enable='between(t\\,{heartbeat_time:.6f}\\,{heartbeat_end:.6f})',"
            f"format=yuv420p"
            f"[{heartbeat_video_label}]"
        )
        video_label = heartbeat_video_label

    if preset["flash_start_seconds"] is not None:
        flash_fade_out_start = preset["flash_start_seconds"] + preset["flash_fade_in_seconds"]
        flash_end = preset["flash_start_seconds"] + preset["flash_duration_seconds"]

        filters.append(
            f"color=c=white@{preset['flash_opacity']:.2f}:s={width}x{height}:d={preset['total_duration']:.3f},"
            f"format=yuva420p,"
            f"fade=t=in:st={preset['flash_start_seconds']:.3f}:d={preset['flash_fade_in_seconds']:.3f}:alpha=1,"
            f"fade=t=out:st={flash_fade_out_start:.3f}:d={flash_end - flash_fade_out_start:.3f}:alpha=1"
            f"[whiteflash]"
        )

        filters.append(
            f"[{video_label}][whiteflash]"
            f"overlay=shortest=1:enable='between(t\\,{preset['flash_start_seconds']:.3f}\\,{flash_end:.3f})',"
            f"format=yuv420p"
            f"[videoout]"
        )
    else:
        filters.append(
            f"[{video_label}]"
            f"format=yuv420p"
            f"[videoout]"
        )

    music_fade_start = preset["music_duration"] - preset["fade_out_seconds"]

    filters.append(
        f"[1:a]"
        f"atrim=start=0:duration={preset['music_duration']:.3f},"
        f"asetpts=N/SR/TB,"
        f"afade=t=out:st={music_fade_start:.3f}:d={preset['fade_out_seconds']:.3f},"
        f"aformat=sample_rates=48000:channel_layouts=stereo"
        f"[musicout]"
    )

    filter_script_file.write_text(";\n".join(filters), encoding="utf-8")

    return segment_plan


def build_montage_ffmpeg_command(concat_file, filter_script_file, temp_output_file, target_bitrate_kbps, video_info, preset):
    maxrate_kbps = target_bitrate_kbps
    bufsize_kbps = int(target_bitrate_kbps * 2.0)
    fps_value = ffmpeg_fps_value(video_info["fps"])
    fps = video_info["fps"]

    if fps > 0:
        gop_size = int(round(fps * 2))
    else:
        gop_size = 60

    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",

        "-fflags", "+genpts",
        "-analyzeduration", "200M",
        "-probesize", "200M",

        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),

        "-stream_loop", "-1",
        "-i", str(preset["music_file"]),

        "-filter_complex_script", str(filter_script_file),
        "-map", "[videoout]",
        "-map", "[musicout]",
        "-sn",
        "-dn",
        "-t", f"{preset['total_duration']:.3f}",

        "-r", fps_value,
        "-c:v", "h264_amf",
        "-quality", AMD_QUALITY,

        "-profile:v", "high",
        "-level", "5.2",

        "-rc", "cbr",
        "-b:v", f"{target_bitrate_kbps}k",
        "-maxrate", f"{maxrate_kbps}k",
        "-bufsize", f"{bufsize_kbps}k",

        "-g", str(gop_size),

        "-c:a", "aac",
        "-b:a", MUSIC_AUDIO_BITRATE,
        "-shortest",

        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",

        str(temp_output_file)
    ]

    return command


def process_group(group_name, video_infos, footage_description, move_originals_after_success=True):
    if not video_infos:
        return False

    first_info = video_infos[0]

    date_label = datetime.now().strftime("%Y-%m-%d")
    timestamp_for_temp_files = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    format_label = first_info["resolution_label"].replace(".", "p")
    format_label = safe_label(format_label)

    # New filename format:
    # 2026-06-17_Visite de Fred_4K.mp4
    output_file = OUTPUT_FOLDER / f"{date_label}_{footage_description}_{format_label}.mp4"

    temp_output_file = OUTPUT_FOLDER / f"{timestamp_for_temp_files}_{format_label}.tmp.mp4"
    concat_file = OUTPUT_FOLDER / f"concat_{timestamp_for_temp_files}_{format_label}.txt"

    log("")
    log("========================================")
    log(f"Processing group: {format_label}")
    log(f"Output filename: {output_file.name}")
    log(f"Resolution: {first_info['width']}x{first_info['height']}")
    log(f"Framerate: {first_info['fps_display']} fps")
    log(f"Codec source: {first_info['codec']}")
    log(f"Files in this group: {len(video_infos)}")
    log("========================================")

    for info in video_infos:
        log(f"  - {info['path'].name}")

    original_total_size = sum(info["size_bytes"] for info in video_infos)
    video_duration = sum(info["duration"] for info in video_infos)

    log(f"Estimated final video duration: {video_duration:.2f} seconds")
    log(f"Video fade in: {VIDEO_FADE_IN_SECONDS} seconds")
    log(f"Video fade out: {VIDEO_FADE_OUT_SECONDS} seconds")

    if ADD_MUSIC:
        log(f"Music file: {MUSIC_FILE}")
        log(f"Music fade in: {MUSIC_FADE_IN_SECONDS} seconds")
        log(f"Music fade out: {MUSIC_FADE_OUT_SECONDS} seconds")

    target_bitrate_kbps = calculate_target_bitrate_kbps(video_infos)

    write_concat_file(video_infos, concat_file)

    command = build_ffmpeg_command(
        concat_file,
        temp_output_file,
        target_bitrate_kbps,
        first_info,
        video_duration
    )

    log("Starting FFmpeg merge, video fade, music fade, and AMD GPU H.264 encoding...")
    result = subprocess.run(command)

    concat_file.unlink(missing_ok=True)

    if result.returncode != 0:
        log("FFmpeg failed. Originals were not moved for this group.")
        temp_output_file.unlink(missing_ok=True)
        return False

    if output_file.exists():
        output_file = unique_path(output_file)

    temp_output_file.rename(output_file)

    final_size = output_file.stat().st_size

    log(f"Created: {output_file}")
    log(f"Original group size: {original_total_size / (1024 ** 3):.2f} GB")
    log(f"Final file size: {final_size / (1024 ** 3):.2f} GB")
    log(f"Final size ratio: {(final_size / original_total_size) * 100:.1f}%")

    if MOVE_ORIGINALS_AFTER_SUCCESS and move_originals_after_success:
        move_originals_to_archive(video_infos)
    else:
        log("Original files were left in place.")

    log("Group done.")
    return True


def process_montage_group(group_name, video_infos, footage_description, preset, move_originals_after_success=True):
    if not video_infos:
        return False

    first_info = video_infos[0]

    date_label = datetime.now().strftime("%Y-%m-%d")
    timestamp_for_temp_files = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    format_label = first_info["resolution_label"].replace(".", "p")
    format_label = safe_label(format_label)

    output_file = OUTPUT_FOLDER / f"{date_label}_EPIC_Edition_{footage_description}_{preset['output_suffix']}_{format_label}.mp4"

    temp_output_file = OUTPUT_FOLDER / f"{timestamp_for_temp_files}_{format_label}_montage.tmp.mp4"
    concat_file = OUTPUT_FOLDER / f"concat_{timestamp_for_temp_files}_{format_label}_montage.txt"
    filter_script_file = OUTPUT_FOLDER / f"filter_{timestamp_for_temp_files}_{format_label}_montage.txt"

    log("")
    log("========================================")
    log(f"Processing montage group: {format_label}")
    log(f"Output filename: {output_file.name}")
    log(f"Resolution: {first_info['width']}x{first_info['height']}")
    log(f"Framerate: {first_info['fps_display']} fps")
    log(f"Codec source: {first_info['codec']}")
    log(f"Files in this group: {len(video_infos)}")
    log("========================================")

    for info in video_infos:
        log(f"  - {info['path'].name}")

    original_total_size = sum(info["size_bytes"] for info in video_infos)
    video_duration = sum(info["duration"] for info in video_infos)

    log(f"Estimated source duration: {video_duration:.2f} seconds")
    log(f"Montage preset: {preset['name']}")
    log(f"Montage final duration: {preset['total_duration']} seconds")
    log(f"Opening: first {preset['opening_seconds']} seconds fade in from black with music")
    log("Music starts at: 00:00")
    if preset["dark_cue_start_seconds"] is not None:
        log(f"Epic dark cue: {preset['dark_cue_start_seconds']:.3f} to {preset['dark_cue_end_seconds']:.3f}")
    if preset["flash_start_seconds"] is not None:
        log(
            "Epic white flash fade cue: "
            f"{preset['flash_start_seconds']:.3f} to "
            f"{preset['flash_start_seconds'] + preset['flash_duration_seconds']:.3f}"
        )
    log(f"Escalation cue: {preset['escalation_cue_seconds']} seconds")
    log(f"Fade to black starts at: {preset['cuts_end_seconds']} seconds")
    log(f"Montage music file: {preset['music_file']}")

    if video_duration < preset["min_source_duration_seconds"]:
        log(
            "ERROR: Montage mode needs at least "
            f"{preset['min_source_duration_seconds']} seconds of source video."
        )
        return False

    target_bitrate_kbps = calculate_target_bitrate_kbps(video_infos)

    write_concat_file(video_infos, concat_file)
    segment_plan = build_montage_filter_script(first_info, video_duration, filter_script_file, preset)
    source_coverage_start = segment_plan[0]["source_start"]
    source_coverage_end = segment_plan[-1]["source_start"] + segment_plan[-1]["source_duration"]

    log(f"Generated {len(segment_plan)} time-based montage clips across the source footage.")
    log(f"Source timeline coverage: {source_coverage_start:.2f} to {source_coverage_end:.2f} seconds.")

    command = build_montage_ffmpeg_command(
        concat_file,
        filter_script_file,
        temp_output_file,
        target_bitrate_kbps,
        first_info,
        preset
    )

    log("Starting FFmpeg cinematic montage edit, speed effects, transitions, and AMD GPU H.264 encoding...")
    result = subprocess.run(command)

    concat_file.unlink(missing_ok=True)
    filter_script_file.unlink(missing_ok=True)

    if result.returncode != 0:
        log("FFmpeg montage failed. Originals were not moved for this group.")
        temp_output_file.unlink(missing_ok=True)
        return False

    if output_file.exists():
        output_file = unique_path(output_file)

    temp_output_file.rename(output_file)

    final_size = output_file.stat().st_size

    log(f"Created: {output_file}")
    log(f"Original group size: {original_total_size / (1024 ** 3):.2f} GB")
    log(f"Final file size: {final_size / (1024 ** 3):.2f} GB")
    log(f"Final size ratio: {(final_size / original_total_size) * 100:.1f}%")

    if MOVE_ORIGINALS_AFTER_SUCCESS and move_originals_after_success:
        move_originals_to_archive(video_infos)
    else:
        log("Original files were left in place.")

    log("Montage group done.")
    return True


def process_videos(video_files, footage_description, production_mode):
    if not video_files:
        log("No video files found.")
        return

    if not wait_until_files_are_stable(video_files):
        log("Files are still changing. Try running the script again after the copy is complete.")
        return

    if is_montage_mode(production_mode):
        montage_preset = montage_preset_for_mode(production_mode)
        if not montage_preset["music_file"].exists():
            log(f"ERROR: Epic music file not found: {montage_preset['music_file']}")
            return
    else:
        montage_preset = None

    if production_mode in {PRODUCTION_MODE_DEFAULT, PRODUCTION_MODE_BOTH} and ADD_MUSIC and not MUSIC_FILE.exists():
        log(f"ERROR: Music file not found: {MUSIC_FILE}")
        return

    groups = group_videos_by_type(video_files)

    if not groups:
        log("No valid video groups found.")
        return

    log(f"Detected {len(groups)} video type(s).")

    if len(groups) > 1:
        log("Multiple video types detected.")
        log("The script will create one output file per type to avoid choppy mixed-resolution or mixed-fps output.")

    for group_name, video_infos in groups.items():
        if production_mode in MONTAGE_PRESETS:
            process_montage_group(group_name, video_infos, footage_description, montage_preset)
        elif production_mode == PRODUCTION_MODE_BOTH:
            full_length_success = process_group(
                group_name,
                video_infos,
                footage_description,
                move_originals_after_success=False
            )

            if not full_length_success:
                log("Skipping epic montage for this group because the full-length render failed.")
                continue

            montage_success = process_montage_group(
                group_name,
                video_infos,
                footage_description,
                montage_preset,
                move_originals_after_success=False
            )

            if montage_success and MOVE_ORIGINALS_AFTER_SUCCESS:
                move_originals_to_archive(video_infos)
            elif montage_success:
                log("Original files were left in place.")
            else:
                log("Originals were not moved because both requested outputs were not completed.")
        else:
            process_group(group_name, video_infos, footage_description)

    log("")
    log("All processing complete.")


def main():
    global MUSIC_FILE

    production_mode = ask_production_mode()

    ensure_folders()

    if not check_tool("ffmpeg"):
        log("ERROR: FFmpeg was not found.")
        log("Install FFmpeg and make sure it is available in your Windows PATH.")
        input("Press Enter to exit...")
        return

    if not check_tool("ffprobe"):
        log("ERROR: FFprobe was not found.")
        log("FFprobe normally comes with FFmpeg. Make sure it is available in your Windows PATH.")
        input("Press Enter to exit...")
        return

    if not check_h264_amf():
        log("ERROR: Your FFmpeg installation does not show h264_amf support.")
        log("Try installing a full FFmpeg build that includes AMD AMF support.")
        log('You can test manually with: ffmpeg -hide_banner -encoders | findstr /i "amf"')
        input("Press Enter to exit...")
        return

    footage_description = ask_footage_description()

    if production_mode in {PRODUCTION_MODE_DEFAULT, PRODUCTION_MODE_BOTH} and ADD_MUSIC:
        MUSIC_FILE = ask_music_file()

    log(f"Input folder: {WATCH_FOLDER}")
    log(f"Output folder: {OUTPUT_FOLDER}")
    log(f"Archive folder: {ARCHIVE_FOLDER}")
    log("Mode: process once, then exit")
    if production_mode == PRODUCTION_MODE_BOTH:
        production_type_label = "Default full length and 2:30 minutes montage"
    elif production_mode in MONTAGE_PRESETS:
        production_type_label = MONTAGE_PRESETS[production_mode]["name"]
    else:
        production_type_label = "Default full length"

    log(f"Production type: {production_type_label}")
    log("Encoder: AMD h264_amf")
    log(f"AMD quality mode: {AMD_QUALITY}")
    log(f"Target size: about {int(TARGET_SIZE_RATIO * 100)}% of original")
    log("Rate control: CBR for more predictable file size")
    log("Framerate mode: automatic, preserves source fps")

    if is_montage_mode(production_mode):
        montage_preset = montage_preset_for_mode(production_mode)
        log(f"Montage duration: {montage_preset['total_duration']} seconds")
        log(f"Montage music enabled: {montage_preset['music_file']}")
        log("Montage music starts immediately")
        if montage_preset["dark_cue_start_seconds"] is not None:
            log(
                "Montage epic dark cue: "
                f"{montage_preset['dark_cue_start_seconds']} to "
                f"{montage_preset['dark_cue_end_seconds']} seconds"
            )
        if montage_preset["flash_start_seconds"] is not None:
            log(
                "Montage epic white flash fade cue: "
                f"{montage_preset['flash_start_seconds']} to "
                f"{montage_preset['flash_start_seconds'] + montage_preset['flash_duration_seconds']} seconds"
            )
        log(f"Montage escalation cue: {montage_preset['escalation_cue_seconds']} seconds")
        log(f"Montage fade out starts at {montage_preset['cuts_end_seconds']} seconds")

    if production_mode in {PRODUCTION_MODE_DEFAULT, PRODUCTION_MODE_BOTH}:
        log(f"Video fade in: {VIDEO_FADE_IN_SECONDS} seconds")
        log(f"Video fade out: {VIDEO_FADE_OUT_SECONDS} seconds")

    if production_mode in {PRODUCTION_MODE_DEFAULT, PRODUCTION_MODE_BOTH} and ADD_MUSIC:
        log(f"Music enabled: {MUSIC_FILE}")
        log(f"Music fade in: {MUSIC_FADE_IN_SECONDS} seconds")
        log(f"Music fade out: {MUSIC_FADE_OUT_SECONDS} seconds")

    video_files = get_video_files()
    process_videos(video_files, footage_description, production_mode)


if __name__ == "__main__":
    main()
