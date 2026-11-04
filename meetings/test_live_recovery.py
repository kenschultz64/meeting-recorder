import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from meetings import live_store
from meetings.models import Meeting


def make_chunk(dest: Path, seconds: float = 1.0) -> bytes:
    """A real webm/opus chunk, the shape the browser recorder sends."""
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:a", "libopus", "-f", "webm", str(dest)],
        check=True, capture_output=True,
    )
    return dest.read_bytes()


class LiveChunkStoreTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._media = tempfile.mkdtemp(prefix='mr-test-media-')
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user('liveuser', password='Live-Pass-7712')
        self.client.force_login(self.user)
        self.m = Meeting.objects.create(title='Live one', audio='', owner=self.user)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(live_store.clear, self.m.pk)

    def test_chunks_persist_and_report_state(self):
        self.assertIsNone(live_store.state(self.m.pk))
        data = make_chunk(self.tmp / 'c1.webm')
        live_store.save_chunk(self.m.pk, 1, data, start=0.0)
        live_store.save_chunk(self.m.pk, 2, data, start=10.0)
        info = live_store.state(self.m.pk)
        self.assertEqual(info['count'], 2)
        self.assertTrue(info['active'])
        self.assertGreaterEqual(info['seconds'], 20)

    def test_header_only_stub_is_ignored(self):
        live_store.save_chunk(self.m.pk, 1, b'\x1a\x45\xdf\xa3' + b'0' * 100)
        self.assertIsNone(live_store.state(self.m.pk))

    def test_assemble_produces_playable_audio(self):
        data = make_chunk(self.tmp / 'c1.webm')
        for seq in (1, 2, 3):
            live_store.save_chunk(self.m.pk, seq, data, start=(seq - 1) * 10)
        out = self.tmp / 'out.webm'
        live_store.assemble(self.m.pk, out)
        self.assertGreater(out.stat().st_size, live_store.MIN_BYTES)
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                                'format=duration', '-of', 'csv=p=0', str(out)],
                               capture_output=True, text=True, check=True)
        self.assertGreater(float(probe.stdout.strip()), 2.0)

    @patch('meetings.views.transcribe_meeting.delay')
    def test_recover_endpoint_attaches_audio(self, delay):
        data = make_chunk(self.tmp / 'c1.webm')
        live_store.save_chunk(self.m.pk, 1, data, start=0.0)
        live_store.save_chunk(self.m.pk, 2, data, start=10.0)
        resp = self.client.post(reverse('recover_live', args=[self.m.pk]))
        self.assertRedirects(resp, reverse('meeting_detail', args=[self.m.pk]))
        self.m.refresh_from_db()
        self.assertTrue(self.m.audio)
        self.assertTrue(Path(self.m.audio.path).exists())
        delay.assert_called_once_with(self.m.pk)
        self.assertIsNone(live_store.state(self.m.pk))

    def test_recover_refuses_other_users_and_get(self):
        other = User.objects.create_user('otheruser', password=None)
        self.client.force_login(other)
        self.assertEqual(self.client.post(reverse('recover_live', args=[self.m.pk])).status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('recover_live', args=[self.m.pk])).status_code, 405)

    def test_unfinished_recording_is_flagged_when_stale(self):
        data = make_chunk(self.tmp / 'c1.webm')
        live_store.save_chunk(self.m.pk, 1, data, start=0.0)
        old = time.time() - 600
        for f in (live_store.chunk_dir(self.m.pk)).glob('*.webm'):
            os.utime(f, (old, old))
        listing = self.client.get(reverse('meeting_list')).content.decode()
        self.assertIn('Not uploaded', listing)
        self.assertIn('recoverable', listing)
        detail = self.client.get(reverse('meeting_detail', args=[self.m.pk])).content.decode()
        self.assertIn('never uploaded', detail)
        self.assertIn(reverse('recover_live', args=[self.m.pk]), detail)

    def test_active_recording_is_flagged_as_running(self):
        data = make_chunk(self.tmp / 'c1.webm')
        live_store.save_chunk(self.m.pk, 1, data, start=0.0)
        listing = self.client.get(reverse('meeting_list')).content.decode()
        self.assertIn('Recording', listing)
        detail = self.client.get(reverse('meeting_detail', args=[self.m.pk])).content.decode()
        self.assertIn('live recording is running', detail)

    @patch('meetings.views.transcribe_meeting.delay')
    def test_final_upload_clears_chunks(self, delay):
        data = make_chunk(self.tmp / 'c1.webm')
        live_store.save_chunk(self.m.pk, 1, data, start=0.0)
        audio = SimpleUploadedFile('rec.webm', data, content_type='audio/webm')
        resp = self.client.post(reverse('meeting_new'),
                                {'title': 'Live one', 'final_for': self.m.pk, 'audio': audio},
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(live_store.state(self.m.pk))
        self.m.refresh_from_db()
        self.assertTrue(self.m.audio)

    def test_new_page_warns_before_leaving(self):
        html = self.client.get(reverse('meeting_new')).content.decode()
        self.assertIn('beforeunload', html)
        self.assertIn('Recording in progress', html)
