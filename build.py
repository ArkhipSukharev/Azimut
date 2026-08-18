# -*- coding: utf-8 -*-
"""Собрать Azimut.exe и zip, который можно просто скачать и запустить."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist" / "Azimut"
SKIP_IN_ZIP = {
    "vault.azimut",
    "settings.json",
    "github.token",
}
SKIP_DIR_IN_ZIP = {"logs", "cache", "active", "profiles", "__pycache__"}


def run(command: list[str]) -> None:
    print("+", " ".join(command))
    subprocess.check_call(command, cwd=ROOT)


def copy_tree(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest)


def copy_payload() -> None:
    copy_tree(ROOT / "engine", DIST / "engine")
    copy_tree(ROOT / "zapret", DIST / "zapret")
    copy_tree(ROOT / "assets", DIST / "assets")
    shutil.copy2(ROOT / "README.md", DIST / "README.md")
    (DIST / "Как открыть.txt").write_text(
        "Откройте файл Azimut.exe.\n\n"
        "Не вытаскивайте его из этой папки. Рядом должны остаться папки engine, zapret и assets.\n\n"
        "Windows спросит права администратора — нажмите «Да». Это нужно для туннеля и обхода YouTube и Discord.\n\n"
        "Python устанавливать не нужно.\n",
        encoding="utf-8",
    )


def make_zip(version: str) -> Path:
    archive = ROOT / "dist" / f"Azimut-{version}.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in DIST.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(DIST)
            if path.name in SKIP_IN_ZIP:
                continue
            if any(part in SKIP_DIR_IN_ZIP for part in relative.parts):
                continue
            if path.suffix.lower() in {".log", ".lnk", ".pyc"}:
                continue
            zf.write(path, Path("Azimut") / relative)
    return archive


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from azimut import APP_VERSION
    from azimut.icon import create_icon
    from azimut.paths import icon_path

    create_icon(icon_path())
    run([sys.executable, "-m", "pip", "install", "pyinstaller>=6.10"])
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            str(ROOT / "Azimut.spec"),
        ]
    )
    if not (DIST / "Azimut.exe").exists():
        raise SystemExit("Не появился Azimut.exe. Сборка не удалась.")
    copy_payload()
    shutil.copy2(DIST / "Azimut.exe", ROOT / "Azimut.exe")
    local_internal = ROOT / "_internal"
    if local_internal.exists():
        shutil.rmtree(local_internal)
    shutil.copytree(DIST / "_internal", local_internal)
    archive = make_zip(APP_VERSION)
    sums = write_sha256sums([archive])
    print("Папка программы:", DIST)
    print("Архив:", archive)
    print("Размер:", archive.stat().st_size)
    print("Контрольные суммы:", sums)
    return 0


def write_sha256sums(files: list[Path]) -> Path:
    dest = ROOT / "dist" / "SHA256SUMS"
    existing: dict[str, str] = {}
    if dest.exists():
        for line in dest.read_text(encoding="ascii", errors="replace").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                existing[parts[-1]] = parts[0]
    for path in files:
        if path.is_file():
            existing[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    dest.write_text("".join(f"{digest}  {name}\n" for name, digest in existing.items()), encoding="ascii")
    return dest


if __name__ == "__main__":
    raise SystemExit(main())
