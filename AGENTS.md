# エージェント向けの案内（Codex / Claude Code 共通）

このリポジトリは SIM WORLD（WorldSim）のエンジン群です。現在は
MVE（最大ボリューム計算、`mve/`、`web/mve/`）と、その前段の
SiteInfo（敷地情報データベース、`db/siteinfo/`、`docs/worldsim/`）を扱っています。

## SiteInfo を実装するときに読む順番

1. `docs/worldsim/vision.md` — 考え方（正確性の層と表現の層を分ける）
2. `docs/worldsim/siteinfo_requirements.md` — 入力要件（自動入力は補助、確定はユーザー）
3. `docs/worldsim/siteinfo_field_definitions.md` — 項目定義書
4. `docs/worldsim/siteinfo_db_design.md` と `db/siteinfo/schema.sql` — DB 設計（スキーマが正）
5. `docs/worldsim/siteinfo_implementation_guide.md` — 実装指示書（API、GeoJSON、取得元別アダプタ、マイルストーン）
6. `docs/worldsim/siteinfo_ui_design.md` — 入力・確認画面
7. `docs/worldsim/siteinfo_agent_prompts.md` — 依頼文のひな形

## 守ること

- 自動入力した値は `site_field_provenance` に `unconfirmed` で記録し、確認済みの値を上書きしない。
- 法令の条文番号・数値は一次情報で確認し、出典を書く。推測で埋めない（`docs/mve/legal_basis.md` の流儀）。
- `db/siteinfo/schema.sql` を変えるときは、設計書と `smoke_test.sql` を同じコミットで直す。
- SiteInfo v0.1 GeoJSON の `properties` キーと MVE の入力形式を壊さない。
- ネットワークに出られない前提でテストを書く（取得元アダプタは fixture で検証）。
- API キーなどの秘密情報はコードに書かない（環境変数）。
- 既存の `mve/`、`web/`、`jwcad_volume/` は SiteInfo の作業で変更しない。
- 1 マイルストーン 1 PR。受け入れ条件を満たしてから PR を作る。

## 検証コマンド

```bash
pip install -e ".[dev]"      # 既存
pytest                       # 既存＋SiteInfo（DB テストは SITEINFO_TEST_DSN があるときだけ）
ruff check .                 # SiteInfo 追加後
# PostGIS があるとき
psql -d siteinfo -v ON_ERROR_STOP=1 -f db/siteinfo/schema.sql
psql -d siteinfo -v ON_ERROR_STOP=1 -f db/siteinfo/seed_catalog.sql
psql -d siteinfo -v ON_ERROR_STOP=1 -f db/siteinfo/smoke_test.sql
```

## MVE について

MVE の設計は `docs/mve/design_spec.md`、操作は `docs/mve/manual.md`。
Python 版と JS 版は同じ結果になることを `tests/test_js_parity.py` で担保している。
