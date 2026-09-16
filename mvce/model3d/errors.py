"""model3d 共通の例外."""
from __future__ import annotations


class Model3DBackendUnavailable(RuntimeError):
    """指定した3Dモデル化バックエンド（FreeCAD/Blender）が実行環境に無いとき。

    黙って別のバックエンドにフォールバックすることはしません（原則H —
    利用者が明示的に選んだバックエンドが使えないなら、そのことを伝えます）。
    """
