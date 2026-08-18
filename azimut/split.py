from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
import ssl
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from .paths import cache_dir
from .sites import CATALOG

IPSUM_URL = "https://raw.githubusercontent.com/1andrevich/Re-filter-lists/main/ipsum.lst"
COMMUNITY_IPS_URL = "https://raw.githubusercontent.com/1andrevich/Re-filter-lists/main/community_ips.lst"
DISCORD_IPS_URL = "https://raw.githubusercontent.com/1andrevich/Re-filter-lists/main/discord_ips.lst"
COMMUNITY_DOMAINS_URL = "https://raw.githubusercontent.com/1andrevich/Re-filter-lists/main/community.lst"
YOUTUBE_CIDR_URL = "https://raw.githubusercontent.com/touhidurrr/iplist-youtube/main/lists/cidr4.txt"

DNS_VIA_TUNNEL = ["8.8.8.8/32", "8.8.4.4/32", "1.1.1.1/32", "1.0.0.1/32"]
YOUTUBE_MARKERS = (
    "youtube.com",
    "youtu.be",
    "youtubekids.com",
    "youtube-nocookie.com",
    "googlevideo.com",
    "ytimg.com",
    "yt.be",
    "ggpht.com",
    "gvt1.com",
    "music.youtube.",
)


def cache_key(
    selected_ids: list[str],
    extra_domains: list[str],
    zapret_enabled: bool = False,
    extra_ips: list[str] | None = None,
) -> str:
    raw = (
        ",".join(sorted(selected_ids))
        + "|"
        + ",".join(sorted(extra_domains))
        + f"|z{int(zapret_enabled)}"
        + "|"
        + ",".join(sorted(extra_ips or []))
    )
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def cache_file(
    selected_ids: list[str],
    extra_domains: list[str],
    zapret_enabled: bool = False,
    extra_ips: list[str] | None = None,
):
    return cache_dir() / f"split_{cache_key(selected_ids, extra_domains, zapret_enabled, extra_ips)}.txt"


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Azimut/1.7"})
    with urllib.request.urlopen(request, timeout=45, context=ssl.create_default_context()) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_cidrs(text: str) -> list[ipaddress.IPv4Network]:
    nets: list[ipaddress.IPv4Network] = []
    for raw in text.splitlines():
        line = raw.strip().split()[0] if raw.strip() else ""
        if not line or line.startswith("#"):
            continue
        if "/" not in line and re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", line):
            line = f"{line}/32"
        try:
            net = ipaddress.ip_network(line, strict=False)
        except ValueError:
            continue
        if isinstance(net, ipaddress.IPv4Network):
            nets.append(net)
    return nets


def is_youtube_domain(domain: str) -> bool:
    value = domain.lower()
    return any(value == item or item in value for item in YOUTUBE_MARKERS)


def resolve_domain(domain: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(domain, 443, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return []
    return list({info[4][0] for info in infos})


def expand_domains(domains: list[str]) -> list[str]:
    result = []
    seen = set()
    for raw in domains:
        item = raw.strip().lower()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
        if not item.startswith("www."):
            www = "www." + item
            if www not in seen:
                seen.add(www)
                result.append(www)
    return result


def resolve_many(domains: list[str], skip_youtube: bool = False) -> list[ipaddress.IPv4Network]:
    unique = []
    seen = set()
    for domain in expand_domains(domains):
        if domain in seen:
            continue
        if skip_youtube and is_youtube_domain(domain):
            continue
        seen.add(domain)
        unique.append(domain)
    nets: list[ipaddress.IPv4Network] = []
    with ThreadPoolExecutor(max_workers=24) as pool:
        futures = [pool.submit(resolve_domain, domain) for domain in unique]
        for future in as_completed(futures):
            for ip in future.result():
                nets.append(ipaddress.ip_network(f"{ip}/32"))
    return nets


def merge(nets: list[ipaddress.IPv4Network]) -> list[ipaddress.IPv4Network]:
    if not nets:
        return []
    return list(ipaddress.collapse_addresses(sorted(set(nets), key=lambda net: (int(net.network_address), net.prefixlen))))


def subtract(includes: list[ipaddress.IPv4Network], excludes: list[ipaddress.IPv4Network]) -> list[ipaddress.IPv4Network]:
    result = merge(includes)
    for exclude in merge(excludes):
        next_result = []
        for item in result:
            if not item.overlaps(exclude):
                next_result.append(item)
            elif exclude.prefixlen <= item.prefixlen:
                continue
            else:
                next_result.extend(item.address_exclude(exclude))
        result = next_result
    return merge(result)


def coarsen(nets: list[ipaddress.IPv4Network], excludes: list[ipaddress.IPv4Network], max_prefix: int = 20) -> list[ipaddress.IPv4Network]:
    ready = []
    for net in nets:
        if net.prefixlen <= max_prefix:
            ready.append(net)
            continue
        try:
            supernet = net.supernet(new_prefix=max_prefix)
        except ValueError:
            ready.append(net)
            continue
        if any(supernet.overlaps(item) for item in excludes):
            ready.append(net)
        else:
            ready.append(supernet)
    return merge(ready)


def youtube_networks() -> list[ipaddress.IPv4Network]:
    nets: list[ipaddress.IPv4Network] = []
    try:
        nets += parse_cidrs(fetch_text(YOUTUBE_CIDR_URL))
    except Exception:
        pass
    nets += resolve_many(
        ["youtube.com", "www.youtube.com", "youtu.be", "googlevideo.com", "i.ytimg.com"],
        skip_youtube=False,
    )
    return merge(nets)


def vpn_selected_ids(selected_ids: list[str], zapret_enabled: bool) -> list[str]:
    if not zapret_enabled:
        return list(selected_ids)
    return [item for item in selected_ids if item not in {"youtube", "discord"}]


def _parse_extra_ips(extra_ips: list[str] | None) -> list[ipaddress.IPv4Network]:
    nets: list[ipaddress.IPv4Network] = []
    for raw in extra_ips or []:
        line = str(raw).strip()
        if not line:
            continue
        if "/" not in line:
            line = f"{line}/32"
        try:
            net = ipaddress.ip_network(line, strict=False)
        except ValueError:
            continue
        if isinstance(net, ipaddress.IPv4Network):
            nets.append(net)
    return nets


def build_split_networks(
    selected_ids: list[str],
    extra_domains: list[str] | None = None,
    zapret_enabled: bool = False,
    extra_ips: list[str] | None = None,
) -> list[ipaddress.IPv4Network]:
    chosen = {item.strip() for item in vpn_selected_ids(selected_ids, zapret_enabled) if item.strip()}
    extra = [item.strip().lower() for item in (extra_domains or []) if item.strip()]
    app_nets = _parse_extra_ips(extra_ips)
    if not chosen and not extra and not app_nets:
        return []
    nets = parse_cidrs("\n".join(DNS_VIA_TUNNEL))
    youtube_on = "youtube" in chosen
    if "blocked_all" in chosen:
        nets += parse_cidrs(fetch_text(IPSUM_URL))
        nets += parse_cidrs(fetch_text(COMMUNITY_IPS_URL))
        domains = [
            line.strip()
            for line in fetch_text(COMMUNITY_DOMAINS_URL).splitlines()
            if line.strip() and not line.startswith("#")
        ]
        nets += resolve_many(domains, skip_youtube=not youtube_on)
        if not zapret_enabled:
            try:
                nets += parse_cidrs(fetch_text(DISCORD_IPS_URL))
            except Exception:
                pass
    for site in CATALOG:
        if site.id not in chosen or site.id == "blocked_all":
            continue
        if site.cidrs:
            nets += parse_cidrs("\n".join(site.cidrs))
        if site.domains:
            nets += resolve_many(site.domains, skip_youtube=False)
        if site.id == "discord" and not zapret_enabled:
            try:
                nets += parse_cidrs(fetch_text(DISCORD_IPS_URL))
            except Exception:
                pass
        if site.id == "youtube":
            nets += youtube_networks()
    if extra:
        nets += resolve_many(extra, skip_youtube=False)
    if app_nets:
        nets += app_nets
    merged = merge(nets)
    if zapret_enabled:
        merged = subtract(merged, youtube_networks())
    elif "blocked_all" in chosen and not youtube_on:
        return coarsen(subtract(merged, youtube_networks()), [], max_prefix=20)
    return merged


def allowed_ips_text(
    selected_ids: list[str],
    extra_domains: list[str] | None = None,
    force: bool = False,
    zapret_enabled: bool = False,
    extra_ips: list[str] | None = None,
) -> str:
    extra = extra_domains or []
    path = cache_file(selected_ids, extra, zapret_enabled, extra_ips)
    if path.exists() and not force:
        return path.read_text(encoding="utf-8").strip()
    try:
        nets = build_split_networks(selected_ids, extra, zapret_enabled, extra_ips)
        items = [str(net) for net in nets]
        lines = []
        for index in range(0, len(items), 40):
            lines.append("AllowedIPs = " + ", ".join(items[index : index + 40]))
        text = "\n".join(lines)
        path.write_text(text, encoding="utf-8")
        return text
    except Exception:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        raise


def apply_mode(
    config_text: str,
    mode: str,
    dns: str,
    selected_ids: list[str],
    extra_domains: list[str] | None = None,
    zapret_enabled: bool = False,
    force: bool = False,
    extra_ips: list[str] | None = None,
) -> str:
    original_allowed = [
        line for line in config_text.splitlines() if line.strip().lower().startswith("allowedips")
    ]
    lines = []
    wrote_dns = False
    for line in config_text.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("allowedips"):
            continue
        if stripped.startswith("dns"):
            if mode == "full":
                lines.append(line)
            elif not wrote_dns:
                lines.append(f"DNS = {dns}")
            wrote_dns = True
            continue
        lines.append(line)
    text = "\n".join(lines).rstrip() + "\n"
    if mode == "full":
        extra = ("\n".join(original_allowed) + "\n") if original_allowed else "AllowedIPs = 0.0.0.0/0, ::/0\n"
    else:
        extra = (
            allowed_ips_text(
                selected_ids,
                extra_domains,
                force=force,
                zapret_enabled=zapret_enabled,
                extra_ips=extra_ips,
            )
            + "\n"
        )
        if extra.strip() == "":
            raise RuntimeError(
                "Не отмечен ни один сайт и ни одна программа для туннеля. "
                "Откройте страницу «Сайты» или «Программы» и выберите, что пускать через VPN."
            )
    if "[Peer]" not in text:
        return text + extra
    head, tail = text.split("[Peer]", 1)
    return head + "[Peer]\n" + extra + tail.lstrip("\n")
