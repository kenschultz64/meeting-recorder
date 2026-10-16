#!/usr/bin/env python3
"""Meeting recorder P1 spike: Parakeet ASR + Nemotron-3 diarization -> speaker-labeled transcript.

Usage: python pipeline.py meeting.wav [--out transcript.json] [--live]
"""
import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests

PARAKEET_URL = "http://127.0.0.1:18771/api/transcribe"


def normalize_wav(src: Path, dst: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1",
         "-ar", "16000", "-c:a", "pcm_s16le", str(dst)],
        check=True,
    )
    return dst


def parakeet_transcribe(wav: Path) -> dict:
    with open(wav, "rb") as f:
        r = requests.post(PARAKEET_URL, files={"file": f}, timeout=600)
    r.raise_for_status()
    return r.json()


def diarize(wav: Path, live: bool) -> list:
    from nemo.collections.asr.models import SortformerEncLabelModel

    t0 = time.time()
    model = SortformerEncLabelModel.from_pretrained("nvidia/Nemotron-3-Diarization")
    model.eval()
    m = model.sortformer_modules
    if live:  # ultra-low latency streaming config
        m.spkcache_len, m.fifo_len, m.chunk_len, m.chunk_right_context, m.spkcache_update_period = 264, 264, 3, 1, 222
    else:  # offline config: best accuracy
        m.spkcache_len, m.fifo_len, m.chunk_len, m.chunk_right_context, m.spkcache_update_period = 264, 40, 340, 40, 300
    model._check_streaming_parameters()
    load_s = time.time() - t0

    t1 = time.time()
    segments = model.diarize(audio=[str(wav)], batch_size=1)[0]
    run_s = time.time() - t1
    print(f"[diar] model load {load_s:.1f}s, inference {run_s:.1f}s", file=sys.stderr)
    # each segment: "begin end speaker_N"
    out = []
    for seg in segments:
        b, e, spk = seg.split()
        out.append({"start": float(b), "end": float(e), "speaker": int(spk.split("_")[1])})
    return out


def speaker_at(seg_start: float, seg_end: float, diar: list) -> str:
    """Speaker with the most overlap with an ASR segment; 'speaker?' if none."""
    best, best_ov = None, 0.0
    for d in diar:
        ov = min(seg_end, d["end"]) - max(seg_start, d["start"])
        if ov > best_ov:
            best, best_ov = d, ov
    if best is None:
        return "speaker?"
    return f"speaker_{best['speaker']}"


def merge(asr: dict, diar: list) -> list:
    rows = []
    for seg in asr.get("segments", []):
        spk = speaker_at(seg["start"], seg["end"], diar)
        rows.append({
            "start": seg["start"], "end": seg["end"], "speaker": spk,
            "text": seg["text"],
            "words": [{"w": w["word"], "s": w["start"], "e": w["end"]} for w in seg.get("words", [])],
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--out", default=None)
    ap.add_argument("--live", action="store_true", help="use streaming (low-latency) diarization config")
    args = ap.parse_args()

    src = Path(args.audio)
    work = Path("/tmp") / f"mr_{uuid.uuid4().hex[:8]}"
    work.mkdir()
    try:
        wav = normalize_wav(src, work / "audio.wav")

        t0 = time.time()
        asr = parakeet_transcribe(wav)
        asr_s = time.time() - t0

        diar = diarize(wav, args.live)

        rows = merge(asr, diar)
        result = {
            "audio": str(src),
            "asr_seconds": round(asr_s, 2),
            "speakers": sorted({r["speaker"] for r in rows}),
            "segments": rows,
        }
        out = Path(args.out) if args.out else src.with_suffix(".transcript.json")
        out.write_text(json.dumps(result, indent=2))
        print(f"wrote {out}")
        for r in rows:
            print(f"[{r['start']:7.2f} - {r['end']:7.2f}] {r['speaker']}: {r['text']}")
    finally:
        subprocess.run(["rm", "-rf", str(work)])


if __name__ == "__main__":
    main()
