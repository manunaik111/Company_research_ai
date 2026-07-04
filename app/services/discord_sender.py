"""
Discord sender (bonus feature).

Uses the Discord Bot HTTP API directly (POST /channels/{id}/messages)
rather than running a persistent bot/gateway connection — a REST call
with the bot token as a Bearer-style "Bot" auth header is sufficient
to post a message + file attachment, and it's much simpler to deploy
(no websocket process to keep alive).

Docs: https://discord.com/developers/docs/resources/message#create-message
"""

import json
import httpx
from typing import Optional

from app.models import CompanyData
from app.services.runtime_config import get_discord_config

DISCORD_API_BASE = "https://discord.com/api/v10"


class DiscordNotConfigured(Exception):
    """Raised when bot token / channel id are missing — caller should
    treat this as 'skip silently', not a hard error, since Discord is
    a bonus feature and shouldn't block the core research flow."""


async def send_report_to_discord(
    applicant_name: str,
    applicant_email: str,
    data: CompanyData,
    pdf_bytes: bytes,
    bot_token: Optional[str] = None,
    channel_id: Optional[str] = None,
) -> dict:
    configured_token, configured_channel = get_discord_config()
    token = bot_token or configured_token
    channel = channel_id or configured_channel

    if not token or not channel:
        raise DiscordNotConfigured("Discord bot token or channel id not configured")

    embed = {
        "title": f"New Company Research: {data.company_name}",
        "color": 0xD97706,  # amber accent, matches PDF/UI theme
        "fields": [
            {"name": "Applicant", "value": applicant_name, "inline": True},
            {"name": "Email", "value": applicant_email, "inline": True},
            {"name": "Company", "value": data.company_name, "inline": True},
            {"name": "Website", "value": data.website, "inline": True},
        ],
    }

    payload_json = {"embeds": [embed]}
    filename = f"{data.company_name.replace(' ', '_').lower()}_research_report.pdf"

    files = {
        "payload_json": (None, json.dumps(payload_json), "application/json"),
        "file": (filename, pdf_bytes, "application/pdf"),
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{DISCORD_API_BASE}/channels/{channel}/messages",
            headers={"Authorization": f"Bot {token}"},
            files=files,
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
