# -*- coding: utf-8 -*-
from __future__ import annotations

import customtkinter as ctk

from . import APP_NAME
from .protect import harden_app_folder
from .vault import VaultError, unlock

BG = "#070B10"
CARD = "#121A22"
TEXT = "#F2F6FA"
MUTED = "#8B9BB0"


def _font(size: int, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)


def ask_vault(root: ctk.CTk) -> bool:
    """Один раз: снять старый пароль и перевести хранилище на защиту Windows."""
    result = {"ok": False}

    dialog = ctk.CTkToplevel(root)
    dialog.title(APP_NAME)
    dialog.geometry("480x360")
    dialog.resizable(False, False)
    dialog.configure(fg_color=BG)
    dialog.grab_set()
    dialog.transient(root)
    dialog.after(80, lambda: (dialog.lift(), password.focus_set()))
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

    card = ctk.CTkFrame(dialog, fg_color=CARD, corner_radius=20)
    card.pack(fill="both", expand=True, padx=22, pady=22)
    inner = ctk.CTkFrame(card, fg_color="transparent")
    inner.pack(fill="both", expand=True, padx=24, pady=22)

    ctk.CTkLabel(inner, text=APP_NAME, font=_font(26, "bold"), text_color=TEXT).pack(anchor="w")
    ctk.CTkLabel(
        inner,
        text="Раньше хранилище открывалось паролем. Введите его один раз — дальше Azimut "
        "будет открываться сразу, а ключи останутся зашифрованными для этого пользователя Windows.",
        font=_font(13),
        text_color=MUTED,
        wraplength=430,
        justify="left",
    ).pack(anchor="w", pady=(8, 14))

    status = ctk.CTkLabel(inner, text="", font=_font(12), text_color="#FF6B7A", wraplength=430, justify="left")
    password = ctk.CTkEntry(
        inner,
        placeholder_text="Старый пароль хранилища",
        show="*",
        height=42,
        corner_radius=10,
        font=_font(14),
    )
    password.pack(fill="x", pady=(4, 8))
    status.pack(anchor="w", pady=(4, 10))

    def submit() -> None:
        try:
            unlock(password.get())
            harden_app_folder()
            result["ok"] = True
            dialog.destroy()
        except VaultError as exc:
            status.configure(text=str(exc))
        except Exception as exc:
            status.configure(text=str(exc))

    ctk.CTkButton(
        inner,
        text="Снять пароль и открыть",
        height=42,
        corner_radius=12,
        command=submit,
    ).pack(fill="x", pady=(8, 0))
    password.bind("<Return>", lambda _event: submit())
    password.focus_set()
    dialog.wait_window()
    return bool(result["ok"])
