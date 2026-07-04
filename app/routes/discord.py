"""
POST /api/discord/send

Called automatically by the frontend right after a PDF report is
generated. Reads the bot token / channel id from environment variables
(no keys are ever entered in the UI, per project decision) and posts
the applicant details + company research + PDF attachment to the
configured Discord channel.

If Discord isn't configured (env vars missing), this returns a soft
"skipped" response rather than an error — Discord is a bonus feature
and must never block or break the core research/PDF flow.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.models import DiscordSendRequest
from app.services.pdf_generator import generate_pdf
from app.services.discord_sender import send_report_to_discord, DiscordNotConfigured

router = APIRouter()


class DiscordSendResponse(BaseModel):
    sent: bool
    skipped_reason: str | None = None
    error: str | None = None


@router.post("/api/discord/send", response_model=DiscordSendResponse)
async def send_to_discord(req: DiscordSendRequest) -> DiscordSendResponse:
    pdf_bytes = generate_pdf(req.data)

    try:
        await send_report_to_discord(
            applicant_name=req.applicant_name,
            applicant_email=req.applicant_email,
            data=req.data,
            pdf_bytes=pdf_bytes,
        )
        return DiscordSendResponse(sent=True)

    except DiscordNotConfigured:
        return DiscordSendResponse(
            sent=False,
            skipped_reason="Discord bot token / channel id not configured on the server.",
        )
    except Exception as e:  # Discord/network errors should never crash the request
        return DiscordSendResponse(sent=False, error=str(e))