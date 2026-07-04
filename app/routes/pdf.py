"""
POST /api/pdf

Takes the already-assembled CompanyData (from a prior /api/research call)
and returns a downloadable PDF. Kept as a separate endpoint rather than
bundled into /api/research so the frontend can re-download the report
without re-running the (slower, rate-limited) research pipeline.
"""

from fastapi import APIRouter
from fastapi.responses import Response

from app.models import PdfRequest
from app.services.pdf_generator import generate_pdf

router = APIRouter()


@router.post("/api/pdf")
async def download_pdf(req: PdfRequest) -> Response:
    pdf_bytes = generate_pdf(req.data)
    filename = f"{req.data.company_name.replace(' ', '_').lower()}_research_report.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )