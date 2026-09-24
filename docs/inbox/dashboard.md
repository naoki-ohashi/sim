---
summary: Obsidian の Dataview で受信箱・下書き・最近の更新・frontmatter 欠けを一覧するダッシュボード。
status: stable
owner: 大橋
updated: 2026-09-24
---

# 文書ダッシュボード（Dataview）

> Obsidian で Dataview プラグインを有効にすると、下のコードブロックが表になります。
> GitHub ではコードのまま表示されます。設定と導入手順は
> [`../worldsim/knowledge_base.md`](../worldsim/knowledge_base.md) の §4。

## 受信箱（未統合）

レビュー待ちの md。統合したら `docs/archive/` へ移し、`status: archived` にする。

```dataview
TABLE summary AS "内容", owner AS "書いた人", sources AS "出典", updated AS "更新"
FROM "docs/inbox"
WHERE status = "inbox"
SORT updated DESC
```

## 受信箱で 14 日以上止まっているもの

```dataview
TABLE summary AS "内容", owner AS "書いた人", updated AS "更新"
FROM "docs/inbox"
WHERE status = "inbox" AND updated AND date(today) - updated > dur(14 days)
SORT updated ASC
```

## 下書きの正本

```dataview
TABLE summary AS "内容", owner AS "担当", updated AS "更新"
FROM "docs" AND -"docs/inbox" AND -"docs/archive"
WHERE status = "draft"
SORT updated DESC
```

## 最近更新した文書

```dataview
TABLE status AS "状態", summary AS "内容", updated AS "更新"
FROM "docs" AND -"docs/archive"
WHERE updated
SORT updated DESC
LIMIT 15
```

## frontmatter が欠けている文書

`summary` か `status` が無い md。索引の説明が本文から推測されるので、付け足す。

```dataview
LIST
FROM "docs" AND -"docs/INDEX"
WHERE !summary OR !status
SORT file.path ASC
```
