"""
Ephemeral runtime configuration.

This project intentionally avoids a database. For the hackathon's Discord
bonus requirement, we keep UI-saved bot credentials in process memory and
fall back to environment variables when no runtime override has been saved.
"""

import os

_discord_bot_token: str | None = None
_discord_channel_id: str | None = None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def save_discord_config(bot_token: str, channel_id: str) -> None:
    global _discord_bot_token, _discord_channel_id
    _discord_bot_token = _clean(bot_token)
    _discord_channel_id = _clean(channel_id)


def clear_discord_config() -> None:
    global _discord_bot_token, _discord_channel_id
    _discord_bot_token = None
    _discord_channel_id = None


def get_discord_config() -> tuple[str | None, str | None]:
    token = _discord_bot_token or _clean(os.getenv("DISCORD_BOT_TOKEN"))
    channel = _discord_channel_id or _clean(os.getenv("DISCORD_CHANNEL_ID"))
    return token, channel


def get_discord_config_status() -> dict[str, str | bool]:
    runtime_configured = bool(_discord_bot_token and _discord_channel_id)
    env_configured = bool(_clean(os.getenv("DISCORD_BOT_TOKEN")) and _clean(os.getenv("DISCORD_CHANNEL_ID")))
    configured = runtime_configured or env_configured

    if runtime_configured:
        source = "runtime"
        message = "Discord settings saved for this running app session."
    elif env_configured:
        source = "environment"
        message = "Discord is configured from server environment variables."
    else:
        source = "none"
        message = "Discord is not configured yet."

    return {
        "configured": configured,
        "source": source,
        "message": message,
    }
