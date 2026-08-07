"""PyInstaller用の起動スクリプト（JWW外部変形本体）。

`jwcad_volume/gaihen.py` を直接エントリにすると、そのファイルが
`__main__` として読み込まれてパッケージの一部でなくなるため、
`from .config import ...` のような相対importが
`ImportError: attempted relative import with no known parent package`
で失敗します。パッケージとしてimportし直すこの薄い層を挟むことで回避します。
"""
import sys

from jwcad_volume.gaihen import main

if __name__ == "__main__":
    sys.exit(main())
