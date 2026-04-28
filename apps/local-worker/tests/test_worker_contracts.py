import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError


TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from openpatch_worker.config import get_settings
from openpatch_worker.schemas.requests import AgentProposeFileRequest, AgentRunRequest, RepoOpenRequest
from openpatch_worker.services.git_providers import resolve_provider_git_options


class WorkerContractTests(unittest.TestCase):
    def test_repo_open_request_accepts_github_provider(self) -> None:
        payload = RepoOpenRequest(
            project_path="octo/demo-repo",
            branch="main",
            git_provider="github",
        )
        self.assertEqual(payload.git_provider, "github")

    def test_agent_run_request_accepts_project_path(self) -> None:
        payload = AgentRunRequest(project_path="examples/demo-repo", task="Summarize the repo")
        self.assertEqual(payload.project_path, "examples/demo-repo")

    def test_agent_run_request_requires_project_path(self) -> None:
        with self.assertRaises(ValidationError):
            AgentRunRequest(repo_path="examples/demo-repo", task="Summarize the repo")

    def test_agent_propose_file_request_requires_project_path(self) -> None:
        with self.assertRaises(ValidationError):
            AgentProposeFileRequest(
                repo_path="examples/demo-repo",
                relative_path="README.md",
                instruction="Refresh this file.",
            )

    def test_runtime_config_resolves_gitlab_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            config_dir = Path(temp_home) / ".repooperator"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "config.json").write_text(
                """
                {
                  "gitProvider": {
                    "provider": "gitlab",
                    "baseUrl": "https://gitlab.example.com",
                    "token": "gitlab-test-token"
                  }
                }
                """.strip(),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"HOME": temp_home}, clear=False):
                settings = get_settings()
                provider_options = resolve_provider_git_options(
                    git_provider="gitlab",
                    project_path="group/demo-repo",
                    settings=settings,
                )

            self.assertIsNotNone(provider_options)
            assert provider_options is not None
            self.assertEqual(
                provider_options.clone_url,
                "https://gitlab.example.com/group/demo-repo.git",
            )
            joined_args = " ".join(provider_options.git_config_args)
            self.assertIn("Authorization: Basic", joined_args)
            self.assertEqual(provider_options.env["GIT_TERMINAL_PROMPT"], "0")
            self.assertEqual(provider_options.env["GIT_ASKPASS"], "true")

    def test_runtime_config_resolves_github_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            config_dir = Path(temp_home) / ".repooperator"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "config.json").write_text(
                """
                {
                  "gitProvider": {
                    "provider": "github",
                    "baseUrl": "https://github.example.com",
                    "token": "github-test-token"
                  }
                }
                """.strip(),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"HOME": temp_home}, clear=False):
                settings = get_settings()
                provider_options = resolve_provider_git_options(
                    git_provider="github",
                    project_path="octo/demo-repo",
                    settings=settings,
                )

            self.assertIsNotNone(provider_options)
            assert provider_options is not None
            self.assertEqual(
                provider_options.clone_url,
                "https://github.example.com/octo/demo-repo.git",
            )
            self.assertIn("Authorization: Basic", " ".join(provider_options.git_config_args))

    def test_runtime_config_prefers_environment_override_for_gitlab(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            config_dir = Path(temp_home) / ".repooperator"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "config.json").write_text(
                """
                {
                  "gitProvider": {
                    "provider": "gitlab",
                    "baseUrl": "https://gitlab.example.com",
                    "token": "stored-token"
                  }
                }
                """.strip(),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "HOME": temp_home,
                    "GITLAB_BASE_URL": "https://gitlab.override.example.com",
                    "GITLAB_TOKEN": "override-token",
                },
                clear=False,
            ):
                settings = get_settings()
                provider_options = resolve_provider_git_options(
                    git_provider="gitlab",
                    project_path="group/demo-repo",
                    settings=settings,
                )

            self.assertIsNotNone(provider_options)
            assert provider_options is not None
            self.assertEqual(
                provider_options.clone_url,
                "https://gitlab.override.example.com/group/demo-repo.git",
            )


if __name__ == "__main__":
    unittest.main()
