import json
import sys
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from repooperator_worker.agent_core.context_budget import ContextBudget, compact_file_contents, estimate_chars  # noqa: E402


class ContextBudgetTests(unittest.TestCase):
    def test_large_file_contents_are_compacted(self) -> None:
        compacted = compact_file_contents(
            {"README.md": "# Demo\n" + "a" * 200, "large.py": "def huge():\n" + "x" * 1000},
            ContextBudget(max_chars=300, reserved_final_answer_chars=50, max_file_chars=180),
        )
        self.assertTrue(compacted.compacted)
        self.assertIn("README.md", compacted.included_files)
        self.assertTrue(compacted.omitted_files)
        json.dumps(compacted.model_dump(), ensure_ascii=False)

    def test_explicit_files_are_preserved_before_non_explicit(self) -> None:
        compacted = compact_file_contents(
            {"noise.py": "n" * 400, "target.py": "t" * 120},
            ContextBudget(max_chars=220, reserved_final_answer_chars=20, max_file_chars=200),
            explicit_files=["target.py"],
        )
        self.assertIn("target.py", compacted.included_files)
        self.assertGreaterEqual(estimate_chars(compacted.included_files["target.py"]), 120)


if __name__ == "__main__":
    unittest.main()
