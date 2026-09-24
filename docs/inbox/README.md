---
summary: AI エージェントや ChatGPT が書いた未統合の md を置く場所。レビュー後に正本へ統合し、元ファイルは archive へ。
status: stable
owner: 大橋
updated: 2026-09-24
---

# 受信箱（docs/inbox）

エージェント（Codex、Claude Code、Gemini）や ChatGPT が書いた **未統合** の md を
置くフォルダです。運用は [`../worldsim/knowledge_base.md`](../worldsim/knowledge_base.md) の §3。

- 置き場所: `docs/inbox/<tool>/YYYY-MM-DD_topic.md`（`<tool>` は `codex` / `claude` / `gemini` / `chatgpt`）
- frontmatter: `status: inbox`、`summary:`、`sources:`（元になった会話・資料）
- 正本（`docs/worldsim/` など）は直接書き換えない。大橋がレビューして統合する。
- 統合したら元ファイルは `docs/archive/` へ移し、`status: archived` にする。
- Obsidian で Dataview を入れていれば、一覧は [`dashboard.md`](dashboard.md) で見られる。

## ひな形

```markdown
---
summary: 1 行の要約
status: inbox
owner: Codex
sources: ChatGPT 会話 2026-09-20
updated: 2026-09-20
---

# 題名

## 提案

## 根拠・出典

## 正本への反映案
- `docs/worldsim/siteinfo_field_definitions.md` §8 に法令 X を追加
```
