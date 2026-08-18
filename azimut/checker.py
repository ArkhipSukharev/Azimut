from __future__ import annotations

import ipaddress
import re
import socket
import ssl
import urllib.request
from dataclasses import dataclass


@dataclass
class SiteCheck:
    route: str
    ips: list[str]
    reachable: bool
    reachable_text: str


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


def _probe_url(url: str, timeout: float = 5) -> bool:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Azimut/1.6"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Azimut/1.6"})
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
        )
    hits = [("через туннель" if any(ipaddress.ip_address(ip) in net for net in nets) else "напрямую") for ip in ips]
    route = hits[0] if all(item == hits[0] for item in hits) else "смешанно"
    reachable = probe_host(host) if probe else False
    return SiteCheck(
        route=route,
        ips=ips,
        reachable=reachable,
        reachable_text="открывается" if reachable else "не открывается",
    )
