# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk

from . import APP_NAME, APP_VERSION
from .autostart import create_app_shortcut, create_desktop_shortcut, set_autostart
from .checker import SiteCheck, check_site
from .secrets import has_github_token, load_github_token, save_github_token
from .icon import create_icon
from .logger import read_log, write_log
from .paths import active_dir, app_root, desktop_dir, icon_path, is_frozen
from .profiles import (
    delete_profile,
    export_profile,
    find_profile,
    import_profile,
    list_profiles,
    new_warp_name,
    rename_profile,
    save_profile,
)
from .settings import Settings
from .sites import CATALOG, CATEGORIES, DEFAULT_SELECTED
from .split import apply_mode
from .tunnel import (
    azimut_running,
    connect_file,
    disconnect_all_azimut,
    is_admin,
    is_profile_running,
    restart_as_admin,
    restore_network,
)
from .warp import ENDPOINTS, create_warp_config, has_amnezia_params, is_generated_warp
from . import zapret as zapret_engine

BG = "#080C12"
SIDE = "#0A1118"
CARD = "#101820"
CARD2 = "#171F29"
LINE = "#2A3A4C"
TEXT = "#F4F8FC"
MUTED = "#8A9BB0"
ACCENT = "#4AA3FF"
OK = "#3DDC97"
BAD = "#FF6B7A"
WARN = "#F0B429"
INK = "#061018"


def _font(size: int, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)


class AzimutApp:
    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self.settings = Settings.load()
        self.status = tk.StringVar(value="Отключено")
        self.profile = tk.StringVar(value=self.settings.last_profile)
        self.mode = tk.StringVar(value=self.settings.mode)
        self.busy = False
        self.connected_since: float | None = None
        self.tray = None
        self.current_page = "home"
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        self.profile_names: list[str] = []
        self._initial_running = set(azimut_running())
        self._restored = False
        self._restarting = False
        self._zapret_busy = False
        self._zapret_combo_ready = False
        self._pending_release = None
        self._bypass_report = None
        self._sites_dirty = False
        self._notified_dead = False
        self._last_tunnel_error = ""
        self._rebuild_job = None
        self._health_ticks = 0
        self._app_ticks = 0
        self._engine_recheck_at = time.time() + 6 * 3600
        self._build()
        self.refresh_profiles()
        self.refresh_status()
        self._enforce_generated_warp_mode(silent=True)
        self._refresh_welcome()
        self._offer_first_import()
        self.root.after(400, self._boot_zapret)
        self.root.after(2500, self._check_updates_later)
        self.root.after(2000, self._tick)

    def _build(self) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.root.title(APP_NAME)
        self.root.geometry("1100x740")
        self.root.minsize(1000, 680)
        self.root.configure(fg_color=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        try:
            ico = icon_path()
            if not ico.exists():
                create_icon(ico)
            self.root.iconbitmap(str(ico))
        except Exception:
            pass

        shell = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        shell.pack(fill="both", expand=True)
        self.shell = shell

        nav = ctk.CTkFrame(shell, fg_color=SIDE, width=228, corner_radius=0)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)

        brand = ctk.CTkFrame(nav, fg_color="transparent")
        brand.pack(fill="x", padx=22, pady=(28, 20))
        ctk.CTkLabel(brand, text=APP_NAME, font=_font(26, "bold"), text_color=TEXT).pack(anchor="w")
        ctk.CTkFrame(brand, fg_color=ACCENT, height=3, width=42, corner_radius=2).pack(anchor="w", pady=(8, 8))
        ctk.CTkLabel(brand, text="тихий выход в сеть", font=_font(12), text_color=MUTED).pack(anchor="w")

        for key, title in [
            ("home", "Главная"),
            ("sites", "Сайты"),
            ("apps", "Программы"),
            ("profiles", "Профили"),
            ("check", "Проверка"),
            ("log", "Журнал"),
            ("settings", "Настройки"),
        ]:
            button = ctk.CTkButton(
                nav,
                text=title,
                font=_font(14),
                anchor="w",
                height=42,
                corner_radius=12,
                fg_color="transparent",
                hover_color=CARD,
                text_color=MUTED,
                command=lambda k=key: self.show(k),
            )
            button.pack(fill="x", padx=14, pady=3)
            self.nav_buttons[key] = button

        ctk.CTkLabel(nav, text=f"версия {APP_VERSION}", font=_font(11), text_color="#5B6B7C").pack(
            side="bottom", padx=22, pady=18, anchor="w"
        )

        self.body = ctk.CTkFrame(shell, fg_color=BG, corner_radius=0)
        self.body.pack(side="left", fill="both", expand=True, padx=28, pady=24)
        self.pages: dict[str, ctk.CTkFrame] = {}
        self._page_home()
        self._page_sites()
        self._page_apps()
        self._page_profiles()
        self._page_check()
        self._page_log()
        self._page_settings()
        self.show("home")
        self._build_wait_overlay()
        self._start_tray()

    def _page_home(self) -> None:
        page = ctk.CTkFrame(self.body, fg_color="transparent")
        self.pages["home"] = page

        self.update_bar = ctk.CTkFrame(page, fg_color="#152433", corner_radius=16, border_width=1, border_color=ACCENT)
        bar_inner = ctk.CTkFrame(self.update_bar, fg_color="transparent")
        bar_inner.pack(fill="x", padx=16, pady=12)
        self.update_label = ctk.CTkLabel(
            bar_inner,
            text="",
            font=_font(13),
            text_color=TEXT,
            anchor="w",
            justify="left",
        )
        self.update_label.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            bar_inner,
            text="Установить обновление",
            width=210,
            height=36,
            corner_radius=10,
            font=_font(13),
            command=self._install_update,
        ).pack(side="right", padx=(12, 0))

        self.welcome = ctk.CTkFrame(page, fg_color=CARD, corner_radius=20, border_width=1, border_color=LINE)
        welcome_inner = ctk.CTkFrame(self.welcome, fg_color="transparent")
        welcome_inner.pack(fill="x", padx=22, pady=18)
        ctk.CTkLabel(welcome_inner, text="С чего начать", font=_font(20, "bold"), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(
            welcome_inner,
            text="Можно сразу открыть YouTube и Discord без VPN. Или собрать свой туннель.",
            font=_font(13),
            text_color=MUTED,
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=(6, 12))
        welcome_row = ctk.CTkFrame(welcome_inner, fg_color="transparent")
        welcome_row.pack(anchor="w")
        ctk.CTkButton(
            welcome_row,
            text="Открыть YouTube и Discord",
            width=250,
            height=40,
            corner_radius=12,
            font=_font(13),
            command=self._welcome_bypass,
        ).pack(side="left")
        ctk.CTkButton(
            welcome_row,
            text="Свой туннель",
            width=180,
            height=40,
            corner_radius=12,
            fg_color=CARD2,
            hover_color=LINE,
            text_color=TEXT,
            font=_font(13),
            command=self._welcome_tunnel,
        ).pack(side="left", padx=(10, 0))

        hero = ctk.CTkFrame(page, fg_color=CARD, corner_radius=28)
        self.home_hero = hero
        hero.pack(fill="both", expand=True)
        inner = ctk.CTkFrame(hero, fg_color="transparent")
        inner.pack(expand=True, fill="both", padx=36, pady=20)

        self.power = ctk.CTkButton(
            inner,
            text="▶",
            width=168,
            height=168,
            corner_radius=84,
            font=_font(36, "bold"),
            fg_color=CARD2,
            hover_color="#1E2C3A",
            border_width=4,
            border_color=LINE,
            text_color=TEXT,
            command=self.toggle_connection,
        )
        self.power.pack(pady=(8, 14))

        self.status_label = ctk.CTkLabel(inner, textvariable=self.status, font=_font(24, "bold"), text_color=TEXT)
        self.status_label.pack()
        self.session_label = ctk.CTkLabel(inner, text="", font=_font(13), text_color=MUTED)
        self.session_label.pack(pady=(2, 8))
        self.tunnel_state = ctk.CTkLabel(inner, text="Туннель выключен", font=_font(13), text_color=MUTED)
        self.tunnel_state.pack()
        self.zapret_state = ctk.CTkLabel(inner, text="Обход выключен", font=_font(13), text_color=MUTED)
        self.zapret_state.pack(pady=(2, 20))

        self.profile_chip = ctk.CTkButton(
            inner,
            text="Профиль не выбран",
            width=260,
            height=40,
            corner_radius=20,
            font=_font(13),
            fg_color=CARD2,
            hover_color=LINE,
            text_color=TEXT,
            command=lambda: self.show("profiles"),
        )
        self.profile_chip.pack()

        modes = ctk.CTkFrame(inner, fg_color=CARD2, corner_radius=16)
        modes.pack(pady=(22, 0))
        self.split_btn = ctk.CTkButton(
            modes,
            text="Сайты и программы",
            width=168,
            height=36,
            corner_radius=12,
            font=_font(13),
            command=lambda: self._set_mode("split"),
        )
        self.split_btn.pack(side="left", padx=4, pady=4)
        self.full_btn = ctk.CTkButton(
            modes,
            text="Весь интернет",
            width=168,
            height=36,
            corner_radius=12,
            font=_font(13),
            command=lambda: self._set_mode("full"),
        )
        self.full_btn.pack(side="left", padx=4, pady=4)

        zapret_box = ctk.CTkFrame(inner, fg_color="transparent")
        zapret_box.pack(pady=(22, 0))
        zapret_row = ctk.CTkFrame(zapret_box, fg_color="transparent")
        zapret_row.pack()
        self.zapret_var = tk.BooleanVar(value=self.settings.zapret_enabled)
        ctk.CTkCheckBox(
            zapret_row,
            text="Обход YouTube и Discord",
            variable=self.zapret_var,
            font=_font(13),
            text_color=TEXT,
            fg_color=ACCENT,
            command=self._toggle_zapret,
        ).pack(side="left")
        ctk.CTkButton(
            zapret_row,
            text="Подобрать",
            width=110,
            height=30,
            corner_radius=10,
            fg_color=CARD2,
            hover_color=LINE,
            text_color=MUTED,
            font=_font(12),
            command=self._pick_zapret,
        ).pack(side="left", padx=(10, 0))
        ctk.CTkButton(
            zapret_row,
            text="Проверить обход",
            width=140,
            height=30,
            corner_radius=10,
            fg_color=CARD2,
            hover_color=LINE,
            text_color=MUTED,
            font=_font(12),
            command=self._check_bypass_now,
        ).pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            zapret_row,
            text="Вернуть прежний",
            width=140,
            height=30,
            corner_radius=10,
            fg_color=CARD2,
            hover_color=LINE,
            text_color=MUTED,
            font=_font(12),
            command=self._restore_bypass,
        ).pack(side="left", padx=(8, 0))

        pick_row = ctk.CTkFrame(zapret_box, fg_color="transparent")
        pick_row.pack(pady=(10, 0))
        ctk.CTkLabel(pick_row, text="Способ", font=_font(13), text_color=MUTED).pack(side="left", padx=(0, 8))
        titles = zapret_engine.strategy_titles()
        current_title = zapret_engine.strategy_title(self.settings.zapret_strategy)
        if current_title == "не выбран":
            current_title = titles[0]
        self.zapret_choice = tk.StringVar(value=current_title)
        self.zapret_combo = ctk.CTkComboBox(
            pick_row,
            variable=self.zapret_choice,
            values=titles,
            width=340,
            height=32,
            corner_radius=10,
            font=_font(13),
            fg_color=CARD2,
            border_color=LINE,
            button_color=LINE,
            dropdown_fg_color=CARD,
            dropdown_hover_color=LINE,
            command=self._on_zapret_strategy_chosen,
        )
        self.zapret_combo.pack(side="left")
        self._zapret_combo_ready = True

        self.zapret_info = ctk.CTkLabel(
            inner,
            text="",
            font=_font(12),
            text_color=MUTED,
            wraplength=640,
            justify="center",
            anchor="center",
        )
        self.zapret_info.pack(pady=(8, 0), padx=16, fill="x")
        self.home_info = ctk.CTkLabel(
            inner,
            text="",
            font=_font(12),
            text_color=MUTED,
            wraplength=640,
            justify="center",
            anchor="center",
        )
        self.home_info.pack(padx=16, fill="x")
        self.close_hint = ctk.CTkLabel(
            inner,
            text="",
            font=_font(12),
            text_color=MUTED,
            wraplength=640,
            justify="center",
            anchor="center",
        )
        self.close_hint.pack(padx=16, pady=(4, 0), fill="x")
        self._paint_mode_buttons()
        self._update_close_hint()

    def _page_sites(self) -> None:
        page = ctk.CTkFrame(self.body, fg_color="transparent")
        self.pages["sites"] = page
        top = ctk.CTkFrame(page, fg_color="transparent")
        top.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(top, text="Сайты через туннель", font=_font(26, "bold"), text_color=TEXT).pack(side="left")
        ctk.CTkLabel(
            page,
            text="Отметьте сервисы, которые должны идти через VPN в режиме «Сайты и программы». Программы выбираются на соседней странице. На WARP, который создал Azimut, этот список не действует: такой профиль всегда пускает весь интернет. Discord и YouTube при включённом обходе идут напрямую, без туннеля. Если туннель уже включён, список применится сам.",
            font=_font(13),
            text_color=MUTED,
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))

        tools = ctk.CTkFrame(page, fg_color="transparent")
        tools.pack(fill="x", pady=(0, 8))
        self.sites_search = ctk.CTkEntry(
            tools,
            placeholder_text="Поиск по названию",
            height=38,
            corner_radius=10,
            font=_font(13),
            fg_color=CARD,
            border_color=LINE,
            width=280,
        )
        self.sites_search.pack(side="left")
        self.sites_search.bind("<KeyRelease>", lambda _event: self._render_sites())
        for title, command in [
            ("Частые", self._sites_preset_default),
            ("Все", self._sites_select_all),
            ("Снять все", self._sites_select_none),
        ]:
            ctk.CTkButton(
                tools,
                text=title,
                width=90,
                height=36,
                corner_radius=10,
                fg_color=CARD,
                hover_color=CARD2,
                text_color=TEXT,
                font=_font(12),
                command=command,
            ).pack(side="left", padx=(8, 0))

        self.site_vars = {
            site.id: tk.BooleanVar(value=site.id in set(self.settings.selected_sites)) for site in CATALOG
        }
        self.apply_sites_bar = ctk.CTkFrame(page, fg_color="#152433", corner_radius=14, border_width=1, border_color=ACCENT)
        apply_inner = ctk.CTkFrame(self.apply_sites_bar, fg_color="transparent")
        apply_inner.pack(fill="x", padx=14, pady=10)
        ctk.CTkLabel(
            apply_inner,
            text="Список изменён. Туннель сейчас сам пересоберёт маршруты. Если не пересобрался — нажмите кнопку.",
            font=_font(13),
            text_color=TEXT,
            wraplength=520,
            justify="left",
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            apply_inner,
            text="Применить сейчас",
            width=170,
            height=34,
            corner_radius=10,
            font=_font(13),
            command=self._apply_sites_now,
        ).pack(side="right", padx=(10, 0))

        self.sites_list = ctk.CTkScrollableFrame(page, fg_color=CARD, corner_radius=20)
        self.sites_list.pack(fill="both", expand=True)

        custom_box = ctk.CTkFrame(page, fg_color=CARD, corner_radius=16)
        custom_box.pack(fill="x", pady=(10, 0))
        inner = ctk.CTkFrame(custom_box, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)
        ctk.CTkLabel(inner, text="Свой адрес сайта", font=_font(13, "bold"), text_color=TEXT).pack(anchor="w")
        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x", pady=(8, 6))
        self.custom_entry = ctk.CTkEntry(
            row,
            placeholder_text="например rutracker.org",
            height=38,
            corner_radius=10,
            font=_font(13),
            fg_color=CARD2,
            border_color=LINE,
        )
        self.custom_entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row, text="Добавить", width=110, height=38, corner_radius=10, font=_font(13), command=self._add_custom_site).pack(
            side="left", padx=(8, 0)
        )
        self.custom_list = ctk.CTkFrame(inner, fg_color="transparent")
        self.custom_list.pack(fill="x")
        self._render_sites()
        self._render_custom_sites()

    def _page_apps(self) -> None:
        page = ctk.CTkFrame(self.body, fg_color="transparent")
        self.pages["apps"] = page
        top = ctk.CTkFrame(page, fg_color="transparent")
        top.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(top, text="Программы через туннель", font=_font(26, "bold"), text_color=TEXT).pack(side="left")
        ctk.CTkLabel(
            page,
            text="Выберите программы, чей интернет должен идти через VPN в режиме «Сайты и программы». Azimut смотрит, к каким адресам подключается выбранная программа, запоминает их и пускает через туннель. Первые секунды после добавления новой программы адреса ещё могут идти напрямую, затем список догоняет. Системные программы Windows сюда лучше не добавлять.",
            font=_font(13),
            text_color=MUTED,
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))
        tools = ctk.CTkFrame(page, fg_color="transparent")
        tools.pack(fill="x", pady=(0, 10))
        ctk.CTkButton(
            tools,
            text="Добавить файл программы",
            width=220,
            height=36,
            corner_radius=10,
            font=_font(13),
            command=self._add_app_file,
        ).pack(side="left")
        ctk.CTkButton(
            tools,
            text="Из запущенных",
            width=150,
            height=36,
            corner_radius=10,
            fg_color=CARD,
            hover_color=CARD2,
            text_color=TEXT,
            font=_font(13),
            command=self._add_running_app,
        ).pack(side="left", padx=(8, 0))
        self.apps_info = ctk.CTkLabel(page, text="", font=_font(12), text_color=MUTED, wraplength=760, justify="left")
        self.apps_info.pack(anchor="w", pady=(0, 8))
        self.apps_list = ctk.CTkScrollableFrame(page, fg_color=CARD, corner_radius=20)
        self.apps_list.pack(fill="both", expand=True)
        self._render_apps()

    def _page_profiles(self) -> None:
        page = ctk.CTkFrame(self.body, fg_color="transparent")
        self.pages["profiles"] = page
        top = ctk.CTkFrame(page, fg_color="transparent")
        top.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(top, text="Профили", font=_font(26, "bold"), text_color=TEXT).pack(side="left")
        actions = ctk.CTkFrame(top, fg_color="transparent")
        actions.pack(side="right")
        for title, cmd in [
            ("Создать WARP", self.create_warp),
            ("Импорт", self.import_cfg),
            ("Экспорт", self.export_cfg),
            ("Переименовать", self.rename_cfg),
            ("Удалить", self.delete_cfg),
        ]:
            primary = title == "Создать WARP"
            ctk.CTkButton(
                actions,
                text=title,
                width=0,
                height=38,
                corner_radius=10,
                fg_color=ACCENT if primary else CARD,
                hover_color="#6BB4FF" if primary else CARD2,
                text_color=INK if primary else TEXT,
                font=_font(12, "bold" if primary else "normal"),
                command=cmd,
            ).pack(side="left", padx=4)

        self.profile_list = ctk.CTkScrollableFrame(page, fg_color=CARD, corner_radius=20)
        self.profile_list.pack(fill="both", expand=True)

    def _page_check(self) -> None:
        page = ctk.CTkFrame(self.body, fg_color="transparent")
        self.pages["check"] = page
        ctk.CTkLabel(page, text="Проверка сайтов", font=_font(26, "bold"), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(
            page,
            text="Показывает, должен ли сайт идти через туннель по списку маршрутов и открывается ли он сейчас именно через туннель, а не просто с компьютера.",
            font=_font(13),
            text_color=MUTED,
        ).pack(anchor="w", pady=(4, 16))
        row = ctk.CTkFrame(page, fg_color="transparent")
        row.pack(fill="x")
        self.check_entry = ctk.CTkEntry(
            row,
            placeholder_text="instagram.com",
            height=42,
            corner_radius=12,
            font=_font(14),
            fg_color=CARD,
            border_color=LINE,
        )
        self.check_entry.pack(side="left", fill="x", expand=True)
        self.check_entry.insert(0, "instagram.com")
        ctk.CTkButton(row, text="Проверить", width=130, height=42, corner_radius=12, font=_font(13), command=self.check_one).pack(
            side="left", padx=8
        )
        ctk.CTkButton(
            row,
            text="Набор сайтов",
            width=140,
            height=42,
            corner_radius=12,
            fg_color=CARD,
            hover_color=CARD2,
            text_color=TEXT,
            font=_font(13),
            command=self.check_set,
        ).pack(side="left")
        self.check_out = ctk.CTkTextbox(page, fg_color=CARD, corner_radius=18, font=_font(13), text_color=TEXT)
        self.check_out.pack(fill="both", expand=True, pady=(16, 0))

    def _page_log(self) -> None:
        page = ctk.CTkFrame(self.body, fg_color="transparent")
        self.pages["log"] = page
        top = ctk.CTkFrame(page, fg_color="transparent")
        top.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(top, text="Журнал", font=_font(26, "bold"), text_color=TEXT).pack(side="left")
        ctk.CTkButton(
            top,
            text="Обновить",
            width=110,
            height=36,
            corner_radius=10,
            fg_color=CARD,
            hover_color=CARD2,
            text_color=TEXT,
            command=self.reload_log,
        ).pack(side="right")
        self.log_view = ctk.CTkTextbox(page, fg_color=CARD, corner_radius=18, font=_font(13), text_color=MUTED)
        self.log_view.pack(fill="both", expand=True)

    def _page_settings(self) -> None:
        page = ctk.CTkFrame(self.body, fg_color="transparent")
        self.pages["settings"] = page
        ctk.CTkLabel(page, text="Настройки", font=_font(26, "bold"), text_color=TEXT).pack(anchor="w", pady=(0, 16))
        scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        card = ctk.CTkFrame(scroll, fg_color=CARD, corner_radius=20)
        card.pack(fill="x")
        box = ctk.CTkFrame(card, fg_color="transparent")
        box.pack(fill="x", padx=24, pady=22)

        ctk.CTkLabel(box, text="Сервер для новых WARP-профилей", font=_font(13), text_color=MUTED).pack(anchor="w")
        self.endpoint_var = tk.StringVar(value=self.settings.endpoint)
        ctk.CTkComboBox(box, variable=self.endpoint_var, values=ENDPOINTS, width=460, height=40, corner_radius=10, font=_font(13)).pack(
            anchor="w", pady=(6, 14)
        )
        ctk.CTkLabel(box, text="Адреса для запросов имён сайтов", font=_font(13), text_color=MUTED).pack(anchor="w")
        self.dns_var = tk.StringVar(value=self.settings.dns)
        ctk.CTkEntry(box, textvariable=self.dns_var, width=460, height=40, corner_radius=10, font=_font(13)).pack(anchor="w", pady=(6, 16))

        self.autostart_var = tk.BooleanVar(value=self.settings.autostart)
        self.autoconnect_var = tk.BooleanVar(value=self.settings.autoconnect)
        self.tray_var = tk.BooleanVar(value=self.settings.minimize_to_tray)
        for text, var in [
            ("Запускать вместе с Windows", self.autostart_var),
            ("Подключать последний профиль при запуске", self.autoconnect_var),
            ("Сворачивать в значок у часов, а не закрывать", self.tray_var),
        ]:
            ctk.CTkCheckBox(box, text=text, variable=var, font=_font(13), text_color=TEXT, fg_color=ACCENT).pack(anchor="w", pady=5)

        self.updates_var = tk.BooleanVar(value=self.settings.check_updates)
        ctk.CTkCheckBox(
            box,
            text="Проверять обновления в закрытом GitHub",
            variable=self.updates_var,
            font=_font(13),
            text_color=TEXT,
            fg_color=ACCENT,
        ).pack(anchor="w", pady=(14, 5))
        ctk.CTkLabel(box, text="Репозиторий GitHub, имя/проект", font=_font(13), text_color=MUTED).pack(anchor="w", pady=(8, 0))
        self.github_repo_var = tk.StringVar(value=self.settings.github_repo)
        ctk.CTkEntry(box, textvariable=self.github_repo_var, width=460, height=40, corner_radius=10, font=_font(13)).pack(
            anchor="w", pady=(6, 10)
        )
        self.github_token_hint = ctk.CTkLabel(
            box,
            text="",
            font=_font(12),
            text_color=MUTED,
            wraplength=640,
            justify="left",
        )
        self.github_token_hint.pack(anchor="w")
        self.github_token_var = tk.StringVar(value="")
        ctk.CTkEntry(
            box,
            textvariable=self.github_token_var,
            width=460,
            height=40,
            corner_radius=10,
            font=_font(13),
            show="•",
            placeholder_text="вставьте новый токен, если нужно заменить",
        ).pack(anchor="w", pady=(6, 16))
        self._refresh_token_hint()

        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(anchor="w", pady=(18, 0))
        ctk.CTkButton(row, text="Сохранить", width=140, height=40, corner_radius=12, command=self.save_settings).pack(side="left")
        ctk.CTkButton(
            row,
            text="Ярлык на рабочий стол",
            width=190,
            height=40,
            corner_radius=12,
            fg_color=CARD2,
            hover_color=LINE,
            text_color=TEXT,
            command=self.make_shortcut,
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            row,
            text="Обновить адреса выбранных сайтов",
            width=190,
            height=40,
            corner_radius=12,
            fg_color=CARD2,
            hover_color=LINE,
            text_color=TEXT,
            command=self.refresh_split,
        ).pack(side="left")
        ctk.CTkButton(
            row,
            text="Проверить файлы обхода",
            width=190,
            height=40,
            corner_radius=12,
            fg_color=CARD2,
            hover_color=LINE,
            text_color=TEXT,
            command=self._diagnose_files,
        ).pack(side="left", padx=8)
        ctk.CTkLabel(
            page,
            text=(
                f"{APP_NAME} шифрует ключи туннелей для этого пользователя Windows "
                "(защита Windows и AES-256-GCM), проверяет целостность движка и ограничивает доступ к своей папке. "
                "Пароль при запуске не нужен. Файл vault.azimut на другом компьютере или под другой учётной записью не откроется."
            ),
            font=_font(12),
            text_color=MUTED,
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=16)

    def show(self, name: str) -> None:
        self.current_page = name
        for page in self.pages.values():
            page.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        for key, button in self.nav_buttons.items():
            if key == name:
                button.configure(fg_color=CARD, text_color=TEXT, hover_color=CARD)
            else:
                button.configure(fg_color="transparent", text_color=MUTED, hover_color=CARD)
        if name == "log":
            self.reload_log()
        if name == "profiles":
            self.refresh_profiles()
        if name == "sites":
            self._render_sites()
            self._render_custom_sites()
        if name == "apps":
            self._render_apps()

    def _set_mode(self, mode: str, silent: bool = False) -> None:
        if mode == "split" and self._current_is_generated_warp():
            if not silent:
                messagebox.showinfo(
                    APP_NAME,
                    "Для WARP, который создал Azimut, режим «Сайты и программы» недоступен. "
                    "Такой профиль всегда пускает весь интернет через туннель. "
                    "Списки на страницах «Сайты» и «Программы» на него не действуют. "
                    "Режим «Сайты и программы» остаётся только для импортированных конфигов.",
                )
            mode = "full"
        self.mode.set(mode)
        self._save_mode()
        self._paint_mode_buttons()
        self._update_home_info()
        if azimut_running() and not silent:
            self._schedule_tunnel_rebuild("сменился режим туннеля")

    def _paint_mode_buttons(self) -> None:
        forbidden = self._current_is_generated_warp()
        if forbidden:
            self.split_btn.configure(
                state="disabled",
                fg_color=CARD2,
                text_color="#5B6B7C",
                hover_color=CARD2,
            )
            self.full_btn.configure(
                state="normal",
                fg_color=ACCENT,
                text_color=INK,
                hover_color="#6BB4FF",
            )
            return
        self.split_btn.configure(state="normal")
        self.full_btn.configure(state="normal")
        if self.mode.get() == "split":
            self.split_btn.configure(fg_color=ACCENT, text_color=INK, hover_color="#6BB4FF")
            self.full_btn.configure(fg_color=CARD2, text_color=TEXT, hover_color=LINE)
        else:
            self.full_btn.configure(fg_color=ACCENT, text_color=INK, hover_color="#6BB4FF")
            self.split_btn.configure(fg_color=CARD2, text_color=TEXT, hover_color=LINE)

    def _paint_power(self, connected: bool) -> None:
        if connected:
            self.power.configure(text="●", fg_color="#123528", hover_color="#164433", border_color=OK, text_color=OK)
            self.status_label.configure(text_color=OK)
        else:
            self.power.configure(text="▶", fg_color=CARD2, hover_color="#1E2C3A", border_color=LINE, text_color=TEXT)
            self.status_label.configure(text_color=TEXT)

    def toggle_connection(self) -> None:
        if azimut_running():
            self.disconnect()
        else:
            self.connect()

    def _offer_first_import(self) -> None:
        if list_profiles():
            return
        desktop = desktop_dir()
        if not desktop.exists():
            return
        found = [item for item in desktop.glob("*.conf") if "warp" in item.name.lower() or "config" in item.name.lower()]
        if not found:
            return
        if not messagebox.askyesno(
            APP_NAME,
            f"На рабочем столе есть {len(found)} конфиг(ов). Добавить их в хранилище профилей Azimut?",
        ):
            return
        for item in found:
            try:
                import_profile(item)
            except Exception:
                continue
        self.refresh_profiles()
        write_log(f"Импортировано с рабочего стола: {len(found)}")

    def _save_mode(self) -> None:
        self.settings.mode = self.mode.get()
        self.settings.exclude_youtube = "youtube" not in self.settings.selected_sites
        self.settings.save()

    def _selected_site_ids(self) -> list[str]:
        return [site.id for site in CATALOG if self.site_vars[site.id].get()]

    def _app_ip_list(self) -> list[str]:
        from .apps import networks_for_apps

        return [str(net) for net in networks_for_apps(self.settings.selected_apps)]

    def _split_can_rebuild(self) -> bool:
        return bool(azimut_running() and self.mode.get() == "split" and not self._current_is_generated_warp())

    def _schedule_tunnel_rebuild(self, reason: str) -> None:
        if not self._split_can_rebuild() and not (
            azimut_running() and self.mode.get() == "full" and "режим" in reason
        ):
            return
        if self._rebuild_job is not None:
            try:
                self.root.after_cancel(self._rebuild_job)
            except Exception:
                pass
        self._sites_dirty = True
        self._update_apply_sites_bar()
        self._rebuild_job = self.root.after(1600, lambda: self._rebuild_tunnel(reason))

    def _rebuild_tunnel(self, reason: str) -> None:
        self._rebuild_job = None
        if not azimut_running() or self.busy:
            return
        write_log(f"Пересобираю туннель: {reason}")
        self._sites_dirty = False
        self._update_apply_sites_bar()
        self.connect()

    def _save_sites(self) -> None:
        self.settings.selected_sites = self._selected_site_ids()
        self.settings.exclude_youtube = "youtube" not in self.settings.selected_sites
        self.settings.save()
        if self._split_can_rebuild():
            self._schedule_tunnel_rebuild("изменился список сайтов")
        self._update_apply_sites_bar()
        self._update_home_info()

    def _render_sites(self) -> None:
        query = self.sites_search.get().strip().lower() if hasattr(self, "sites_search") else ""
        for child in self.sites_list.winfo_children():
            child.destroy()
        for category in CATEGORIES:
            items = [site for site in CATALOG if site.category == category]
            if query:
                items = [
                    site
                    for site in items
                    if query in site.title.lower() or query in site.id or any(query in domain for domain in site.domains)
                ]
            if not items:
                continue
            ctk.CTkLabel(self.sites_list, text=category, font=_font(14, "bold"), text_color=ACCENT).pack(
                anchor="w", padx=16, pady=(14, 6)
            )
            grid = ctk.CTkFrame(self.sites_list, fg_color="transparent")
            grid.pack(fill="x", padx=12)
            for index, site in enumerate(items):
                cell = ctk.CTkFrame(grid, fg_color=CARD2, corner_radius=12)
                cell.grid(row=index // 2, column=index % 2, sticky="nsew", padx=6, pady=6)
                grid.grid_columnconfigure(0, weight=1)
                grid.grid_columnconfigure(1, weight=1)
                box = ctk.CTkCheckBox(
                    cell,
                    text=site.title,
                    variable=self.site_vars[site.id],
                    font=_font(14),
                    text_color=TEXT,
                    fg_color=ACCENT,
                    command=self._save_sites,
                )
                box.pack(anchor="w", padx=14, pady=(10, 4 if site.note else 10))
                if site.note:
                    ctk.CTkLabel(cell, text=site.note, font=_font(11), text_color=MUTED, wraplength=320, justify="left").pack(
                        anchor="w", padx=14, pady=(0, 10)
                    )

    def _render_custom_sites(self) -> None:
        for child in self.custom_list.winfo_children():
            child.destroy()
        if not self.settings.custom_sites:
            ctk.CTkLabel(self.custom_list, text="Своих адресов пока нет", font=_font(12), text_color=MUTED).pack(anchor="w")
            return
        for domain in self.settings.custom_sites:
            row = ctk.CTkFrame(self.custom_list, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=domain, font=_font(13), text_color=TEXT).pack(side="left")
            ctk.CTkButton(
                row,
                text="Убрать",
                width=80,
                height=28,
                corner_radius=8,
                fg_color=CARD2,
                hover_color=LINE,
                text_color=TEXT,
                font=_font(12),
                command=lambda item=domain: self._remove_custom_site(item),
            ).pack(side="right")

    def _sites_preset_default(self) -> None:
        chosen = set(DEFAULT_SELECTED)
        for site_id, var in self.site_vars.items():
            var.set(site_id in chosen)
        self._save_sites()
        self._render_sites()

    def _sites_select_all(self) -> None:
        for var in self.site_vars.values():
            var.set(True)
        self._save_sites()
        self._render_sites()

    def _sites_select_none(self) -> None:
        for var in self.site_vars.values():
            var.set(False)
        self._save_sites()
        self._render_sites()

    def _add_custom_site(self) -> None:
        raw = self.custom_entry.get().strip().lower()
        raw = raw.replace("http://", "").replace("https://", "").split("/")[0].split(":")[0]
        if raw.startswith("www."):
            raw = raw[4:]
        if not raw or "." not in raw or " " in raw:
            messagebox.showinfo(APP_NAME, "Введите обычный адрес сайта, например instagram.com")
            return
        if raw not in self.settings.custom_sites:
            self.settings.custom_sites.append(raw)
            self.settings.save()
        if self._split_can_rebuild():
            self._schedule_tunnel_rebuild("добавлен свой сайт")
        self.custom_entry.delete(0, "end")
        self._render_custom_sites()
        self._update_apply_sites_bar()
        self._update_home_info()
        write_log(f"Добавлен свой сайт в туннель: {raw}")

    def _remove_custom_site(self, domain: str) -> None:
        self.settings.custom_sites = [item for item in self.settings.custom_sites if item != domain]
        self.settings.save()
        if self._split_can_rebuild():
            self._schedule_tunnel_rebuild("убран свой сайт")
        self._render_custom_sites()
        self._update_apply_sites_bar()
        self._update_home_info()

    def _render_apps(self) -> None:
        if not hasattr(self, "apps_list"):
            return
        from .apps import display_name, load_learned

        for child in self.apps_list.winfo_children():
            child.destroy()
        learned = load_learned()
        apps = list(self.settings.selected_apps)
        if hasattr(self, "apps_info"):
            if apps:
                self.apps_info.configure(
                    text=f"Выбрано программ: {len(apps)}. Адреса подтягиваются, пока программа в сети."
                )
            else:
                self.apps_info.configure(text="Пока ни одна программа не выбрана.")
        if not apps:
            ctk.CTkLabel(
                self.apps_list,
                text="Добавьте Telegram, браузер или другую программу — её адреса пойдут в туннель вместе с выбранными сайтами.",
                font=_font(13),
                text_color=MUTED,
                wraplength=680,
                justify="left",
            ).pack(anchor="w", padx=18, pady=18)
            return
        for path in apps:
            card = ctk.CTkFrame(self.apps_list, fg_color=CARD2, corner_radius=14)
            card.pack(fill="x", padx=12, pady=6)
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=14, pady=12)
            ctk.CTkLabel(inner, text=display_name(path), font=_font(15, "bold"), text_color=TEXT).pack(anchor="w")
            count = len(learned.get(path) or [])
            ctk.CTkLabel(
                inner,
                text=f"{path}\nзапомнено адресов: {count}",
                font=_font(12),
                text_color=MUTED,
                justify="left",
            ).pack(anchor="w", pady=(4, 0))
            ctk.CTkButton(
                inner,
                text="Убрать",
                width=90,
                height=30,
                corner_radius=8,
                fg_color=CARD,
                hover_color=LINE,
                text_color=TEXT,
                font=_font(12),
                command=lambda item=path: self._remove_app(item),
            ).pack(anchor="w", pady=(8, 0))

    def _save_apps(self) -> None:
        self.settings.save()
        self._render_apps()
        if self._split_can_rebuild():
            self._schedule_tunnel_rebuild("изменился список программ")
        self._update_home_info()

    def _add_app_file(self) -> None:
        from .apps import normalize_app_path

        source = filedialog.askopenfilename(filetypes=[("Программы", "*.exe"), ("Все файлы", "*.*")])
        if not source:
            return
        path = normalize_app_path(source)
        if not path:
            return
        if path not in self.settings.selected_apps:
            self.settings.selected_apps.append(path)
        self._save_apps()
        write_log(f"В туннель добавлена программа: {path}")

    def _add_running_app(self) -> None:
        from .apps import list_running_apps

        running = list_running_apps()
        if not running:
            messagebox.showinfo(APP_NAME, "Сейчас нет подходящих запущенных программ.")
            return
        picker = tk.Toplevel(self.root)
        picker.title("Запущенные программы")
        picker.configure(bg=BG)
        picker.geometry("640x420")
        picker.transient(self.root)
        box = ctk.CTkScrollableFrame(picker, fg_color=CARD, corner_radius=12)
        box.pack(fill="both", expand=True, padx=16, pady=16)
        for path, name in running:
            ctk.CTkButton(
                box,
                text=f"{name}\n{path}",
                anchor="w",
                height=52,
                corner_radius=10,
                fg_color=CARD2,
                hover_color=LINE,
                text_color=TEXT,
                font=_font(13),
                command=lambda item=path: self._pick_running_app(picker, item),
            ).pack(fill="x", pady=4)

    def _pick_running_app(self, window, path: str) -> None:
        from .apps import normalize_app_path

        chosen = normalize_app_path(path)
        try:
            window.destroy()
        except Exception:
            pass
        if not chosen:
            return
        if chosen not in self.settings.selected_apps:
            self.settings.selected_apps.append(chosen)
        self._save_apps()
        write_log(f"В туннель добавлена запущенная программа: {chosen}")

    def _remove_app(self, path: str) -> None:
        self.settings.selected_apps = [item for item in self.settings.selected_apps if item != path]
        self._save_apps()

    def _prepared_config(self, text: str, name: str = "", source: str = "", force_split: bool = False) -> str:
        if is_generated_warp(text, name, source):
            return text
        if self.mode.get() == "full" and has_amnezia_params(text):
            return text
        return apply_mode(
            text,
            self.mode.get(),
            self.settings.dns,
            self.settings.selected_sites,
            self.settings.custom_sites,
            zapret_enabled=bool(self.settings.zapret_enabled),
            force=force_split,
            extra_ips=self._app_ip_list(),
        )

    def _zapret_status_text(self) -> str:
        if not self.settings.zapret_enabled:
            return ""
        title = zapret_engine.strategy_title(self.settings.zapret_strategy)
        if self.settings.zapret_strategy:
            return f"Включён обход «{title}»"
        return "Включён обход"

    def _set_zapret_combo(self, title: str) -> None:
        if not hasattr(self, "zapret_combo") or not title or title == "не выбран":
            return
        self._zapret_combo_ready = False
        self.zapret_choice.set(title)
        try:
            self.zapret_combo.set(title)
        except Exception:
            pass
        self.root.after(80, lambda: setattr(self, "_zapret_combo_ready", True))

    def _zapret_combo_fallback(self) -> str:
        title = zapret_engine.strategy_title(self.settings.zapret_strategy)
        if title == "не выбран":
            return zapret_engine.strategy_titles()[0]
        return title

    def _on_zapret_strategy_chosen(self, title: str) -> None:
        if not self._zapret_combo_ready:
            return
        strategy_id = zapret_engine.strategy_id_for_title(title)
        if not strategy_id:
            return
        if strategy_id == self.settings.zapret_strategy and self.settings.zapret_enabled and zapret_engine.is_running():
            return
        if self._zapret_busy:
            self._set_zapret_combo(self._zapret_combo_fallback())
            messagebox.showinfo(APP_NAME, "Сейчас уже меняется обход. Подождите несколько секунд.")
            return
        if azimut_running() and self.mode.get() == "full":
            self._set_zapret_combo(self._zapret_combo_fallback())
            messagebox.showwarning(
                APP_NAME,
                "Сначала выключите туннель или включите режим «Сайты и программы». "
                "Иначе проверка не отличит обход от VPN.",
            )
            return
        self.zapret_var.set(True)
        self.settings.zapret_enabled = True
        self.settings.zapret_strategy = strategy_id
        self.settings.save()
        self._start_zapret_job(force_pick=False, chosen=strategy_id)

    def _show_zapret_result(self, result) -> None:
        self._set_zapret_combo(result.title)
        extra = result.probe.display()
        if result.probe.good_enough:
            text = f"Включён обход «{result.title}».\n{extra}"
        else:
            text = f"Включён обход «{result.title}»: сайты открываются не все.\n{extra}"
        if self._bypass_report and getattr(self._bypass_report, "rolled_back", False):
            text = "Новая версия обхода хуже открывала сайты, поэтому возвращена прежняя.\n" + text
        self.zapret_info.configure(text=text)
        self._refresh_engine_states()

    def _maybe_autoconnect(self) -> None:
        if self.settings.autoconnect and self.profile.get() and not azimut_running():
            self.connect()

    def _set_zapret_progress(self, message: str) -> None:
        if hasattr(self, "zapret_info"):
            self.zapret_info.configure(text=message)
        if hasattr(self, "zapret_state"):
            self.zapret_state.configure(text=message)

    def _start_zapret_job(self, force_pick: bool = False, then_connect: bool = False, chosen: str | None = None) -> None:
        if self._zapret_busy:
            messagebox.showinfo(APP_NAME, "Сейчас уже подбирается обход. Подождите, это занимает две-три минуты.")
            return
        self._zapret_busy = True
        self._refresh_engine_states()
        if force_pick:
            self._set_zapret_progress("Подбираю обход…")
        else:
            title = zapret_engine.strategy_title(chosen or self.settings.zapret_strategy)
            if title == "не выбран":
                title = zapret_engine.strategy_titles()[0]
            self._set_zapret_progress(f"Включаю обход «{title}»")

        def runner():
            error = None
            result = None
            started = ""
            try:
                def progress(message: str) -> None:
                    self.root.after(0, lambda text=message: self._set_zapret_progress(text))

                if force_pick:
                    result = zapret_engine.pick_best(progress=progress, preferred=self.settings.zapret_strategy)
                else:
                    started = zapret_engine.start(chosen or self.settings.zapret_strategy)
                report = self._bypass_report
                if (
                    result
                    and not result.probe.good_enough
                    and report
                    and (report.zapret_updated or report.goodbyedpi_updated)
                ):
                    from .bypass_update import has_backup, restore_backup

                    if has_backup():
                        progress("Новая версия обхода хуже прежней. Возвращаю рабочую копию…")
                        if restore_backup():
                            report.rolled_back = True
                            report.zapret_updated = False
                            report.goodbyedpi_updated = False
                            started = zapret_engine.start(self.settings.zapret_strategy)
                            result = None
            except Exception as exc:
                error = exc

            def finish():
                self._zapret_busy = False
                self._refresh_engine_states()
                if not self.settings.zapret_enabled:
                    zapret_engine.stop(force=True)
                    self.zapret_info.configure(text=self._zapret_status_text())
                    self._update_home_info()
                    if then_connect:
                        self._maybe_autoconnect()
                    return
                if error:
                    write_log(f"Не удалось включить обход: {error}")
                    self.zapret_var.set(False)
                    self.settings.zapret_enabled = False
                    self.settings.save()
                    self.zapret_info.configure(text=str(error))
                    messagebox.showerror(APP_NAME, str(error))
                elif result:
                    self.settings.zapret_strategy = result.strategy
                    self.settings.save()
                    self._show_zapret_result(result)
                    write_log(f"Обход «{result.title}»: {result.probe.summary()}")
                elif started:
                    self.settings.zapret_strategy = started
                    self.settings.save()
                    title = zapret_engine.strategy_title(started)
                    self._set_zapret_combo(title)
                    self.zapret_info.configure(text=f"Включён обход «{title}»")
                    write_log(f"Включён обход «{title}»")
                self._update_home_info()
                self._refresh_engine_states()
                if then_connect:
                    self._maybe_autoconnect()

            self.root.after(0, finish)

        threading.Thread(target=runner, daemon=True).start()

    def _boot_zapret(self) -> None:
        self._set_zapret_progress("Проверяю версии обхода…")

        def runner():
            report = None
            error = None
            try:
                from .bypass_update import ensure_latest

                def progress(message: str) -> None:
                    self.root.after(0, lambda text=message: self._set_zapret_progress(text))

                report = ensure_latest(self.settings.github_token, progress=progress)
            except Exception as exc:
                error = exc

            def finish():
                if error:
                    write_log(f"Проверка zapret и GoodbyeDPI: {error}")
                    self.zapret_info.configure(text=f"Не удалось проверить версии обхода: {error}")
                elif report:
                    self._bypass_report = report
                    write_log(report.summary())
                    self.zapret_info.configure(text=report.summary())
                if self.settings.zapret_enabled:
                    self._start_zapret_job(force_pick=False, then_connect=True)
                else:
                    self._maybe_autoconnect()

            self.root.after(0, finish)

        threading.Thread(target=runner, daemon=True).start()

    def _pick_zapret(self) -> None:
        if not self.settings.zapret_enabled:
            self.zapret_var.set(True)
            self.settings.zapret_enabled = True
            self.settings.save()
        if azimut_running() and self.mode.get() == "full":
            messagebox.showwarning(
                APP_NAME,
                "Сначала выключите туннель или включите режим «Сайты и программы». "
                "Иначе проверка не отличит обход от VPN.",
            )
            return
        self._start_zapret_job(force_pick=True)

    def _toggle_zapret(self) -> None:
        enabled = bool(self.zapret_var.get())
        self.settings.zapret_enabled = enabled
        self.settings.save()
        if not enabled:
            zapret_engine.stop(force=True)
            self.zapret_info.configure(text=self._zapret_status_text())
            write_log("Обход Discord и YouTube выключен")
            self._update_home_info()
            if self._split_can_rebuild() or azimut_running():
                self._schedule_tunnel_rebuild("обход выключен")
            return
        self._start_zapret_job(force_pick=False)
        if self._split_can_rebuild() or azimut_running():
            self._schedule_tunnel_rebuild("обход включён")

    def _check_bypass_now(self) -> None:
        if self._zapret_busy or self.busy:
            messagebox.showinfo(APP_NAME, "Сейчас уже идёт другая операция. Подождите несколько секунд.")
            return
        self._set_zapret_progress("Проверяю версии обхода…")

        def runner():
            report = None
            error = None
            try:
                from .bypass_update import ensure_latest

                def progress(message: str) -> None:
                    self.root.after(0, lambda text=message: self._set_zapret_progress(text))

                report = ensure_latest(self.settings.github_token, progress=progress)
            except Exception as exc:
                error = exc

            def finish():
                if error:
                    write_log(f"Ручная проверка обхода: {error}")
                    self.zapret_info.configure(text=f"Не удалось проверить версии обхода: {error}")
                    messagebox.showerror(APP_NAME, str(error))
                    return
                if report:
                    self._bypass_report = report
                    write_log(report.summary())
                    self.zapret_info.configure(text=report.summary())
                if self.settings.zapret_enabled:
                    self.zapret_var.set(True)
                    self._start_zapret_job(force_pick=False)
                else:
                    messagebox.showinfo(APP_NAME, report.summary() if report else "Проверка обхода завершена.")

            self.root.after(0, finish)

        threading.Thread(target=runner, daemon=True).start()

    def _restore_bypass(self) -> None:
        from .bypass_update import has_backup, restore_backup

        if not has_backup():
            messagebox.showinfo(APP_NAME, "Сохранённой прежней версии обхода пока нет. Она появится после первого обновления zapret или GoodbyeDPI.")
            return
        if not messagebox.askyesno(APP_NAME, "Вернуть предыдущие файлы zapret и GoodbyeDPI?"):
            return

        def work():
            if not restore_backup():
                raise RuntimeError("Не удалось вернуть прежние файлы обхода.")
            return True

        def done(_ok):
            write_log("Возвращена прежняя версия обхода")
            if self.settings.zapret_enabled:
                self._start_zapret_job(force_pick=False)
            else:
                messagebox.showinfo(APP_NAME, "Прежние файлы обхода возвращены.")

        self._run_bg(work, done, wait_title="Возвращаю обход", wait_text="Копирую сохранённые файлы на место.")

    def _diagnose_files(self) -> None:
        from .diagnose import inspect

        report = inspect()
        messagebox.showinfo(APP_NAME, report.summary())
        write_log(report.summary())

    def _check_updates_later(self) -> None:
        if not self.settings.check_updates or not self.settings.github_repo.strip():
            return

        def work():
            from .updater import check_for_update

            return check_for_update(self.settings.github_repo, self.settings.github_token)

        def runner():
            error = None
            result = None
            try:
                result = work()
            except Exception as exc:
                error = exc

            def finish():
                if error:
                    write_log(f"Проверка обновлений: {error}")
                    return
                if not result:
                    return
                self._pending_release = result
                self.update_label.configure(
                    text=f"Доступна версия {result.version}. Сейчас стоит {APP_VERSION}."
                )
                self.update_bar.pack(fill="x", pady=(0, 14), before=self.home_hero)
                write_log(f"Найдено обновление {result.version}")

            self.root.after(0, finish)

        threading.Thread(target=runner, daemon=True).start()

    def _install_update(self) -> None:
        release = self._pending_release
        if not release:
            return
        if not messagebox.askyesno(
            APP_NAME,
            f"Установить обновление {release.version}? Azimut закроется и откроется уже новой версией. "
            "Ваши профили и настройки не затираются.",
        ):
            return

        def work():
            from .updater import apply_update

            try:
                disconnect_all_azimut()
            except Exception:
                pass
            try:
                zapret_engine.stop(force=True)
            except Exception:
                pass
            return apply_update(self.settings.github_repo, self.settings.github_token, release)

        def done(mode):
            write_log(f"Установка обновления {release.version}, режим {mode}")
            if mode == "installer":
                messagebox.showinfo(APP_NAME, "Открылся установщик. Дойдите до конца, затем снова откройте Azimut.")
            self._quit()

        self._run_bg(work, done, wait_title="Обновление", wait_text="Скачиваю файлы. Не закрывайте окно.")

    def save_settings(self) -> None:
        self.settings.endpoint = self.endpoint_var.get()
        self.settings.dns = self.dns_var.get()
        self.settings.autostart = bool(self.autostart_var.get())
        self.settings.autoconnect = bool(self.autoconnect_var.get())
        self.settings.minimize_to_tray = bool(self.tray_var.get())
        self.settings.check_updates = bool(self.updates_var.get())
        self.settings.github_repo = self.github_repo_var.get().strip()
        typed_token = self.github_token_var.get().strip()
        if typed_token:
            save_github_token(typed_token)
            self.settings.github_token = typed_token
            self.github_token_var.set("")
        else:
            self.settings.github_token = load_github_token()
        self.settings.save()
        self._refresh_token_hint()
        self._update_close_hint()
        try:
            set_autostart(self.settings.autostart)
        except Exception as exc:
            self.autostart_var.set(False)
            self.settings.autostart = False
            self.settings.save()
            messagebox.showerror(APP_NAME, f"Автозапуск не включён.\n\n{exc}")
            return
        write_log("Настройки сохранены")
        messagebox.showinfo(APP_NAME, "Настройки сохранены.")

    def make_shortcut(self) -> None:
        try:
            create_app_shortcut()
            path = create_desktop_shortcut()
            messagebox.showinfo(APP_NAME, f"Ярлык на рабочем столе: {path}")
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def refresh_profiles(self) -> None:
        for child in self.profile_list.winfo_children():
            child.destroy()
        self.profile_names = []
        running = {item.name for item in list_profiles() if is_profile_running(item.name)}
        items = list_profiles()
        if not items:
            empty = ctk.CTkFrame(self.profile_list, fg_color=CARD2, corner_radius=16)
            empty.pack(fill="x", padx=16, pady=18)
            ctk.CTkLabel(
                empty,
                text="Профилей пока нет",
                font=_font(16, "bold"),
                text_color=TEXT,
            ).pack(anchor="w", padx=18, pady=(16, 6))
            ctk.CTkLabel(
                empty,
                text="Нажмите «Создать WARP» — на экране появится ожидание, пока программа дойдёт до Cloudflare. Это может занять до минуты, это не зависание.\n\nЕсли есть готовый файл .conf — кнопка «Импорт».",
                font=_font(13),
                text_color=MUTED,
                wraplength=640,
                justify="left",
            ).pack(anchor="w", padx=18, pady=(0, 16))
        for item in items:
            self.profile_names.append(item.name)
            selected = item.name == self.profile.get()
            live = item.name in running
            card = ctk.CTkButton(
                self.profile_list,
                text=f"{'●  ' if live else '○  '}{item.name}\n{item.kind}{'  ·  сейчас в сети' if live else ''}",
                anchor="w",
                height=64,
                corner_radius=14,
                font=_font(14),
                fg_color=ACCENT if selected else CARD2,
                text_color="#061018" if selected else TEXT,
                hover_color="#7BB8FF" if selected else LINE,
                command=lambda n=item.name: self._select_profile(n),
            )
            card.pack(fill="x", padx=10, pady=6)
        if self.profile_names and not self.profile.get():
            self.profile.set(self.profile_names[0])
            self.settings.last_profile = self.profile_names[0]
            self.settings.save()
        self._update_home_info()
        self._refresh_welcome()

    def _select_profile(self, name: str, drop_tunnel: bool = True) -> None:
        previous = self.profile.get()
        if previous == name:
            self.settings.last_profile = name
            self.settings.save()
            self.refresh_profiles()
            self._enforce_generated_warp_mode(silent=True)
            return
        if self.busy:
            messagebox.showinfo(APP_NAME, "Подождите, сейчас выполняется другая операция.")
            return
        live = bool(azimut_running())
        if drop_tunnel and live and not self._need_admin():
            return
        self.profile.set(name)
        self.settings.last_profile = name
        self.settings.save()
        self._enforce_generated_warp_mode(silent=True)
        if drop_tunnel and live:
            self._drop_active_tunnels(
                f"Выбран профиль {name}. Прежний туннель выключен, новый нужно включить кнопкой."
            )
            return
        self.refresh_profiles()

    def _drop_active_tunnels(self, message: str) -> None:
        def work():
            return disconnect_all_azimut()

        def done(stopped):
            self.connected_since = None
            write_log(message)
            self.refresh_status()
            self.refresh_profiles()
            self.home_info.configure(text="Туннель выключен. Новый профиль нужно включить кнопкой.")

        self._run_bg(work, done)

    def _current_is_generated_warp(self) -> bool:
        profile = find_profile(self.profile.get()) if self.profile.get() else None
        if not profile:
            return False
        return is_generated_warp(profile.text, profile.name, profile.source)

    def _enforce_generated_warp_mode(self, silent: bool = True) -> None:
        if self._current_is_generated_warp() and self.mode.get() != "full":
            self._set_mode("full", silent=silent)
        else:
            self._paint_mode_buttons()
            self._update_home_info()

    def _update_home_info(self) -> None:
        name = self.profile.get() or "Профиль не выбран"
        if hasattr(self, "profile_chip"):
            self.profile_chip.configure(text=name)
        if not hasattr(self, "home_info"):
            return
        profile = find_profile(self.profile.get()) if self.profile.get() else None
        if profile and is_generated_warp(profile.text, profile.name, profile.source):
            self.home_info.configure(
                text="Этот WARP создан Azimut: весь интернет идёт через туннель. Режим «Сайты и программы» для него выключен."
            )
        elif profile and self.mode.get() == "split" and "0.0.0.0/0" in profile.text:
            self.home_info.configure(
                text="Режим «Сайты и программы» подменяет маршруты из файла. Для конфига из Amnezia WG нажмите «Весь интернет»."
            )
        elif self.mode.get() == "split":
            sites = len(self.settings.selected_sites) + len(self.settings.custom_sites)
            apps = len(self.settings.selected_apps)
            self.home_info.configure(text=f"Через туннель: сайтов {sites}, программ {apps}.")
        else:
            self.home_info.configure(text="")

    def _need_admin(self) -> bool:
        if is_admin():
            return True
        if messagebox.askyesno(APP_NAME, "Для подключения нужны права администратора. Перезапустить программу?"):
            self._restarting = True
            restart_as_admin()
            self.root.destroy()
        return False

    def _build_wait_overlay(self) -> None:
        self.wait_overlay = ctk.CTkFrame(self.shell, fg_color="#05080C")
        box = ctk.CTkFrame(self.wait_overlay, fg_color=CARD, corner_radius=24, border_width=1, border_color=LINE)
        box.place(relx=0.5, rely=0.5, anchor="center")
        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.pack(padx=42, pady=36)
        self.wait_title = ctk.CTkLabel(inner, text="", font=_font(22, "bold"), text_color=TEXT)
        self.wait_title.pack()
        self.wait_detail = ctk.CTkLabel(
            inner,
            text="",
            font=_font(14),
            text_color=MUTED,
            wraplength=440,
            justify="center",
        )
        self.wait_detail.pack(pady=(10, 18))
        self.wait_bar = ctk.CTkProgressBar(
            inner,
            width=340,
            height=8,
            corner_radius=8,
            progress_color=ACCENT,
            fg_color=CARD2,
        )
        self.wait_bar.pack()
        try:
            self.wait_bar.configure(mode="indeterminate")
        except Exception:
            pass

    def _show_wait(self, title: str, detail: str = "") -> None:
        self.wait_title.configure(text=title)
        self.wait_detail.configure(text=detail)
        self.wait_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.wait_overlay.lift()
        try:
            self.wait_bar.start()
        except Exception:
            self.wait_bar.set(0.18)
        self.root.update_idletasks()

    def _set_wait(self, title: str | None = None, detail: str | None = None) -> None:
        if title:
            self.wait_title.configure(text=title)
        if detail is not None:
            self.wait_detail.configure(text=detail)

    def _hide_wait(self) -> None:
        try:
            self.wait_bar.stop()
        except Exception:
            pass
        self.wait_overlay.place_forget()

    def _run_bg(self, work, done=None, wait_title: str = "", wait_text: str = "") -> None:
        if self.busy:
            messagebox.showinfo(APP_NAME, "Подождите, сейчас выполняется другая операция.")
            return
        self.busy = True
        if wait_title:
            self._show_wait(wait_title, wait_text)

        def runner():
            error = None
            result = None
            try:
                result = work()
            except Exception as exc:
                error = exc

            def finish():
                self.busy = False
                self._hide_wait()
                if error:
                    text = str(error)
                    if "рукопожатие" in text.lower() or "не ответил" in text.lower():
                        self._last_tunnel_error = text
                        self.status.set("Сервер не ответил")
                    write_log(f"Ошибка: {error}")
                    self._refresh_engine_states()
                    messagebox.showerror(APP_NAME, text)
                elif done:
                    done(result)

            self.root.after(0, finish)

        threading.Thread(target=runner, daemon=True).start()

    def create_warp(self) -> None:
        wanted_zapret = bool(self.settings.zapret_enabled)

        def work():
            endpoint = self.endpoint_var.get().strip() or self.settings.endpoint
            saved = self.settings.zapret_strategy

            def progress(message: str) -> None:
                self.root.after(0, lambda text=message: self._set_wait(detail=text))

            if wanted_zapret:
                self.root.after(
                    0,
                    lambda: self._set_wait(detail="Подбираю обход именно для адреса Cloudflare. Это может занять пару минут…"),
                )
                picked = zapret_engine.pick_for_cloudflare(progress=progress, preferred=saved)
                self.settings.zapret_strategy = picked.strategy
                self.settings.save()
                time.sleep(1.0)
            self.root.after(0, lambda: self._set_wait(detail="Запрашиваю профиль у Cloudflare. Подождите, это не зависание…"))
            try:
                text = create_warp_config(endpoint, self.settings.dns)
            except Exception as exc:
                if not wanted_zapret:
                    zapret_engine.stop(force=True)
                raise RuntimeError(
                    "Служебный адрес Cloudflare всё ещё не открывается. "
                    "На новом компьютере часто мешает антивирус: добавьте всю папку Azimut в исключения "
                    "и создайте WARP ещё раз. Либо импортируйте готовый файл .conf кнопкой «Импорт»."
                ) from exc
            active = zapret_engine.active_strategy()
            if active:
                self.settings.zapret_strategy = active
            if not wanted_zapret:
                zapret_engine.stop(force=True)
                self.settings.zapret_enabled = False
            else:
                self.settings.zapret_enabled = True
            self.settings.save()
            return text

        def done(text):
            profile = save_profile(new_warp_name(), text, source="warp")
            self._select_profile(profile.name)
            self._set_mode("full", silent=True)
            self.zapret_var.set(wanted_zapret)
            if hasattr(self, "zapret_info"):
                title = zapret_engine.strategy_title(self.settings.zapret_strategy)
                self._set_zapret_combo(title)
                self.zapret_info.configure(text=self._zapret_status_text())
            self._refresh_engine_states()
            self._refresh_welcome()
            write_log(f"Создан профиль {profile.name}")
            messagebox.showinfo(APP_NAME, f"Профиль создан: {profile.name}")

        self._run_bg(
            work,
            done,
            wait_title="Создаю WARP",
            wait_text="Сразу после нажатия идёт работа в фоне. Полоска внизу значит, что программа не зависла.",
        )

    def import_cfg(self) -> None:
        source = filedialog.askopenfilename(filetypes=[("Конфиги", "*.conf"), ("Все файлы", "*.*")])
        if not source:
            return
        profile = import_profile(Path(source))
        self._select_profile(profile.name)
        if self.mode.get() != "full":
            self._set_mode("full")
        self._refresh_welcome()
        write_log(f"Импортирован {profile.name}")
        messagebox.showinfo(
            APP_NAME,
            "Конфиг сохранён как есть — без подмены маршрутов и без добавления чужой маскировки. "
            "Включён режим «Весь интернет», как в Amnezia WG. "
            "Если потом включить «Сайты и программы», Azimut вырежет AllowedIPs из файла и подставит свой список.",
        )

    def export_cfg(self) -> None:
        name = self.profile.get()
        if not name:
            return
        dest = filedialog.asksaveasfilename(defaultextension=".conf", initialfile=f"{name}.conf")
        if not dest:
            return
        if not messagebox.askyesno(
            APP_NAME,
            "Файл будет сохранён обычным текстом, без шифрования хранилища. Продолжить?",
        ):
            return
        export_profile(name, Path(dest))
        write_log(f"Экспортирован {name}")

    def rename_cfg(self) -> None:
        name = self.profile.get()
        if not name:
            return
        new_name = simpledialog.askstring(APP_NAME, "Новое имя профиля:", initialvalue=name)
        if not new_name:
            return
        profile = rename_profile(name, new_name)
        self._select_profile(profile.name, drop_tunnel=False)

    def delete_cfg(self) -> None:
        name = self.profile.get()
        if not name or not messagebox.askyesno(APP_NAME, f"Удалить профиль {name}?"):
            return
        try:
            disconnect_all_azimut()
        except Exception:
            pass
        delete_profile(name)
        self.profile.set("")
        self.refresh_profiles()
        write_log(f"Удалён профиль {name}")

    def connect(self) -> None:
        if not self._need_admin():
            return
        name = self.profile.get()
        profile = find_profile(name)
        if not profile:
            messagebox.showinfo(APP_NAME, "Сначала выберите или создайте профиль.")
            return
        if is_generated_warp(profile.text, profile.name, profile.source):
            self._set_mode("full", silent=True)
        self._last_tunnel_error = ""
        self.status.set("Подключаю")
        self._paint_power(False)
        self._refresh_engine_states()

        def work():
            from .warp import harden_config

            force_split = self.mode.get() == "split"
            prepared = harden_config(
                self._prepared_config(profile.text, profile.name, profile.source, force_split=force_split)
            )
            return connect_file(active_dir() / f"{profile.name}.conf", prepared)

        def done(tunnel_name):
            self.connected_since = time.time()
            self._sites_dirty = False
            self._notified_dead = False
            self._update_apply_sites_bar()
            write_log(f"Подключено: {tunnel_name}, режим {self.mode.get()}")
            self.refresh_status()

        self._run_bg(
            work,
            done,
            wait_title="Подключаю",
            wait_text="Жду ответ сервера. Если сервер молчит, обычный интернет сразу вернётся.",
        )

    def disconnect(self) -> None:
        if not self._need_admin():
            return

        def work():
            return disconnect_all_azimut()

        def done(stopped):
            self.connected_since = None
            write_log("Отключено: " + (", ".join(stopped) if stopped else "активных туннелей не было"))
            self.refresh_status()
            self.refresh_profiles()

        self._run_bg(work, done)

    def refresh_split(self) -> None:
        def work():
            from .split import allowed_ips_text

            return allowed_ips_text(
                self.settings.selected_sites,
                self.settings.custom_sites,
                force=True,
                zapret_enabled=bool(self.settings.zapret_enabled),
                extra_ips=self._app_ip_list(),
            )

        def done(text):
            write_log("Список адресов выбранных сайтов обновлён")
            messagebox.showinfo(APP_NAME, f"Список обновлён, сетей: {text.count('AllowedIPs')}")

        self._run_bg(work, done)

    def _current_config_text(self) -> str:
        profile = find_profile(self.profile.get())
        if not profile:
            raise RuntimeError("Профиль не выбран.")
        return self._prepared_config(profile.text, profile.name, profile.source)

    def check_one(self) -> None:
        host = self.check_entry.get().strip()
        if not host:
            return

        def work():
            return check_site(host, self._current_config_text(), probe=True)

        def done(result: SiteCheck):
            self.check_out.delete("1.0", "end")
            color = OK if result.reachable else MUTED
            self.check_out.insert(
                "1.0",
                f"{host}\nпо списку маршрутов: {result.route}\nсейчас по сети: {result.reachable_text}\n{', '.join(result.ips)}",
            )
            self.check_out.configure(text_color=color)

        self._run_bg(work, done, wait_title="Проверяю", wait_text=host)

    def check_set(self) -> None:
        hosts = []
        seen = set()
        for site in CATALOG:
            if site.id in self.settings.selected_sites and site.domains:
                host = site.domains[0]
                if host not in seen:
                    seen.add(host)
                    hosts.append(host)
        for domain in self.settings.custom_sites:
            if domain not in seen:
                seen.add(domain)
                hosts.append(domain)
        for host in ["youtube.com", "google.com", "yandex.ru", "vk.com", "gosuslugi.ru"]:
            if host not in seen:
                seen.add(host)
                hosts.append(host)
        def work():
            config = self._current_config_text()
            lines = []
            for host in hosts:
                try:
                    result = check_site(host, config, probe=True)
                    mark = "●" if result.reachable else "○"
                    lines.append(
                        f"{mark}  {host:<22} список:{result.route:<14} сейчас:{result.reachable_text:<28} {', '.join(result.ips)}"
                    )
                except Exception as exc:
                    lines.append(f"!  {host:<22} ошибка           {exc}")
            return "\n".join(lines)

        def done(text: str):
            self.check_out.delete("1.0", "end")
            self.check_out.insert("1.0", text)
            self.check_out.configure(text_color=TEXT)

        self._run_bg(work, done, wait_title="Проверяю набор", wait_text="Смотрю маршрут и доступность сайтов.")

    def reload_log(self) -> None:
        self.log_view.delete("1.0", "end")
        self.log_view.insert("1.0", read_log())

    def refresh_status(self) -> None:
        running = azimut_running()
        if running:
            self.status.set("Подключено")
            self._last_tunnel_error = ""
            if self.connected_since is None:
                self.connected_since = time.time()
            self._paint_power(True)
        elif self.status.get() in {"Подключаю", "Сервер не ответил", "Туннель оборвался"}:
            self._paint_power(False)
        elif self._last_tunnel_error:
            self.status.set("Сервер не ответил")
            self.connected_since = None
            self.session_label.configure(text="")
            self._paint_power(False)
        else:
            self.status.set("Отключено")
            self.connected_since = None
            self.session_label.configure(text="")
            self._paint_power(False)
        self._update_home_info()
        self._refresh_engine_states()
        self._update_apply_sites_bar()

    def _tick(self) -> None:
        if self.connected_since:
            seconds = int(time.time() - self.connected_since)
            hours, rem = divmod(seconds, 3600)
            minutes, secs = divmod(rem, 60)
            self.session_label.configure(text=f"В сети  {hours:02}:{minutes:02}:{secs:02}")
        running = azimut_running()
        if self.connected_since and not running and not self.busy:
            if not self._notified_dead:
                self._notified_dead = True
                self.connected_since = None
                write_log("Служба туннеля остановилась сама")
                try:
                    restore_network()
                except Exception as exc:
                    write_log(f"Не удалось подчистить туннель после обрыва: {exc}")
                self.status.set("Туннель оборвался")
                self._paint_power(False)
                messagebox.showwarning(
                    APP_NAME,
                    "Служба туннеля остановилась сама. Обычный интернет возвращён.",
                )
        elif running:
            self._notified_dead = False
        self._app_ticks += 1
        if self._app_ticks >= 3:
            self._app_ticks = 0
            self._watch_selected_apps()
        self._health_ticks += 1
        if self._health_ticks >= 45:
            self._health_ticks = 0
            self._health_check_bypass()
        if time.time() >= self._engine_recheck_at:
            self._engine_recheck_at = time.time() + 6 * 3600
            self._recheck_engines_quiet()
        self.refresh_status()
        self.root.after(4000, self._tick)

    def _watch_selected_apps(self) -> None:
        if not self.settings.selected_apps or not self._split_can_rebuild() or self.busy:
            return

        def runner():
            from .apps import remember_live_ips

            try:
                added = remember_live_ips(self.settings.selected_apps)
            except Exception as exc:
                write_log(f"Не удалось посмотреть адреса программ: {exc}")
                return
            if added:
                write_log(f"У выбранных программ появились новые адреса: {len(added)}")
                self.root.after(0, lambda: self._schedule_tunnel_rebuild("новые адреса программ"))
                self.root.after(0, self._render_apps)

        threading.Thread(target=runner, daemon=True).start()

    def _health_check_bypass(self) -> None:
        if not self.settings.zapret_enabled or self._zapret_busy or self.busy:
            return
        if azimut_running() and self.mode.get() == "full":
            return
        if not zapret_engine.is_running():
            return

        def runner():
            try:
                probe = zapret_engine.probe_sites()
            except Exception as exc:
                write_log(f"Проверка живого обхода не удалась: {exc}")
                return
            if probe.good_enough:
                return
            write_log(f"Обход перестал открывать сайты: {probe.summary()}. Подбираю другой способ.")
            self.root.after(0, lambda: self._start_zapret_job(force_pick=True))

        threading.Thread(target=runner, daemon=True).start()

    def _recheck_engines_quiet(self) -> None:
        if self._zapret_busy or self.busy:
            return

        def runner():
            try:
                from .bypass_update import ensure_latest

                report = ensure_latest(self.settings.github_token)
            except Exception as exc:
                write_log(f"Повторная проверка версий обхода: {exc}")
                return

            def finish():
                self._bypass_report = report
                write_log(report.summary())
                if report.zapret_updated or report.goodbyedpi_updated:
                    self.zapret_info.configure(text=report.summary())
                    if self.settings.zapret_enabled:
                        self._start_zapret_job(force_pick=False)

            self.root.after(0, finish)

        threading.Thread(target=runner, daemon=True).start()

    def _start_tray(self) -> None:
        try:
            import pystray
            from PIL import Image

            image = Image.open(icon_path().with_suffix(".png")) if icon_path().with_suffix(".png").exists() else Image.open(icon_path())
            menu = pystray.Menu(
                pystray.MenuItem("Открыть", self._show_window, default=True),
                pystray.MenuItem("Подключить", lambda: self.root.after(0, self.connect)),
                pystray.MenuItem("Отключить", lambda: self.root.after(0, self.disconnect)),
                pystray.MenuItem("Выход", self._quit),
            )
            self.tray = pystray.Icon("Azimut", image, APP_NAME, menu)
            threading.Thread(target=self.tray.run, daemon=True).start()
        except Exception as exc:
            self.tray = None
            write_log(f"Значок у часов не запустился: {exc}")
            if hasattr(self, "close_hint"):
                self.close_hint.configure(
                    text="Значок у часов не запустился. Закрытие окна выключит сеть. Перезапустите программу."
                )

    def _show_window(self, *_args) -> None:
        self.root.after(0, lambda: (self.root.deiconify(), self.root.lift()))

    def restore_network(self) -> None:
        if self._restored or self._restarting:
            return
        self._restored = True
        try:
            stopped = restore_network(self._initial_running)
            try:
                zapret_engine.stop()
            except Exception:
                pass
            try:
                from .vault import lock

                lock()
            except Exception:
                pass
            if stopped:
                write_log("При выходе сеть возвращена: отключены " + ", ".join(stopped))
            else:
                write_log("При выходе сеть уже была в исходном состоянии")
        except Exception as exc:
            write_log(f"Не удалось вернуть сеть при выходе: {exc}")

    def on_close(self) -> None:
        if self.settings.minimize_to_tray and self.tray is not None:
            self.root.withdraw()
            return
        self._quit()

    def _network_active(self) -> bool:
        try:
            return bool(azimut_running() or zapret_engine.is_running())
        except Exception:
            return bool(azimut_running())

    def _confirm_quit(self) -> bool:
        if not self._network_active():
            return True
        return bool(
            messagebox.askyesno(
                APP_NAME,
                "Туннель или обход ещё работают. Выйти и вернуть обычный интернет?",
            )
        )

    def _quit(self, *_args) -> None:
        if not self._confirm_quit():
            return
        self.restore_network()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.after(0, self.root.destroy)

    def _refresh_welcome(self) -> None:
        if not hasattr(self, "welcome"):
            return
        show = not self.settings.welcome_done and not list_profiles()
        if show:
            self.welcome.pack(fill="x", pady=(0, 14), before=self.home_hero)
        else:
            self.welcome.pack_forget()

    def _welcome_bypass(self) -> None:
        self.settings.welcome_done = True
        self.settings.zapret_enabled = True
        self.settings.save()
        self.zapret_var.set(True)
        self._refresh_welcome()
        self._start_zapret_job(force_pick=False)

    def _welcome_tunnel(self) -> None:
        self.settings.welcome_done = True
        self.settings.save()
        self._refresh_welcome()
        self.show("profiles")

    def _refresh_token_hint(self) -> None:
        if not hasattr(self, "github_token_hint"):
            return
        if has_github_token():
            self.github_token_hint.configure(
                text="Токен GitHub сохранён под защитой Windows на этом компьютере. "
                "Поле ниже оставьте пустым, чтобы оставить прежний токен. "
                "Чтобы заменить — вставьте новый."
            )
        else:
            self.github_token_hint.configure(
                text="Личный токен GitHub только на чтение. Он хранится под защитой Windows, "
                "в открытый файл настроек не попадает и на GitHub из программы не уходит."
            )

    def _update_close_hint(self) -> None:
        if not hasattr(self, "close_hint"):
            return
        if self.settings.minimize_to_tray:
            self.close_hint.configure(text="Закрытие окна не выключает сеть — программа остаётся у часов.")
        else:
            self.close_hint.configure(text="Закрытие окна выключает туннель и обход.")

    def _refresh_engine_states(self) -> None:
        if hasattr(self, "tunnel_state"):
            if self.status.get() == "Подключаю":
                self.tunnel_state.configure(text="Туннель подключается")
            elif self.status.get() == "Сервер не ответил":
                self.tunnel_state.configure(text="Туннель: сервер не ответил")
            elif self.status.get() == "Туннель оборвался":
                self.tunnel_state.configure(text="Туннель оборвался, интернет возвращён")
            elif azimut_running():
                self.tunnel_state.configure(text="Туннель в сети")
            else:
                self.tunnel_state.configure(text="Туннель выключен")
        if hasattr(self, "zapret_state"):
            if self._zapret_busy:
                self.zapret_state.configure(text="Обход: подбираю способ")
            elif not self.settings.zapret_enabled:
                self.zapret_state.configure(text="Обход выключен")
            elif zapret_engine.is_running():
                title = zapret_engine.strategy_title(self.settings.zapret_strategy)
                extra = (self.zapret_info.cget("text") or "") if hasattr(self, "zapret_info") else ""
                versions = ""
                if self._bypass_report and (self._bypass_report.zapret_tag or self._bypass_report.goodbyedpi_tag):
                    versions = f" · zapret {self._bypass_report.zapret_tag or '—'}, GoodbyeDPI {self._bypass_report.goodbyedpi_tag or '—'}"
                if "не все" in extra:
                    self.zapret_state.configure(text=f"Обход «{title}»: сайты открываются не все{versions}")
                else:
                    self.zapret_state.configure(text=f"Обход работает: {title}{versions}")
            else:
                self.zapret_state.configure(text="Обход включён в настройках, но сейчас не запущен")

    def _update_apply_sites_bar(self) -> None:
        if not hasattr(self, "apply_sites_bar"):
            return
        show = (
            self._sites_dirty
            and azimut_running()
            and self.mode.get() == "split"
            and not self._current_is_generated_warp()
        )
        if show:
            if not self.apply_sites_bar.winfo_ismapped():
                self.apply_sites_bar.pack(fill="x", pady=(0, 10), before=self.sites_list)
        else:
            self.apply_sites_bar.pack_forget()

    def _apply_sites_now(self) -> None:
        if not azimut_running():
            self._sites_dirty = False
            self._update_apply_sites_bar()
            return
        self._sites_dirty = False
        self._update_apply_sites_bar()
        self.connect()


def run() -> None:
    import ctypes

    from .icon import create_icon
    from .lockscreen import ask_vault
    from .paths import icon_path
    from .vault import VaultError, open_or_create, vault_needs_password

    console = ctypes.windll.kernel32.GetConsoleWindow()
    if console:
        ctypes.windll.user32.ShowWindow(console, 0)
    if not icon_path().exists():
        create_icon(icon_path())
    try:
        from .autostart import create_app_shortcut
        from .paths import desktop_shortcut_exists

        if is_frozen():
            pass
        elif not (app_root() / "Azimut.lnk").exists() and not desktop_shortcut_exists():
            create_app_shortcut()
    except Exception:
        pass
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.withdraw()
    root.update()
    try:
        if vault_needs_password():
            if not ask_vault(root):
                root.destroy()
                return
        else:
            open_or_create()
    except VaultError as exc:
        messagebox.showerror(APP_NAME, str(exc))
        root.destroy()
        return
    root.deiconify()
    app = AzimutApp(root)
    import atexit
    atexit.register(app.restore_network)
    root.mainloop()
