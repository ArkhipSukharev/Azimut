# -*- coding: utf-8 -*-
"""Собрать установщик Azimut-Setup.exe через Inno Setup."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ISS = ROOT / "installer" / "azimut.iss"


def find_iscc() -> Path:
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise SystemExit(
        "Не найден компилятор Inno Setup (ISCC.exe).\n"
        "Установите Inno Setup 6 и повторите: python make_installer.py"
    )


def ensure_utf8_bom(path: Path) -> None:
    data = path.read_bytes()
    if not data.startswith(b"\xef\xbb\xbf"):
        path.write_bytes(b"\xef\xbb\xbf" + data)


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from azimut import APP_VERSION

    exe = ROOT / "dist" / "Azimut" / "Azimut.exe"
    if not exe.is_file():
        raise SystemExit("Сначала соберите программу: python build.py")
    if not (ROOT / "dist" / "Azimut" / "_internal").is_dir():
        raise SystemExit("Нет папки dist\\Azimut\\_internal. Сначала соберите программу: python build.py")
    ensure_utf8_bom(ISS)
    iscc = find_iscc()
    output_dir = ROOT / "dist"
    output_dir.mkdir(exist_ok=True)
    command = [
        str(iscc),
        f"/DAppVer={APP_VERSION}",
        str(ISS),
    ]
    print("+", " ".join(command))
    subprocess.check_call(command, cwd=ROOT)
    setup = output_dir / f"Azimut-Setup-{APP_VERSION}.exe"
    if not setup.is_file():
        raise SystemExit("Установщик не появился.")
    sums = ROOT / "dist" / "SHA256SUMS"
    existing: dict[str, str] = {}
    if sums.exists():
        for line in sums.read_text(encoding="ascii", errors="replace").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                existing[parts[-1]] = parts[0]
    existing[setup.name] = hashlib.sha256(setup.read_bytes()).hexdigest()
    sums.write_text("".join(f"{digest}  {name}\n" for name, digest in existing.items()), encoding="ascii")
    print("Установщик:", setup)
    print("Размер:", setup.stat().st_size)
    print("Контрольные суммы:", sums)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
