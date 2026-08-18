# -*- coding: utf-8 -*-
from __future__ import annotations

import ctypes
import ipaddress
import json
import os
import socket
import struct
from ctypes import wintypes
from pathlib import Path

from .paths import cache_dir
from .split import expand_domains, resolve_many

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002
AF_INET = 2
TCP_TABLE_OWNER_PID_CONNECTIONS = 5
ERROR_INSUFFICIENT_BUFFER = 122

APP_HINTS = {
    "telegram.exe": ["telegram.org", "t.me", "telegram.me", "tdesktop.com"],
    "discord.exe": ["discord.com", "discord.gg", "discordapp.com", "discord.media"],
    "spotify.exe": ["spotify.com", "spotifycdn.com", "scdn.co"],
    "steam.exe": ["steampowered.com", "steamcommunity.com", "steamstatic.com"],
    "whatsapp.exe": ["whatsapp.com", "whatsapp.net"],
    "signal.exe": ["signal.org"],
    "slack.exe": ["slack.com"],
    "zoom.exe": ["zoom.us"],
}


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class MIB_TCPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ("dwState", wintypes.DWORD),
        ("dwLocalAddr", wintypes.DWORD),
        ("dwLocalPort", wintypes.DWORD),
        ("dwRemoteAddr", wintypes.DWORD),
        ("dwRemotePort", wintypes.DWORD),
        ("dwOwningPid", wintypes.DWORD),
    ]


def normalize_app_path(path: str) -> str:
    raw = (path or "").strip().strip('"')
    if not raw:
        return ""
    try:
        resolved = Path(raw)
        if resolved.exists():
            raw = str(resolved.resolve())
    except Exception:
        pass
    return os.path.normcase(os.path.normpath(raw))


def display_name(path: str) -> str:
    return Path(path).name or path


def learned_path() -> Path:
    return cache_dir() / "app_ips.json"


def load_learned() -> dict[str, list[str]]:
    path = learned_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    result: dict[str, list[str]] = {}
    for key, values in raw.items():
        norm = normalize_app_path(str(key))
        ips = []
        seen = set()
        for item in values or []:
            text = str(item).strip()
            if not text or text in seen or not _public_ip(text):
                continue
            seen.add(text)
            ips.append(text)
        if norm and ips:
            result[norm] = ips
    return result


def save_learned(data: dict[str, list[str]]) -> None:
    learned_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(
        address.version == 4
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )


def _dword_ip(value: int) -> str:
    return socket.inet_ntoa(struct.pack("<I", value & 0xFFFFFFFF))


def _process_path(pid: int) -> str:
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return normalize_app_path(buffer.value)
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
    return ""


def list_running_apps() -> list[tuple[str, str]]:
    snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == ctypes.c_void_p(-1).value or snapshot == 0xFFFFFFFF:
        return []
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    found: dict[str, str] = {}
    try:
        if not ctypes.windll.kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return []
        while True:
            path = _process_path(int(entry.th32ProcessID))
            if path and path not in found:
                low = path.lower()
                if "\\windows\\" not in low and not low.endswith("\\azimut.exe"):
                    found[path] = display_name(path)
            if not ctypes.windll.kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        ctypes.windll.kernel32.CloseHandle(snapshot)
    return sorted(found.items(), key=lambda item: item[1].lower())


def _tcp_rows() -> list[MIB_TCPROW_OWNER_PID]:
    size = wintypes.DWORD(0)
    iphlpapi = ctypes.windll.iphlpapi
    iphlpapi.GetExtendedTcpTable(
        None,
        ctypes.byref(size),
        True,
        AF_INET,
        TCP_TABLE_OWNER_PID_CONNECTIONS,
        0,
    )
    if size.value < 4:
        return []
    buffer = ctypes.create_string_buffer(size.value)
    code = iphlpapi.GetExtendedTcpTable(
        buffer,
        ctypes.byref(size),
        True,
        AF_INET,
        TCP_TABLE_OWNER_PID_CONNECTIONS,
        0,
    )
    if code == ERROR_INSUFFICIENT_BUFFER:
        buffer = ctypes.create_string_buffer(size.value)
        code = iphlpapi.GetExtendedTcpTable(
            buffer,
            ctypes.byref(size),
            True,
            AF_INET,
            TCP_TABLE_OWNER_PID_CONNECTIONS,
            0,
        )
    if code != 0:
        return []
    count = struct.unpack_from("<I", buffer.raw, 0)[0]
    row_size = ctypes.sizeof(MIB_TCPROW_OWNER_PID)
    rows = []
    offset = 4
    for _ in range(count):
        if offset + row_size > len(buffer.raw):
            break
        rows.append(MIB_TCPROW_OWNER_PID.from_buffer_copy(buffer.raw[offset : offset + row_size]))
        offset += row_size
    return rows


def live_ips_for_apps(paths: list[str]) -> dict[str, list[str]]:
    wanted = {normalize_app_path(item) for item in paths if normalize_app_path(item)}
    if not wanted:
        return {}
    pid_to_path: dict[int, str] = {}
    collected: dict[str, set[str]] = {item: set() for item in wanted}
    for row in _tcp_rows():
        remote = _dword_ip(int(row.dwRemoteAddr))
        if not _public_ip(remote):
            continue
        pid = int(row.dwOwningPid)
        path = pid_to_path.get(pid)
        if path is None:
            path = _process_path(pid)
            pid_to_path[pid] = path
        if path in collected:
            collected[path].add(remote)
    return {key: sorted(values) for key, values in collected.items() if values}


def remember_live_ips(paths: list[str]) -> list[str]:
    learned = load_learned()
    fresh = live_ips_for_apps(paths)
    added: list[str] = []
    for path, ips in fresh.items():
        current = list(learned.get(path) or [])
        seen = set(current)
        changed = False
        for ip in ips:
            if ip not in seen:
                seen.add(ip)
                current.append(ip)
                added.append(ip)
                changed = True
        if changed:
            learned[path] = current
    if added:
        save_learned(learned)
    return added


def hint_networks(paths: list[str]) -> list[ipaddress.IPv4Network]:
    domains: list[str] = []
    seen = set()
    for path in paths:
        name = display_name(path).lower()
        for domain in APP_HINTS.get(name, []):
            if domain not in seen:
                seen.add(domain)
                domains.append(domain)
    if not domains:
        return []
    return resolve_many(expand_domains(domains), skip_youtube=False)


def networks_for_apps(paths: list[str]) -> list[ipaddress.IPv4Network]:
    wanted = [normalize_app_path(item) for item in paths if normalize_app_path(item)]
    if not wanted:
        return []
    remember_live_ips(wanted)
    learned = load_learned()
    nets: list[ipaddress.IPv4Network] = []
    seen = set()
    for path in wanted:
        for ip in learned.get(path) or []:
            if ip in seen or not _public_ip(ip):
                continue
            seen.add(ip)
            nets.append(ipaddress.ip_network(f"{ip}/32"))
    nets.extend(hint_networks(wanted))
    return nets
