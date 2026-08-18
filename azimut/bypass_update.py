# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import ssl
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .paths import app_root
from .protect import atomic_write, sha256_file

API = "https://api.github.com"
ZAPRET_REPO = "bol-van/zapret"
ZAPRET_BUNDLE = "bol-van/zapret-win-bundle"
GOODBYE_REPO = "ValdikSS/GoodbyeDPI"

ZAPRET_FILES = (
    ("zapret-winws/winws.exe", "zapret/bin/winws.exe"),
    ("zapret-winws/WinDivert.dll", "zapret/bin/WinDivert.dll"),
    ("zapret-winws/WinDivert64.sys", "zapret/bin/WinDivert64.sys"),
    ("zapret-winws/cygwin1.dll", "zapret/bin/cygwin1.dll"),
    ("zapret-winws/files/quic_initial_www_google_com.bin", "zapret/bin/quic_initial_www_google_com.bin"),
    ("zapret-winws/files/tls_clienthello_www_google_com.bin", "zapret/bin/tls_clienthello_www_google_com.bin"),
)

OPTIONAL_ZAPRET_FILES = (
    ("zapret-winws/files/tls_clienthello_max_ru.bin", "zapret/bin/tls_clienthello_max_ru.bin"),
    ("zapret-winws/files/ACTIVE_DISCORD_UDP.bin", "zapret/bin/ACTIVE_DISCORD_UDP.bin"),
)

BACKUP_RELATIVE = (
    "zapret/bin/winws.exe",
    "zapret/bin/WinDivert.dll",
    "zapret/bin/WinDivert64.sys",
    "zapret/bin/cygwin1.dll",
    "zapret/bin/quic_initial_www_google_com.bin",
    "zapret/bin/tls_clienthello_www_google_com.bin",
    "zapret/bin/tls_clienthello_max_ru.bin",
    "zapret/bin/ACTIVE_DISCORD_UDP.bin",
    "zapret/goodbyedpi/goodbyedpi.exe",
)


@dataclass
class BypassReport:
    zapret_tag: str = ""
    goodbyedpi_tag: str = ""
    zapret_updated: bool = False
    goodbyedpi_updated: bool = False
    already_current: bool = False
    rolled_back: bool = False
    error: str = ""
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.error and not (self.zapret_tag or self.goodbyedpi_tag):
            return f"Не удалось проверить обход: {self.error}"
        parts = []
        if self.zapret_tag:
            extra = "обновлён" if self.zapret_updated else "актуальный"
            parts.append(f"zapret {self.zapret_tag} ({extra})")
        if self.goodbyedpi_tag:
            extra = "обновлён" if self.goodbyedpi_updated else "актуальный"
            parts.append(f"GoodbyeDPI {self.goodbyedpi_tag} ({extra})")
        text = ", ".join(parts) if parts else "версии обхода не удалось узнать"
        if self.error:
            text += f". {self.error}"
        return text


def versions_path() -> Path:
    return app_root() / "zapret" / "versions.json"


def goodbyedpi_dir() -> Path:
    path = app_root() / "zapret" / "goodbyedpi"
    path.mkdir(parents=True, exist_ok=True)
    return path


def goodbyedpi_path() -> Path:
    return goodbyedpi_dir() / "goodbyedpi.exe"


def backup_dir() -> Path:
    path = app_root() / "zapret" / "backup"
    path.mkdir(parents=True, exist_ok=True)
    return path


def has_backup() -> bool:
    folder = app_root() / "zapret" / "backup"
    return (folder / "winws.exe").is_file() or (folder / "goodbyedpi.exe").is_file()


def snapshot_backup() -> None:
    dest_root = backup_dir()
    copied = False
    for relative in BACKUP_RELATIVE:
        source = app_root() / relative.replace("/", "\\")
        if not source.is_file():
            continue
        dest = dest_root / Path(relative).name
        dest.write_bytes(source.read_bytes())
        copied = True
    if copied:
        versions = versions_path()
        if versions.is_file():
            (dest_root / "versions.json").write_bytes(versions.read_bytes())


def restore_backup() -> bool:
    folder = app_root() / "zapret" / "backup"
    if not has_backup():
        return False
    from . import zapret as zapret_engine

    try:
        zapret_engine.stop(force=True)
    except Exception:
        pass
    mapping = {
        "winws.exe": app_root() / "zapret" / "bin" / "winws.exe",
        "WinDivert.dll": app_root() / "zapret" / "bin" / "WinDivert.dll",
        "WinDivert64.sys": app_root() / "zapret" / "bin" / "WinDivert64.sys",
        "cygwin1.dll": app_root() / "zapret" / "bin" / "cygwin1.dll",
        "quic_initial_www_google_com.bin": app_root() / "zapret" / "bin" / "quic_initial_www_google_com.bin",
        "tls_clienthello_www_google_com.bin": app_root() / "zapret" / "bin" / "tls_clienthello_www_google_com.bin",
        "tls_clienthello_max_ru.bin": app_root() / "zapret" / "bin" / "tls_clienthello_max_ru.bin",
        "ACTIVE_DISCORD_UDP.bin": app_root() / "zapret" / "bin" / "ACTIVE_DISCORD_UDP.bin",
        "goodbyedpi.exe": goodbyedpi_path(),
    }
    restored = False
    for name, dest in mapping.items():
        source = folder / name
        if source.is_file():
            _replace_file(source, dest)
            restored = True
    snapshot = folder / "versions.json"
    if snapshot.is_file():
        versions_path().write_bytes(snapshot.read_bytes())
    return restored


def load_versions() -> dict:
    path = versions_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_versions(data: dict) -> None:
    versions_path().parent.mkdir(parents=True, exist_ok=True)
    versions_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def recorded_hashes() -> dict[str, str]:
    raw = load_versions().get("hashes") or {}
    return {str(key): str(value).lower() for key, value in raw.items() if value}


def _headers(token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Azimut",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token.strip():
        headers["Authorization"] = "Bearer " + token.strip()
    return headers


def _get_json(url: str, token: str) -> dict | list:
    request = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(request, timeout=25, context=ssl.create_default_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def _download(url: str, token: str, dest: Path, accept: str = "application/octet-stream") -> Path:
    headers = _headers(token)
    headers["Accept"] = accept
    request = urllib.request.Request(url, headers=headers)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=180, context=ssl.create_default_context()) as response:
        dest.write_bytes(response.read())
    if dest.stat().st_size < 100:
        raise RuntimeError(f"Скачанный файл слишком маленький: {dest.name}")
    return dest


def _latest_release(repo: str, token: str) -> dict:
    return _get_json(f"{API}/repos/{repo}/releases/latest", token)


def _github_file(repo: str, path: str, token: str) -> tuple[str, str]:
    data = _get_json(f"{API}/repos/{repo}/contents/{path}", token)
    sha = str(data.get("sha") or "")
    url = str(data.get("download_url") or "")
    if not sha or not url:
        raise RuntimeError(f"GitHub не отдал файл {path} из {repo}.")
    return sha, url


def _replace_file(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    atomic_write(dest, data)


def _update_zapret(token: str, stored: dict, progress=None) -> tuple[bool, str]:
    winws_blob, _url = _github_file(ZAPRET_BUNDLE, "zapret-winws/winws.exe", token)
    if stored.get("zapret_winws_blob") == winws_blob and (app_root() / "zapret" / "bin" / "winws.exe").is_file():
        return False, winws_blob
    if progress:
        progress("Скачиваю свежий zapret с официального GitHub…")
    from . import zapret as zapret_engine

    try:
        zapret_engine.stop(force=True)
    except Exception:
        pass
    snapshot_backup()
    hashes = dict(stored.get("hashes") or {})
    with tempfile.TemporaryDirectory(prefix="azimut_zapret_") as raw:
        work = Path(raw)
        for remote, relative in ZAPRET_FILES + OPTIONAL_ZAPRET_FILES:
            try:
                _blob, url = _github_file(ZAPRET_BUNDLE, remote, token)
                downloaded = _download(url, token, work / Path(remote).name, accept="*/*")
            except Exception:
                if (remote, relative) in OPTIONAL_ZAPRET_FILES:
                    continue
                raise
            dest = app_root() / relative.replace("/", "\\")
            _replace_file(downloaded, dest)
            hashes[relative] = sha256_file(dest)
    stored["zapret_winws_blob"] = winws_blob
    stored["hashes"] = hashes
    return True, winws_blob


def _find_goodbyedpi(folder: Path) -> Path | None:
    found = sorted(folder.rglob("goodbyedpi.exe"))
    if not found:
        return None
    for path in found:
        if "x86_64" in str(path).lower() or "64" in path.parent.name:
            return path
    return found[-1]


def _update_goodbyedpi(token: str, stored: dict, tag: str, asset: dict, progress=None) -> bool:
    if stored.get("goodbyedpi_tag") == tag and goodbyedpi_path().is_file():
        return False
    if progress:
        progress(f"Скачиваю GoodbyeDPI {tag} с официального GitHub…")
    from . import zapret as zapret_engine

    try:
        zapret_engine.stop(force=True)
    except Exception:
        pass
    snapshot_backup()
    url = str(asset.get("url") or "")
    if not url:
        raise RuntimeError("У релиза GoodbyeDPI нет файла для скачивания.")
    with tempfile.TemporaryDirectory(prefix="azimut_goodbye_") as raw:
        work = Path(raw)
        archive = _download(url, token, work / str(asset.get("name") or "goodbyedpi.zip"))
        unpacked = work / "unpacked"
        unpacked.mkdir()
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(unpacked)
        exe = _find_goodbyedpi(unpacked)
        if exe is None:
            raise RuntimeError("В архиве GoodbyeDPI нет goodbyedpi.exe.")
        dest_dir = goodbyedpi_dir()
        _replace_file(exe, dest_dir / "goodbyedpi.exe")
        for name in ("WinDivert.dll", "WinDivert64.sys", "WinDivert.dll", "WinDivert32.sys"):
            match = next((item for item in exe.parent.glob(name) if item.is_file()), None)
            if match:
                _replace_file(match, dest_dir / match.name)
    hashes = dict(stored.get("hashes") or {})
    hashes["zapret/goodbyedpi/goodbyedpi.exe"] = sha256_file(goodbyedpi_path())
    stored["goodbyedpi_tag"] = tag
    stored["hashes"] = hashes
    return True


def ensure_latest(token: str = "", progress=None) -> BypassReport:
    report = BypassReport()
    stored = load_versions()
    token = token or ""
    try:
        if progress:
            progress("Смотрю официальный zapret на GitHub…")
        zapret = _latest_release(ZAPRET_REPO, token)
        report.zapret_tag = str(zapret.get("tag_name") or "").lstrip("vV")
        stored["zapret_tag"] = str(zapret.get("tag_name") or "")
        updated, _blob = _update_zapret(token, stored, progress=progress)
        report.zapret_updated = updated
        if updated:
            report.notes.append(f"zapret обновлён до {stored['zapret_tag']}")
    except urllib.error.HTTPError as exc:
        report.error = f"GitHub ответил кодом {exc.code} при проверке zapret."
    except Exception as exc:
        report.error = str(exc)

    try:
        if progress:
            progress("Смотрю официальный GoodbyeDPI на GitHub…")
        goodbye = _latest_release(GOODBYE_REPO, token)
        tag = str(goodbye.get("tag_name") or "")
        report.goodbyedpi_tag = tag
        assets = goodbye.get("assets") or []
        asset = None
        for item in assets:
            name = str(item.get("name") or "").lower()
            if name.endswith(".zip") and "goodbyedpi" in name:
                asset = item
                break
        if asset is None and assets:
            asset = assets[0]
        if asset is None:
            raise RuntimeError("В релизе GoodbyeDPI нет архива.")
        updated = _update_goodbyedpi(token, stored, tag, asset, progress=progress)
        report.goodbyedpi_updated = updated
        if updated:
            report.notes.append(f"GoodbyeDPI обновлён до {tag}")
    except urllib.error.HTTPError as exc:
        extra = f"GitHub ответил кодом {exc.code} при проверке GoodbyeDPI."
        report.error = f"{report.error} {extra}".strip() if report.error else extra
    except Exception as exc:
        report.error = f"{report.error} {exc}".strip() if report.error else str(exc)

    report.already_current = not report.zapret_updated and not report.goodbyedpi_updated and not report.error
    if report.zapret_tag or report.goodbyedpi_tag or stored.get("hashes"):
        save_versions(stored)
    return report
