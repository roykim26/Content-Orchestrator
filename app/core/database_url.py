import os
from pathlib import Path

def resolve_database_url(configured_database_url: str | None) -> str:
    if not configured_database_url:
        app_data_root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        default_root = Path(app_data_root) if app_data_root else Path.home() / ".content-orchestrator"
        default_path = default_root / "ContentOrchestrator" / "content_orchestrator.sqlite3"
        default_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{default_path.as_posix()}"

    if configured_database_url.startswith("sqlite:///./"):
        relative_path = configured_database_url.removeprefix("sqlite:///./")
        absolute_path = (Path.cwd() / relative_path).resolve()
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{absolute_path.as_posix()}"

    return configured_database_url
