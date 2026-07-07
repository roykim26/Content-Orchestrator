from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))
router = APIRouter()


@router.get("/topic-manager", response_class=HTMLResponse)
def topic_manager_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("topic_manager.html", {"request": request})
