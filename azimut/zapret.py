from __future__ import annotations

import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from .paths import app_root, cache_dir, logs_dir

PID_NAME = "azimut_winws.pid"
WINWS_NAME = "winws.exe"
PROBE_WAIT = 2.2
PROBE_TIMEOUT = 4

PROBE_SITES = [
    ("YouTube", "https://www.youtube.com/"),
    ("Discord", "https://discord.com/"),
    ("Картинки YouTube", "https://i.ytimg.com/"),
    ("Шлюз Discord", "https://gateway.discord.gg/"),
]

HOSTS_YOUTUBE = [
    "youtube.com",
    "youtu.be",
    "googlevideo.com",
    "ytimg.com",
    "ggpht.com",
    "youtube-nocookie.com",
    "youtubekids.com",
    "yt.be",
    "googleapis.com",
    "gstatic.com",
    "youtubei.googleapis.com",
    "yt3.ggpht.com",
    "jnn-pa.googleapis.com",
]

HOSTS_DISCORD = [
    "discord.com",
    "discord.gg",
    "discordapp.com",
    "discord.media",
    "discordapp.net",
    "discord.co",
    "gateway.discord.gg",
    "cdn.discordapp.com",
    "media.discordapp.net",
    "images-ext-1.discordapp.net",
    "images-ext-2.discordapp.net",
]

HOSTS_GOOGLE = [
    "google.com",
    "gstatic.com",
    "googleapis.com",
    "googleusercontent.com",
]

HOSTS_CLOUDFLARE = [
    "api.cloudflareclient.com",
    "cloudflareclient.com",
    "engage.cloudflareclient.com",
]


def zapret_dir() -> Path:
    return app_root() / "zapret"


def bin_dir() -> Path:
    return zapret_dir() / "bin"


def pid_path() -> Path:
    return zapret_dir() / PID_NAME


def winws_path() -> Path:
    return bin_dir() / WINWS_NAME


def hosts_dir() -> Path:
    path = cache_dir() / "bypass"
    path.mkdir(parents=True, exist_ok=True)
    return path


def engine_ready() -> bool:
    needed = [
        winws_path(),
        bin_dir() / "WinDivert.dll",
        bin_dir() / "WinDivert64.sys",
        bin_dir() / "quic_initial_www_google_com.bin",
        bin_dir() / "tls_clienthello_www_google_com.bin",
        bin_dir() / "ACTIVE_DISCORD_UDP.bin",
    ]
    return all(path.exists() for path in needed)


def _decode(raw: bytes) -> str:
    for encoding in ("cp866", "cp1251", "utf-8"):
        try:
            return raw.decode(encoding)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def _hidden(args: list[str], cwd: Path | None = None) -> SimpleNamespace:
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    proc = subprocess.run(
        args,
        capture_output=True,
        cwd=str(cwd) if cwd else None,
        startupinfo=startup,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return SimpleNamespace(
        returncode=proc.returncode,
        stdout=_decode(proc.stdout or b""),
        stderr=_decode(proc.stderr or b""),
    )


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    check = _hidden(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"])
    return str(pid) in check.stdout and WINWS_NAME.lower() in check.stdout.lower()


def _our_pid() -> int | None:
    path = pid_path()
    if not path.exists():
        return None
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return None
    if _pid_alive(pid):
        return pid
    path.unlink(missing_ok=True)
    return None


_started_by_us = False
_active_strategy = ""


def is_running() -> bool:
    if _our_pid() is not None:
        return True
    check = _hidden(["tasklist", "/FI", f"IMAGENAME eq {WINWS_NAME}", "/FO", "CSV", "/NH"])
    return WINWS_NAME.lower() in check.stdout.lower() and "INFO:" not in check.stdout


def active_strategy() -> str:
    return _active_strategy


@dataclass(frozen=True)
class Strategy:
    id: str
    title: str
    kind: str


@dataclass
class ProbeResult:
    ok: dict[str, bool] = field(default_factory=dict)

    @property
    def score(self) -> int:
        return sum(1 for value in self.ok.values() if value)

    @property
    def total(self) -> int:
        return len(self.ok)

    @property
    def good_enough(self) -> bool:
        return bool(self.ok.get("YouTube") and self.ok.get("Discord"))

    def summary(self) -> str:
        if not self.ok:
            return "сайты ещё не проверялись"
        parts = []
        for name, value in self.ok.items():
            parts.append(f"{name} {self._verb(name, value)}")
        return ", ".join(parts)

    def display(self) -> str:
        if not self.ok:
            return "Сайты ещё не проверялись."
        return "\n".join(f"{name} — {self._verb(name, value)}" for name, value in self.ok.items())

    @staticmethod
    def _verb(name: str, ok: bool) -> str:
        plural = name.lower().startswith("картинк")
        if plural:
            return "открываются" if ok else "не открываются"
        return "открывается" if ok else "не открывается"


@dataclass
class PickResult:
    strategy: str
    title: str
    probe: ProbeResult
    tried: int = 0
    reused: bool = False


STRATEGIES: list[Strategy] = [
    Strategy("general", "general", "general"),
    Strategy("alt", "general (ALT)", "alt"),
    Strategy("alt2", "general (ALT2)", "alt2"),
    Strategy("alt3", "general (ALT3)", "alt3"),
    Strategy("alt4", "general (ALT4)", "alt4"),
    Strategy("alt5", "general (ALT5)", "alt5"),
    Strategy("alt6", "general (ALT6)", "alt6"),
    Strategy("alt7", "general (ALT7)", "alt7"),
    Strategy("alt8", "general (ALT8)", "alt8"),
    Strategy("alt9", "general (ALT9)", "alt9"),
    Strategy("alt10", "general (ALT10)", "alt10"),
    Strategy("alt11", "general (ALT11)", "alt11"),
    Strategy("alt12", "general (ALT12)", "alt12"),
    Strategy("exp", "general (EXP)", "exp"),
    Strategy("fake_tls_auto", "general (FAKE TLS AUTO)", "fake_tls_auto"),
    Strategy("fake_tls_auto_alt", "general (FAKE TLS AUTO ALT)", "fake_tls_auto_alt"),
    Strategy("fake_tls_auto_alt2", "general (FAKE TLS AUTO ALT2)", "fake_tls_auto_alt2"),
    Strategy("fake_tls_auto_alt3", "general (FAKE TLS AUTO ALT3)", "fake_tls_auto_alt3"),
    Strategy("simple_fake", "general (SIMPLE FAKE)", "simple_fake"),
    Strategy("simple_fake_alt", "general (SIMPLE FAKE ALT)", "simple_fake_alt"),
    Strategy("simple_fake_alt2", "general (SIMPLE FAKE ALT2)", "simple_fake_alt2"),
    Strategy("goodbye9", "Как GoodbyeDPI, режим 9", "goodbye9"),
    Strategy("goodbye5", "Как GoodbyeDPI, режим 5", "goodbye5"),
]

LEGACY_STRATEGY_IDS = {
    "fake_tls": "fake_tls_auto",
    "split": "general",
    "split_small": "alt2",
    "fake_ts": "alt",
    "disorder": "alt5",
}


def list_strategies() -> list[Strategy]:
    return list(STRATEGIES)


def find_strategy(strategy_id: str) -> Strategy | None:
    wanted = (strategy_id or "").strip().lower()
    if not wanted:
        return None
    wanted = LEGACY_STRATEGY_IDS.get(wanted, wanted)
    for item in STRATEGIES:
        if item.id == wanted:
            return item
    return None


def strategy_title(strategy_id: str) -> str:
    item = find_strategy(strategy_id)
    return item.title if item else "не выбран"


def strategy_titles() -> list[str]:
    return [item.title for item in STRATEGIES]


def strategy_id_for_title(title: str) -> str:
    wanted = (title or "").strip()
    for item in STRATEGIES:
        if item.title == wanted:
            return item.id
    return ""


def _write_hosts(name: str, hosts: list[str]) -> str:
    path = hosts_dir() / name
    path.write_text("\n".join(hosts) + "\n", encoding="utf-8")
    return str(path)


def _fakes() -> dict[str, str]:
    folder = str(bin_dir()) + "\\"
    return {
        "quic": folder + "quic_initial_www_google_com.bin",
        "tls": folder + "tls_clienthello_www_google_com.bin",
        "discord": folder + "ACTIVE_DISCORD_UDP.bin",
        "http": folder + "tls_clienthello_max_ru.bin",
    }


def _https_trick(kind: str, fakes: dict[str, str], youtube: bool = False) -> list[str]:
    tls = fakes["tls"]
    http = fakes["http"]
    if youtube and kind in {"simple_fake", "alt12", "exp"}:
        args = [
            "--dpi-desync=hostfakesplit",
            "--dpi-desync-fooling=ts",
            "--dpi-desync-hostfakesplit-mod=host=www.google.com",
        ]
        if kind == "simple_fake":
            return ["--ip-id=zero"] + args
        return ["--ip-id=zero"] + args
    tricks: dict[str, list[str]] = {
        "general": [
            "--dpi-desync=multisplit",
            f"--dpi-desync-split-seqovl={'681' if youtube else '568'}",
            "--dpi-desync-split-pos=1",
            f"--dpi-desync-split-seqovl-pattern={tls}",
        ],
        "alt": [
            "--dpi-desync=fake,fakedsplit",
            "--dpi-desync-repeats=6",
            "--dpi-desync-fooling=ts",
            "--dpi-desync-fakedsplit-pattern=0x00",
            f"--dpi-desync-fake-tls={tls}",
            f"--dpi-desync-fake-http={http}",
        ],
        "alt2": [
            "--dpi-desync=multisplit",
            "--dpi-desync-split-seqovl=652",
            "--dpi-desync-split-pos=2",
            f"--dpi-desync-split-seqovl-pattern={tls}",
        ],
        "alt3": [
            "--dpi-desync=fake,hostfakesplit",
            "--dpi-desync-fake-tls-mod=rnd,dupsid,sni=www.google.com",
            "--dpi-desync-hostfakesplit-mod=host=www.google.com,altorder=1",
            "--dpi-desync-fooling=ts",
        ],
        "alt4": [
            "--dpi-desync=fake,multisplit",
            "--dpi-desync-repeats=6",
            "--dpi-desync-fooling=badseq",
            "--dpi-desync-badseq-increment=1000",
            f"--dpi-desync-fake-tls={tls}",
        ],
        "alt5": [
            "--dpi-desync=syndata,multidisorder",
        ],
        "alt6": [
            "--dpi-desync=multisplit",
            "--dpi-desync-split-seqovl=681",
            "--dpi-desync-split-pos=1",
            f"--dpi-desync-split-seqovl-pattern={tls}",
        ],
        "alt7": [
            "--dpi-desync=multisplit",
            "--dpi-desync-split-pos=2,sniext+1",
            "--dpi-desync-split-seqovl=679",
            f"--dpi-desync-split-seqovl-pattern={tls}",
        ],
        "alt8": [
            "--dpi-desync=fake",
            "--dpi-desync-fake-tls-mod=none",
            "--dpi-desync-repeats=6",
            "--dpi-desync-fooling=badseq",
            "--dpi-desync-badseq-increment=2",
            f"--dpi-desync-fake-http={http}",
        ],
        "alt9": [
            "--dpi-desync=hostfakesplit",
            "--dpi-desync-repeats=4",
            "--dpi-desync-fooling=ts",
            "--dpi-desync-hostfakesplit-mod=host=www.google.com",
        ],
        "alt10": [
            "--dpi-desync=fake",
            "--dpi-desync-repeats=6",
            "--dpi-desync-fooling=ts",
            f"--dpi-desync-fake-tls={tls}",
            "--dpi-desync-fake-tls-mod=none",
            f"--dpi-desync-fake-http={http}",
        ],
        "alt11": [
            "--dpi-desync=fake,multisplit",
            "--dpi-desync-split-seqovl=681",
            "--dpi-desync-split-pos=1",
            "--dpi-desync-fooling=ts",
            "--dpi-desync-repeats=8",
            f"--dpi-desync-split-seqovl-pattern={tls}",
            f"--dpi-desync-fake-tls={tls}",
        ],
        "alt12": [
            "--dpi-desync=fake,multisplit",
            "--dpi-desync-split-seqovl=664",
            "--dpi-desync-split-pos=1",
            "--dpi-desync-fooling=ts",
            "--dpi-desync-repeats=8",
            f"--dpi-desync-split-seqovl-pattern={http}",
            f"--dpi-desync-fake-tls={tls}",
        ],
        "exp": [
            "--dpi-desync=fake,multisplit",
            "--dpi-desync-split-seqovl=480",
            "--dpi-desync-split-pos=1",
            "--dpi-desync-fooling=ts",
            "--dpi-desync-repeats=8",
            f"--dpi-desync-split-seqovl-pattern={tls}",
            f"--dpi-desync-fake-tls={tls}",
        ],
        "fake_tls_auto": [
            "--dpi-desync=fake,multidisorder",
            "--dpi-desync-split-pos=1,midsld",
            "--dpi-desync-repeats=11",
            "--dpi-desync-fooling=badseq",
            "--dpi-desync-fake-tls=0x00000000",
            "--dpi-desync-fake-tls=!",
            "--dpi-desync-fake-tls-mod=rnd,dupsid,sni=www.google.com",
            f"--dpi-desync-fake-http={http}",
        ],
        "fake_tls_auto_alt": [
            "--dpi-desync=fake,fakedsplit",
            "--dpi-desync-split-pos=1",
            "--dpi-desync-fooling=badseq",
            "--dpi-desync-badseq-increment=2",
            "--dpi-desync-repeats=8",
            "--dpi-desync-fake-tls-mod=rnd,dupsid,sni=www.google.com",
            f"--dpi-desync-fake-http={http}",
        ],
        "fake_tls_auto_alt2": [
            "--dpi-desync=fake,multisplit",
            "--dpi-desync-split-seqovl=681",
            "--dpi-desync-split-pos=1",
            "--dpi-desync-fooling=badseq",
            "--dpi-desync-badseq-increment=10000000",
            "--dpi-desync-repeats=8",
            f"--dpi-desync-split-seqovl-pattern={tls}",
            "--dpi-desync-fake-tls-mod=rnd,dupsid,sni=www.google.com",
        ],
        "fake_tls_auto_alt3": [
            "--dpi-desync=fake,multisplit",
            "--dpi-desync-split-seqovl=681",
            "--dpi-desync-split-pos=1",
            "--dpi-desync-fooling=ts",
            "--dpi-desync-repeats=8",
            f"--dpi-desync-split-seqovl-pattern={tls}",
            "--dpi-desync-fake-tls-mod=rnd,dupsid,sni=www.google.com",
        ],
        "simple_fake": [
            "--dpi-desync=fake",
            "--dpi-desync-repeats=6",
            "--dpi-desync-fooling=ts",
            f"--dpi-desync-fake-tls={tls}",
            f"--dpi-desync-fake-http={http}",
        ],
        "simple_fake_alt": [
            "--dpi-desync=fake",
            "--dpi-desync-repeats=6",
            "--dpi-desync-fooling=badseq",
            "--dpi-desync-badseq-increment=2",
            f"--dpi-desync-fake-tls={tls}",
            f"--dpi-desync-fake-http={http}",
        ],
        "simple_fake_alt2": [
            "--dpi-desync=fake",
            "--dpi-desync-repeats=6",
            "--dpi-desync-fooling=ts",
            f"--dpi-desync-fake-tls={tls}",
            f"--dpi-desync-fake-http={http}",
        ],
        "goodbye9": [
            "--dpi-desync=fake,multisplit",
            "--dpi-desync-split-pos=2",
            "--dpi-desync-repeats=6",
            "--dpi-desync-fooling=badseq,badsum",
            "--dpi-desync-fake-tls=!",
            f"--dpi-desync-fake-http={http}",
        ],
        "goodbye5": [
            "--dpi-desync=fake,multisplit",
            "--dpi-desync-split-pos=2",
            "--dpi-desync-autottl",
            "--dpi-desync-fake-tls=!",
            f"--dpi-desync-fake-http={http}",
        ],
    }
    args = tricks.get(kind)
    if not args:
        raise RuntimeError(f"Неизвестный встроенный обход: {kind}")
    if youtube:
        return ["--ip-id=zero"] + args
    return list(args)


def _quic_repeats(kind: str) -> str:
    if kind in {
        "fake_tls_auto",
        "fake_tls_auto_alt",
        "fake_tls_auto_alt2",
        "fake_tls_auto_alt3",
        "alt11",
        "alt12",
        "exp",
        "goodbye9",
    }:
        return "11"
    return "6"


def winws_args_for(strategy: Strategy) -> list[str]:
    fakes = _fakes()
    youtube = _write_hosts("youtube.txt", HOSTS_YOUTUBE)
    discord = _write_hosts("discord.txt", HOSTS_DISCORD)
    cloudflare = _write_hosts("cloudflare.txt", HOSTS_CLOUDFLARE)
    general = _write_hosts(
        "general.txt", HOSTS_YOUTUBE + HOSTS_DISCORD + HOSTS_GOOGLE + HOSTS_CLOUDFLARE
    )
    kind = strategy.kind
    quic_n = _quic_repeats(kind)
    if kind == "exp":
        quic_block = [
            "--filter-l7=quic",
            f"--hostlist={youtube}",
            "--dpi-desync=fake",
            f"--dpi-desync-repeats={quic_n}",
            f"--dpi-desync-fake-quic={fakes['quic']}",
        ]
        discord_udp = [
            "--filter-udp=19294-19344,50000-50100",
            "--filter-l7=discord,stun,unknown",
            "--dpi-desync=fake",
            "--dpi-desync-any-protocol=1",
            f"--dpi-desync-fake-discord={fakes['quic']}",
            f"--dpi-desync-fake-discord={fakes['discord']}",
            f"--dpi-desync-fake-stun={fakes['discord']}",
            f"--dpi-desync-fake-unknown-udp={fakes['quic']}",
            f"--dpi-desync-fake-unknown-udp={fakes['discord']}",
            "--dpi-desync-repeats=6",
        ]
    else:
        quic_block = [
            "--filter-udp=443",
            f"--hostlist={youtube}",
            "--dpi-desync=fake",
            f"--dpi-desync-repeats={quic_n}",
            f"--dpi-desync-fake-quic={fakes['quic']}",
        ]
        discord_udp = [
            "--filter-udp=19294-19344,50000-50100",
            "--filter-l7=discord,stun",
            "--dpi-desync=fake",
            f"--dpi-desync-fake-discord={fakes['discord']}",
            f"--dpi-desync-fake-stun={fakes['discord']}",
            "--dpi-desync-repeats=6",
        ]
    return [
        str(winws_path()),
        "--wf-tcp=80,443,2053,2083,2087,2096,8443",
        "--wf-udp=443,19294-19344,50000-50100",
        *quic_block,
        "--new",
        *discord_udp,
        "--new",
        "--filter-tcp=2053,2083,2087,2096,8443",
        "--hostlist-domains=discord.media",
        *_https_trick(kind, fakes),
        "--new",
        "--filter-tcp=443",
        f"--hostlist={youtube}",
        *_https_trick(kind, fakes, youtube=True),
        "--new",
        "--filter-tcp=80,443",
        f"--hostlist={general}",
        *_https_trick(kind, fakes),
        "--new",
        "--filter-tcp=443",
        f"--hostlist={discord}",
        *_https_trick(kind, fakes),
        "--new",
        "--filter-tcp=443",
        f"--hostlist={cloudflare}",
        *_https_trick(kind, fakes),
    ]


def _probe_url(url: str) -> bool:
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        proc = subprocess.run(
            [
                "curl.exe",
                "-I",
                "-s",
                "-m",
                str(PROBE_TIMEOUT),
                "-o",
                "NUL",
                "-w",
                "%{http_code}",
                "--tlsv1.2",
                "--tls-max",
                "1.2",
                url,
            ],
            capture_output=True,
            startupinfo=startup,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        return _probe_url_fallback(url)
    code = _decode(proc.stdout or b"").strip()
    return bool(re.fullmatch(r"[1-5]\d{2}", code))


def _probe_url_fallback(url: str) -> bool:
    import ssl
    import urllib.request

    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Azimut/1.2"})
    try:
        with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT, context=ssl.create_default_context()) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Azimut/1.2"})
            with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT, context=ssl.create_default_context()) as response:
                return 200 <= int(response.status) < 500
        except Exception:
            return False


def probe_sites() -> ProbeResult:
    result = ProbeResult()
    with ThreadPoolExecutor(max_workers=len(PROBE_SITES)) as pool:
        order = [name for name, _url in PROBE_SITES]
        mapped = {name: pool.submit(_probe_url, url) for name, url in PROBE_SITES}
        for name in order:
            try:
                result.ok[name] = bool(mapped[name].result())
            except Exception:
                result.ok[name] = False
    return result


def _kill_our_winws() -> None:
    pid = _our_pid()
    if pid is not None:
        _hidden(["taskkill", "/PID", str(pid), "/F"])
    ours = winws_path().resolve().as_posix().lower()
    listing = _hidden(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process -Filter \"name='winws.exe'\" | "
            "ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.ExecutablePath }",
        ]
    )
    for line in listing.stdout.splitlines():
        if "|" not in line:
            continue
        pid_text, path = line.split("|", 1)
        if path.strip().replace("\\", "/").lower() == ours:
            _hidden(["taskkill", "/PID", pid_text.strip(), "/F"])
    pid_path().unlink(missing_ok=True)


def stop(force: bool = False) -> None:
    global _started_by_us, _active_strategy
    if not force and not _started_by_us and _our_pid() is None:
        return
    _kill_our_winws()
    _started_by_us = False
    _active_strategy = ""


def _ensure_engine() -> None:
    if not engine_ready():
        raise RuntimeError(
            "Антивирус или сбой диска убрал файлы обхода (winws или WinDivert). "
            "Добавьте всю папку Azimut в исключения антивируса и поставьте программу заново. "
            "Azimut не будет перебирать способы обхода, пока файлы не вернутся."
        )
    from .protect import verify_zapret_engine

    try:
        verify_zapret_engine()
    except RuntimeError as exc:
        raise RuntimeError(
            str(exc)
            + " Часто так делает антивирус. Добавьте папку Azimut в исключения "
            "и восстановите файлы из установщика."
        ) from exc


def start(strategy: str | None = None, replace: bool = False) -> str:
    global _started_by_us, _active_strategy
    chosen = find_strategy(strategy or "") or STRATEGIES[0]
    if is_running() and not replace and _active_strategy == chosen.id:
        return chosen.id
    _ensure_engine()
    stop(force=True)
    args = winws_args_for(chosen)
    log = logs_dir() / "zapret.log"
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    with open(log, "ab") as stream:
        try:
            proc = subprocess.Popen(
                args,
                cwd=str(bin_dir()),
                stdout=stream,
                stderr=stream,
                startupinfo=startup,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError as exc:
            if getattr(exc, "winerror", None) == 740:
                raise RuntimeError(
                    "Для обхода нужны права администратора. Закройте Azimut и откройте его снова — Windows спросит разрешение."
                ) from exc
            raise
    time.sleep(0.8)
    if proc.poll() is not None:
        details = log.read_text(encoding="utf-8", errors="replace")[-800:]
        raise RuntimeError(
            "Не удалось запустить обход Discord и YouTube. "
            "Часто антивирус удаляет драйвер WinDivert — добавьте папку программы Azimut в исключения.\n"
            + details
        )
    pid_path().write_text(str(proc.pid), encoding="utf-8")
    _started_by_us = True
    _active_strategy = chosen.id
    return chosen.id


def _try_strategy(item: Strategy, progress=None) -> ProbeResult:
    if progress:
        progress(f"Проверяю обход «{item.title}»…")
    start(item.id, replace=True)
    time.sleep(PROBE_WAIT)
    return probe_sites()


def pick_best(progress=None, preferred: str | None = None) -> PickResult:
    _ensure_engine()
    ordered = list(STRATEGIES)
    saved = find_strategy(preferred or "")
    if saved:
        ordered = [saved] + [item for item in ordered if item.id != saved.id]
    best: PickResult | None = None
    tried = 0
    last_error = None
    total = len(ordered)
    for item in ordered:
        tried += 1
        if progress:
            progress(f"Проверяю обход «{item.title}» ({tried} из {total})…")
        try:
            probe = _try_strategy(item, progress)
        except Exception as exc:
            last_error = exc
            continue
        candidate = PickResult(strategy=item.id, title=item.title, probe=probe, tried=tried)
        if best is None or probe.score > best.probe.score:
            best = candidate
        if probe.good_enough:
            if progress:
                progress(f"Подобрал обход «{item.title}». {probe.summary()}.")
            return candidate
    if best is None:
        detail = f" {last_error}" if last_error else ""
        raise RuntimeError("Не удалось запустить ни один встроенный обход." + detail)
    start(best.strategy, replace=True)
    if progress:
        progress(f"Лучший из проверенных: «{best.title}». {best.probe.summary()}.")
    best.tried = tried
    return best


def pick_for_cloudflare(progress=None, preferred: str | None = None) -> PickResult:
    from .warp import cloudflare_reachable

    _ensure_engine()
    ordered = list(STRATEGIES)
    saved = find_strategy(preferred or "")
    if saved:
        ordered = [saved] + [item for item in ordered if item.id != saved.id]
    last_error = None
    tried = 0
    total = len(ordered)
    for item in ordered:
        tried += 1
        if progress:
            progress(f"Проверяю обход «{item.title}» для адреса Cloudflare ({tried} из {total})…")
        try:
            start(item.id, replace=True)
            time.sleep(PROBE_WAIT)
        except Exception as exc:
            last_error = exc
            continue
        if cloudflare_reachable():
            if progress:
                progress(f"Обход «{item.title}» открывает служебный адрес Cloudflare.")
            probe = ProbeResult(ok={"Cloudflare": True})
            return PickResult(strategy=item.id, title=item.title, probe=probe, tried=tried)
    detail = f" {last_error}" if last_error else ""
    raise RuntimeError(
        "Ни один встроенный обход не открыл служебный адрес Cloudflare." + detail
        + " Добавьте папку Azimut в исключения антивируса и попробуйте ещё раз. "
        "Либо импортируйте готовый файл .conf."
    )


def start_and_probe(strategy: str | None = None, progress=None) -> PickResult:
    chosen = find_strategy(strategy or "") or STRATEGIES[0]
    if progress:
        progress(f"Включаю обход «{chosen.title}»…")
    start(chosen.id, replace=True)
    time.sleep(PROBE_WAIT)
    probe = probe_sites()
    if progress:
        progress(f"Обход «{chosen.title}». {probe.summary()}.")
    return PickResult(strategy=chosen.id, title=chosen.title, probe=probe, tried=1, reused=True)


def start_or_pick(saved: str | None = None, progress=None) -> PickResult:
    if find_strategy(saved or ""):
        return start_and_probe(saved, progress)
    return pick_best(progress=progress, preferred=saved)
