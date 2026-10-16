from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from .models import Meeting
from .render import transcript_to_text,transcript_to_markdown
from unittest.mock import patch

class SpeakerNamesTests(TestCase):
 def setUp(self):
  self.u=User.objects.create_user('owner');self.other=User.objects.create_user('other')
  self.m=Meeting.objects.create(owner=self.u,title='Names',status='transcribed',transcript_json={'segments':[{'speaker':'speaker_0','text':'Budget approved.','start':0,'end':3},{'speaker':'speaker_1','text':'I will follow up.','start':3,'end':5}]})
  self.client.force_login(self.u)
  self.url=reverse('name_speakers',args=[self.m.pk])
 def test_save_export_summary_clear(self):
  self.assertEqual(self.client.post(self.url,{'speaker_speaker_0':'Ken','speaker_speaker_1':'Natasha'}).status_code,302)
  self.m.refresh_from_db();t=self.m.transcript_json
  self.assertEqual(t['segments'][0]['speaker'],'speaker_0')
  self.assertIn('Ken:',transcript_to_text(t));self.assertIn('**Natasha**',transcript_to_markdown(t))
  with patch('meetings.llm._chat',return_value='summary') as chat:
   from .llm import summarize_transcript
   summarize_transcript('Names',t)
   self.assertIn('Ken: Budget approved.',chat.call_args.args[2])
  self.assertContains(self.client.get(reverse('meeting_detail',args=[self.m.pk])),'Ken')
  self.client.post(self.url,{})
  self.m.refresh_from_db();self.assertEqual(self.m.transcript_json['speaker_names'],{})
 def test_access_validation_csrf(self):
  self.assertEqual(self.client.get(self.url).status_code,405)
  self.assertEqual(self.client.post(self.url,{'speaker_speaker_0':'x'*101}).status_code,400)
  self.client.force_login(self.other)
  self.assertEqual(self.client.post(self.url,{'speaker_speaker_0':'Stolen'}).status_code,404)
  from django.test import Client
  c=Client(enforce_csrf_checks=True);c.force_login(self.u)
  self.assertEqual(c.post(self.url,{}).status_code,403)
 def test_html_escaped(self):
  self.client.post(self.url,{'speaker_speaker_0':'<script>alert(1)</script>'})
  r=self.client.get(reverse('meeting_detail',args=[self.m.pk]))
  self.assertContains(r,'&lt;script&gt;alert(1)&lt;/script&gt;')
  self.assertNotContains(r,'<script>alert(1)</script>')
