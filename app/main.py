"""
Application entrypoint.

Serves:
  - GET  /              the single-page chat UI (Jinja2 template)
  - GET  /static/*       CSS/JS assets
  - POST /api/research   main research orchestration
  - POST /api/pdf        PDF download
  - POST /api/discord/send  bonus Discord integration
  - GET  /api/health     simple liveness check for deployment platforms
"""

from pathlib import Path
from dotenv import load_dotenv

load_dotenv()  # must run before any os.getenv() calls in service modules

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from app.routes import research, pdf, discord, settings

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="Company Research AI", version="1.0.0")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

app.include_router(research.router)
app.include_router(pdf.router)
app.include_router(discord.router)
app.include_router(settings.router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/health")
async def health():
    return {"status": "ok"}
