import os
import subprocess
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

from repooperator_worker.config import get_settings
from repooperator_worker.schemas.requests import (
    AgentProposeFileRequest,
    AgentRunRequest,
    RepoOpenRequest,
    ThreadUpsertRequest,
)
from repooperator_worker.services.agent_service import run_agent_task
from repooperator_worker.services.common import get_repooperator_home_dir
from repooperator_worker.services.git_providers import resolve_provider_git_options
from repooperator_worker.services.repo_service import open_repository, plan_repository_open
from repooperator_worker.services.repo_open_requests import (
    clear_repository_open_request,
    is_repository_open_request_current,
    mark_repository_open_request_current,
)
from repooperator_worker.services.thread_service import list_threads, upsert_thread


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

    def test_agent_run_request_accepts_repository_trace(self) -> None:
        payload = AgentRunRequest(
            project_path="examples/demo-repo",
            task="Summarize the repo",
            git_provider="gitlab",
            branch="main",
        )
        self.assertEqual(payload.git_provider, "gitlab")
        self.assertEqual(payload.branch, "main")

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

            with patch.dict(
                os.environ,
                {
                    "HOME": temp_home,
                    "REPOOPERATOR_CONFIG_PATH": "",
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
                "https://gitlab.example.com/group/demo-repo.git",
            )
            self.assertEqual(
                settings.repooperator_config_path,
                (Path(temp_home) / ".repooperator" / "config.json").resolve(),
            )
            self.assertEqual(
                settings.repooperator_home_dir,
                (Path(temp_home) / ".repooperator").resolve(),
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

            with patch.dict(
                os.environ,
                {
                    "HOME": temp_home,
                    "REPOOPERATOR_CONFIG_PATH": "",
                },
                clear=False,
            ):
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

    def test_runtime_config_resolves_explicit_gitlab_when_default_is_github(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            config_dir = Path(temp_home) / ".repooperator"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "config.json").write_text(
                """
                {
                  "gitProvider": {
                    "provider": "github",
                    "baseUrl": "https://github.example.com",
                    "token": "github-default-token"
                  },
                  "repositorySources": [
                    {
                      "provider": "github",
                      "baseUrl": "https://github.example.com",
                      "token": "github-source-token"
                    },
                    {
                      "provider": "gitlab",
                      "baseUrl": "https://gitlab.example.com",
                      "token": "gitlab-source-token"
                    }
                  ]
                }
                """.strip(),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "HOME": temp_home,
                    "REPOOPERATOR_CONFIG_PATH": "",
                    "GITHUB_BASE_URL": "",
                    "GITHUB_TOKEN": "",
                    "GITLAB_BASE_URL": "",
                    "GITLAB_TOKEN": "",
                },
                clear=False,
            ):
                settings = get_settings()
                provider_options = resolve_provider_git_options(
                    git_provider="gitlab",
                    project_path="group/demo-repo",
                    settings=settings,
                )

            self.assertEqual(settings.configured_git_provider, "github")
            self.assertIsNotNone(provider_options)
            assert provider_options is not None
            self.assertEqual(
                provider_options.clone_url,
                "https://gitlab.example.com/group/demo-repo.git",
            )

    def test_runtime_config_resolves_explicit_github_when_default_is_gitlab(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            config_dir = Path(temp_home) / ".repooperator"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "config.json").write_text(
                """
                {
                  "gitProvider": {
                    "provider": "gitlab",
                    "baseUrl": "https://gitlab.example.com",
                    "token": "gitlab-default-token"
                  },
                  "repositorySources": [
                    {
                      "provider": "gitlab",
                      "baseUrl": "https://gitlab.example.com",
                      "token": "gitlab-source-token"
                    },
                    {
                      "provider": "github",
                      "baseUrl": "https://github.example.com",
                      "token": "github-source-token"
                    }
                  ]
                }
                """.strip(),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "HOME": temp_home,
                    "REPOOPERATOR_CONFIG_PATH": "",
                    "GITHUB_BASE_URL": "",
                    "GITHUB_TOKEN": "",
                    "GITLAB_BASE_URL": "",
                    "GITLAB_TOKEN": "",
                },
                clear=False,
            ):
                settings = get_settings()
                provider_options = resolve_provider_git_options(
                    git_provider="github",
                    project_path="octo/demo-repo",
                    settings=settings,
                )

            self.assertEqual(settings.configured_git_provider, "gitlab")
            self.assertIsNotNone(provider_options)
            assert provider_options is not None
            self.assertEqual(
                provider_options.clone_url,
                "https://github.example.com/octo/demo-repo.git",
            )

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
                    "REPOOPERATOR_CONFIG_PATH": "",
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

    def test_runtime_config_prefers_repooperator_config_path_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            config_path = Path(temp_home) / "custom" / "config.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                """
                {
                  "gitProvider": {
                    "provider": "gitlab",
                    "baseUrl": "https://gitlab.env.example.com",
                    "token": "env-token"
                  }
                }
                """.strip(),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "HOME": temp_home,
                    "REPOOPERATOR_CONFIG_PATH": str(config_path),
                },
                clear=False,
            ):
                settings = get_settings()

            self.assertEqual(settings.repooperator_config_path, config_path.resolve())
            self.assertEqual(settings.repooperator_home_dir, config_path.parent.resolve())
            self.assertEqual(settings.gitlab_base_url, "https://gitlab.env.example.com")

    def test_runtime_config_uses_repooperator_config_path_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            config_path = Path(temp_home) / ".repooperator" / "config.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                """
                {
                  "gitProvider": {
                    "provider": "github",
                    "baseUrl": "https://github.repooperator.example.com",
                    "token": "repooperator-token"
                  }
                }
                """.strip(),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "HOME": temp_home,
                    "REPOOPERATOR_CONFIG_PATH": str(config_path),
                },
                clear=False,
            ):
                settings = get_settings()

            self.assertEqual(settings.repooperator_config_path, config_path.resolve())
            self.assertEqual(settings.repooperator_home_dir, config_path.parent.resolve())
            self.assertEqual(settings.github_base_url, "https://github.repooperator.example.com")

    def test_runtime_config_falls_back_to_repooperator_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            config_path = Path(temp_home) / ".repooperator" / "config.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                """
                {
                  "gitProvider": {
                    "provider": "local"
                  }
                }
                """.strip(),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"HOME": temp_home}, clear=True):
                settings = get_settings()
                home_dir = get_repooperator_home_dir()

            self.assertEqual(settings.repooperator_config_path, config_path.resolve())
            self.assertEqual(home_dir, config_path.parent.resolve())

    def test_repository_switch_replaces_active_agent_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            repooperator_dir = Path(temp_home) / ".repooperator"
            repo_base = repooperator_dir / "repos"
            repo_base.mkdir(parents=True, exist_ok=True)
            config_path = repooperator_dir / "config.json"
            config_path.write_text(
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

            gitlab_repo = repo_base / "group" / "repo-a"
            local_repo = Path(temp_home) / "work" / "repo-b"
            _init_git_repo(gitlab_repo, "Repo A")
            _init_git_repo(local_repo, "Repo B")

            prompts: list[str] = []

            def fake_generate_text(_client, prompt) -> str:
                prompts.append(prompt.user_prompt)
                return "grounded answer"

            with patch.dict(
                os.environ,
                {
                    "HOME": temp_home,
                    "REPOOPERATOR_CONFIG_PATH": str(config_path),
                    "LOCAL_REPO_BASE_DIR": str(repo_base),
                    "OPENAI_BASE_URL": "http://127.0.0.1:11434/v1",
                    "OPENAI_API_KEY": "test-key",
                    "OPENAI_MODEL": "test-model",
                },
                clear=False,
            ), patch(
                "repooperator_worker.services.repo_service._fetch_repository",
                return_value=None,
            ), patch(
                "repooperator_worker.services.agent_service.OpenAICompatibleModelClient.generate_text",
                fake_generate_text,
            ):
                opened_gitlab = open_repository(
                    RepoOpenRequest(
                        project_path="group/repo-a",
                        branch="main",
                        git_provider="gitlab",
                    )
                )
                first = run_agent_task(
                    AgentRunRequest(
                        project_path=opened_gitlab.project_path,
                        git_provider=opened_gitlab.git_provider,
                        branch=opened_gitlab.branch,
                        task="Summarize this repository.",
                    )
                )

                opened_local = open_repository(
                    RepoOpenRequest(
                        project_path=str(local_repo),
                        branch="main",
                        git_provider="local",
                    )
                )
                second = run_agent_task(
                    AgentRunRequest(
                        project_path=opened_local.project_path,
                        git_provider=opened_local.git_provider,
                        branch=opened_local.branch,
                        task="Summarize this repository.",
                    )
                )

                with self.assertRaises(ValueError):
                    run_agent_task(
                        AgentRunRequest(
                            project_path=opened_gitlab.project_path,
                            git_provider=opened_gitlab.git_provider,
                            branch=opened_gitlab.branch,
                            task="This stale request should be rejected.",
                        )
                    )

            self.assertEqual(first.active_repository_source, "gitlab")
            self.assertEqual(first.active_repository_path, "group/repo-a")
            self.assertEqual(second.active_repository_source, "local")
            self.assertEqual(second.active_repository_path, str(local_repo.resolve()))
            self.assertIn("source: local", prompts[-1])
            self.assertIn(str(local_repo.resolve()), prompts[-1])
            self.assertNotIn("group/repo-a", prompts[-1])

    def test_repository_open_plan_distinguishes_clone_and_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            repooperator_dir = Path(temp_home) / ".repooperator"
            repo_base = repooperator_dir / "repos"
            existing_repo = repo_base / "group" / "repo-a"
            existing_repo.mkdir(parents=True, exist_ok=True)
            config_path = repooperator_dir / "config.json"
            config_path.write_text(
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

            with patch.dict(
                os.environ,
                {
                    "HOME": temp_home,
                    "REPOOPERATOR_CONFIG_PATH": str(config_path),
                    "LOCAL_REPO_BASE_DIR": str(repo_base),
                },
                clear=False,
            ):
                refresh_plan = plan_repository_open(
                    RepoOpenRequest(
                        project_path="group/repo-a",
                        branch="main",
                        git_provider="gitlab",
                    )
                )
                clone_plan = plan_repository_open(
                    RepoOpenRequest(
                        project_path="group/repo-b",
                        branch="main",
                        git_provider="gitlab",
                    )
                )

            self.assertEqual(refresh_plan.open_mode, "refresh")
            self.assertTrue(refresh_plan.local_checkout_exists)
            self.assertEqual(clone_plan.open_mode, "clone")
            self.assertFalse(clone_plan.local_checkout_exists)

    def test_repository_open_request_identity_ignores_stale_operations(self) -> None:
        mark_repository_open_request_current("open-repo-a")
        self.assertTrue(is_repository_open_request_current("open-repo-a"))

        mark_repository_open_request_current("open-repo-b")
        self.assertFalse(is_repository_open_request_current("open-repo-a"))
        self.assertTrue(is_repository_open_request_current("open-repo-b"))

        clear_repository_open_request("open-repo-a")
        self.assertTrue(is_repository_open_request_current("open-repo-b"))

        clear_repository_open_request("open-repo-b")
        self.assertFalse(is_repository_open_request_current("open-repo-b"))

    def test_thread_history_persists_across_restart_and_repository_switch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            config_dir = Path(temp_home) / ".repooperator"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "config.json").write_text("{}", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "HOME": temp_home,
                    "REPOOPERATOR_CONFIG_PATH": str(config_dir / "config.json"),
                },
                clear=False,
            ):
                upsert_thread(
                    ThreadUpsertRequest(
                        id="thread-repo-a",
                        title="repo-a",
                        repo={
                            "project_path": "group/repo-a",
                            "git_provider": "gitlab",
                            "local_repo_path": str(config_dir / "repos" / "group" / "repo-a"),
                            "branch": "main",
                            "cloned": False,
                            "is_git_repository": True,
                            "message": "Repository ready",
                        },
                        messages=[
                            {
                                "id": "message-a-1",
                                "role": "system",
                                "content": "Repository switched. New chat started for gitlab:group/repo-a @ main.",
                                "timestamp": "2026-04-28T00:00:00.000Z",
                            },
                            {
                                "id": "message-a-2",
                                "role": "assistant",
                                "content": "Answer grounded in repo A.",
                                "timestamp": "2026-04-28T00:01:00.000Z",
                            },
                        ],
                        created_at="2026-04-28T00:00:00.000Z",
                        updated_at="2026-04-28T00:01:00.000Z",
                    )
                )

                restarted_worker_view = list_threads()

                upsert_thread(
                    ThreadUpsertRequest(
                        id="thread-repo-b",
                        title="repo-b",
                        repo={
                            "project_path": str(Path(temp_home) / "work" / "repo-b"),
                            "git_provider": "local",
                            "local_repo_path": str(Path(temp_home) / "work" / "repo-b"),
                            "branch": "main",
                            "cloned": False,
                            "is_git_repository": True,
                            "message": "Repository ready",
                        },
                        messages=[
                            {
                                "id": "message-b-1",
                                "role": "system",
                                "content": "Repository switched. New chat started for local:repo-b @ main.",
                                "timestamp": "2026-04-28T00:02:00.000Z",
                            }
                        ],
                        created_at="2026-04-28T00:02:00.000Z",
                        updated_at="2026-04-28T00:02:00.000Z",
                    )
                )

                switched_repository_view = list_threads()

            self.assertEqual(len(restarted_worker_view.threads), 1)
            self.assertEqual(restarted_worker_view.threads[0].id, "thread-repo-a")
            self.assertEqual(restarted_worker_view.threads[0].repo.git_provider, "gitlab")
            self.assertEqual(restarted_worker_view.threads[0].repo.branch, "main")
            self.assertEqual(len(restarted_worker_view.threads[0].messages), 2)

            self.assertEqual(len(switched_repository_view.threads), 2)
            self.assertEqual(switched_repository_view.threads[0].id, "thread-repo-b")
            self.assertEqual(switched_repository_view.threads[0].repo.git_provider, "local")
            self.assertEqual(switched_repository_view.threads[1].id, "thread-repo-a")


def _init_git_repo(path: Path, readme_title: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, stdout=subprocess.DEVNULL)
    (path / "README.md").write_text(f"# {readme_title}\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=RepoOperator Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "init",
        ],
        cwd=path,
        check=True,
        stdout=subprocess.DEVNULL,
    )


if __name__ == "__main__":
    unittest.main()
