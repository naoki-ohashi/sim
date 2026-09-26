"""docs/ の索引・リンク切れ・エージェント案内ファイルの整合を検査する（ネットワーク不要）。"""
from __future__ import annotations

import json
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
        REPO / "docs" / "inbox" / "dashboard.md",
        REPO / "docs" / "archive" / "README.md",
    ]:
        head = md.read_text(encoding="utf-8").split("---\n", 2)
        assert len(head) == 3 and head[0] == "", md
        assert "summary:" in head[1] and "status:" in head[1], md


def test_obsidian_recommended_plugins():
    """推奨プラグインの一覧と設定がコミットされ、危険な設定になっていない。"""
    obsidian = REPO / ".obsidian"
    enabled = json.loads((obsidian / "community-plugins.json").read_text(encoding="utf-8"))
    assert enabled == ["dataview", "obsidian-git"]
    for plugin_id in enabled:
        assert (obsidian / "plugins" / plugin_id / "data.json").is_file(), plugin_id

    dataview = json.loads((obsidian / "plugins" / "dataview" / "data.json").read_text(encoding="utf-8"))
    assert dataview["enableDataviewJs"] is False
    assert dataview["enableInlineDataviewJs"] is False

    git = json.loads((obsidian / "plugins" / "obsidian-git" / "data.json").read_text(encoding="utf-8"))
    # 正本は PR で入れるので、自動コミット・自動 push はしない
    assert git["autoSaveInterval"] == 0
    assert git["autoPushInterval"] == 0


def test_obsidian_templates():
    """テンプレートのフォルダ設定と、受信箱・正本・保管のひな形が揃っている。"""
    settings = json.loads((REPO / ".obsidian" / "templates.json").read_text(encoding="utf-8"))
    folder = REPO / settings["folder"]
    assert folder.is_dir()
    expected_status = {"受信箱メモ.md": "inbox", "正本.md": "draft", "統合済み.md": "archived"}
    for name, status in expected_status.items():
        head = (folder / name).read_text(encoding="utf-8").split("---\n", 2)
        assert len(head) == 3 and head[0] == "", name
        assert f"status: {status}\n" in head[1], name
        assert "updated: {{date:YYYY-MM-DD}}" in head[1], name
    assert (folder / "未決・決定.md").is_file()
