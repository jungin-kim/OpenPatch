import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from openpatch_worker.services.provider_service import (
    _build_github_api_base,
    _build_gitlab_api_base,
    list_recent_project_paths,
)


class ProviderServiceTests(unittest.TestCase):
    def test_build_gitlab_api_base(self) -> None:
        self.assertEqual(
            _build_gitlab_api_base("https://gitlab.example.com/"),
            "https://gitlab.example.com/api/v4",
        )

    def test_build_github_api_base_for_public_github(self) -> None:
        self.assertEqual(
            _build_github_api_base("https://github.com"),
            "https://api.github.com",
        )

    def test_build_github_api_base_for_github_enterprise(self) -> None:
        self.assertEqual(
            _build_github_api_base("https://github.example.com"),
            "https://github.example.com/api/v3",
        )

    def test_list_recent_project_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_repo_base:
            repo_base = Path(temp_repo_base)
            project_one = repo_base / "group-one" / "repo-one"
            project_two = repo_base / "group-two" / "repo-two"
            (project_one / ".git").mkdir(parents=True)
            (project_two / ".git").mkdir(parents=True)

            with patch.dict(
                os.environ,
                {"LOCAL_REPO_BASE_DIR": temp_repo_base},
                clear=False,
            ):
                recent = list_recent_project_paths(limit=10)

            self.assertIn("group-one/repo-one", recent)
            self.assertIn("group-two/repo-two", recent)


if __name__ == "__main__":
    unittest.main()
