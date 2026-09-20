"""判定の型と UNDETERMINED 伝播の検証（基本設計 原則H・不変条件 M-6/M-7）。"""
import pickle

import pytest

from mvce.verdict import (
    UNDETERMINED,
    Judgement,
    Reason,
    Verdict,
    VerdictError,
    combine,
    from_margin,
    is_undetermined,
)


# --- combine の強さ関係 -------------------------------------------------

def test_pass_only_is_pass():
    assert combine([Verdict.PASS, Verdict.PASS]) is Verdict.PASS


def test_fail_beats_pass():
    assert combine([Verdict.PASS, Verdict.FAIL]) is Verdict.FAIL


def test_fail_beats_requires_review():
    """境界値の制約が1つあっても、明確な不適合があれば不適合。"""
    assert combine([Verdict.REQUIRES_REVIEW, Verdict.FAIL]) is Verdict.FAIL


def test_requires_review_beats_pass():
    assert combine([Verdict.PASS, Verdict.REQUIRES_REVIEW]) is Verdict.REQUIRES_REVIEW


def test_undetermined_beats_pass():
    """M-6: PASS で上書きしてはならない。"""
    assert combine([Verdict.PASS, Verdict.UNDETERMINED]) is Verdict.UNDETERMINED


def test_undetermined_beats_fail():
    """M-6 は FAIL に対しても効く。

    判断できない制約が残っている限り支配的制約（M-3）を名指しできない
    ので、総合判定は「判断できない」。明確な不適合は parts に残る。
    """
    assert combine([Verdict.FAIL, Verdict.UNDETERMINED]) is Verdict.UNDETERMINED


def test_empty_is_undetermined():
    """何も判定していないことは適合ではない（原則H）。"""
    assert combine([]) is Verdict.UNDETERMINED


def test_combine_rejects_non_verdict():
    with pytest.raises(VerdictError):
        combine([Verdict.PASS, True])


# --- from_margin（M-7 の境界値） ---------------------------------------

def test_margin_clearly_positive_is_pass():
    assert from_margin(0.5, epsilon=0.1) is Verdict.PASS


def test_margin_clearly_negative_is_fail():
    assert from_margin(-0.5, epsilon=0.1) is Verdict.FAIL


@pytest.mark.parametrize("margin", [0.0, 0.05, -0.05, 0.0999, -0.0999])
def test_margin_within_epsilon_requires_review(margin):
    """M-7: 数値誤差の範囲では適合と断定しない。"""
    assert from_margin(margin, epsilon=0.1) is Verdict.REQUIRES_REVIEW


def test_margin_exactly_at_epsilon_is_conclusive():
    """epsilon ちょうどは誤差の外側として扱う（境界の定義を固定する）。"""
    assert from_margin(0.1, epsilon=0.1) is Verdict.PASS
    assert from_margin(-0.1, epsilon=0.1) is Verdict.FAIL


def test_zero_epsilon_never_requires_review():
    assert from_margin(0.0, epsilon=0.0) is Verdict.FAIL
    assert from_margin(1e-12, epsilon=0.0) is Verdict.PASS


def test_nan_margin_is_rejected():
    with pytest.raises(VerdictError):
        from_margin(float("nan"), epsilon=0.1)


def test_negative_epsilon_is_rejected():
    with pytest.raises(VerdictError):
        from_margin(1.0, epsilon=-0.1)


# --- Judgement -----------------------------------------------------------

def test_aggregate_propagates_undetermined():
    j = Judgement.aggregate("総合", [
        Judgement("日影", Verdict.PASS),
        Judgement("天空率", Verdict.UNDETERMINED,
                  [Reason("profile_missing", "東京都方式以外は 2.0 では未対応")]),
    ])
    assert j.verdict is Verdict.UNDETERMINED


def test_aggregate_of_all_pass_is_pass():
    j = Judgement.aggregate("総合", [
        Judgement("日影", Verdict.PASS),
        Judgement("天空率", Verdict.PASS),
    ])
    assert j.verdict is Verdict.PASS


def test_cannot_overwrite_undetermined_with_pass():
    """M-6 を型レベルで強制する。集約側で握りつぶせない。"""
    with pytest.raises(VerdictError):
        Judgement("総合", Verdict.PASS, parts=[
            Judgement("天空率", Verdict.UNDETERMINED, [Reason("x", "y")]),
        ])


def test_undetermined_leaf_requires_a_reason():
    """原則H: 何が足りないのかを書かずに UNDETERMINED を返させない。"""
    with pytest.raises(VerdictError):
        Judgement("天空率", Verdict.UNDETERMINED)


def test_empty_aggregate_is_undetermined_with_reason():
    j = Judgement.aggregate("総合", [])
    assert j.verdict is Verdict.UNDETERMINED
    assert j.reasons and j.reasons[0].code == "no_checks_performed"


def test_fail_is_recoverable_from_an_undetermined_aggregate():
    """総合が UNDETERMINED でも、明確な不適合は失われない。"""
    j = Judgement.aggregate("総合", [
        Judgement("日影", Verdict.FAIL, [Reason("over_hours", "5m線で3.2時間")]),
        Judgement("天空率", Verdict.UNDETERMINED, [Reason("no_profile", "方式未登録")]),
    ])
    assert j.verdict is Verdict.UNDETERMINED
    assert [p.subject for p in j.find(Verdict.FAIL)] == ["日影"]


def test_find_returns_leaves_only():
    inner = Judgement.aggregate("天空率", [
        Judgement("道路", Verdict.PASS),
        Judgement("隣地", Verdict.PASS),
    ])
    j = Judgement.aggregate("総合", [inner, Judgement("日影", Verdict.PASS)])
    assert [p.subject for p in j.find(Verdict.PASS)] == ["道路", "隣地", "日影"]


def test_all_reasons_collects_depth_first():
    j = Judgement.aggregate("総合", [
        Judgement("日影", Verdict.FAIL, [Reason("a", "あ")]),
        Judgement.aggregate("天空率", [
            Judgement("道路", Verdict.FAIL, [Reason("b", "い")]),
        ]),
    ])
    assert [r.code for r in j.all_reasons()] == ["a", "b"]


def test_reason_str_includes_article():
    assert str(Reason("x", "算定位置が敷地内に入る", "令135条の9")) == \
        "算定位置が敷地内に入る（令135条の9）"


def test_to_dict_is_json_ready():
    import json
    j = Judgement.aggregate("総合", [
        Judgement("日影", Verdict.PASS),
        Judgement("天空率", Verdict.UNDETERMINED,
                  [Reason("no_profile", "方式未登録", "法56条7項")]),
    ])
    payload = json.loads(json.dumps(j.to_dict(), ensure_ascii=False))
    assert payload["verdict"] == "undetermined"
    assert payload["parts"][1]["reasons"][0]["article"] == "法56条7項"
    assert "reasons" not in payload["parts"][0]


def test_judgement_rejects_non_judgement_parts():
    with pytest.raises(VerdictError):
        Judgement("総合", Verdict.PASS, parts=[Verdict.PASS])


def test_verdict_str_is_the_serialized_value():
    assert str(Verdict.REQUIRES_REVIEW) == "requires_review"


def test_is_conclusive():
    assert Verdict.PASS.is_conclusive and Verdict.FAIL.is_conclusive
    assert not Verdict.UNDETERMINED.is_conclusive
    assert not Verdict.REQUIRES_REVIEW.is_conclusive


# --- UNDETERMINED 番兵 ---------------------------------------------------

def test_sentinel_is_falsy_and_singleton():
    assert not UNDETERMINED
    assert type(UNDETERMINED)() is UNDETERMINED
    assert pickle.loads(pickle.dumps(UNDETERMINED)) is UNDETERMINED


def test_sentinel_is_not_none():
    """「未設定」と「求められなかった」を混同しない。"""
    assert UNDETERMINED is not None
    assert UNDETERMINED != None  # noqa: E711


@pytest.mark.parametrize("op", [
    lambda v: v + 1,
    lambda v: 1 + v,
    lambda v: v * 2,
    lambda v: v / 2,
    lambda v: -v,
    lambda v: abs(v),
    lambda v: float(v),
    lambda v: int(v),
    lambda v: v > 1,
    lambda v: 1 < v,
])
def test_sentinel_refuses_arithmetic(op):
    """0 や NaN として静かに計算へ紛れ込ませない（原則H）。"""
    with pytest.raises(TypeError):
        op(UNDETERMINED)


def test_is_undetermined_covers_both_forms():
    assert is_undetermined(UNDETERMINED)
    assert is_undetermined(Verdict.UNDETERMINED)
    assert not is_undetermined(0.0)
    assert not is_undetermined(None)
    assert not is_undetermined(Verdict.PASS)
