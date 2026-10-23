"""Audio clips for the demo video: your recording if present, else Amazon Polly, else macOS ``say``.

    uv run python scripts/video/tts.py prepare      # narration + user lines → out/audio/*.wav, durations.json
    uv run python scripts/video/tts.py alexa ID "text"   # one Alexa reply → out/audio/ID.wav, prints seconds

Voices: Alexa = Polly ``Joanna`` (generative, falls back to neural); placeholders for you = ``Matthew``.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).parent
OUT = HERE / "out" / "audio"
RECORDED = HERE / "audio"
VOICES = {"alexa": ("Joanna", "Samantha"), "user": ("Matthew", "Alex"), "narrator": ("Matthew", "Daniel")}


def seconds(path: Path) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(probe.stdout.strip())


def to_wav(src: Path, dest: Path) -> None:
    """48 kHz mono, loudness-normalised, so every clip sits at the same level."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", "48000",
         "-af", "loudnorm=I=-18:TP=-2:LRA=11", str(dest)],
        check=True,
    )  # fmt: skip


def polly(text: str, voice: str, dest: Path) -> bool:
    try:
        import boto3

        client = boto3.client("polly", region_name="us-east-1")
        for engine in ("generative", "neural"):
            try:
                audio = client.synthesize_speech(Text=text, VoiceId=voice, Engine=engine, OutputFormat="mp3")
                dest.write_bytes(audio["AudioStream"].read())
                return True
            except client.exceptions.EngineNotSupportedException:
                continue
            except Exception as error:  # noqa: BLE001 — try the next engine, then fall back to `say`
                if "AccessDenied" in str(error) or "Unrecognized" in str(error):
                    return False
                continue
    except Exception:  # noqa: BLE001
        return False
    return False


def synth(clip_id: str, text: str, role: str) -> float:
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"{clip_id}.wav"
    recorded = next((p for p in RECORDED.glob(f"{clip_id}.*") if p.suffix in {".m4a", ".wav", ".mp3", ".aiff"}), None)
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.mp3"
        if recorded is not None:
            raw = recorded
        elif not polly(text, VOICES[role][0], raw):
            raw = Path(tmp) / "raw.aiff"
            for voice in (VOICES[role][1], "Samantha"):  # `say` sometimes hangs on a voice; retry once
                try:
                    subprocess.run(["say", "-v", voice, "-r", "185", "-o", str(raw), text], check=True, timeout=20)
                    break
                except subprocess.TimeoutExpired:
                    continue
        to_wav(raw, dest)
    return seconds(dest)


def prepare() -> None:
    if polly("test", "Joanna", Path(tempfile.gettempdir()) / "polly-check.mp3") is False:
        print("Polly unavailable: using macOS `say` placeholders")
    shots = yaml.safe_load((HERE / "shots.yaml").read_text())
    durations: dict[str, float] = {}
    for name, slide in shots["slides"].items():
        durations[f"n_{name}"] = synth(f"n_{name}", slide["narration"], "narrator")
    for turn in shots["turns"]:
        if "say" in turn:
            durations[turn["id"]] = synth(turn["id"], turn["say"], "user")
        if "after" in turn:
            durations[f"n_{turn['id']}"] = synth(f"n_{turn['id']}", turn["after"], "narrator")
    (HERE / "out" / "durations.json").write_text(json.dumps(durations, indent=1))
    recorded = sorted(p.stem for p in RECORDED.glob("*")) if RECORDED.exists() else []
    print(f"{len(durations)} clips; your recordings used: {recorded or 'none'}")


if __name__ == "__main__":
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is required")
    if sys.argv[1] == "prepare":
        prepare()
    elif sys.argv[1] == "alexa":
        print(f"{synth(sys.argv[2], sys.argv[3], 'alexa'):.3f}")
    os.environ.setdefault("AWS_REGION", "us-east-1")
