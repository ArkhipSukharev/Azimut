from __future__ import annotations

import ipaddress
import re
import socket
import ssl
import struct
import urllib.request
from dataclasses import dataclass

from .tunnel import azimut_running, run_hidden

IP_UNICAST_IF = 31


@dataclass
class SiteCheck:
    route: str
    ips: list[str]
    reachable: bool
    reachable_text: str
    via_tunnel: str


def parse_allowed(config_text: str) -> list[ipaddress.IPv4Network]:
    nets = []
    for raw in re.findall(r"\d+\.\d+\.\d+\.\d+/\d+", config_text):
        net = ipaddress.ip_network(raw, strict=False)
        if isinstance(net, ipaddress.IPv4Network):
            nets.append(net)
    return nets


def resolve_host(host: str) -> list[str]:
    value = host.strip()
    if value.startswith("http://") or value.startswith("https://"):
        value = value.split("://", 1)[1]
    value = value.split("/", 1)[0].split(":", 1)[0]
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", value):
        return [value]
    infos = socket.getaddrinfo(value, 443, socket.AF_INET, socket.SOCK_STREAM)
    ips = []
    seen = set()
    for info in infos:
        ip = info[4][0]
        if ip not in seen:
            seen.add(ip)
            ips.append(ip)
    return ips


def tunnel_interface_index() -> int | None:
    if not azimut_running():
        return None
    listing = run_hidden(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-NetAdapter | Where-Object { "
            "$_.Status -eq 'Up' -and "
            "($_.InterfaceDescription -match 'WireGuard|Wintun|Amnezia' -or $_.Name -match 'Azimut') "
            "} | Select-Object -ExpandProperty ifIndex",
        ]
    )
    for raw in listing.stdout.splitlines():
        text = raw.strip()
        if text.isdigit():
            return int(text)
    return None


def _probe_bound(ip: str, if_index: int, timeout: float = 5) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        packed = struct.pack("@I", socket.htonl(if_index))
        sock.setsockopt(socket.IPPROTO_IP, IP_UNICAST_IF, packed)
        sock.connect((ip, 443))
        return True
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(timeout)
            sock.setsockopt(socket.IPPROTO_IP, IP_UNICAST_IF, if_index)
            sock.connect((ip, 443))
            return True
        except Exception:
            return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _probe_url(url: str, timeout: float = 5) -> bool:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Azimut/1.7"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Azimut/1.7"})
            with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
                return 200 <= int(response.status) < 500
        except Exception:
            return False


def probe_host(host: str) -> bool:
    value = host.strip()
    if not value.startswith("http://") and not value.startswith("https://"):
        value = "https://" + value.split("/")[0]
    return _probe_url(value)


def check_site(host: str, config_text: str, probe: bool = True) -> SiteCheck:
    nets = parse_allowed(config_text)
    try:
        ips = resolve_host(host)
    except OSError:
        ips = []
    if not ips:
        reachable = probe_host(host) if probe else False
        return SiteCheck(
            route="нет адреса",
            ips=[],
            reachable=reachable,
            reachable_text="открывается" if reachable else "не открывается",
            via_tunnel="туннель не проверялся",
        )
    hits = [("через туннель" if any(ipaddress.ip_address(ip) in net for net in nets) else "напрямую") for ip in ips]
    route = hits[0] if all(item == hits[0] for item in hits) else "смешанно"
    reachable = probe_host(host) if probe else False
    via = "туннель выключен"
    if_index = tunnel_interface_index()
    if if_index:
        bound_ok = any(_probe_bound(ip, if_index) for ip in ips[:3])
        if bound_ok:
            via = "открывается через туннель"
        elif reachable:
            via = "сайт отвечает, но не через туннель"
        else:
            via = "через туннель не открывается"
    elif azimut_running():
        via = "адаптер туннеля не найден"
    reachable_text = via if if_index else ("открывается" if reachable else "не открывается")
    if if_index:
        reachable_text = via
        reachable = via == "открывается через туннель" or (reachable and route == "напрямую")
    return SiteCheck(
        route=route,
        ips=ips,
        reachable=reachable,
        reachable_text=reachable_text,
        via_tunnel=via,
    )
