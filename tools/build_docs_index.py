#!/usr/bin/env python3
"""docs/ 配下の Markdown を走査して索引（docs/INDEX.md）を生成し、リンク切れを検出する。

Obsidian の vault としてリポジトリを開いたとき、この索引が「Map of Content」に
なる。エージェント（Codex / Claude Code / Gemini）が md を追加・統合したあとに
必ず実行して、索引とリンクの整合を保つ。

使い方:
    python3 tools/build_docs_index.py          # INDEX.md を書き換え、リンク切れを表示
    python3 tools/build_docs_index.py --check  # 書き換えず、索引が古い・リンク切れがあれば終了コード 1

規約:
- タイトルは frontmatter の `title`、無ければ最初の見出し 1（`# ...`）、無ければファイル名。
- 説明は frontmatter の `summary`、無ければ最初の空でない段落の 1 行目（引用・見出し・
  コードを除く）。
- リンクは相対パスの Markdown リンクだけを検査する（http(s)、mailto、`#` だけ、
  絶対パスは対象外）。`[[wikilink]]` は使わない（GitHub で描画されないため）。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
INDEX = DOCS / "INDEX.md"
BEGIN = "<!-- BEGIN GENERATED INDEX -->"
END = "<!-- END GENERATED INDEX -->"

# 索引に載せる順番と見出し。ここに無いフォルダは末尾にアルファベット順で並ぶ。
SECTIONS: list[tuple[str, str]] = [
    ("worldsim", "WorldSim / SiteInfo（構想・要件・設計・実装指示）"),
    ("mve", "MVE（最大ボリューム計算）"),
    (".", "MVE 以前の文書（JW-CAD 版など）"),
    ("inbox", "受信箱（AI が書いた未統合の md）"),
    ("archive", "保管（統合済み・古い版）"),
]

LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def parse_frontmatter(text: str) -> dict[str, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "-")):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip("\"'")
    return out


def strip_frontmatter(text: str) -> str:
    return FRONTMATTER_RE.sub("", text, count=1)


def title_of(path: Path, text: str, fm: dict[str, str]) -> str:
    if fm.get("title"):
        return fm["title"]
    for line in strip_frontmatter(text).splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def plain(s: str) -> str:
    """索引に載せる 1 行から、リンク・強調・コード記法を落とす。"""
    s = LINK_RE.sub(r"\1", s)
    return s.replace("**", "").replace("`", "").strip()


def summary_of(text: str, fm: dict[str, str]) -> str:
    if fm.get("summary"):
        return plain(fm["summary"])
    in_code = False
    for line in strip_frontmatter(text).splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not s or s.startswith(("#", ">", "|", "-", "*", "<!--", "!")):
            continue
        return plain(s)[:80]
    return ""


def check_links(md: Path, text: str) -> list[str]:
    """相対リンクの参照先が存在しなければ、その一覧を返す。"""
    broken: list[str] = []
    for _, target in LINK_RE.findall(strip_frontmatter(text)):
        if target.startswith(("http://", "https://", "mailto:", "#", "/")):
            continue
        target_path = target.split("#", 1)[0]
        if not target_path:
            continue
        if not (md.parent / target_path).exists():
            broken.append(target)
    return broken


def build(md_files: list[Path]) -> tuple[str, dict[Path, list[str]]]:
    groups: dict[str, list[tuple[Path, str, str, dict[str, str]]]] = {}
    broken: dict[Path, list[str]] = {}
    for md in md_files:
        text = md.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        rel = md.relative_to(DOCS)
        key = rel.parts[0] if len(rel.parts) > 1 else "."
        groups.setdefault(key, []).append((rel, title_of(md, text, fm), summary_of(text, fm), fm))
        b = check_links(md, text)
        if b:
            broken[md] = b

    order = [k for k, _ in SECTIONS if k in groups]
    order += sorted(k for k in groups if k not in order)
    titles = dict(SECTIONS)

    lines: list[str] = []
    for key in order:
        lines.append(f"## {titles.get(key, key)}")
        lines.append("")
        lines.append("| 文書 | 内容 | 状態 |")
        lines.append("|---|---|---|")
        for rel, title, summary, fm in sorted(groups[key], key=lambda t: str(t[0])):
            status = fm.get("status", "")
            lines.append(f"| [{title}]({rel.as_posix()}) | {summary} | {status} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n", broken


def render_index(generated: str) -> str:
    if INDEX.exists():
        current = INDEX.read_text(encoding="utf-8")
        if BEGIN in current and END in current:
            head = current.split(BEGIN, 1)[0]
            tail = current.split(END, 1)[1]
            return f"{head}{BEGIN}\n{generated}{END}{tail}"
    head = (
        "---\n"
        "title: 文書索引（Map of Content）\n"
        "status: generated\n"
        "---\n\n"
        "# 文書索引（Map of Content）\n\n"
        "> このファイルは `python3 tools/build_docs_index.py` が生成します。"
        "マーカーの間は手で編集しないでください。\n"
        "> 運用ルールは [worldsim/knowledge_base.md](worldsim/knowledge_base.md)。\n\n"
    )
    return f"{head}{BEGIN}\n{generated}{END}\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="書き換えずに検査だけ行う")
    args = ap.parse_args()

    md_files = sorted(p for p in DOCS.rglob("*.md") if p != INDEX)
    generated, broken = build(md_files)
    new_index = render_index(generated)

    for md, targets in sorted(broken.items()):
        for t in targets:
            print(f"リンク切れ: {md.relative_to(REPO)} -> {t}")

    if args.check:
        stale = not INDEX.exists() or INDEX.read_text(encoding="utf-8") != new_index
        if stale:
            print("docs/INDEX.md が古いです。python3 tools/build_docs_index.py を実行してください。")
        return 1 if (stale or broken) else 0

    INDEX.write_text(new_index, encoding="utf-8")
    print(f"docs/INDEX.md を更新しました（{len(md_files)} 件）。")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
