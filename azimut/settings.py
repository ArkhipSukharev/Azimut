from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields

from .paths import settings_path
from .secrets import load_github_token, migrate_github_token
from .sites import DEFAULT_SELECTED


@dataclass
class Settings:
    endpoint: str = "162.159.193.1:500"
    dns: str = "1.1.1.1, 1.0.0.1"
    mode: str = "split"
    exclude_youtube: bool = True
    autostart: bool = False
    autoconnect: bool = False
    minimize_to_tray: bool = True
    last_profile: str = ""
    selected_sites: list[str] = field(default_factory=lambda: list(DEFAULT_SELECTED))
    custom_sites: list[str] = field(default_factory=list)
    zapret_enabled: bool = True
    zapret_strategy: str = ""
    check_updates: bool = True
    github_repo: str = "ArkhipSukharev/Azimut"
    github_token: str = ""
    welcome_done: bool = False

    def save(self) -> None:
        payload = asdict(self)
        payload["github_token"] = ""
        settings_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> "Settings":
        path = settings_path()
        if not path.exists():
            data = cls()
            data.save()
            return data
        raw = json.loads(path.read_text(encoding="utf-8"))
        known = {item.name for item in fields(cls)}
        data = cls(**{key: value for key, value in raw.items() if key in known})
        if "selected_sites" not in raw:
            data.selected_sites = list(DEFAULT_SELECTED)
            if data.exclude_youtube is False and "youtube" not in data.selected_sites:
                data.selected_sites.append("youtube")
        leftover = str(raw.get("github_token") or "").strip()
        dirty = leftover or "selected_sites" not in raw
        if leftover:
            migrate_github_token(leftover)
        try:
            data.github_token = load_github_token()
        except Exception:
            data.github_token = ""
        if dirty:
            data.save()
        return data
