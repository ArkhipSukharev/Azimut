from __future__ import annotations

import ctypes
import re
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from .engine import engine_exe, ensure_engine

TUNNEL_PREFIX = "Azimut__"
SERVICE_PREFIXES = ("AmneziaWGTunnel$", "WireGuardTunnel$")


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def restart_as_admin() -> None:
    from .paths import app_root, launcher_arguments, launcher_target

    ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        str(launcher_target()),
        launcher_arguments(),
        str(app_root()),
        1,
    )


def is_amnezia_config(text: str) -> bool:
    return bool(re.search(r"^\s*(Jc|Jmin|Jmax|H1|I1|S1)\s*=", text, re.I | re.M))


def safe_name(name: str) -> str:
    name = Path(name).stem
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or "AzimutTunnel"


def tunnel_name_for(profile_name: str) -> str:
    base = safe_name(profile_name)
    if base.startswith(TUNNEL_PREFIX):
        return base
    return TUNNEL_PREFIX + base


def profile_from_tunnel(name: str) -> str:
    if name.startswith(TUNNEL_PREFIX):
        return name[len(TUNNEL_PREFIX) :]
    return name


def _decode(raw: bytes) -> str:
    for encoding in ("cp866", "cp1251", "utf-8"):
        try:
            return raw.decode(encoding)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def run_hidden(args: list[str]) -> SimpleNamespace:
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    proc = subprocess.run(
        args,
        capture_output=True,
        startupinfo=startup,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return SimpleNamespace(
        returncode=proc.returncode,
        stdout=_decode(proc.stdout or b""),
        stderr=_decode(proc.stderr or b""),
    )


def _explain(text: str) -> str:
    low = text.lower()
    if "2:" in text or "не удается найти" in low or "cannot find the file" in low:
        return "Windows не нашла файл старой службы туннеля. Azimut поставит подключение заново."
    if "5:" in text or "отказано" in low or "access is denied" in low:
        return "Не хватает прав администратора."
    if "1058" in text or "отключена" in low:
        return "Служба туннеля отключена в Windows."
    return text.strip() or "неизвестная ошибка Windows"


def _service_names(tunnel: str) -> list[str]:
    return [prefix + tunnel for prefix in SERVICE_PREFIXES]


def _service_running(output: str) -> bool:
    return bool(re.search(r":\s*4\b", output)) or "RUNNING" in output.upper()


def _service_exists(output: str) -> bool:
    low = output.lower()
    if "1060" in output or "does not exist" in low or "не существует" in low:
        return False
    return bool(output.strip()) and "FAILED" not in output.upper()


def list_services() -> dict[str, dict]:
    result: dict[str, dict] = {}
    try:
        import win32service

        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ENUMERATE_SERVICE)
        services = win32service.EnumServicesStatus(
            scm, win32service.SERVICE_WIN32, win32service.SERVICE_STATE_ALL
        )
        for name, _display, status in services:
            if name.startswith("AmneziaWGTunnel$") or name.startswith("WireGuardTunnel$"):
                tunnel = name.split("$", 1)[1]
                result[tunnel] = {
                    "service": name,
                    "running": status[1] == 4,
                    "amnezia": name.startswith("AmneziaWGTunnel$"),
                }
        return result
    except Exception:
        pass

    from .paths import active_dir

    names = {path.stem for path in active_dir().glob("*.conf")}
    for tunnel in names:
        for service in _service_names(tunnel):
            proc = run_hidden(["sc", "query", service])
            text = proc.stdout + proc.stderr
            if not _service_exists(text):
                continue
            result[tunnel] = {
                "service": service,
                "running": _service_running(text),
                "amnezia": service.startswith("AmneziaWGTunnel$"),
            }
            break
    return result


def running_tunnels() -> list[str]:
    return [name for name, info in list_services().items() if info["running"]]


def azimut_running() -> list[str]:
    return [name for name in running_tunnels() if name.startswith(TUNNEL_PREFIX)]


def is_profile_running(profile_name: str) -> bool:
    names = set(running_tunnels())
    return tunnel_name_for(profile_name) in names or safe_name(profile_name) in names


def start_service(service_name: str) -> None:
    proc = run_hidden(["sc", "start", service_name])
    text = (proc.stdout + proc.stderr).lower()
    if proc.returncode != 0 and "already" not in text and "уже" not in text:
        raise RuntimeError(_explain(proc.stderr or proc.stdout))


def stop_service(service_name: str) -> None:
    run_hidden(["sc", "stop", service_name])


def install_tunnel(exe: Path, config_path: Path) -> None:
    if not exe.exists():
        raise RuntimeError(f"Не найден встроенный движок туннеля:\n{exe}")
    if not config_path.exists():
        raise RuntimeError(f"Не найден файл конфига:\n{config_path}")
    proc = run_hidden([str(exe), "/installtunnelservice", str(config_path)])
    if proc.returncode != 0:
        raise RuntimeError(_explain(proc.stderr or proc.stdout))


def uninstall_tunnel(exe: Path, tunnel_name: str) -> None:
    if exe.exists():
        run_hidden([str(exe), "/uninstalltunnelservice", tunnel_name])


def _service_image(service: str) -> str:
    proc = run_hidden(["sc", "qc", service])
    match = re.search(r"BINARY_PATH_NAME\s*:\s*(.+)", proc.stdout, re.I)
    if match:
        return match.group(1).strip()
    match = re.search(r"Имя_двоичного_файла\s*:\s*(.+)", proc.stdout, re.I)
    if match:
        return match.group(1).strip()
    return proc.stdout


def _service_exe_path(image: str) -> Path | None:
    image = image.strip()
    if not image:
        return None
    if image.startswith('"'):
        end = image.find('"', 1)
        if end > 1:
            return Path(image[1:end])
    token = re.split(r"\s+/", image, maxsplit=1)[0].strip().strip('"')
    return Path(token) if token else None


def _purge_tunnel(tunnel: str) -> None:
    for service in _service_names(tunnel):
        stop_service(service)
    time.sleep(0.2)
    try:
        uninstall_tunnel(engine_exe(), tunnel)
    except Exception:
        pass
    time.sleep(0.2)
    for service in _service_names(tunnel):
        run_hidden(["sc", "delete", service])


def cleanup_broken_tunnels() -> list[str]:
    """Remove leftover Windows tunnel services whose program is gone (PORTAL WG, old WireGuard)."""
    removed: list[str] = []
    ours = str(engine_exe()).lower()
    for tunnel, info in list(list_services().items()):
        service = info["service"]
        image = _service_image(service)
        low = image.lower()
        exe_path = _service_exe_path(image)
        missing = bool(exe_path) and not exe_path.exists()
        foreign = ("portal wg" in low) or ("\\wireguard\\wireguard.exe" in low)
        ours_ok = bool(exe_path) and str(exe_path).lower() == ours and exe_path.exists()
        if tunnel.startswith(TUNNEL_PREFIX):
            continue
        if ours_ok:
            continue
        if missing or foreign:
            _purge_tunnel(tunnel)
            removed.append(tunnel)
    return removed


def latest_handshake(tunnel: str) -> int | None:
    """Unix time of last handshake, 0 if never, None if the tool cannot see the tunnel."""
    from .paths import engine_dir

    awg = engine_dir() / "awg.exe"
    if not awg.exists():
        return None
    proc = run_hidden([str(awg), "show", tunnel, "latest-handshakes"])
    text = (proc.stdout or "").strip()
    if proc.returncode != 0 or not text:
        names = run_hidden([str(awg), "show", "interfaces"])
        if tunnel not in names.stdout:
            return None
        return 0
    best = None
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[-1].isdigit():
            value = int(parts[-1])
            best = value if best is None else max(best, value)
    return best


def wait_handshake(tunnel: str, timeout: float = 15, full_tunnel: bool = False) -> None:
    seen_dead = False
    deadline = time.time() + timeout
    while time.time() < deadline:
        stamp = latest_handshake(tunnel)
        if stamp is not None and stamp > 0:
            return
        if stamp == 0:
            seen_dead = True
        time.sleep(0.7)
    if not seen_dead and not full_tunnel:
        return
    if not seen_dead and full_tunnel:
        ping = run_hidden(["ping", "-n", "1", "-w", "2000", "1.1.1.1"])
        if ping.returncode == 0:
            return
    _purge_tunnel(tunnel)
    from .protect import wipe_active_configs

    wipe_active_configs()
    raise RuntimeError(
        "Сервер не ответил на рукопожатие, поэтому Azimut сразу вернул обычный интернет. "
        "Иначе весь трафик ушёл бы в мёртвый туннель и сеть пропала бы. "
        "Для нового WARP выберите в настройках другой адрес точки входа и создайте профиль ещё раз. "
        "Или сначала включите уже рабочий купленный туннель, а WARP создайте поверх него."
    )


def connect_file(config_path: Path, text: str | None = None) -> str:
    from .paths import active_dir
    from .protect import atomic_write, wipe_active_configs
    from .warp import harden_config

    exe = ensure_engine()
    cleanup_broken_tunnels()
    if text is None:
        text = config_path.read_text(encoding="utf-8", errors="replace")
    text = harden_config(text)
    name = tunnel_name_for(config_path.name)
    legacy = safe_name(config_path.name)
    if legacy.startswith(TUNNEL_PREFIX):
        legacy = profile_from_tunnel(legacy)
    target = active_dir() / f"{name}.conf"
    disconnect_all_azimut()
    _purge_tunnel(name)
    if legacy and legacy != name:
        _purge_tunnel(legacy)
    atomic_write(target, text.encode("utf-8"))
    time.sleep(0.4)
    install_tunnel(exe, target)
    deadline = time.time() + 8
    running = False
    while time.time() < deadline:
        if name in running_tunnels() or is_profile_running(name):
            running = True
            break
        time.sleep(0.4)
    if not running:
        services = list_services()
        info = services.get(name)
        if info and not info["running"]:
            start_service(info["service"])
        running = name in running_tunnels() or is_profile_running(name)
    if not running:
        _purge_tunnel(name)
        wipe_active_configs()
        raise RuntimeError("Туннель установлен, но Windows не смогла его запустить. Интернет не трогали.")
    wait_handshake(name, full_tunnel="0.0.0.0/0" in text)
    return name


def disconnect_name(name: str) -> None:
    tunnel = name if name.startswith(TUNNEL_PREFIX) else tunnel_name_for(name)
    _purge_tunnel(tunnel)
    _purge_tunnel(safe_name(name))


def disconnect_all_azimut() -> list[str]:
    stopped: list[str] = []
    seen: set[str] = set()
    for name in list(list_services()):
        if not name.startswith(TUNNEL_PREFIX):
            continue
        _purge_tunnel(name)
        stopped.append(name)
        seen.add(name)
    for name in list(azimut_running()):
        if name in seen:
            continue
        _purge_tunnel(name)
        stopped.append(name)
    from .protect import wipe_active_configs

    wipe_active_configs()
    return stopped


def restore_network(keep_running: set[str] | None = None) -> list[str]:
    stopped = disconnect_all_azimut()
    stopped.extend(cleanup_broken_tunnels())
    return stopped
