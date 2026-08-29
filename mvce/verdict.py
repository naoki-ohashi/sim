"""判定の型と UNDETERMINED の伝播。

MVCE の各エンジン（日影・天空率・斜線・容積率）は「適合したか」を
真偽値ではなく `Verdict` で返します。真偽値だと、次の2つを表現できない
からです。

- **判断できない**（`UNDETERMINED`）— 自治体データが未整備、審査機関の
  方式が未定義、上流の `planned_far` が未確定、といった理由で計算を
  実行してはいけない状態。基本設計 原則H。
- **境界値**（`REQUIRES_REVIEW`）— 数値誤差の範囲でしか差がつかず、
  適合と断定してはいけない状態。基本設計 不変条件 M-7。

「判断できない」を `False`（不適合）にまとめてしまうと、データを足せば
通るかもしれない敷地を捨ててしまいます。逆に `True` にまとめると、
根拠のない適合を返してしまいます。どちらも実務では使えません。

不変条件 M-6 — UNDETERMINED は伝播する
---------------------------------------
下位のどれか一つでも `UNDETERMINED` なら、上位の総合判定も
`UNDETERMINED` になります。`PASS` で上書きしてはいけません。

この規則は `FAIL` に対しても効きます。「日影は明確に不適合で、天空率は
判断できない」という状態の総合判定は `UNDETERMINED` です。不適合の側に
倒したほうが安全に見えますが、MVCE の出力は不変条件 M-3 により
「なぜこれ以上入らないか」（`binding_constraint`）を答えられなければ
価値がありません。判断できない制約が残っている限り、支配的制約を
名指しできないので、総合判定は「判断できない」が正確です。

失われる情報はありません。`Judgement.parts` に下位の判定がそのまま
残るので、`judgement.find(Verdict.FAIL)` で明確な不適合を取り出せます。

この構造は `Judgement` のコンストラクタが強制します。`parts` を持つ
`Judgement` の `verdict` が `combine(parts)` と食い違う場合、生成時点で
`VerdictError` を送出します。集約側で握りつぶせないようにするためです。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Iterator, Optional, Sequence, Tuple, Union


class VerdictError(ValueError):
    """判定の組み立てが不変条件に反したときに送出する。"""


class Verdict(Enum):
    """適合判定の4状態。"""

    PASS = "pass"
    """適合。根拠のある余裕をもって基準を満たしている。"""

    FAIL = "fail"
    """不適合。基準を満たしていないことが確定している。"""

    UNDETERMINED = "undetermined"
    """判断不能。データ未整備・方式未定義・上流未確定。原則H。"""

    REQUIRES_REVIEW = "requires_review"
    """境界値。有資格者の確認を要する。不変条件 M-7。"""

    def __str__(self) -> str:  # JSON やログに出すとき用
        return self.value

    @property
    def is_conclusive(self) -> bool:
        """`PASS` / `FAIL` のように、それ以上の情報なしで扱える判定か。"""
        return self in (Verdict.PASS, Verdict.FAIL)


# 集約したときの強さ。数字が大きいほうが勝つ。
# UNDETERMINED が最強なのが不変条件 M-6。
_PRECEDENCE = {
    Verdict.PASS: 0,
    Verdict.REQUIRES_REVIEW: 1,
    Verdict.FAIL: 2,
    Verdict.UNDETERMINED: 3,
}


def combine(verdicts: Iterable[Verdict]) -> Verdict:
    """下位判定を1つにまとめる。強さは PASS < REQUIRES_REVIEW < FAIL < UNDETERMINED。

    空の列を渡した場合は `UNDETERMINED` を返します。「何も判定していない」
    ことは「適合」ではありません（原則H）。判定すべき制約が本当に無い
    場合は、その旨を理由に添えた `PASS` を明示的に1件渡してください。
    """
    strongest = None
    for verdict in verdicts:
        if not isinstance(verdict, Verdict):
            raise VerdictError(f"Verdict ではない値が渡されました: {verdict!r}")
        if strongest is None or _PRECEDENCE[verdict] > _PRECEDENCE[strongest]:
            strongest = verdict
    return Verdict.UNDETERMINED if strongest is None else strongest


def from_margin(
    margin: float,
    *,
    epsilon: float,
    subject: str = "",
) -> Verdict:
    """余裕（実測値 − 基準値）から判定を作る。境界値は M-7 により REQUIRES_REVIEW。

    `margin` は「正なら適合側」に符号を揃えた差です。天空率なら Ps − Pr、
    日影なら 規制時間 − 実日影時間。`epsilon` はそのエンジンが主張できる
    有効数字の幅で、これを下回る差は数値誤差と区別がつかないため
    `PASS` にも `FAIL` にもしません。
    """
    if epsilon < 0:
        raise VerdictError(f"epsilon は 0 以上にしてください: {epsilon!r}")
    if margin != margin:  # NaN。計算が壊れているので黙って通さない
        raise VerdictError(f"margin が NaN です（{subject or '判定対象不明'}）")
    if abs(margin) < epsilon:
        return Verdict.REQUIRES_REVIEW
    return Verdict.PASS if margin > 0.0 else Verdict.FAIL


@dataclass(frozen=True)
class Reason:
    """判定の理由。日本語で、人が読んで次の一手が分かる粒度で書く。"""

    code: str
    """機械可読な識別子（例: `profile_not_registered`）。"""

    message: str
    """日本語の説明。UNDETERMINED なら「何を足せば判定できるか」を書く。"""

    article: Optional[str] = None
    """根拠条文（例: `令135条の9`）。条文に紐づかない理由は None。"""

    def __str__(self) -> str:
        return f"{self.message}（{self.article}）" if self.article else self.message


@dataclass(frozen=True)
class Judgement:
    """1つの判定。下位判定を束ねる集約にもなる。

    `parts` を与えた場合、`verdict` は `combine(parts)` と一致していなければ
    なりません（不変条件 M-6）。一致しない値を渡すと `VerdictError` です。
    集約は `Judgement.aggregate()` を使うのが普通で、そちらは自動で
    正しい `verdict` を計算します。
    """

    subject: str
    """何についての判定か（例: `天空率（道路）`）。"""

    verdict: Verdict
    reasons: Tuple[Reason, ...] = ()
    parts: Tuple["Judgement", ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.verdict, Verdict):
            raise VerdictError(f"verdict が Verdict ではありません: {self.verdict!r}")
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "parts", tuple(self.parts))
        for part in self.parts:
            if not isinstance(part, Judgement):
                raise VerdictError(f"parts に Judgement 以外が含まれています: {part!r}")
        if self.parts:
            expected = combine(part.verdict for part in self.parts)
            if self.verdict is not expected:
                raise VerdictError(
                    f"{self.subject}: 下位判定は {expected} ですが {self.verdict} を"
                    f"指定しました。不変条件 M-6 により上書きできません"
                )
        if self.verdict is Verdict.UNDETERMINED and not self.reasons and not self.parts:
            raise VerdictError(
                f"{self.subject}: UNDETERMINED には理由が必要です。"
                f"何が足りなくて判断できないのかを Reason に書いてください（原則H）"
            )

    @classmethod
    def aggregate(
        cls,
        subject: str,
        parts: Sequence["Judgement"],
        reasons: Sequence[Reason] = (),
    ) -> "Judgement":
        """下位判定から総合判定を組み立てる。M-6 に従って verdict を決める。"""
        parts = tuple(parts)
        verdict = combine(part.verdict for part in parts)
        reasons = tuple(reasons)
        if verdict is Verdict.UNDETERMINED and not parts and not reasons:
            reasons = (
                Reason(
                    code="no_checks_performed",
                    message=f"{subject}: 判定した制約が1つもありません。"
                    f"適用すべき制約が無いことが確認できている場合は、"
                    f"その旨を理由に添えた PASS を明示してください",
                ),
            )
        return cls(subject=subject, verdict=verdict, reasons=reasons, parts=parts)

    def walk(self) -> Iterator["Judgement"]:
        """自分自身と、すべての下位判定を深さ優先で辿る。"""
        yield self
        for part in self.parts:
            for node in part.walk():
                yield node

    def find(self, verdict: Verdict) -> Tuple["Judgement", ...]:
        """指定の判定を持つ葉を集める。総合が UNDETERMINED でも FAIL を取り出せる。"""
        return tuple(node for node in self.walk() if node.verdict is verdict and not node.parts)

    def all_reasons(self) -> Tuple[Reason, ...]:
        """自分と下位のすべての理由を、辿った順に集める。"""
        return tuple(reason for node in self.walk() for reason in node.reasons)

    def to_dict(self) -> dict:
        """JSON へ落とすための素の辞書。`io/result_json.py`（Phase 4）が使う。"""
        payload: dict = {"subject": self.subject, "verdict": self.verdict.value}
        if self.reasons:
            payload["reasons"] = [
                {"code": r.code, "message": r.message, **({"article": r.article} if r.article else {})}
                for r in self.reasons
            ]
        if self.parts:
            payload["parts"] = [part.to_dict() for part in self.parts]
        return payload


class _Undetermined:
    """数値フィールドの「判断できない」を表す番兵。

    `achievable_far: float | UNDETERMINED` のように、値が無いのではなく
    「求められなかった」ことを表します。`None`（未設定）とは区別します。

    算術に混ぜると `TypeError` になります。0 や NaN として静かに計算へ
    紛れ込み、根拠のない数字が出力まで流れるのを防ぐためです。
    """

    _instance: Optional["_Undetermined"] = None

    def __new__(cls) -> "_Undetermined":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNDETERMINED"

    def __str__(self) -> str:
        return "UNDETERMINED"

    def __bool__(self) -> bool:
        # if value: ... で「値がある」と誤読されないよう偽にする
        return False

    def __eq__(self, other: Any) -> bool:
        return other is self

    def __hash__(self) -> int:
        return hash("mvce.UNDETERMINED")

    def _reject(self, *_args: Any, **_kwargs: Any) -> Any:
        raise TypeError(
            "UNDETERMINED は計算に使えません。判断できない値を数値として"
            "扱おうとしています（原則H）。is_undetermined() で分岐してください"
        )

    __add__ = __radd__ = __sub__ = __rsub__ = _reject
    __mul__ = __rmul__ = __truediv__ = __rtruediv__ = _reject
    __floordiv__ = __rfloordiv__ = __mod__ = __rmod__ = _reject
    __pow__ = __rpow__ = __neg__ = __pos__ = __abs__ = _reject
    __lt__ = __le__ = __gt__ = __ge__ = _reject
    __float__ = __int__ = __round__ = _reject

    def __reduce__(self) -> str:  # pickle しても同一インスタンスに戻す
        return "UNDETERMINED"


UNDETERMINED = _Undetermined()
"""数値が求められなかったことを表す唯一の番兵。`is` で比較してください。"""

Undeterminable = Union[float, _Undetermined]
"""`float` か `UNDETERMINED` を取る数値フィールドの型注釈。"""


def is_undetermined(value: Any) -> bool:
    """`UNDETERMINED` 番兵か、`UNDETERMINED` 判定かを見分ける。"""
    return value is UNDETERMINED or value is Verdict.UNDETERMINED


__all__ = [
    "Judgement",
    "Reason",
    "UNDETERMINED",
    "Undeterminable",
    "Verdict",
    "VerdictError",
    "combine",
    "from_margin",
    "is_undetermined",
]
