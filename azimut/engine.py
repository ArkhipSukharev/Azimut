from __future__ import annotations

import shutil
import ssl
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from .paths import engine_dir
from .protect import MSI_SHA256, verify_bytes, verify_tunnel_engine

MSI_URL = (
    "https://github.com/amnezia-vpn/amneziawg-windows-client/"
    "releases/download/2.0.2/amneziawg-amd64-2.0.2.msi"
)
REQUIRED = ("amneziawg.exe", "wintun.dll")
OPTIONAL = ("awg.exe",)


def engine_exe() -> Path:
    return engine_dir() / "amneziawg.exe"


def engine_ready() -> bool:
    folder = engine_dir()
    return all((folder / name).exists() for name in REQUIRED)


def ensure_engine() -> Path:
    if engine_ready():
        verify_tunnel_engine()
        return engine_exe()
    _install_from_msi()
    if not engine_ready():
        raise RuntimeError(
            "Не удалось подготовить встроенный движок туннеля.\n"
            "Нужные файлы: amneziawg.exe и wintun.dll в папке engine рядом с Azimut."
        )
    verify_tunnel_engine()
    return engine_exe()


def _install_from_msi() -> None:
    folder = engine_dir()
    with tempfile.TemporaryDirectory(prefix="azimut_engine_") as raw:
        work = Path(raw)
        msi = work / "amneziawg.msi"
        extract = work / "extract"
        extract.mkdir()
        _download(MSI_URL, msi)
        proc = subprocess.run(
            ["msiexec", "/a", str(msi), "/qn", f"TARGETDIR={extract}"],
            capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError("Не удалось распаковать встроенный движок туннеля.")
        found = {path.name.lower(): path for path in extract.rglob("*") if path.is_file()}
        for name in (*REQUIRED, *OPTIONAL):
            source = found.get(name.lower())
            if source:
                shutil.copy2(source, folder / name)


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Azimut"})
    with urllib.request.urlopen(request, context=ssl.create_default_context(), timeout=120) as response:
        data = response.read()
        verify_bytes(data, MSI_SHA256, "установочный пакет движка")
        dest.write_bytes(data)
    if dest.stat().st_size < 100_000:
        raise RuntimeError("Скачанный файл движка туннеля слишком маленький, загрузка не удалась.")
