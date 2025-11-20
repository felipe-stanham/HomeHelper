from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# Resolve templates directory relative to project root
# File path: <project_root>/src/homehelper/web/dashboard.py
# parents[0] = web, parents[1] = homehelper, parents[2] = src
PROJECT_ROOT = Path(__file__).resolve().parents[2].parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main HomeHelper dashboard page.

    Data is populated client-side via calls to existing JSON APIs
    (e.g. /health and /api/apps). This keeps the server-side view
    simple and aligned with the manual-refresh pattern.
    """
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
        },
    )
