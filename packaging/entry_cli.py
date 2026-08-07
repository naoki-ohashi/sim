"""PyInstaller用の起動スクリプト（単体コマンド版）。

理由は entry_gaihen.py と同じ（パッケージ内モジュールを直接エントリに
すると相対importが壊れるため、importし直す薄い層を挟む）。
"""
import sys

from jwcad_volume.cli import main

if __name__ == "__main__":
    sys.exit(main())
