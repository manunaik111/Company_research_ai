"""
Shared data models for the Company Research Assistant.

These models define the contract between the crawler, the AI layer,
the PDF generator, and the frontend.
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
    rationale: str = ""


class SourceReference(BaseModel):
    label: str
    url: str
    source_type: str
    notes: str = ""


class CompanyData(BaseModel):
    """Fully assembled research result used by the UI, PDF, and Discord."""

    company_name: str
    website: str
    phone: Optional[str] = "Not publicly listed"
    address: Optional[str] = "Not publicly listed"
    summary: str = ""
    industry: str = ""
    target_customers: str = ""
    business_model: str = ""
    key_highlights: list[str] = Field(default_factory=list)
    products_services: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    competitors: list[Competitor] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)

    # Diagnostics shown in UI / useful for debugging.
    pages_crawled: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ResearchResponse(BaseModel):
    success: bool
    data: Optional[CompanyData] = None
    error: Optional[str] = None


class PdfRequest(BaseModel):
    """PDF generation takes already-assembled CompanyData."""

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
