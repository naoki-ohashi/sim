# エージェント向けの案内（Codex / Claude Code / Gemini 共通）

このリポジトリは WORLD SIM（WorldSim）のエンジン群です。現在は
MVE（最大ボリューム計算、`mve/`、`web/mve/`）と、その前段の
SiteInfo（敷地情報データベース、`db/siteinfo/`、`docs/worldsim/`）を扱っています。
文書の索引は `docs/INDEX.md`、文書の整理・統合ルールは
`docs/worldsim/knowledge_base.md`（リポジトリを Obsidian の vault として扱う）。
`AGENTS.md`・`CLAUDE.md`・`GEMINI.md` は同じ内容で、どれか 1 つを直したら他も同じにする。

## SiteInfo を実装するときに読む順番

1. `docs/worldsim/vision.md` — 考え方（正確性の層と表現の層を分ける）
2. `docs/worldsim/siteinfo_requirements.md` — 入力要件（自動入力は補助、確定はユーザー）
3. `docs/worldsim/siteinfo_field_definitions.md` — 項目定義書
4. `docs/worldsim/siteinfo_db_design.md` と `db/siteinfo/schema.sql` — DB 設計（スキーマが正）
5. `docs/worldsim/siteinfo_implementation_guide.md` — 実装指示書（API、GeoJSON、取得元別アダプタ、マイルストーン）
6. `docs/worldsim/siteinfo_ui_design.md` — 入力・確認画面
7. `docs/worldsim/siteinfo_agent_prompts.md` — 依頼文のひな形
8. `docs/worldsim/knowledge_base.md` — md の書き方と受信箱→正本の統合手順

## 守ること

- 自動入力した値は `site_field_provenance` に `unconfirmed` で記録し、確認済みの値を上書きしない。
- 法令の条文番号・数値は一次情報で確認し、出典を書く。推測で埋めない（`docs/mve/legal_basis.md` の流儀）。
- `db/siteinfo/schema.sql` を変えるときは、設計書と `smoke_test.sql` を同じコミットで直す。
- SiteInfo v0.1 GeoJSON の `properties` キーと MVE の入力形式を壊さない。
- ネットワークに出られない前提でテストを書く（取得元アダプタは fixture で検証）。
- API キーなどの秘密情報はコードに書かない（環境変数）。
- 既存の `mve/`、`web/`、`jwcad_volume/` は SiteInfo の作業で変更しない。
- 1 マイルストーン 1 PR。受け入れ条件を満たしてから PR を作る。
- 文書（md）を書くときは frontmatter（`summary` / `status` / `owner` / `updated`）を付け、
  リンクは相対パスの Markdown リンクにする（`[[wikilink]]` は使わない）。
- 依頼されていない文書の追加・提案は正本を直接書き換えず `docs/inbox/<tool>/` に置く。
- `docs/` の md を増減・改名したら `python3 tools/build_docs_index.py` で
  `docs/INDEX.md` を再生成し、リンク切れを 0 にする。

## 検証コマンド

```bash
pip install -e ".[dev]"      # 既存
pytest                       # 既存＋SiteInfo（DB テストは SITEINFO_TEST_DSN があるときだけ）
ruff check .                 # SiteInfo 追加後
python3 tools/build_docs_index.py --check   # 文書索引とリンク切れ（pytest でも走る）
# PostGIS があるとき
psql -d siteinfo -v ON_ERROR_STOP=1 -f db/siteinfo/schema.sql
psql -d siteinfo -v ON_ERROR_STOP=1 -f db/siteinfo/seed_catalog.sql
psql -d siteinfo -v ON_ERROR_STOP=1 -f db/siteinfo/smoke_test.sql
```

## MVE について

MVE の設計は `docs/mve/design_spec.md`、操作は `docs/mve/manual.md`。
Python 版と JS 版は同じ結果になることを `tests/test_js_parity.py` で担保している。
