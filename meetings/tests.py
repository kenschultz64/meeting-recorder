import re
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import Export, LiveSegment, Meeting, Note

WEBM_MAGIC = b"\x1a\x45\xdf\xa3PAY"



def fake_transcript():
    return {"segments": [{"start": 0.0, "end": 2.0, "speaker": "speaker_0",
                          "text": "hello", "words": []}],
            "speakers": ["speaker_0"], "duration_sec": 2.0, "asr_seconds": 1.0}


def meeting_kwargs(**kw):
    kw.setdefault("audio", SimpleUploadedFile("a.mp3", b"x", content_type="audio/mpeg"))
    return kw


class OwnershipTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", password="pw")
        self.bob = User.objects.create_user("bob", password="pw")
        self.mine = Meeting.objects.create(**meeting_kwargs(title="Mine", owner=self.alice,
                                                           transcript_json=fake_transcript()))
        self.theirs = Meeting.objects.create(**meeting_kwargs(title="Theirs", owner=self.bob,
                                                          transcript_json=fake_transcript()))
        self.legacy = Meeting.objects.create(
            title="Legacy",  # unowned -> visible to all
            audio=SimpleUploadedFile("legacy.mp3", b"x", content_type="audio/mpeg"))

    def test_list_only_own_plus_legacy(self):
        self.client.force_login(self.alice)
        titles = [m.title for m in self.client.get(reverse("meeting_list")).context["meetings"]]
        self.assertIn("Mine", titles)
        self.assertNotIn("Legacy", titles)
        self.assertNotIn("Theirs", titles)

    def test_detail_404_for_other_users_meeting(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse("meeting_detail", args=[self.theirs.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("meeting_detail", args=[self.mine.pk])).status_code, 200)

    def test_export_views_404_for_other_users(self):
        self.client.force_login(self.alice)
        for name in ["download_transcript", "do_summary"]:
            if name == "download_transcript":
                url = reverse(name, args=[self.theirs.pk, "txt"])
            else:
                url = reverse(name, args=[self.theirs.pk])
            self.assertEqual(self.client.get(url).status_code, 404, name)

    def test_new_meeting_gets_owner(self):
        self.client.force_login(self.alice)
        with patch("meetings.views.transcribe_meeting") as task:
            audio = SimpleUploadedFile("a.mp3", b"xx", content_type="audio/mpeg")
            resp = self.client.post(reverse("meeting_new"), {"title": "New", "audio": audio})
            self.assertEqual(resp.status_code, 302)
            m = Meeting.objects.get(title="New")
            self.assertEqual(m.owner, self.alice)
            task.delay.assert_called_once_with(m.pk)


class DeleteTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", password="pw")
        self.bob = User.objects.create_user("bob", password="pw")
        self.m = Meeting.objects.create(
            title="Doomed", owner=self.alice,
            audio=SimpleUploadedFile("a.mp3", b"audio-bytes", content_type="audio/mpeg"),
            transcript_json=fake_transcript())
        Note.objects.create(meeting=self.m, text="note")
        Export.objects.create(meeting=self.m, kind="text", target="a.txt")
        LiveSegment.objects.create(meeting=self.m, seq=1, text="chunk")

    def test_confirm_page_renders(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("delete_meeting", args=[self.m.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Permanently delete")

    def test_post_delete_removes_everything(self):
        self.client.force_login(self.alice)
        audio_name = self.m.audio.name
        resp = self.client.post(reverse("delete_meeting", args=[self.m.pk]))
        self.assertRedirects(resp, reverse("meeting_list"))
        self.assertFalse(Meeting.objects.filter(pk=self.m.pk).exists())
        self.assertEqual(Note.objects.count(), 0)
        self.assertEqual(Export.objects.count(), 0)
        self.assertEqual(LiveSegment.objects.count(), 0)
        from django.core.files.storage import default_storage
        self.assertFalse(default_storage.exists(audio_name))

    def test_cannot_delete_other_users_meeting(self):
        self.client.force_login(self.bob)
        resp = self.client.post(reverse("delete_meeting", args=[self.m.pk]))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Meeting.objects.filter(pk=self.m.pk).exists())


class LivePreviewTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", password="pw")
        self.bob = User.objects.create_user("bob", password="pw")

    def test_live_create_returns_meeting_id(self):
        self.client.force_login(self.alice)
        resp = self.client.post(reverse("meeting_new"),
                                {"title": "Live", "live": "1"},
                                HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 200)
        mid = int(resp.headers["X-Meeting-Id"])
        m = Meeting.objects.get(pk=mid)
        self.assertEqual(m.owner, self.alice)

    def test_live_chunk_stores_segment(self):
        m = Meeting.objects.create(**meeting_kwargs(title="Live", owner=self.alice))
        self.client.force_login(self.alice)
        with patch("meetings.views.transcribe_chunk") as task:
            chunk = SimpleUploadedFile("chunk-1.webm", WEBM_MAGIC + b"payload", content_type="audio/webm")
            resp = self.client.post(reverse("live_chunk", args=[m.pk]),
                                    {"chunk": chunk, "seq": "1", "start": "0"},
                                    HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertEqual(resp.status_code, 200)
            task.delay.assert_called_once_with(m.pk, 1, WEBM_MAGIC + b"payload", 0.0, 0.0)
        # simulate the worker result
        LiveSegment.objects.create(meeting=m, seq=1, start=0, end=10, text="first chunk")
        import json
        data = json.loads(self.client.get(reverse("live_segments", args=[m.pk])).content)
        self.assertEqual(len(data["segments"]), 1)
        self.assertEqual(data["segments"][0]["text"], "first chunk")
        # incremental: after=1 returns nothing
        data2 = json.loads(self.client.get(reverse("live_segments", args=[m.pk]) + "?after=1").content)
        self.assertEqual(data2["segments"], [])

    def test_live_views_404_for_other_user(self):
        m = Meeting.objects.create(**meeting_kwargs(title="Private", owner=self.alice))
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse("live_segments", args=[m.pk])).status_code, 404)
        chunk = SimpleUploadedFile("chunk-1.webm", WEBM_MAGIC + b"x", content_type="audio/webm")
        self.assertEqual(self.client.post(reverse("live_chunk", args=[m.pk]),
                                          {"chunk": chunk, "seq": "1"}).status_code, 404)

    def test_final_for_attaches_audio_to_live_row(self):
        m = Meeting.objects.create(**meeting_kwargs(title="Live", owner=self.alice))
        self.client.force_login(self.alice)
        with patch("meetings.views.transcribe_meeting") as task:
            audio = SimpleUploadedFile("rec.webm", b"fullrecording", content_type="audio/webm")
            resp = self.client.post(reverse("meeting_new"),
                                    {"title": "Renamed", "audio": audio, "final_for": str(m.pk)},
                                    HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertEqual(resp.status_code, 200)
            m.refresh_from_db()
            self.assertEqual(m.title, "Renamed")
            self.assertTrue(m.audio.name)
            self.assertEqual(Meeting.objects.filter(title="Renamed").count(), 1)
            task.delay.assert_called_once_with(m.pk)


class UserManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("root", "r@example.invalid", "Adm1nPw!")
        self.plain = User.objects.create_user("bob", password="pw")

    def test_users_page_superuser_only(self):
        self.client.force_login(self.plain)
        self.assertEqual(self.client.get(reverse("user_list")).status_code, 302)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("user_list")), "Add a person")

    def test_create_user(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("user_create"),
                                {"username": "natasha", "password": "NatashasPw9"})
        self.assertRedirects(resp, reverse("user_list"))
        u = User.objects.get(username="natasha")
        self.assertTrue(u.check_password("NatashasPw9"))
        self.assertFalse(u.is_superuser)

    def test_reject_duplicate_and_weak(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("user_create"), {"username": "bob", "password": "Whatever123"})
        self.assertEqual(User.objects.filter(username="bob").count(), 1)
        self.client.post(reverse("user_create"), {"username": "carol", "password": "short"})
        self.assertFalse(User.objects.filter(username="carol").exists())

    def test_set_password(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("user_set_password", args=[self.plain.pk]),
                         {"password": "Zephyr9Blue7"})
        self.plain.refresh_from_db()
        self.assertTrue(self.plain.check_password("Zephyr9Blue7"))

    def test_delete_user_keeps_meetings_unowned(self):
        m = Meeting.objects.create(**meeting_kwargs(title="Bob meeting", owner=self.plain))
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("user_delete", args=[self.plain.pk]))
        self.assertRedirects(resp, reverse("user_list"))
        self.assertFalse(User.objects.filter(pk=self.plain.pk).exists())
        m.refresh_from_db()
        self.assertIsNone(m.owner)

    def test_admin_cannot_delete_self(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("user_delete", args=[self.admin.pk]))
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())


class DocsGuideTests(TestCase):
    """The Docs menu item hands out the PDF, but only to signed-in users."""

    def setUp(self):
        self.user = User.objects.create_user("docreader", password="DocsPass!2026")

    def test_docs_requires_login(self):
        response = self.client.get("/docs/guide.pdf")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_docs_download_serves_pdf(self):
        self.client.force_login(self.user)
        response = self.client.get("/docs/guide.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response["Content-Disposition"])
        body = b"".join(response.streaming_content)
        self.assertEqual(body[:5], b"%PDF-")
        self.assertGreater(len(body), 100_000)

    def test_app_title_rebranded(self):
        self.client.force_login(self.user)
        html = self.client.get("/").content.decode()
        self.assertIn("GoGospelNow.com Meeting Recorder", html)
        self.assertIn("Docs", html)


class SpeakerCeilingTests(TestCase):
    """A full house of 8 voices gets a plain-language heads-up on the meeting page."""

    def setUp(self):
        self.user = User.objects.create_user("ceilinguser", password="Ceiling!2026")
        self.client.force_login(self.user)

    def _meeting(self, n_speakers):
        segments = [{"speaker": f"speaker_{i}", "start": i * 5.0, "end": i * 5.0 + 4.0,
                     "text": f"speaker {i} speaking here"} for i in range(n_speakers)]
        return Meeting.objects.create(
            owner=self.user, title=f"{n_speakers} speaker meeting", status="transcribed",
            audio="meetings/2026/10/x.webm",
            transcript_json={"segments": segments,
                             "speakers": [f"speaker_{i}" for i in range(n_speakers)]})

    def test_eight_speakers_shows_ceiling_notice(self):
        m = self._meeting(8)
        html = self.client.get(f"/meetings/{m.pk}/").content.decode()
        self.assertIn("the most the speaker separation can tell apart", html)
        self.assertIn("8 different voices", html)

    def test_three_speakers_shows_no_notice(self):
        m = self._meeting(3)
        html = self.client.get(f"/meetings/{m.pk}/").content.decode()
        self.assertNotIn("the most the speaker separation can tell apart", html)

    def test_nine_speakers_still_renders(self):
        """Beyond the ceiling the app must still render every line (model emits max 8 anyway)."""
        m = self._meeting(8)
        m.transcript_json["segments"].append({"speaker": "speaker_7", "start": 40.0, "end": 44.0,
                                              "text": "a ninth voice folded into an existing label"})
        m.save(update_fields=["transcript_json"])
        html = self.client.get(f"/meetings/{m.pk}/").content.decode()
        self.assertIn("a ninth voice folded into an existing label", html)
