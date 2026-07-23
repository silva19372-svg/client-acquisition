from __future__ import annotations

import hmac
import logging
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .settings import Settings
from .store import LeadStore, PostgresLeadStore


LOG = logging.getLogger("caller_portal.api")


class ImportRequest(BaseModel):
    leads: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


def create_app(
    *,
    settings: Settings | None = None,
    store: LeadStore | None = None,
    replenisher: Callable[[], int] | None = None,
) -> FastAPI:
    config = settings or Settings.from_env()
    supplied_store = store is not None
    repository = store or PostgresLeadStore(config.database_url, config.batch_size)

    if replenisher is None and not supplied_store:
        from .collect import replenish_public_leads

        replenisher = lambda: replenish_public_leads(
            config,
            repository,
            reason="on-demand reserve replenishment before a caller refresh",
        )

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
        reserve_threshold = config.batch_size + config.ready_reserve
        if repository.ready_count() < reserve_threshold and replenisher is not None:
            try:
                replenisher()
            except Exception as exc:  # Keep the caller's existing batch visible if collection is temporarily unavailable.
                LOG.warning("Lead reserve replenishment failed: %s", exc)
        payload = repository.assign_next_batch(caller_id)
        if not payload.get("refreshed"):
            payload["message"] = "Your current call list is still available while the next reserve is being prepared."
        return {"ok": True, **payload}

    @app.post("/v1/internal/import")
    async def import_leads(request: Request, payload: ImportRequest) -> dict[str, Any]:
        secret = str(request.headers.get("x-portal-secret") or "")
        if not config.portal_shared_secret or not hmac.compare_digest(secret, config.portal_shared_secret):
            raise HTTPException(status_code=403, detail="Import access denied.")
        count = repository.upsert_leads(payload.leads, "manual migration")
        return {"ok": True, "imported": count}

    return app

app = create_app()
