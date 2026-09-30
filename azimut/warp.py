from __future__ import annotations

import base64
import json
import os
import random
import re
import socket
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

API_URL = "https://api.cloudflareclient.com/v0a1922/reg"
API_VERSION = "v0a1922"
CLOUDFLARE_PUBLIC_KEY = "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="
GENERATED_MARK = "Azimut-Generated"
DEFAULT_WARP_PORT = "2408"
CLIENT_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "okhttp/3.12.1",
    "CF-Client-Version": "a-6.3-1922",
}

ENDPOINTS = [
    "162.159.193.1:500",
    "162.159.192.1:2408",
    "162.159.195.1:500",
    "188.114.96.7:1701",
    "188.114.97.7:1701",
    "engage.cloudflareclient.com:4500",
    "engage.cloudflareclient.com:2408",
]


def generate_keypair() -> tuple[str, str]:
    private = X25519PrivateKey.generate()
    private_b64 = base64.b64encode(
        private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    ).decode("ascii")
    public_b64 = base64.b64encode(
        private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode("ascii")
    return private_b64, public_b64


def _api_context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_default_certs()
    return context


def _api_request(url: str, body: dict, token: str = "", method: str = "POST", timeout: int = 25) -> dict:
    headers = dict(CLIENT_HEADERS)
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_api_context()) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Cloudflare ответил кодом {exc.code}: {details[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Служебный адрес Cloudflare сейчас не открывается. "
            "Azimut подбирает обход именно для этого адреса. Подождите конец подбора "
            "или импортируйте готовый файл .conf кнопкой «Импорт»."
        ) from exc


def register_device(public_key: str, timeout: int = 25) -> dict:
    body = {
        "key": public_key,
        "install_id": "",
        "fcm_token": "",
        "tos": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "model": "PC",
        "serial_number": "",
        "locale": "en_US",
        "type": "Android",
    }
    return _api_request(API_URL, body, timeout=timeout)


def enable_warp(payload: dict) -> None:
    device_id = str(payload.get("id") or "").strip()
    token = str(payload.get("token") or "").strip()
    if not device_id or not token:
        return
    url = f"https://api.cloudflareclient.com/{API_VERSION}/reg/{device_id}"
    try:
        _api_request(url, {"warp_enabled": True}, token=token, method="PATCH")
    except Exception:
        return


def cloudflare_reachable(timeout: float = 8) -> bool:
    request = urllib.request.Request(
        "https://api.cloudflareclient.com/",
        method="GET",
        headers={
            "User-Agent": CLIENT_HEADERS["User-Agent"],
            "CF-Client-Version": CLIENT_HEADERS["CF-Client-Version"],
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            return 100 <= int(response.status) < 600
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def is_warp_config(text: str) -> bool:
    if CLOUDFLARE_PUBLIC_KEY in text:
        return True
    low = text.lower()
    return "172.16.0.2" in text and (
        "engage.cloudflareclient.com" in low or "162.159.19" in text or "188.114.9" in text
    )


def is_generated_warp(text: str, name: str = "", source: str = "") -> bool:
    if (source or "").strip().lower() == "warp":
        return True
    if GENERATED_MARK in (text or ""):
        return True
    stem = (name or "").strip()
    return stem.upper().startswith("WARP_") and is_warp_config(text or "")


def has_i1(text: str) -> bool:
    match = re.search(r"^\s*I1\s*=\s*(.+)$", text, re.I | re.M)
    return bool(match and len(match.group(1).strip()) > 20)


def has_amnezia_params(text: str) -> bool:
    return bool(re.search(r"(?im)^\s*(Jc|Jmin|Jmax|JunkPacketCount|H1|I1|S1)\s*=", text))


def split_host_port(value: str) -> tuple[str, str]:
    value = (value or "").strip()
    if not value:
        return "", ""
    if value.startswith("["):
        closing = value.find("]")
        if closing > 1:
            host = value[1:closing]
            rest = value[closing + 1 :]
            port = rest[1:] if rest.startswith(":") else ""
            return host, port
        return value, ""
    if value.count(":") == 1:
        host, port = value.rsplit(":", 1)
        return host, port
    return value, ""


def valid_port(port: str) -> bool:
    return bool(port) and port.isdigit() and 1 <= int(port) <= 65535


def load_preferred_endpoint() -> str:
    try:
        from .settings import Settings

        return (Settings.load().endpoint or "").strip()
    except Exception:
        return ""


def sanitize_endpoint(value: str, preferred: str = "") -> str:
    value = (value or "").strip()
    preferred = (preferred or "").strip()
    host, port = split_host_port(value)
    if host and valid_port(port):
        return resolve_endpoint(f"{host}:{port}")
    pref_host, pref_port = split_host_port(preferred)
    if pref_host and valid_port(pref_port):
        return resolve_endpoint(f"{pref_host}:{pref_port}")
    if host and re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
        return f"{host}:{DEFAULT_WARP_PORT}"
    if host:
        return resolve_endpoint(f"{host}:{DEFAULT_WARP_PORT}")
    if preferred:
        return resolve_endpoint(preferred)
    return resolve_endpoint(f"engage.cloudflareclient.com:{DEFAULT_WARP_PORT}")


def resolve_endpoint(endpoint: str) -> str:
    endpoint = (endpoint or "").strip()
    host, port = split_host_port(endpoint)
    if not host:
        return endpoint
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
        return f"{host}:{port}" if port else host
    if not port:
        return endpoint
    try:
        infos = socket.getaddrinfo(host, int(port), socket.AF_INET, socket.SOCK_DGRAM)
        return f"{infos[0][4][0]}:{port}"
    except Exception:
        return endpoint


def _set_line(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"(?im)^\s*{re.escape(key)}\s*=.*$")
    line = f"{key} = {value}"
    if pattern.search(text):
        return pattern.sub(line, text, count=1)
    if re.search(r"(?im)^\s*\[Peer\]", text):
        return re.sub(r"(?im)^\s*\[Peer\]", line + "\n\n[Peer]", text, count=1)
    return text.rstrip() + "\n" + line + "\n"


def _random_blob(minimum: int = 16, maximum: int = 48) -> str:
    return "<b 0x" + os.urandom(random.randint(minimum, maximum)).hex() + ">"


def _i1_from_profiles() -> str | None:
    texts = []
    try:
        from .vault import is_unlocked, list_profiles

        if is_unlocked():
            texts.extend(item.text for item in list_profiles())
    except Exception:
        pass
    from .paths import profiles_dir

    for path in profiles_dir().glob("*.conf"):
        try:
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
    for text in texts:
        if not is_warp_config(text):
            continue
        match = re.search(r"^\s*I1\s*=\s*(.+)$", text, re.I | re.M)
        if match and "<b 0x" in match.group(1).lower() and len(match.group(1)) > 200:
            return match.group(1).strip()
    return None


def _i1_from_snapshot() -> str | None:
    path = Path(__file__).with_name("warp_i1.hex")
    if not path.exists():
        return None
    hexpart = re.sub(r"[^0-9a-fA-F]", "", path.read_text(encoding="ascii", errors="replace"))
    if len(hexpart) < 200:
        return None
    return "<b 0x" + hexpart.lower() + ">"


def camouflage_i1() -> str:
    return _i1_from_profiles() or _i1_from_snapshot() or _random_blob(1100, 1250)


def harden_config(text: str, preferred_endpoint: str = "") -> str:
    """Fill camouflage only for bare WireGuard WARP. Ready Amnezia files stay untouched."""
    match = re.search(r"(?im)^\s*Endpoint\s*=\s*(.+)$", text)
    current = match.group(1).strip() if match else ""
    if is_warp_config(text) or GENERATED_MARK in (text or ""):
        text = _set_line(text, "Endpoint", sanitize_endpoint(current, preferred_endpoint or load_preferred_endpoint()))
    elif current:
        text = _set_line(text, "Endpoint", resolve_endpoint(current))
    if has_amnezia_params(text):
        return text
    if not is_warp_config(text):
        return text
    if not has_i1(text):
        text = _set_line(text, "I1", camouflage_i1())
        for index, key in enumerate(("I2", "I3", "I4", "I5"), start=2):
            if not re.search(rf"(?im)^\s*{key}\s*=", text):
                text = _set_line(text, key, _random_blob(16, 40))
    if not re.search(r"(?im)^\s*Jc\s*=", text):
        text = _set_line(text, "Jc", "4")
        text = _set_line(text, "Jmin", "40")
        text = _set_line(text, "Jmax", "70")
    return text


def reserved_from_client_id(client_id: str) -> str | None:
    text = (client_id or "").strip()
    if not text:
        return None
    try:
        raw = base64.b64decode(text)
    except Exception:
        return None
    if len(raw) < 3:
        return None
    return f"{raw[0]}, {raw[1]}, {raw[2]}"


def peer_endpoint(payload: dict, fallback: str) -> str:
    cfg = payload.get("config") or {}
    peers = cfg.get("peers") or [{}]
    peer = peers[0] if peers else {}
    endpoint = peer.get("endpoint") or {}
    fallback = (fallback or "").strip()
    host = (endpoint.get("host") or "").strip()
    v4 = (endpoint.get("v4") or "").strip()
    ports = [str(item) for item in (endpoint.get("ports") or []) if valid_port(str(item))]
    api_port = split_host_port(host)[1]
    port = api_port if valid_port(api_port) else (ports[0] if ports else DEFAULT_WARP_PORT)
    pref_host, pref_port = split_host_port(fallback)
    if pref_host and valid_port(pref_port):
        return resolve_endpoint(f"{pref_host}:{pref_port}")
    v4_host, v4_port = split_host_port(v4)
    if v4_host and re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", v4_host):
        chosen_port = v4_port if valid_port(v4_port) else port
        return f"{v4_host}:{chosen_port}"
    if host:
        return sanitize_endpoint(host, fallback)
    return sanitize_endpoint("", fallback)


def build_config(private_key: str, payload: dict, endpoint: str, dns: str) -> str:
    cfg = payload.get("config") or {}
    interface = (cfg.get("interface") or {}).get("addresses") or {}
    peers = cfg.get("peers") or [{}]
    peer = peers[0] if peers else {}
    address_v4 = interface.get("v4") or "172.16.0.2/32"
    address_v6 = interface.get("v6") or ""
    public_key = peer.get("public_key") or CLOUDFLARE_PUBLIC_KEY
    if "/" not in str(address_v4):
        address_v4 = f"{address_v4}/32"
    if address_v6 and "/" not in str(address_v6):
        address_v6 = f"{address_v6}/128"
    addresses = address_v4 if not address_v6 else f"{address_v4}, {address_v6}"
    endpoint = peer_endpoint(payload, endpoint)
    reserved = reserved_from_client_id(str(cfg.get("client_id") or ""))
    reserved_line = f"Reserved = {reserved}\n" if reserved else ""
    i1 = camouflage_i1()
    text = f"""# {GENERATED_MARK}
[Interface]
PrivateKey = {private_key}
Address = {addresses}
DNS = {dns}
MTU = 1280
Jc = 4
Jmin = 40
Jmax = 70
S1 = 0
S2 = 0
S3 = 0
S4 = 0
H1 = 1
H2 = 2
H3 = 3
H4 = 4
I1 = {i1}
I2 = {_random_blob(16, 32)}
I3 = {_random_blob(16, 32)}
I4 = {_random_blob(16, 32)}
I5 = {_random_blob(16, 32)}

[Peer]
PublicKey = {public_key}
{reserved_line}AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = {endpoint}
PersistentKeepalive = 25
"""
    return harden_config(text)


def create_warp_config(endpoint: str, dns: str) -> str:
    private_key, public_key = generate_keypair()
    payload = register_device(public_key)
    enable_warp(payload)
    return build_config(private_key, payload, endpoint, dns)
