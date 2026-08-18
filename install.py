# -*- coding: utf-8 -*-
"""Поставить библиотеки, без которых исходники Azimut не откроются."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    requirements = ROOT / "requirements.txt"
    if not requirements.is_file():
        print("Рядом нет файла requirements.txt")
        return 1
    command = [sys.executable, "-m", "pip", "install", "-r", str(requirements)]
    print("+", " ".join(command))
    subprocess.check_call(command, cwd=ROOT)
    print("Готово. Откройте launch.pyw")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
