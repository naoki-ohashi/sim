"""docs/ の索引・リンク切れ・エージェント案内ファイルの整合を検査する（ネットワーク不要）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_docs_index_is_current_and_links_resolve():
    proc = subprocess.run(
        [sys.executable, str(REPO / "tools" / "build_docs_index.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_agent_guides_are_identical():
    texts = {name: (REPO / name).read_text(encoding="utf-8") for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md")}
    assert texts["AGENTS.md"] == texts["CLAUDE.md"] == texts["GEMINI.md"]


def test_docs_have_frontmatter_summary():
    """正本（worldsim）と受信箱・保管の案内は frontmatter に summary と status を持つ。"""
    for md in sorted((REPO / "docs" / "worldsim").glob("*.md")) + [
        REPO / "docs" / "inbox" / "README.md",
        REPO / "docs" / "archive" / "README.md",
    ]:
        head = md.read_text(encoding="utf-8").split("---\n", 2)
        assert len(head) == 3 and head[0] == "", md
        assert "summary:" in head[1] and "status:" in head[1], md
