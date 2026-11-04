"""Transcription pipeline: Parakeet ASR + Nemotron-3 diarization -> merged transcript.

Ported from the verified P1 spike (spike/pipeline.py).
"""
import subprocess
import shutil
import tempfile
import time
import re
from pathlib import Path

import requests
from django.conf import settings

DIAR_OFFLINE = dict(spkcache_len=264, fifo_len=40, chunk_len=340,
                    chunk_right_context=40, spkcache_update_period=300)
DIAR_LIVE = dict(spkcache_len=264, fifo_len=264, chunk_len=3,
                 chunk_right_context=1, spkcache_update_period=222)

_diar_model = None


def normalize_wav(src: Path, dst: Path) -> Path:
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1",
         "-ar", "16000", "-c:a", "pcm_s16le", str(dst)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        detail = (r.stderr or "").strip()[:300]
        raise RuntimeError(f"ffmpeg failed (rc={r.returncode}): {detail}")
    return dst


def probe_duration(path: Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True).stdout.strip()
        return float(out)
    except Exception:
        return None


def parakeet_transcribe(wav: Path) -> dict:
    with open(wav, "rb") as f:
        r = requests.post(
            settings.PARAKEET_URL,
            files={"file": f},
            data={"response_format": "verbose_json", "timestamp_granularities[]": "word"},
            timeout=1800,
        )
    r.raise_for_status()
    return normalize_asr_response(r.json())


def normalize_asr_response(payload: dict) -> dict:
    """Normalize the native endpoint and OpenAI verbose-JSON ASR formats."""
    segments = payload.get("segments") or []
    if segments and any(segment.get("words") for segment in segments):
        return payload

    words = payload.get("words") or []
    normalized_words = []
    for item in words:
        word = str(item.get("word") or item.get("w") or "").strip()
        if not word:
            continue
        normalized_words.append({
            "word": word,
            "start": float(item.get("start", item.get("s", 0.0))),
            "end": float(item.get("end", item.get("e", 0.0))),
        })
    if not normalized_words:
        return payload

    grouped = []
    current = []
    for word in normalized_words:
        current.append(word)
        duration = word["end"] - current[0]["start"]
        if re.search(r"[.!?][\"')\]]?$", word["word"]) or duration >= 12.0:
            grouped.append(current)
            current = []
    if current:
        grouped.append(current)

    payload = dict(payload)
    payload["segments"] = [{
        "start": group[0]["start"],
        "end": group[-1]["end"],
        "text": " ".join(word["word"] for word in group),
        "words": group,
    } for group in grouped]
    return payload


def get_diar_model():
    global _diar_model
    if _diar_model is None:
        from nemo.collections.asr.models import SortformerEncLabelModel
        _diar_model = SortformerEncLabelModel.from_pretrained("nvidia/Nemotron-3-Diarization")
        _diar_model.eval()
    return _diar_model


def diarize(wav: Path, live: bool = False) -> list:
    model = get_diar_model()
    m = model.sortformer_modules
    cfg = DIAR_LIVE if live else DIAR_OFFLINE
    for k, v in cfg.items():
        setattr(m, k, v)
    model._check_streaming_parameters()
    segments = model.diarize(audio=[str(wav)], batch_size=1)[0]
    out = []
    for seg in segments:  # '0.030 2.320 speaker_0'
        b, e, spk = seg.split()
        out.append({"start": float(b), "end": float(e), "speaker": int(spk.split("_")[1])})
    return out


def speaker_at(seg_start: float, seg_end: float, diar: list) -> str:
    best, best_ov = None, 0.0
    for d in diar:
        ov = min(seg_end, d["end"]) - max(seg_start, d["start"])
        if ov > best_ov:
            best, best_ov = d, ov
    return f"speaker_{best['speaker']}" if best else "speaker?"


def merge(asr: dict, diar: list) -> list:
    rows = []
    for seg in asr.get("segments", []):
        rows.append({
            "start": seg["start"], "end": seg["end"],
            "speaker": speaker_at(seg["start"], seg["end"], diar),
            "text": seg["text"],
            "words": [{"w": w["word"], "s": w["start"], "e": w["end"]}
                      for w in seg.get("words", [])],
        })
    return rows


def transcribe_audio_file(audio_path: Path) -> dict:
    """Full pipeline for one audio file -> transcript dict."""
    work = Path(tempfile.mkdtemp(prefix="meeting-recorder-"))
    try:
        wav = normalize_wav(audio_path, work / "audio.wav")
        duration = probe_duration(wav)
        t0 = time.time()
        asr = parakeet_transcribe(wav)
        diar = diarize(wav)
        segments = merge(asr, diar)
        return {
            "segments": segments,
            "speakers": sorted({s["speaker"] for s in segments}),
            "duration_sec": duration,
            "asr_seconds": round(time.time() - t0, 1),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def transcribe_chunk_bytes(audio_bytes: bytes) -> str:
    """ASR a small webm chunk (no diarization) -> plain text for live preview."""
    work = Path(tempfile.mkdtemp(prefix="meeting-recorder-chunk-"))
    try:
        src = work / "chunk.webm"
        src.write_bytes(audio_bytes)
        wav = normalize_wav(src, work / "chunk.wav")
        asr = parakeet_transcribe(wav)
        return asr.get("text", "").strip()
    finally:
        shutil.rmtree(work, ignore_errors=True)
