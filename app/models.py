"""
Shared data models for the Company Research Assistant.

These models define the "contract" between the crawler, the AI layer,
the PDF generator, and the frontend — every piece of the app speaks
in terms of these shapes, so changing one service doesn't ripple
silently into another.
"""

from typing import Optional
from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    """Incoming request from the chat UI."""
    query: str = Field(..., description="Company name OR website URL")
    model: Optional[str] = Field(
        default=None,
        description="OpenRouter model id override, e.g. 'anthropic/claude-3.5-sonnet'",
    )


class Competitor(BaseModel):
    name: str
    website: Optional[str] = None


class CompanyData(BaseModel):
    """Fully assembled research result — used for the chat response,
    the PDF report, and the Discord payload."""
    company_name: str
    website: str
    phone: Optional[str] = "Not publicly listed"
    address: Optional[str] = "Not publicly listed"
    summary: str = ""
    products_services: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    competitors: list[Competitor] = Field(default_factory=list)

    # Diagnostics shown in UI / useful for debugging, not required by spec
    pages_crawled: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ResearchResponse(BaseModel):
    success: bool
    data: Optional[CompanyData] = None
    error: Optional[str] = None


class PdfRequest(BaseModel):
    """PDF generation takes the already-assembled CompanyData —
    no need to re-crawl or re-call the AI."""
    data: CompanyData


class DiscordSendRequest(BaseModel):
    applicant_name: str
    applicant_email: str
    data: CompanyData


class DiscordSettingsRequest(BaseModel):
    bot_token: str = Field(
        default="",
        description="Discord bot token entered in the UI settings section",
    )
    channel_id: str = Field(
        default="",
        description="Discord channel id entered in the UI settings section",
    )


class DiscordSettingsResponse(BaseModel):
    configured: bool
    source: str
    message: str
