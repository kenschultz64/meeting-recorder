"""Render a transcript dict into plain text or Markdown."""


def transcript_to_text(t: dict) -> str:
    t = named_transcript(t)
    lines = []
    for s in t["segments"]:
        lines.append(f"[{s['start']:7.2f} - {s['end']:7.2f}] {s['speaker']}: {s['text']}")
    return "\n".join(lines)


def transcript_to_markdown(t: dict, title: str = "Meeting transcript",
                           summary: str = "") -> str:
    t = named_transcript(t)
    lines = [f"# {title}", ""]
    if summary:
        lines += ["## Summary", "", summary, ""]
    lines += ["## Transcript", ""]
    current = None
    for s in t["segments"]:
        if s["speaker"] != current:
            lines.append(f"**{s['speaker']}** ({s['start']:.0f}s): {s['text']}")
            current = s["speaker"]
        else:
            lines.append(f"{s['text']}")
        lines.append("")
    return "\n".join(lines)


def named_transcript(t):
    if not t:
        return t
    names = t.get("speaker_names", {})
    return {**t, "segments": [{**s, "speaker": names.get(s["speaker"]) or s["speaker"]}
                              for s in t.get("segments", [])]}
