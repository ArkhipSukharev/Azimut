from __future__ import annotations

import json
import os
import re
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import APP_VERSION
from .paths import app_root

API = "https://api.github.com"
SKIP_FILES = {"vault.azimut", "settings.json", "github.token"}
SKIP_DIRS = {"logs", "cache", "active", "profiles"}
CHECKSUM_NAMES = {
    "sha256sums",
    "sha256sums.txt",
    "sha256.txt",
    "checksums.txt",
    "checksums",
    "azimut-sha256.txt",
}


@dataclass
class ReleaseInfo:
    version: str
    tag: str
    notes: str
    setup_asset: dict | None
    zip_asset: dict | None
    checksums_asset: dict | None


def parse_version(text: str) -> tuple[int, ...]:
    text = (text or "").strip().lstrip("vV")
    parts = [int(piece) for piece in re.split(r"\D+", text) if piece.isdigit()]
    return tuple(parts or [0])


def is_newer(latest: str, current: str = APP_VERSION) -> bool:
    return parse_version(latest) > parse_version(current)


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


def _normalize_repo(repo: str) -> str:
    repo = (repo or "").strip().removeprefix("https://github.com/").strip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    return repo


def fetch_latest(repo: str, token: str) -> ReleaseInfo:
    repo = _normalize_repo(repo)
    if "/" not in repo:
        raise RuntimeError("В настройках укажите репозиторий в виде имя/проект, например myname/Azimut.")
    try:
        data = _get_json(f"{API}/repos/{repo}/releases/latest", token)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(
                "Релиз не найден. В закрытом репозитории нужен личный токен GitHub "
                "с правом чтения, и хотя бы один опубликованный Release."
            ) from exc
        if exc.code in {401, 403}:
            raise RuntimeError("GitHub не пустил к репозиторию. Проверьте токен и доступ к закрытому проекту.") from exc
        raise RuntimeError(f"GitHub ответил кодом {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Нет доступа к GitHub. Проверьте сеть.") from exc

    tag = str(data.get("tag_name") or "")
    version = tag.lstrip("vV") or APP_VERSION
    assets = data.get("assets") or []
    setup = None
    archive = None
    checksums = None
    for asset in assets:
        name = str(asset.get("name") or "").lower()
        stem = Path(name).name
        if stem in CHECKSUM_NAMES or "sha256" in name:
            checksums = asset
        elif name.endswith(".exe") and "setup" in name:
            setup = asset
        elif name.endswith(".zip") and "azimut" in name:
            archive = asset
        elif name.endswith(".zip") and archive is None:
            archive = asset
    return ReleaseInfo(
        version=version,
        tag=tag,
        notes=str(data.get("body") or "").strip(),
        setup_asset=setup,
        zip_asset=archive,
        checksums_asset=checksums,
    )


def check_for_update(repo: str, token: str) -> ReleaseInfo | None:
    if not _normalize_repo(repo):
        return None
    latest = fetch_latest(repo, token)
    if is_newer(latest.version):
        return latest
    return None


def parse_checksums(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"([0-9a-fA-F]{64})\s+\*?(.+)$", line)
        if not match:
            continue
        found[Path(match.group(2).strip().strip('"')).name.lower()] = match.group(1).lower()
    return found


def verify_download(path: Path, checksums: dict[str, str]) -> None:
    from .protect import sha256_file

    expected = checksums.get(path.name.lower())
    if not expected:
        raise RuntimeError(
            f"В файле контрольных сумм нет строки для {path.name}. "
            "Обновление не установлено."
        )
    got = sha256_file(path)
    if got.lower() != expected:
        raise RuntimeError(
            f"Файл {path.name} не прошёл проверку контрольной суммы. "
            "Его могли подменить. Обновление не установлено."
        )


def _load_checksums(release: ReleaseInfo, token: str, folder: Path) -> dict[str, str]:
    if not release.checksums_asset:
        raise RuntimeError(
            "В релизе нет файла с контрольными суммами (SHA256SUMS). "
            "Azimut не будет ставить такое обновление."
        )
    name = str(release.checksums_asset.get("name") or "SHA256SUMS")
    dest = _download_asset(release.checksums_asset, token, folder / name, min_size=64)
    text = dest.read_text(encoding="utf-8", errors="replace")
    checksums = parse_checksums(text)
    if not checksums:
        raise RuntimeError("Файл контрольных сумм пустой или в незнакомом формате. Обновление не установлено.")
    return checksums


def _github_json_error(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace").strip()
    if not text.startswith("{"):
        return ""
    try:
        payload = json.loads(text)
    except Exception:
        return ""
    return str(payload.get("message") or "").strip()


def _download_asset(asset: dict, token: str, dest: Path, min_size: int = 1000) -> Path:
    candidates = []
    api_url = str(asset.get("url") or "").strip()
    browser_url = str(asset.get("browser_download_url") or "").strip()
    if api_url:
        candidates.append((api_url, "application/octet-stream"))
    if browser_url and browser_url != api_url:
        candidates.append((browser_url, "*/*"))
    if not candidates:
        raise RuntimeError("У релиза нет файла для скачивания.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_error = "GitHub не отдал файл обновления."
    for url, accept in candidates:
        headers = _headers(token)
        headers["Accept"] = accept
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=180, context=ssl.create_default_context()) as response:
                data = response.read()
        except urllib.error.HTTPError as exc:
            last_error = f"GitHub ответил кодом {exc.code} при скачивании {dest.name}."
            continue
        except urllib.error.URLError:
            last_error = "Нет доступа к GitHub. Проверьте сеть."
            continue
        message = _github_json_error(data)
        if message:
            last_error = f"GitHub не отдал файл {dest.name}: {message}"
            continue
        if len(data) < min_size:
            last_error = (
                f"Скачанный файл {dest.name} слишком маленький ({len(data)} байт). "
                "Проверьте токен и вложение релиза."
            )
            continue
        dest.write_bytes(data)
        return dest
    raise RuntimeError(last_error)


def uses_installer() -> bool:
    return "program files" in str(app_root()).lower()


def _copy_update_tree(source: Path, dest: Path) -> None:
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if path.name in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())


def _extract_payload(archive: Path) -> Path:
    import shutil

    work = archive.parent / "unpacked"
    if work.exists():
        shutil.rmtree(work)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(work)
    inner = work / "Azimut"
    return inner if inner.is_dir() else work


def _write_replacer(folder: Path, pid: int) -> Path:
    script = folder / "apply_azimut_update.bat"
    root = app_root()
    exe = root / "Azimut.exe"
    source = folder / "payload"
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        f"set TARGET={root}",
        f"set SOURCE={source}",
        ":wait",
        f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul',
        "if not errorlevel 1 (",
        "  timeout /t 1 /nobreak >nul",
        "  goto wait",
        ")",
        'xcopy /E /Y /I /Q "%SOURCE%\\*" "%TARGET%\\" >nul',
        f'start "" "{exe}"',
        'del "%~f0"',
    ]
    script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return script


def apply_update(repo: str, token: str, release: ReleaseInfo) -> str:
    temp = Path(tempfile.mkdtemp(prefix="azimut_update_"))
    checksums = _load_checksums(release, token, temp)
    if uses_installer() and release.setup_asset:
        setup = _download_asset(
            release.setup_asset,
            token,
            temp / str(release.setup_asset.get("name") or "Azimut-Setup.exe"),
        )
        verify_download(setup, checksums)
        subprocess.Popen([str(setup)], cwd=str(setup.parent))
        return "installer"
    asset = release.zip_asset or release.setup_asset
    if asset is None:
        raise RuntimeError("В релизе нет файла Azimut-Setup.exe или zip-архива программы.")
    name = str(asset.get("name") or "update.bin")
    downloaded = _download_asset(asset, token, temp / name)
    verify_download(downloaded, checksums)
    if name.lower().endswith(".exe"):
        subprocess.Popen([str(downloaded)], cwd=str(downloaded.parent))
        return "installer"
    payload_root = _extract_payload(downloaded)
    payload_copy = temp / "payload"
    payload_copy.mkdir()
    _copy_update_tree(payload_root, payload_copy)
    script = _write_replacer(temp, os.getpid())
    subprocess.Popen(
        ["cmd.exe", "/c", str(script)],
        cwd=str(temp),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return "replace"


def can_check(repo: str) -> bool:
    return bool(_normalize_repo(repo))
