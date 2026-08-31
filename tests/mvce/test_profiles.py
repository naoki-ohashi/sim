"""`ComplianceProfile`（運用差と解釈の外部化）のテスト。

固定するのは3つです。

1. 既定（`statutory`）は**条文だけ**で、行政庁の運用も選択規定も使わない
2. `statutory` 以外には**出典が必須**（原則F）
3. 実装を持っていない方式を指定したら**止まる**（推測で動かさない）
"""
import textwrap

import pytest

from mvce.config import load_project
from mvce.profiles import (
    STATUTORY_PROFILE,
    ComplianceProfile,
    builtin_names,
    load_profile,
    profile_from_dict,
)
from mvce.sources import SourceRef
from mvce.zoning import UndeterminedRegulation

_SOURCE = {"document": "○○市建築基準法施行細則", "confirmed_on": "2026-08-30"}


# === 既定は条文だけ ===================================================

def test_statutory_uses_nothing_beyond_the_statute():
    p = STATUTORY_PROFILE
    assert p.name == "statutory"
    assert p.railway_is_adjacent_relaxation is False
    assert p.park_is_deemed_boundary is False
    assert p.apply_article_134_2 is False
    assert p.sky_region_split_method is None


def test_statutory_is_a_builtin():
    assert "statutory" in builtin_names()
    assert load_profile("statutory") == STATUTORY_PROFILE


def test_ground_average_default_is_the_length_weighted_reading():
    assert STATUTORY_PROFILE.ground_average_method == "length_weighted"
    assert STATUTORY_PROFILE.ground_weighted is True


def test_simple_mean_is_selectable():
    p = ComplianceProfile(name="x", source=SourceRef(**_SOURCE),
                          ground_average_method="simple_mean")
    assert p.ground_weighted is False


# === 出典（原則F）=====================================================

def test_a_named_profile_needs_a_source():
    with pytest.raises(ValueError, match="source"):
        ComplianceProfile(name="○○市", railway_is_adjacent_relaxation=True)


def test_statutory_does_not_need_a_source():
    ComplianceProfile(name="statutory")


def test_source_round_trips_from_a_dict():
    p = profile_from_dict({"name": "○○市", "source": _SOURCE,
                           "railway_is_adjacent_relaxation": True})
    assert p.source.document == "○○市建築基準法施行細則"
    assert p.railway_is_adjacent_relaxation is True


# === 実装していない方式は止める =======================================

def test_an_unimplemented_split_method_refuses():
    with pytest.raises(UndeterminedRegulation, match="区域分割方式"):
        ComplianceProfile(name="x", source=SourceRef(**_SOURCE),
                          sky_region_split_method="jcba")


def test_the_refusal_says_why():
    with pytest.raises(UndeterminedRegulation) as e:
        ComplianceProfile(name="x", source=SourceRef(**_SOURCE),
                          sky_region_split_method="tokyo")
    assert "令135条の6第3項" in str(e.value)
    assert "取得できていません" in str(e.value)


# === 入力の検証 =======================================================

def test_unknown_keys_are_rejected():
    with pytest.raises(ValueError, match="未知のキー"):
        profile_from_dict({"name": "statutory", "sky_ratio_interval": 4.0})


def test_name_is_required():
    with pytest.raises(ValueError, match="name"):
        profile_from_dict({"railway_is_adjacent_relaxation": True})


def test_bad_ground_method_is_rejected():
    with pytest.raises(ValueError, match="ground_average_method"):
        ComplianceProfile(name="statutory", ground_average_method="median")


@pytest.mark.parametrize("kwargs", [
    {"sky_reference_layers": 0},
    {"sky_azimuth_count": 3},
    {"sky_measurement_interval_m": 0.0},
])
def test_accuracy_values_are_validated(kwargs):
    with pytest.raises(ValueError):
        ComplianceProfile(name="statutory", **kwargs)


def test_missing_profile_file_says_what_is_available():
    with pytest.raises(FileNotFoundError, match="statutory"):
        load_profile("nonexistent-profile")


# === YAML との繋ぎ ====================================================

_BASE_YAML = """
site:
  points: [[0, 0], [30, 0], [30, 20], [0, 20]]
  edges:
    - kind: road
      road_width_m: 6.0
    - kind: adjacent
    - kind: adjacent
      relaxation: {kind: railway, width_m: 8.0}
    - kind: adjacent
  zoning:
    zone_type: 1res
    far_ratio: 200
    coverage_ratio: 60
"""


def _write(tmp_path, extra=""):
    path = tmp_path / "p.yaml"
    path.write_text(_BASE_YAML + textwrap.dedent(extra), encoding="utf-8")
    return str(path)


def test_project_defaults_to_statutory(tmp_path):
    project = load_project(_write(tmp_path))
    assert project.profile.name == "statutory"
    assert project.site.railway_is_adjacent_relaxation is False


def test_profile_supplies_the_site_flags(tmp_path):
    path = _write(tmp_path, """
        profile:
          name: ○○市
          source:
            document: ○○市建築基準法施行細則
            confirmed_on: 2026-08-30
          railway_is_adjacent_relaxation: true
          apply_article_134_2: true
        """)
    project = load_project(path)
    assert project.site.railway_is_adjacent_relaxation is True
    assert project.site.apply_article_134_2 is True


def test_the_site_yaml_wins_over_the_profile(tmp_path):
    """敷地に明示があればそちらが優先。プロファイルは既定を配るだけ。"""
    path = _write(tmp_path, """
        profile:
          name: ○○市
          source:
            document: ○○市建築基準法施行細則
            confirmed_on: 2026-08-30
          railway_is_adjacent_relaxation: true
        """)
    text = open(path, encoding="utf-8").read().replace(
        "  zoning:", "  railway_is_adjacent_relaxation: false\n  zoning:")
    open(path, "w", encoding="utf-8").write(text)
    assert load_project(path).site.railway_is_adjacent_relaxation is False


def test_profile_can_be_named(tmp_path):
    assert load_project(_write(tmp_path, "\nprofile: statutory\n")).profile.name == "statutory"


def test_profile_feeds_the_optimize_options(tmp_path):
    path = _write(tmp_path, """
        profile:
          name: ○○市
          source:
            document: ○○市建築基準法施行細則
            confirmed_on: 2026-08-30
          ground_average_method: simple_mean
          sky_reference_layers: 32
          sky_azimuth_count: 144
        """)
    options = load_project(path).options
    assert options.ground_average_weighted is False
    assert options.sky_reference_layers == 32
    assert options.sky_ratio_n_azimuth == 144


def test_profile_appears_in_the_notes(tmp_path):
    notes = load_project(_write(tmp_path)).notes
    assert any("プロファイル: statutory" in n for n in notes)


# === JCBA 報告書（平成22年）が挙げる5つの運用選択 =====================
#
# 報告書はいずれも「特定行政庁の判断に委ねられる」「いずれの運用も可能」と
# しています。だからコードに直書きせず、プロファイルに置きます（原則A・G）。

def test_corner_region_default_is_the_majority_operation():
    """出隅の「2Aかつ35m」。既定は「広い道路に垂直」（街区主義）。

    JCBA 報告書のアンケートで2/3、「基準総則・集団規定の適用事例」も同じ。
    `road_regions.py` が辺の無限直線からの距離で切っているのがこれです。
    """
    assert STATUTORY_PROFILE.corner_region_method == "perpendicular"


def test_the_arc_corner_method_is_refused():
    """円弧状の区域区分（敷地主義）は未実装。名前だけ受けて中身が違うより止める。"""
    with pytest.raises(UndeterminedRegulation, match="円弧"):
        ComplianceProfile(name="x", source=SourceRef(**_SOURCE),
                          corner_region_method="arc")


def test_an_unknown_corner_method_is_a_value_error():
    with pytest.raises(ValueError, match="corner_region_method"):
        ComplianceProfile(name="x", source=SourceRef(**_SOURCE),
                          corner_region_method="street-block")


def test_one_road_angle_is_recorded_but_not_applied():
    """屈曲道路の「一の道路」。報告書は120°超だが行政庁の判断に委ねられる。

    MVCE は辺の併合をしないので、いまは記録用です。値を持てること自体を
    固定して、あとで実装するときの受け口にします。
    """
    p = ComplianceProfile(name="x", source=SourceRef(**_SOURCE),
                          one_road_angle_deg=120.0)
    assert p.one_road_angle_deg == 120.0
    assert any("120度超" in line for line in p.describe_ja())


def test_one_road_angle_is_range_checked():
    with pytest.raises(ValueError, match="one_road_angle_deg"):
        ComplianceProfile(name="x", source=SourceRef(**_SOURCE),
                          one_road_angle_deg=0.0)


def test_continuous_adjacent_boundary_is_refused():
    """「連続した一の隣地境界線」方式は未実装（MVCE は敷地区分方式）。"""
    with pytest.raises(UndeterminedRegulation, match="敷地区分方式"):
        ComplianceProfile(name="x", source=SourceRef(**_SOURCE),
                          continuous_adjacent_boundary=True)


def test_level_region_split_is_refused():
    """高低差区分区域そのものが未実装。報告書も法文上の規定が無いと認めている。"""
    with pytest.raises(UndeterminedRegulation, match="高低差区分区域"):
        ComplianceProfile(name="x", source=SourceRef(**_SOURCE),
                          level_region_split_method="perpendicular")


def test_the_new_knobs_load_from_yaml(tmp_path):
    path = _write(tmp_path, """
        profile:
          name: ○○市
          source:
            document: ○○市天空率取扱い
            confirmed_on: 2026-08-30
          corner_region_method: perpendicular
          one_road_angle_deg: 120
        """)
    profile = load_project(path).profile
    assert profile.corner_region_method == "perpendicular"
    assert profile.one_road_angle_deg == 120
