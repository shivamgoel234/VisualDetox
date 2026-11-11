"""Exercise the Gemini adapter without using credentials or API credits."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app import models

ISSUE = {
    "id": "issue-1",
    "severity": "high",
    "description": "The heading has low contrast.",
    "element_description": "heading",
    "viewport": "desktop",
}


def gemini_reply(text: str, reason: str = "STOP") -> httpx.Response:
    return httpx.Response(200, json={"candidates": [{
        "finishReason": reason,
        "content": {"parts": [{"text": text}]},
    }]})


class GeminiTests(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.TemporaryDirectory()
        self.addCleanup(self.cache.cleanup)
        config = patch.multiple(
            models.settings,
            MOCK_MODE=False,
            GEMINI_API_KEY="test-key",
            CACHE_DIR=Path(self.cache.name),
        )
        config.start()
        self.addCleanup(config.stop)
        self.post = self.enterContext(patch("app.models.httpx.post"))

    def test_issue_schema_and_cache(self):
        self.post.return_value = gemini_reply(models.json.dumps([ISSUE]))
        first = models.find_issues(b"desktop", mobile_png=b"mobile")
        self.assertEqual(first, [ISSUE])
        self.assertEqual(models.find_issues(b"desktop", mobile_png=b"mobile"), first)
        self.post.assert_called_once()
        request = self.post.call_args.kwargs
        self.assertEqual(request["headers"]["x-goog-api-key"], "test-key")
        payload = request["json"]
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(sum("inlineData" in part for part in payload["contents"][0]["parts"]), 2)

        token = models.fresh_run.set(True)
        try:
            models.find_issues(b"desktop", mobile_png=b"mobile")
        finally:
            models.fresh_run.reset(token)
        self.assertEqual(self.post.call_count, 2)

    def test_repair_and_verdict(self):
        html = "<!doctype html><html><body><h1>Heading</h1></body></html>"
        self.post.return_value = gemini_reply(html)
        self.assertEqual(models.fix_code(html, [ISSUE]), html)

        verdict = {"id": "issue-1", "fixed": True, "evidence": "The heading is legible."}
        self.post.return_value = gemini_reply(models.json.dumps([verdict]))
        self.assertEqual(models.verify_fixes(b"before", b"after", [ISSUE]), [verdict])

    def test_quota_and_truncated_response(self):
        self.post.return_value = httpx.Response(429)
        with self.assertRaisesRegex(models.ModelError, "quota"):
            models.find_issues(b"desktop")

        self.post.return_value = gemini_reply("[", reason="MAX_TOKENS")
        with self.assertRaisesRegex(models.ModelError, "invalid response"):
            models.find_issues(b"desktop")


if __name__ == "__main__":
    unittest.main()
