"""出典の記録（原則F）。

自治体データ・審査機関プロファイル・座標系定義など、外部の一次情報に
由来する値には出典を必ず添えます。「この数字はどこから来たのか」に
答えられないデータは、事業判断の根拠にできません。

`confirmed_on` は**その原文を実際に見た日**です。制定日でも公布日でも
ありません。法令も条例も改正されるので、いつ時点の確認かが分からない
データは再照合できません。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class SourceRef:
    """一次情報への参照。"""

    document: str
    """文書名（例: `建築基準法施行令`、`EPSG Geodetic Parameter Dataset`）。"""

    confirmed_on: str
    """原文を確認した日（`YYYY-MM-DD`）。"""

    url: Optional[str] = None
    """原文の URL。紙資料しかない場合は None にして `note` に所在を書く。"""

    note: Optional[str] = None
    """版・施行日・注意書きなど。"""

    def __post_init__(self) -> None:
        if not self.document.strip():
            raise ValueError("出典には document が必要です（原則F）")
        if not _ISO_DATE.match(self.confirmed_on):
            raise ValueError(
                f"confirmed_on は YYYY-MM-DD で書いてください: {self.confirmed_on!r}"
            )

    def to_dict(self) -> dict:
        payload: dict = {"document": self.document, "confirmed_on": self.confirmed_on}
        if self.url:
            payload["url"] = self.url
        if self.note:
            payload["note"] = self.note
        return payload

    @classmethod
    def from_dict(cls, data: Any) -> "SourceRef":
        """自治体 YAML / プロファイル YAML の `source:` ブロックから作る。"""
        if not isinstance(data, dict):
            raise ValueError("source は document / confirmed_on を持つマップにしてください")
        unknown = set(data) - {"document", "confirmed_on", "url", "note"}
        if unknown:
            raise ValueError(f"source に未知のキーがあります: {sorted(unknown)}")
        missing = {"document", "confirmed_on"} - set(data)
        if missing:
            raise ValueError(f"source に {sorted(missing)} がありません（原則F）")
        return cls(
            document=str(data["document"]),
            confirmed_on=str(data["confirmed_on"]),
            url=data.get("url"),
            note=data.get("note"),
        )

    def __str__(self) -> str:
        tail = f" {self.url}" if self.url else ""
        return f"{self.document}（{self.confirmed_on} 確認）{tail}".rstrip()
