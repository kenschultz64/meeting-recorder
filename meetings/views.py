import re
import time

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.password_validation import validate_password
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from pathlib import Path
from django.shortcuts import get_object_or_404, redirect, render

from . import live_store, render as render_mod
from .llm import summarize_transcript
from .models import Export, LiveSegment, Meeting, Note
from .tasks import export_to_gdrive, transcribe_chunk, transcribe_meeting


def _owned(request, pk):
    """Fetch a meeting the user owns (or an unowned legacy row), else 404."""
    return get_object_or_404(
        Meeting.objects.filter(Q(owner=request.user)), pk=pk)


@login_required
def meeting_list(request):
    meetings = list(Meeting.objects.filter(Q(owner=request.user)))
    for m in meetings:
        # A live row has no audio yet; show what was captured so the user can
        # find a recording whose tab went away.
        m.live = live_store.state(m.pk) if not m.audio else None
    return render(request, "meetings/list.html", {"meetings": meetings})


@login_required
def meeting_new(request):
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        audio = request.FILES.get("audio")
        if request.POST.get("live") and request.headers.get("X-Requested-With") == "XMLHttpRequest":
            # live preview: create the meeting row now; audio arrives with the final submit
            m = Meeting.objects.create(title=title or "Live recording",
                                       created_by=request.user, owner=request.user)
            resp = JsonResponse({"id": m.pk})
            resp["X-Meeting-Id"] = str(m.pk)
            return resp
        final_for = request.POST.get("final_for")
        if final_for and request.headers.get("X-Requested-With") == "XMLHttpRequest":
            m = _owned(request, int(final_for))
            m.audio = audio
            if title:
                m.title = title
            m.save(update_fields=["audio", "title"])
            live_store.clear(m.pk)  # final audio supersedes the preview chunks
            transcribe_meeting.delay(m.pk)
            return JsonResponse({"id": m.pk})
        if not audio:
            messages.error(request, "Please choose an audio file.")
            return redirect("meeting_new")
        if not title:
            title = re.sub(r"\.[^.]+$", "", audio.name)
        m = Meeting.objects.create(title=title, audio=audio,
                                   created_by=request.user, owner=request.user)
        transcribe_meeting.delay(m.pk)
        messages.success(request, f"Uploaded. Transcription started for “{title}”.")
        return redirect("meeting_detail", m.pk)
    return render(request, "meetings/new.html")


# Hard ceiling of the diarization model (Nemotron-3-Diarization: 8 output channels).
DIARIZER_MAX_SPEAKERS = 8


@login_required
def meeting_detail(request, pk):
    m = _owned(request, pk)
    transcript = None
    if m.transcript_json:
        transcript = render_mod.named_transcript(m.transcript_json)["segments"]
    return render(request, "meetings/detail.html", {
        "m": m, "transcript": transcript, "speakers": speaker_rows(m.transcript_json),
        "live": live_store.state(m.pk) if not m.audio else None,
        "notes": m.notes.all(), "exports": m.exports.all(),
        # Nemotron-3-Diarization has exactly 8 output channels; a full 8 means a
        # larger meeting may have had voices folded into someone else's label.
        "speaker_ceiling": len(transcript or []) and len(speaker_rows(m.transcript_json)) >= DIARIZER_MAX_SPEAKERS,
        "diarizer_max": DIARIZER_MAX_SPEAKERS,
    })


@login_required
def add_note(request, pk):
    m = _owned(request, pk)
    if request.method == "POST":
        text = request.POST.get("text", "").strip()
        if text:
            Note.objects.create(meeting=m, text=text, created_by=request.user)
    return redirect("meeting_detail", pk)


@login_required
def do_summary(request, pk):
    m = _owned(request, pk)
    if not m.transcript_json:
        messages.error(request, "No transcript yet.")
        return redirect("meeting_detail", pk)
    m.summary = summarize_transcript(m.title, m.transcript_json)
    m.save(update_fields=["summary"])
    messages.success(request, "Summary generated.")
    return redirect("meeting_detail", pk)


@login_required
def delete_meeting(request, pk):
    m = _owned(request, pk)
    if request.method == "POST":
        title = m.title
        try:
            m.audio.delete(save=False)
        except Exception:
            pass
        live_store.clear(pk)
        m.delete()  # notes/exports/live segments cascade
        messages.success(request, f"Deleted “{title}” (audio, transcript, notes, exports).")
        return redirect("meeting_list")
    return render(request, "meetings/delete_confirm.html", {"m": m})


@login_required
def live_chunk(request, pk):
    """Receive one ~10s webm chunk from the browser recorder -> ASR preview task."""
    m = _owned(request, pk)
    chunk = request.FILES.get("chunk")
    try:
        seq = int(request.POST.get("seq", "0"))
        start = float(request.POST.get("start", "0"))
    except ValueError:
        return JsonResponse({"ok": False}, status=400)
    if not chunk or not seq:
        return JsonResponse({"ok": False, "error": "missing chunk"}, status=400)
    data = chunk.read()
    # sniff container magic: webm/mkv EBML, mp4 ftyp, ogg, wav, mp3, asf
    head = data[:12]
    MAGIC = {b"\x1a\x45\xdf\xa3": "webm", b"OggS": "ogg", b"RIFF": "wav",
             b"ID3": "mp3", b"\x30\x26\xb2\x75": "asf"}
    ok_magic = any(head.startswith(p) for p in MAGIC) or head[4:8] == b"ftyp"
    if not ok_magic:
        return JsonResponse({"ok": False,
                             "error": "not an audio container (first bytes: %s)" % head[:8].hex()},
                            status=400)
    # Keep a copy so an interrupted recording can be rebuilt after the tab dies.
    live_store.save_chunk(m.pk, seq, data, start)
    transcribe_chunk.delay(m.pk, seq, data, start, start)
    return JsonResponse({"ok": True, "seq": seq})


@login_required
def live_segments(request, pk):
    """Polling endpoint: incremental transcript chunks since `after`."""
    m = _owned(request, pk)
    after = int(request.GET.get("after", 0))
    rows = LiveSegment.objects.filter(meeting=m, seq__gt=after).order_by("seq")
    data = [{"seq": s.seq, "start": s.start, "end": s.end,
             "speaker": s.speaker, "text": s.text} for s in rows]
    return JsonResponse({"segments": data, "status": m.status, "error": m.error})


@login_required
def recover_live(request, pk):
    """Rebuild an interrupted live recording from the chunks kept server-side."""
    from django.core.files.base import ContentFile

    m = _owned(request, pk)
    if request.method != "POST":
        return HttpResponse(status=405)
    if m.audio:
        messages.info(request, "This meeting already has audio.")
        return redirect("meeting_detail", m.pk)
    info = live_store.state(m.pk)
    if not info:
        messages.error(request, "No saved audio was found for this meeting.")
        return redirect("meeting_detail", m.pk)
    tmp = Path(settings.MEDIA_ROOT) / "live_chunks" / f"recovered-{m.pk}-{int(time.time())}.webm"
    try:
        live_store.assemble(m.pk, tmp)
        m.audio.save(tmp.name, ContentFile(tmp.read_bytes()), save=False)
        m.status = Meeting.Status.UPLOADED
        m.error = ""
        m.save(update_fields=["audio", "status", "error"])
    except Exception as exc:
        messages.error(request, f"Could not rebuild the recording: {exc}")
        return redirect("meeting_detail", m.pk)
    finally:
        tmp.unlink(missing_ok=True)
    live_store.clear(m.pk)
    transcribe_meeting.delay(m.pk)
    messages.success(request, f"Recovered about {info['seconds']}s of audio — transcribing now.")
    return redirect("meeting_detail", m.pk)


# ---- user management (admin-created accounts, superuser only) ----

@login_required
@user_passes_test(lambda u: u.is_superuser)
def user_list(request):
    from django.contrib.auth.models import User
    users = [{"u": u, "n": Meeting.objects.filter(owner=u).count()}
             for u in User.objects.all().order_by("username")]
    return render(request, "meetings/users.html", {"users": users})


@login_required
@user_passes_test(lambda u: u.is_superuser)
def user_create(request):
    from django.contrib.auth.models import User
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        if not username or not password:
            messages.error(request, "Username and password are both required.")
        elif User.objects.filter(username=username).exists():
            messages.error(request, f"Username “{username}” already exists.")
        else:
            try:
                validate_password(password)
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
            else:
                User.objects.create_user(username=username, password=password)
                messages.success(request, f"Account created for “{username}”. Give them this password.")
    return redirect("user_list")


@login_required
@user_passes_test(lambda u: u.is_superuser)
def user_set_password(request, pk):
    from django.contrib.auth.models import User
    u = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        password = request.POST.get("password", "")
        try:
            validate_password(password, user=u)
        except Exception as exc:
            messages.error(request, " ".join(getattr(exc, "messages", [str(exc)])))
        else:
            u.set_password(password)
            u.save()
            messages.success(request, f"Password updated for “{u.username}”.")
    return redirect("user_list")


@login_required
@user_passes_test(lambda u: u.is_superuser)
def user_delete(request, pk):
    from django.contrib.auth.models import User
    u = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        if u.pk == request.user.pk:
            messages.error(request, "You cannot delete your own account.")
        else:
            n = Meeting.objects.filter(owner=u).count()
            u.delete()
            messages.success(request, f"Deleted “{u.username}”. Their {n} meeting(s) remain but are now unowned.")
    return redirect("user_list")


# ---- export options ----

@login_required
def download_transcript(request, pk, fmt):
    """Copy/download: serve transcript as .txt or .md download."""
    m = _owned(request, pk)
    if not m.transcript_json:
        messages.error(request, "No transcript yet.")
        return redirect("meeting_detail", pk)
    slug = re.sub(r"[^a-z0-9]+", "-", m.title.lower()).strip("-") or f"meeting-{pk}"
    if fmt == "md":
        body = render_mod.transcript_to_markdown(
            m.transcript_json, title=m.title, summary=m.summary)
        resp = HttpResponse(body, content_type="text/markdown; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{slug}.md"'
        Export.objects.create(meeting=m, kind=Export.Kind.MARKDOWN,
                              target=f"{slug}.md", created_by=request.user)
    else:
        body = render_mod.transcript_to_text(m.transcript_json)
        resp = HttpResponse(body, content_type="text/plain; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{slug}.txt"'
        Export.objects.create(meeting=m, kind=Export.Kind.TEXT,
                              target=f"{slug}.txt", created_by=request.user)
    return resp


@login_required
def send_to_gdrive(request, pk):
    """Send transcript (+summary) to Google Drive via the gog CLI."""
    m = _owned(request, pk)
    if not m.transcript_json:
        messages.error(request, "No transcript yet.")
        return redirect("meeting_detail", pk)
    body = render_mod.transcript_to_text(m.transcript_json)
    if m.summary:
        body = f"SUMMARY\n=======\n{m.summary}\n\nTRANSCRIPT\n=========\n{body}"
    slug = re.sub(r"[^a-z0-9]+", "-", m.title.lower()).strip("-") or f"meeting-{pk}"
    try:
        info = export_to_gdrive(m, body, f"{slug}.txt")
        Export.objects.create(meeting=m, kind=Export.Kind.GDRIVE,
                              target=info.get("link") or info["id"],
                              created_by=request.user)
        messages.success(request, f"Saved to Google Drive: {info.get('link') or info['id']}")
    except Exception as exc:
        messages.error(request, f"Google Drive export failed: {exc}")
    return redirect("meeting_detail", pk)


# Speaker identities remain stable; user-supplied names are a display mapping.
def speaker_rows(transcript):
    rows = {}
    t = transcript or {}
    names = t.get("speaker_names", {})
    for s in t.get("segments", []):
        key = s["speaker"]
        if key not in rows:
            rows[key] = {"key": key, "name": names.get(key, ""),
                         "start": s["start"], "end": min(s["end"], s["start"] + 8)}
    return list(rows.values())


@login_required
def name_speakers(request, pk):
    from django.views.decorators.http import require_POST
    from django.db import transaction
    from django.http import HttpResponseNotAllowed
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    with transaction.atomic():
        m = get_object_or_404(Meeting.objects.select_for_update(), pk=pk, owner=request.user)
        if not m.transcript_json or m.status != Meeting.Status.TRANSCRIBED:
            return HttpResponse("Transcribe this meeting first.", status=400)
        names = {}
        for row in speaker_rows(m.transcript_json):
            name = request.POST.get("speaker_" + row["key"], "").strip()
            if len(name) > 100 or any(ord(c) < 32 for c in name):
                return HttpResponse("Use names of at most 100 characters, without control characters.", status=400)
            if name:
                names[row["key"]] = name
        m.transcript_json = {**m.transcript_json, "speaker_names": names}
        m.save(update_fields=["transcript_json"])
    messages.success(request, "Speaker names saved. Existing summaries and previously saved files are unchanged; regenerate them to use these names.")
    return redirect("meeting_detail", pk)


@login_required
def private_audio(request, name):
    from django.http import FileResponse
    m = get_object_or_404(Meeting, audio=name, owner=request.user)
    response = FileResponse(m.audio.open("rb"), content_type="audio/webm" if name.endswith(".webm") else None)
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def docs_guide(request):
    """Download the Meeting Recorder user guide."""
    from django.conf import settings
    from django.http import FileResponse, Http404
    path = Path(settings.BASE_DIR) / "docs" / "meeting-recorder-guide.pdf"
    if not path.exists():
        raise Http404("User guide not available")
    response = FileResponse(path.open("rb"), content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="Meeting-Recorder-User-Guide.pdf"'
    response["Cache-Control"] = "private, max-age=600"
    return response
