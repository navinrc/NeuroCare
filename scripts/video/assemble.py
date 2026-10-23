"""Cut the waits out of the simulator take, add slides, and lay the audio (demo video).

    uv run python scripts/video/assemble.py        # → scripts/video/out/neurocare-demo.mp4

Inputs from record.mjs: out/sim.webm, out/events.json, out/slides/*.png; audio from tts.py.
Cuts: the model/tool wait in each turn (kept: THINK_KEEP ms of the thinking bar) and the minute
before the reminder fires. Everything shown is from the one live take.
"""

import json
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "out"
AUDIO = OUT / "audio"
FPS = 30
SLIDE_PAD = {"title": 1.0, "architecture": 1.2, "closing": 2.0}


def run(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def seconds(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return float(out.strip())


def keep_intervals(events: list[dict], think_keep: int) -> list[tuple[float, float]]:
    start = next(e["t"] for e in events if e["type"] == "start")
    end = next(e["t"] for e in events if e["type"] == "end")
    cuts: list[tuple[float, float]] = []
    for i, e in enumerate(events):
        if e["type"] == "think":
            speak = next(x for x in events[i:] if x["type"] == "speak")
            if speak["t"] - e["t"] > think_keep:
                cuts.append((e["t"] + think_keep, speak["t"] - 60))
        if e["type"] == "wait_reminder":
            fired = next(x for x in events[i:] if x["type"] == "reminder")
            cuts.append((e["t"] + 800, fired["t"] - 300))
    keep, cursor = [], start
    for a, b in sorted(cuts):
        if a > cursor:
            keep.append((cursor, a))
        cursor = max(cursor, b)
    keep.append((cursor, end))
    return [(a / 1000, b / 1000) for a, b in keep if b > a]


def mapper(keep: list[tuple[float, float]]):
    def to_out(t_ms: float) -> float:
        t, offset = t_ms / 1000, 0.0
        for a, b in keep:
            if t < a:
                return offset
            if t <= b:
                return offset + (t - a)
            offset += b - a
        return offset

    return to_out


def slide(name: str, duration: float) -> Path:
    dest = OUT / f"seg_{name}.mp4"
    run("-loop", "1", "-i", str(OUT / "slides" / f"{name}.png"), "-t", f"{duration:.3f}", "-r", str(FPS),
        "-vf", "format=yuv420p,fade=t=in:st=0:d=0.4", "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(dest))  # fmt: skip
    return dest


def main() -> None:
    data = json.loads((OUT / "events.json").read_text())
    events, think_keep = data["events"], data["think_keep"]
    keep = keep_intervals(events, think_keep)
    to_out = mapper(keep)

    select = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in keep)
    sim = OUT / "seg_sim.mp4"
    run("-i", str(OUT / "sim.webm"),
        "-vf", f"fps={FPS},select='{select}',setpts=N/{FPS}/TB,format=yuv420p",
        "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(sim))  # fmt: skip
    sim_len = seconds(sim)

    lengths = {name: seconds(AUDIO / f"n_{name}.wav") + pad for name, pad in SLIDE_PAD.items()}
    segments = [slide("title", lengths["title"]), slide("architecture", lengths["architecture"]), sim]
    segments.append(slide("closing", lengths["closing"]))
    sim_at = lengths["title"] + lengths["architecture"]
    total = sim_at + sim_len + lengths["closing"]

    listing = OUT / "segments.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in segments))
    video = OUT / "video_only.mp4"
    run("-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(video))

    # audio placements: (seconds into the final video, clip)
    placements: list[tuple[float, Path]] = [
        (0.5, AUDIO / "n_title.wav"),
        (lengths["title"] + 0.5, AUDIO / "n_architecture.wav"),
        (sim_at + sim_len + 0.6, AUDIO / "n_closing.wav"),
    ]
    chimes: list[float] = []
    for e in events:
        at = sim_at + to_out(e["t"])
        if e["type"] == "listen":
            placements.append((at + 0.2, AUDIO / f"{e['id']}.wav"))
        elif e["type"] in ("speak", "narrate"):
            placements.append((at + 0.05, AUDIO / f"{e['audio']}.wav"))
        elif e["type"] == "reminder":
            chimes.append(at)
            placements.append((at + 0.9, AUDIO / f"{e['audio']}.wav"))

    chime = OUT / "chime.wav"
    run("-f", "lavfi", "-i", "sine=f=880:d=0.5", "-f", "lavfi", "-i", "sine=f=1320:d=0.6",
        "-filter_complex", "[0]afade=t=out:st=0.1:d=0.4,volume=0.35[a];[1]adelay=180|180,afade=t=out:st=0.3:d=0.5,volume=0.35[b];[a][b]amix=2:normalize=0,aresample=48000",
        "-ac", "1", str(chime))  # fmt: skip
    placements += [(t, chime) for t in chimes]

    inputs, filters = [], []
    for i, (at, clip) in enumerate(placements):
        inputs += ["-i", str(clip)]
        delay = max(0, int(at * 1000))
        filters.append(f"[{i}]adelay={delay}|{delay}[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(placements)))
    filters.append(f"{mix}amix=inputs={len(placements)}:normalize=0:dropout_transition=0,apad,atrim=0:{total:.3f}[mix]")
    audio = OUT / "audio_mix.wav"
    run(*inputs, "-filter_complex", ";".join(filters), "-map", "[mix]", "-ar", "48000", "-ac", "2", str(audio))

    final = OUT / "neurocare-demo.mp4"
    run("-i", str(video), "-i", str(audio), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
        "-movflags", "+faststart", str(final))  # fmt: skip
    print(
        f"{final}  {seconds(final):.1f} s  (slides {sim_at:.1f}+{lengths['closing']:.1f} s, live take {sim_len:.1f} s)"
    )


if __name__ == "__main__":
    main()
