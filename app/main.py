from __future__ import annotations

import hmac
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .settings import Settings
from .store import LeadStore, PostgresLeadStore


class ImportRequest(BaseModel):
    leads: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


def create_app(*, settings: Settings | None = None, store: LeadStore | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    repository = store or PostgresLeadStore(config.database_url, config.batch_size)

    app = FastAPI(title="Jarvis Caller Portal API", docs_url=None, redoc_url=None)
    app.state.settings = config
    app.state.store = repository

    @app.on_event("startup")
    def initialise_store() -> None:
        repository.initialise()

    def require_portal(
        x_portal_secret: Annotated[str | None, Header()] = None,
        x_portal_user: Annotated[str | None, Header()] = None,
    ) -> str:
        if not config.portal_shared_secret or not x_portal_secret or not hmac.compare_digest(x_portal_secret, config.portal_shared_secret):
            raise HTTPException(status_code=403, detail="Caller portal access denied.")
        caller_id = (x_portal_user or "").strip()
        if not caller_id or len(caller_id) > 128:
            raise HTTPException(status_code=400, detail="A verified caller identity is required.")
        return caller_id

    @app.get("/v1/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/v1/caller/current")
    def current_batch(caller_id: str = Depends(require_portal)) -> dict[str, Any]:
        return {"ok": True, **repository.current_batch(caller_id)}

    @app.post("/v1/caller/refresh")
    def refresh_batch(caller_id: str = Depends(require_portal)) -> dict[str, Any]:
        return {"ok": True, **repository.assign_next_batch(caller_id)}

    @app.post("/v1/internal/import")
    async def import_leads(request: Request, payload: ImportRequest) -> dict[str, Any]:
        secret = str(request.headers.get("x-portal-secret") or "")
        if not config.portal_shared_secret or not hmac.compare_digest(secret, config.portal_shared_secret):
            raise HTTPException(status_code=403, detail="Import access denied.")
        count = repository.upsert_leads(payload.leads, "manual migration")
        return {"ok": True, "imported": count}

    return app


app = create_app()
