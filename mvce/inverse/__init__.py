"""逆解析エンジン — 規制側から建てられる形状を求める。

`shadow_envelope` が逆日影（勾配屋根面の探索）。逆天空率（`sky_envelope`）は
MVCE 2.0 Phase 3 で追加します。

基本設計の不変条件 M-4: `shadow_envelope` と `sky_envelope` は互いを
import してはいけません。両者は支配する変数（時刻 / 方位）も制約の形も
違うため、一体化すると保守が破綻します。協調は `mvce/orchestrator.py`
の責務です。
"""
