"""Web content extraction hardening (0.25.0).

A JS-rendered page (e.g. a YouTube watch URL) fetched with a byte cap left an
unterminated <script> whose raw JS/JSON (ytInitialPlayerResponse …) leaked into
the evidence text; the model then hallucinated an answer around it and backfilled
from unrelated repo files. sanitize now drops unterminated script/style blocks,
and fetch leads with the page's own title/description meta tags.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest import mock  # noqa: E402

from repooperator_worker.agent_core import web_research  # noqa: E402
from repooperator_worker.agent_core.web_research import (  # noqa: E402
    extract_meta_content,
    extract_readable_text,
    fetch_url,
    sanitize_web_content,
)


class WebContentExtractionTests(unittest.TestCase):
    def test_strips_closed_script_and_style(self) -> None:
        html_doc = "<html><head><style>.a{color:red}</style><script>var x=1;</script></head><body>Hello world</body></html>"
        out = sanitize_web_content(html_doc)
        self.assertIn("Hello world", out)
        self.assertNotIn("var x", out)
        self.assertNotIn("color:red", out)

    def test_strips_unterminated_truncated_script(self) -> None:
        # Simulate a page truncated mid-<script> (no closing tag) — the previous
        # regex could not match and the JS survived.
        html_doc = (
            "<title>Some Video</title><body><p>Visible text.</p>"
            '<script nonce="abc">var ytInitialPlayerResponse = {"a":1,"b":'
            + ("x" * 5000)  # truncated, never closes
        )
        out = sanitize_web_content(html_doc)
        self.assertIn("Visible text.", out)
        self.assertNotIn("ytInitialPlayerResponse", out)
        self.assertNotIn("var yt", out)
        self.assertLess(len(out), 200)

    def test_extract_meta_description_and_title(self) -> None:
        html_doc = (
            '<meta property="og:title" content="운명적인 첫만남">'
            '<meta name="description" content="치지직 타르코프 방송 영상입니다.">'
        )
        self.assertEqual(extract_meta_content(html_doc, {"og:title", "twitter:title"}), "운명적인 첫만남")
        self.assertEqual(
            extract_meta_content(html_doc, {"description", "og:description"}),
            "치지직 타르코프 방송 영상입니다.",
        )

    def test_extract_meta_handles_attr_order_and_unescape(self) -> None:
        html_doc = '<meta content="A &amp; B" property="og:description" />'
        self.assertEqual(extract_meta_content(html_doc, {"og:description"}), "A & B")

    def test_extract_meta_missing_returns_empty(self) -> None:
        self.assertEqual(extract_meta_content("<html></html>", {"description"}), "")

    def test_readable_prefers_article_and_drops_boilerplate(self) -> None:
        html_doc = (
            "<body><nav>MENU HOME ABOUT</nav>"
            "<article><h1>Real Title</h1><p>" + ("The actual article body. " * 20) + "</p></article>"
            "<footer>copyright junk links</footer></body>"
        )
        out = extract_readable_text(html_doc)
        self.assertIn("actual article body", out)
        self.assertNotIn("MENU HOME", out)
        self.assertNotIn("copyright junk", out)

    def test_readable_falls_back_when_no_article(self) -> None:
        html_doc = "<body><div>" + ("Plain page content here. " * 20) + "</div></body>"
        self.assertIn("Plain page content here", extract_readable_text(html_doc))

    def test_low_signal_page_gets_guard_note_not_fabrication(self) -> None:
        # A login/JS-only page: no meta description, no readable body.
        walled = "<html><head><title>Sign in</title></head><body><script>app()</script></body>"
        with mock.patch.object(web_research, "_http_get", return_value=walled):
            rec = fetch_url("https://example.com/private", run_id="t").model_dump()
        self.assertTrue(rec["metadata"]["low_signal"])
        self.assertIn("could not read this page", rec["text"].lower())
        self.assertIn("do not describe", rec["text"].lower())

    def test_page_with_description_is_not_low_signal(self) -> None:
        page = (
            '<html><head><title>Vid</title>'
            '<meta property="og:description" content="A real video description of the content.">'
            "</head><body><script>player()</script></body>"
        )
        with mock.patch.object(web_research, "_http_get", return_value=page):
            rec = fetch_url("https://example.com/watch", run_id="t2").model_dump()
        self.assertFalse(rec["metadata"]["low_signal"])
        self.assertIn("real video description", rec["text"])


if __name__ == "__main__":
    unittest.main()
