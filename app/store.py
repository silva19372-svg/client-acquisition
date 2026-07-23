from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from typing import Any, Iterator, Protocol

from .domain import caller_card, imported_record, now_iso


class LeadStore(Protocol):
    def initialise(self) -> None: ...
    def current_batch(self, caller_id: str) -> dict[str, Any]: ...
    def assign_next_batch(self, caller_id: str) -> dict[str, Any]: ...
    def upsert_leads(self, records: list[dict[str, Any]], source: str) -> int: ...
    def record_collection(self, prepared: int, detail: str) -> None: ...


SCHEMA = """
CREATE TABLE IF NOT EXISTS portal_leads (
    id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    score INTEGER NOT NULL,
    has_phone BOOLEAN NOT NULL,
    record JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS portal_leads_ready_idx ON portal_leads (status, has_phone, score DESC, updated_at DESC);
CREATE TABLE IF NOT EXISTS caller_batches (
    id UUID PRIMARY KEY,
    caller_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS caller_batches_caller_idx ON caller_batches (caller_id, created_at DESC);
CREATE TABLE IF NOT EXISTS caller_batch_leads (
    lead_id TEXT PRIMARY KEY REFERENCES portal_leads(id) ON DELETE CASCADE,
    batch_id UUID NOT NULL REFERENCES caller_batches(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS collection_runs (
    id BIGSERIAL PRIMARY KEY,
    prepared INTEGER NOT NULL,
    detail TEXT NOT NULL,
    ran_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


class PostgresLeadStore:
    def __init__(self, database_url: str, batch_size: int) -> None:
        self.database_url = database_url
        self.batch_size = batch_size

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - Railway installs this dependency.
            raise RuntimeError("psycopg is not installed.") from exc
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required.")
        with psycopg.connect(self.database_url) as connection:
            yield connection

    def initialise(self) -> None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(SCHEMA)

    def _batch_payload(self, connection: Any, batch_id: str | None) -> dict[str, Any]:
        if not batch_id:
            return {"leads": [], "batch_created_at": "", "remaining_pool": 0}
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT l.record, b.created_at
                FROM caller_batch_leads bl
                JOIN portal_leads l ON l.id = bl.lead_id
                JOIN caller_batches b ON b.id = bl.batch_id
                WHERE bl.batch_id = %s
                ORDER BY l.score DESC, (l.record ->> 'name') ASC
                """,
                (batch_id,),
            )
            rows = cursor.fetchall()
            cursor.execute(
                """
                SELECT COUNT(*) FROM portal_leads l
                WHERE l.has_phone = TRUE
                  AND l.status IN ('Found', 'Reviewed', 'Approved')
                  AND NOT EXISTS (SELECT 1 FROM caller_batch_leads bl WHERE bl.lead_id = l.id)
                """
            )
            remaining = int(cursor.fetchone()[0])
        records = [row[0] if isinstance(row[0], dict) else json.loads(row[0]) for row in rows]
        created_at = rows[0][1].isoformat() if rows else ""
        return {
            "leads": [caller_card(record) for record in records],
            "batch_created_at": created_at,
            "remaining_pool": remaining,
        }

    def current_batch(self, caller_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id::text FROM caller_batches WHERE caller_id = %s ORDER BY created_at DESC LIMIT 1",
                    (caller_id,),
                )
                row = cursor.fetchone()
            return self._batch_payload(connection, row[0] if row else None)

    def assign_next_batch(self, caller_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                batch_id = str(uuid.uuid4())
                cursor.execute("INSERT INTO caller_batches (id, caller_id) VALUES (%s, %s)", (batch_id, caller_id))
                cursor.execute(
                    """
                    SELECT l.id
                    FROM portal_leads l
                    WHERE l.has_phone = TRUE
                      AND l.status IN ('Found', 'Reviewed', 'Approved')
                      AND NOT EXISTS (SELECT 1 FROM caller_batch_leads bl WHERE bl.lead_id = l.id)
                    ORDER BY l.score DESC, l.updated_at DESC, (l.record ->> 'name') ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                    """,
                    (self.batch_size,),
                )
                lead_ids = [row[0] for row in cursor.fetchall()]
                for lead_id in lead_ids:
                    cursor.execute("INSERT INTO caller_batch_leads (lead_id, batch_id) VALUES (%s, %s)", (lead_id, batch_id))
            return self._batch_payload(connection, batch_id)

    def upsert_leads(self, records: list[dict[str, Any]], source: str) -> int:
        accepted = [record for record in (imported_record(item) for item in records) if record]
        with self._connection() as connection:
            with connection.cursor() as cursor:
                for record in accepted:
                    cursor.execute(
                        """
                        INSERT INTO portal_leads (id, dedupe_key, status, score, has_phone, record, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, TRUE, %s::jsonb, %s::timestamptz, NOW())
                        ON CONFLICT (dedupe_key) DO UPDATE SET
                            score = EXCLUDED.score,
                            has_phone = TRUE,
                            record = EXCLUDED.record,
                            updated_at = NOW()
                        """,
                        (
                            record["id"],
                            record["dedupe_key"],
                            record["status"],
                            record["score"],
                            json.dumps(record),
                            record["created_at"],
                        ),
                    )
                cursor.execute("INSERT INTO collection_runs (prepared, detail) VALUES (%s, %s)", (len(accepted), source[:500]))
        return len(accepted)

    def record_collection(self, prepared: int, detail: str) -> None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO collection_runs (prepared, detail) VALUES (%s, %s)", (prepared, detail[:500]))


class MemoryLeadStore:
    """Small deterministic store used only by tests and local API smoke checks."""

    def __init__(self, records: list[dict[str, Any]] | None = None, batch_size: int = 6) -> None:
        self.batch_size = batch_size
        self.records: dict[str, dict[str, Any]] = {}
        self.batches: dict[str, list[str]] = {}
        self.assigned: set[str] = set()
        self.runs: list[dict[str, Any]] = []
        self.upsert_leads(records or [], "memory seed")

    def initialise(self) -> None:
        return None

    def current_batch(self, caller_id: str) -> dict[str, Any]:
        ids = self.batches.get(caller_id, [])
        return {"leads": [caller_card(self.records[item]) for item in ids], "batch_created_at": "", "remaining_pool": self._remaining()}

    def _remaining(self) -> int:
        return sum(1 for lead_id in self.records if lead_id not in self.assigned)

    def assign_next_batch(self, caller_id: str) -> dict[str, Any]:
        eligible = [
            item for item in self.records.values()
            if item["id"] not in self.assigned and item.get("status") in {"Found", "Reviewed", "Approved"}
        ]
        eligible.sort(key=lambda item: (-int(item.get("score", 0)), item["name"]))
        selected = eligible[: self.batch_size]
        ids = [item["id"] for item in selected]
        self.assigned.update(ids)
        self.batches[caller_id] = ids
        return {"leads": [caller_card(item) for item in selected], "batch_created_at": now_iso(), "remaining_pool": self._remaining()}

    def upsert_leads(self, records: list[dict[str, Any]], source: str) -> int:
        accepted = [record for record in (imported_record(item) for item in records) if record]
        for record in accepted:
            self.records[record["id"]] = record
        self.runs.append({"prepared": len(accepted), "detail": source})
        return len(accepted)

    def record_collection(self, prepared: int, detail: str) -> None:
        self.runs.append({"prepared": prepared, "detail": detail})
