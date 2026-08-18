from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Site:
    id: str
    title: str
    category: str
    domains: list[str] = field(default_factory=list)
    cidrs: list[str] = field(default_factory=list)
    note: str = ""


META_RANGES = [
    "31.13.64.0/18",
    "45.64.40.0/22",
    "66.220.144.0/20",
    "69.63.176.0/20",
    "69.171.224.0/19",
    "102.132.96.0/20",
    "129.134.0.0/16",
    "157.240.0.0/16",
    "163.70.128.0/17",
    "173.252.64.0/18",
    "179.60.192.0/22",
    "185.60.216.0/22",
    "204.15.20.0/22",
]

TWITTER_RANGES = [
    "104.244.40.0/21",
    "192.133.76.0/22",
    "199.16.156.0/22",
    "199.59.148.0/22",
]

CATALOG: list[Site] = [
    Site("instagram", "Instagram", "Соцсети", ["instagram.com", "cdninstagram.com", "ig.me", "instagram.net"], META_RANGES),
    Site("facebook", "Facebook", "Соцсети", ["facebook.com", "fb.com", "fbcdn.net", "facebook.net", "fbsbx.com", "messenger.com"], META_RANGES),
    Site("threads", "Threads", "Соцсети", ["threads.net", "threads.com"], META_RANGES),
    Site("twitter", "X / Twitter", "Соцсети", ["x.com", "twitter.com", "twimg.com", "t.co", "pscp.tv"], TWITTER_RANGES),
    Site("tiktok", "TikTok", "Соцсети", ["tiktok.com", "tiktokcdn.com", "tiktokv.com", "musical.ly", "byteoversea.com", "ibyteimg.com"]),
    Site("reddit", "Reddit", "Соцсети", ["reddit.com", "redd.it", "redditmedia.com", "redditstatic.com"]),
    Site("linkedin", "LinkedIn", "Соцсети", ["linkedin.com", "licdn.com", "lnkd.in"]),
    Site("discord", "Discord", "Мессенджеры", ["discord.com", "discord.gg", "discordapp.com", "discord.media", "discordapp.net", "discord.co"], note="Голос и сам Discord лучше открывать обходом zapret, а не через VPN."),
    Site("telegram", "Telegram", "Мессенджеры", ["telegram.org", "t.me", "telegram.me", "tdesktop.com"]),
    Site("whatsapp", "WhatsApp", "Мессенджеры", ["whatsapp.com", "whatsapp.net", "wa.me"], META_RANGES),
    Site("signal", "Signal", "Мессенджеры", ["signal.org", "whispersystems.org"]),
    Site("chatgpt", "ChatGPT", "Нейросети", ["chatgpt.com", "openai.com", "chat.openai.com", "oaistatic.com", "cdn.oaistatic.com", "cdn.openai.com", "auth0.openai.com", "api.openai.com", "platform.openai.com", "oaiusercontent.com", "challenges.cloudflare.com"]),
    Site("claude", "Claude", "Нейросети", ["claude.ai", "anthropic.com"]),
    Site("gemini", "Google Gemini", "Нейросети", ["gemini.google.com", "aistudio.google.com", "generativelanguage.googleapis.com"]),
    Site("copilot", "Microsoft Copilot", "Нейросети", ["copilot.microsoft.com", "copilot.cloud.microsoft"]),
    Site("grok", "Grok", "Нейросети", ["grok.com", "x.ai"]),
    Site("youtube", "YouTube", "Видео и музыка", ["youtube.com", "youtu.be", "googlevideo.com", "ytimg.com", "ggpht.com", "youtubekids.com", "youtube-nocookie.com", "yt.be"], note="При включённом обходе zapret YouTube идёт напрямую, не через VPN."),
    Site("twitch", "Twitch", "Видео и музыка", ["twitch.tv", "twitchcdn.net", "jtvnw.net", "ttvnw.net"]),
    Site("spotify", "Spotify", "Видео и музыка", ["spotify.com", "spotifycdn.com", "scdn.co", "spoti.fi"]),
    Site("soundcloud", "SoundCloud", "Видео и музыка", ["soundcloud.com", "sndcdn.com"]),
    Site("netflix", "Netflix", "Видео и музыка", ["netflix.com", "nflxvideo.net", "nflximg.net", "nflxext.com", "nflxso.net"]),
    Site("github", "GitHub", "Разработка", ["github.com", "githubusercontent.com", "githubassets.com", "github.io", "ghcr.io"]),
    Site("gitlab", "GitLab", "Разработка", ["gitlab.com", "gitlab.net"]),
    Site("stackoverflow", "Stack Overflow", "Разработка", ["stackoverflow.com", "stackexchange.com", "sstatic.net"]),
    Site("npm", "npm", "Разработка", ["npmjs.com", "npmjs.org"]),
    Site("medium", "Medium", "Новости и прочее", ["medium.com"]),
    Site("bbc", "BBC", "Новости и прочее", ["bbc.com", "bbc.co.uk", "bbci.co.uk"]),
    Site("nytimes", "New York Times", "Новости и прочее", ["nytimes.com", "nyt.com"]),
    Site(
        "blocked_all",
        "Все заблокированные сайты",
        "Большие списки",
        note="Открытый перечень сетей, которые обычно недоступны из России. Можно включить вместе с отдельными сервисами.",
    ),
]

DEFAULT_SELECTED = [
    "instagram",
    "facebook",
    "discord",
    "chatgpt",
    "claude",
    "twitter",
    "tiktok",
    "spotify",
]

CATEGORIES = [
    "Соцсети",
    "Мессенджеры",
    "Нейросети",
    "Видео и музыка",
    "Разработка",
    "Новости и прочее",
    "Большие списки",
]


def site_by_id(site_id: str) -> Site | None:
    for item in CATALOG:
        if item.id == site_id:
            return item
    return None


def selected_titles(selected_ids: list[str], extra_domains: list[str] | None = None) -> list[str]:
    titles = [item.title for item in CATALOG if item.id in selected_ids]
    extras = [item for item in (extra_domains or []) if item]
    return titles + extras
