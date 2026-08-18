# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .paths import app_root
from .protect import TRUSTED_SHA256, sha256_file


REQUIRED = (
    ("engine/amneziawg.exe", "Движок туннеля", True),
    ("engine/wintun.dll", "Сетевой драйвер туннеля", True),
    ("zapret/bin/winws.exe", "Программа обхода zapret", True),
    ("zapret/bin/WinDivert.dll", "Библиотека перехвата пакетов", True),
    ("zapret/bin/WinDivert64.sys", "Драйвер перехвата пакетов", True),
    ("zapret/bin/cygwin1.dll", "Служебная библиотека zapret", False),
    ("zapret/bin/quic_initial_www_google_com.bin", "Образец QUIC для обхода", True),
    ("zapret/bin/tls_clienthello_www_google_com.bin", "Образец TLS для обхода", True),
    ("zapret/bin/tls_clienthello_max_ru.bin", "Дополнительный образец TLS", False),
    ("zapret/bin/ACTIVE_DISCORD_UDP.bin", "Образец Discord для обхода", True),
    ("zapret/goodbyedpi/goodbyedpi.exe", "Программа GoodbyeDPI", False),
)


@dataclass
class FileStatus:
    relative: str
    title: str
    required: bool
    exists: bool
    hash_ok: bool | None
    path: Path


@dataclass
class DiagnoseReport:
    files: list[FileStatus] = field(default_factory=list)

    @property
    def missing_required(self) -> list[FileStatus]:
        return [item for item in self.files if item.required and not item.exists]

    @property
    def broken_required(self) -> list[FileStatus]:
        return [item for item in self.files if item.required and item.exists and item.hash_ok is False]

    def ok(self) -> bool:
        return not self.missing_required and not self.broken_required

    def summary(self) -> str:
        missing = self.missing_required
        broken = self.broken_required
        if not missing and not broken:
            extra = [item.title for item in self.files if not item.exists]
            if extra:
                return "Обязательные файлы на месте. Нет необязательных: " + ", ".join(extra) + "."
            return "Все файлы туннеля и обхода на месте."
        parts = []
        if missing:
            names = ", ".join(f"{item.title} ({item.relative})" for item in missing)
            parts.append("Антивирус или сбой диска убрал: " + names + ".")
        if broken:
            names = ", ".join(f"{item.title} ({item.relative})" for item in broken)
            parts.append("Повреждены: " + names + ".")
        folder = str(app_root())
        parts.append(f"Добавьте всю папку в исключения антивируса: {folder}")
        parts.append("Затем поставьте программу заново из установщика или нажмите «Проверить обход» — недостающие файлы обхода скачаются с официального GitHub.")
        return " ".join(parts)


def inspect() -> DiagnoseReport:
    from .protect import _expected_hashes

    report = DiagnoseReport()
    root = app_root()
    for relative, title, required in REQUIRED:
        path = root / relative.replace("/", "\\")
        exists = path.is_file()
        hash_ok: bool | None = None
        if exists:
            allowed = _expected_hashes(relative)
            if allowed:
                hash_ok = sha256_file(path).lower() in allowed
            elif relative in TRUSTED_SHA256:
                hash_ok = sha256_file(path).lower() == TRUSTED_SHA256[relative].lower()
        report.files.append(
            FileStatus(
                relative=relative,
                title=title,
                required=required,
                exists=exists,
                hash_ok=hash_ok,
                path=path,
            )
        )
    return report
