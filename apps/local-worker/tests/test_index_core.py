"""Unit tests for the codebase index core (build / incremental / BM25 / symbols).

These drive builder+store+query directly on a temp repo and temp DB, so they do
not depend on the worker's home directory or on tree-sitter being installed. The
regex-fallback path is what CI exercises (the tree-sitter extra is not installed
there); the tree-sitter assertions skip gracefully when the pack is absent.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from repooperator_worker.agent_core.index import builder, query, store  # noqa: E402
from repooperator_worker.agent_core.index import symbols as symbols_mod  # noqa: E402


def _write(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class IndexCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        self.db = Path(self._tmp.name) / "index.db"
        self.conn = store.connect(self.db)

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    # ── build ────────────────────────────────────────────────────────────────
    def test_build_catalogs_supported_files_and_skips_junk(self) -> None:
        _write(self.repo, "src/app.py", "def hello():\n    return 1\n")
        _write(self.repo, "README.md", "# Title\nsome text\n")
        _write(self.repo, "node_modules/pkg/index.js", "module.exports = 1\n")  # skip dir
        (self.repo / "logo.png").write_bytes(b"\x89PNG\x00\x00binary")          # binary
        _write(self.repo, "src/app 2.py", "x = 1\n")                             # stale dup copy

        stats = builder.build(self.conn, self.repo)
        paths = {row["path"] for row in self.conn.execute("SELECT path FROM files")}

        self.assertIn("src/app.py", paths)
        self.assertIn("README.md", paths)
        self.assertNotIn("node_modules/pkg/index.js", paths)
        self.assertNotIn("logo.png", paths)
        self.assertNotIn("src/app 2.py", paths)
        self.assertEqual(stats["indexed"], store.file_count(self.conn))

    # ── incremental refresh ───────────────────────────────────────────────────
    def test_refresh_picks_up_add_change_delete(self) -> None:
        _write(self.repo, "a.py", "def alpha():\n    pass\n")
        _write(self.repo, "b.py", "def beta():\n    pass\n")
        builder.build(self.conn, self.repo)

        # add
        _write(self.repo, "c.py", "def gamma():\n    pass\n")
        # change
        _write(self.repo, "a.py", "def alpha_renamed():\n    pass\n")
        # delete
        (self.repo / "b.py").unlink()

        result = builder.refresh_stale(self.conn, self.repo)
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["changed"], 1)
        self.assertEqual(result["removed"], 1)

        self.assertTrue(query.lookup_symbol(self.conn, "gamma"))
        self.assertTrue(query.lookup_symbol(self.conn, "alpha_renamed"))
        self.assertFalse(query.lookup_symbol(self.conn, "alpha"))  # old name gone
        self.assertFalse(query.lookup_symbol(self.conn, "beta"))   # deleted file

    def test_apply_delta_updates_immediately(self) -> None:
        _write(self.repo, "x.py", "def one():\n    pass\n")
        builder.build(self.conn, self.repo)
        _write(self.repo, "y.py", "def two():\n    pass\n")
        builder.apply_delta(self.conn, self.repo, created=["y.py"])
        self.assertTrue(query.lookup_symbol(self.conn, "two"))

    # ── BM25 ranking ──────────────────────────────────────────────────────────
    def test_bm25_only_matches_files_with_term(self) -> None:
        _write(self.repo, "hit.py", "needle needle configuration handler\n")
        _write(self.repo, "miss.py", "completely unrelated content here\n")
        builder.build(self.conn, self.repo)
        results = query.search_files(self.conn, [], text_queries=["needle"], max_results=10)
        paths = [r["path"] for r in results]
        self.assertIn("hit.py", paths)
        self.assertNotIn("miss.py", paths)

    def test_bm25_length_normalization_prefers_concise_file(self) -> None:
        _write(self.repo, "short.py", "widget = 1\n")
        _write(self.repo, "long.py", "widget = 1\n" + "filler = 0\n" * 400)
        builder.build(self.conn, self.repo)
        results = query.search_files(self.conn, [], text_queries=["widget"], max_results=10)
        paths = [r["path"] for r in results]
        self.assertEqual(paths[0], "short.py", f"expected short.py first, got {paths}")

    # ── search_files signals ──────────────────────────────────────────────────
    def test_search_files_basename_and_symbol_signals(self) -> None:
        _write(self.repo, "pkg/service.py", "def compute_total():\n    return 0\n")
        builder.build(self.conn, self.repo)

        by_name = query.search_files(self.conn, ["service.py"], max_results=5)
        self.assertEqual(by_name[0]["path"], "pkg/service.py")
        self.assertTrue(any("basename" in r for r in by_name[0]["reasons"]))

        by_symbol = query.search_files(self.conn, ["compute_total"], max_results=5)
        self.assertEqual(by_symbol[0]["path"], "pkg/service.py")
        self.assertTrue(any("symbol" in r for r in by_symbol[0]["reasons"]))

    # ── symbols: regex fallback always works ──────────────────────────────────
    def test_regex_fallback_extracts_defs(self) -> None:
        syms, mode = symbols_mod._extract_regex("class Foo:\n    def bar(self):\n        pass\n"), None
        names = {s.name for s in syms}
        self.assertIn("Foo", names)
        self.assertIn("bar", names)

    @unittest.skipUnless(symbols_mod.tree_sitter_available(), "tree-sitter pack not installed")
    def test_tree_sitter_symbols_when_available(self) -> None:
        _write(self.repo, "m.py", "class Widget:\n    def render(self):\n        return 1\n")
        builder.build(self.conn, self.repo)
        cls = query.lookup_symbol(self.conn, "Widget")
        self.assertTrue(cls and cls[0]["kind"] == "class")
        meth = query.lookup_symbol(self.conn, "render")
        self.assertTrue(meth and meth[0]["line"] == 2)

    # ── search_text ───────────────────────────────────────────────────────────
    def test_search_text_returns_line_matches_from_catalog(self) -> None:
        _write(self.repo, "svc.py", "def handler():\n    token = SECRET\n    return handler\n")
        builder.build(self.conn, self.repo)
        matches, files_searched, truncated = query.search_text(
            self.conn, self.repo, query="def handler", path_globs=[],
            max_results=10, case_sensitive=False, regex=False, context_lines=1,
        )
        self.assertTrue(matches)
        self.assertEqual(matches[0]["path"], "svc.py")
        self.assertEqual(matches[0]["line"], 1)
        self.assertGreaterEqual(files_searched, 1)


if __name__ == "__main__":
    unittest.main()
