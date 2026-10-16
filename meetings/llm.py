"""LLM summarization via cw2 Flash-Next with cwbrain5 vLLM fallback."""
import requests
from django.conf import settings


def _chat(url: str, model: str, prompt: str, max_tokens: int = 1500) -> str:
    r = requests.post(
        f"{url}/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=300,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def summarize_transcript(title: str, transcript: dict) -> str:
    from .render import named_transcript
    transcript = named_transcript(transcript)
    lines = [f"{s['speaker']}: {s['text']}" for s in transcript["segments"]]
    body = "\n".join(lines)
    if len(body) > 30000:  # keep within model context
        body = body[:30000] + "\n[transcript truncated]"
    prompt = (
        "You are a meeting-minutes assistant. Summarize this meeting transcript in Markdown with these sections:\n"
        "## Key Points\n## Decisions Made\n## Action Items (who / what / when)\n## Open Questions\n\n"
        f"Meeting title: {title}\n\nTranscript:\n{body}"
    )
    try:
        return _chat(settings.LLM_URL, settings.LLM_MODEL, prompt)
    except Exception:
        return _chat(settings.LLM_FALLBACK_URL, settings.LLM_FALLBACK_MODEL, prompt)
