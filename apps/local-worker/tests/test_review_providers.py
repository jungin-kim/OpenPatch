"""Tests for merge/pull request creation (review_providers).

GitHub PR creation is exercised alongside GitLab MR creation to lock in the
symmetry added in 0.17.0. Network is mocked at urlopen; no real API is hit.
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from repooperator_worker.config import ProviderSettings  # noqa: E402
from repooperator_worker.schemas import GitMergeRequestCreateRequest  # noqa: E402
from repooperator_worker.services import review_providers  # noqa: E402
from repooperator_worker.services.review_providers import (  # noqa: E402
    MergeRequestProviderContext,
    create_merge_request,
)


class _FakeSettings:
    def __init__(self, provider: str, base_url: str, token: str) -> None:
        self._settings = ProviderSettings(provider=provider, base_url=base_url, token=token)

    def get_provider_settings(self, provider: str) -> ProviderSettings:
        return self._settings


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ReviewProvidersTests(unittest.TestCase):
    def test_github_pull_request_hits_pulls_endpoint_and_maps_response(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout=30):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["data"] = json.loads(req.data.decode("utf-8"))
            captured["headers"] = {k.lower(): v for k, v in req.headers.items()}
            body = json.dumps(
                {"html_url": "https://github.com/owner/repo/pull/7", "number": 7, "state": "open", "title": "Add feature"}
            ).encode("utf-8")
            return _FakeResponse(body)

        payload = GitMergeRequestCreateRequest(
            project_path="owner/repo",
            git_provider="github",
            source_branch="feature",
            target_branch="main",
            title="Add feature",
            description="Adds the feature.",
        )
        ctx = MergeRequestProviderContext(settings=_FakeSettings("github", "https://github.com", "tok"))

        with mock.patch.object(review_providers.request, "urlopen", fake_urlopen):
            result = create_merge_request(payload, ctx)

        self.assertEqual(captured["url"], "https://api.github.com/repos/owner/repo/pulls")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["data"], {"title": "Add feature", "head": "feature", "base": "main", "body": "Adds the feature."})
        self.assertIn("authorization", captured["headers"])
        self.assertEqual(result.web_url, "https://github.com/owner/repo/pull/7")
        self.assertEqual(result.iid, "7")
        self.assertEqual(result.state, "open")
        self.assertEqual(result.git_provider, "github")

    def test_github_enterprise_uses_api_v3_base(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout=30):
            captured["url"] = req.full_url
            return _FakeResponse(json.dumps({"html_url": "u", "number": 3, "state": "open"}).encode("utf-8"))

        payload = GitMergeRequestCreateRequest(
            project_path="team/svc", git_provider="github", source_branch="f", target_branch="main", title="T",
        )
        ctx = MergeRequestProviderContext(settings=_FakeSettings("github", "https://ghe.corp.example", "tok"))
        with mock.patch.object(review_providers.request, "urlopen", fake_urlopen):
            create_merge_request(payload, ctx)
        self.assertEqual(captured["url"], "https://ghe.corp.example/api/v3/repos/team/svc/pulls")

    def test_gitlab_merge_request_still_works(self) -> None:
        def fake_urlopen(req, timeout=30):
            self.assertIn("/api/v4/projects/", req.full_url)
            self.assertTrue(req.full_url.endswith("/merge_requests"))
            return _FakeResponse(
                json.dumps({"web_url": "https://gitlab.com/g/p/-/merge_requests/2", "iid": 2, "state": "opened", "title": "T"}).encode("utf-8")
            )

        payload = GitMergeRequestCreateRequest(
            project_path="group/proj", git_provider="gitlab", source_branch="f", target_branch="main", title="T",
        )
        ctx = MergeRequestProviderContext(settings=_FakeSettings("gitlab", "https://gitlab.com", "tok"))
        with mock.patch.object(review_providers.request, "urlopen", fake_urlopen):
            result = create_merge_request(payload, ctx)
        self.assertEqual(result.iid, "2")
        self.assertEqual(result.state, "opened")

    def test_github_requires_token(self) -> None:
        payload = GitMergeRequestCreateRequest(
            project_path="o/r", git_provider="github", source_branch="f", target_branch="main", title="T",
        )
        ctx = MergeRequestProviderContext(settings=_FakeSettings("github", "https://github.com", ""))
        with self.assertRaises(ValueError):
            create_merge_request(payload, ctx)


if __name__ == "__main__":
    unittest.main()
