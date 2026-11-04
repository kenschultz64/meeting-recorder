from django.test import SimpleTestCase

from .pipeline import normalize_asr_response


class AsrCompatibilityTests(SimpleTestCase):
    def test_native_segment_response_is_preserved(self):
        payload = {"text": "Hello.", "segments": [{
            "start": 0.0, "end": 0.5, "text": "Hello.",
            "words": [{"word": "Hello.", "start": 0.0, "end": 0.5}],
        }]}
        self.assertIs(normalize_asr_response(payload), payload)

    def test_openai_words_are_grouped_into_sentence_segments(self):
        payload = {"text": "Hello there. Next item", "words": [
            {"word": "Hello", "start": 0.0, "end": 0.3},
            {"word": "there.", "start": 0.3, "end": 0.8},
            {"word": "Next", "start": 1.0, "end": 1.2},
            {"word": "item", "start": 1.2, "end": 1.5},
        ]}
        result = normalize_asr_response(payload)
        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual(result["segments"][0]["text"], "Hello there.")
        self.assertEqual(result["segments"][1]["words"][1]["word"], "item")