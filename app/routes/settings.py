"""
Discord settings endpoints.

The hackathon bonus asks for a settings section where the evaluator can
enter a Discord bot token and channel id. We keep those values in memory
for the life of the running process and fall back to environment variables
when no runtime override has been saved.
"""

from fastapi import APIRouter, HTTPException

from app.models import DiscordSettingsRequest, DiscordSettingsResponse
from app.services.runtime_config import (
    clear_discord_config,
    get_discord_config_status,
    save_discord_config,
)

router = APIRouter()


@router.get("/api/settings/discord", response_model=DiscordSettingsResponse)
async def get_discord_settings() -> DiscordSettingsResponse:
    status = get_discord_config_status()
    return DiscordSettingsResponse(**status)


@router.post("/api/settings/discord", response_model=DiscordSettingsResponse)
async def save_discord_settings(req: DiscordSettingsRequest) -> DiscordSettingsResponse:
    bot_token = req.bot_token.strip()
    channel_id = req.channel_id.strip()

    if not bot_token and not channel_id:
        clear_discord_config()
        status = get_discord_config_status()
        return DiscordSettingsResponse(
            configured=status["configured"],
            source=status["source"],
            message="Cleared runtime Discord settings. Environment variables still apply if present.",
        )

    if not bot_token or not channel_id:
        raise HTTPException(status_code=400, detail="Enter both Discord bot token and channel ID.")

    save_discord_config(bot_token, channel_id)
    status = get_discord_config_status()
    return DiscordSettingsResponse(**status)
