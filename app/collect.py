from __future__ import annotations

import json
import logging
import os
import sys
import urllib.parse
import urllib.request
from typing import Any

from .domain import osm_record
from .settings import Settings
from .store import PostgresLeadStore

LOG = logging.getLogger("caller_portal.collect")

DEFAULT_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
)


def endpoints() -> list[str]:
    raw = str(os.getenv("OVERPASS_URLS") or "").strip()
    values = [part.strip() for part in raw.split(",") if part.strip()] if raw else list(DEFAULT_ENDPOINTS)
    return list(dict.fromkeys(values))


def fetch_osm_restaurants(limit: int) -> list[dict[str, Any]]:
    bbox = str(os.getenv("OSM_BBOX") or "12.90,77.55,13.02,77.68").strip()
    parts = [part.strip() for part in bbox.split(",")]
    if len(parts) != 4:
        raise RuntimeError("OSM_BBOX must be south,west,north,east.")
    south, west, north, east = parts
    query = (
        "[out:json][timeout:45];("
        f"nwr[\"amenity\"=\"restaurant\"][\"phone\"]({south},{west},{north},{east});"
        f"nwr[\"amenity\"=\"restaurant\"][\"contact:phone\"]({south},{west},{north},{east});"
        ");out center tags " + str(max(40, min(500, limit * 5))) + ";"
    )
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    errors: list[str] = []
    for endpoint in endpoints():
        request = urllib.request.Request(endpoint, data=data, headers={"User-Agent": "JarvisCallerPortal/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=70) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            elements = payload.get("elements") if isinstance(payload, dict) else []
            if isinstance(elements, list):
                return [item for item in elements if isinstance(item, dict)]
        except Exception as exc:
            errors.append(f"{endpoint}: {exc}")
    raise RuntimeError("; ".join(errors) or "OpenStreetMap returned no usable payload")


def run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_env()
    store = PostgresLeadStore(settings.database_url, settings.batch_size)
    store.initialise()
    elements = fetch_osm_restaurants(settings.daily_limit)
    records = [record for record in (osm_record(element, settings.city) for element in elements) if record]
    prepared = store.upsert_leads(records[: settings.daily_limit], "scheduled OpenStreetMap public-business collection")
    LOG.info("Prepared %s callable public-business leads.", prepared)
    return prepared


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        LOG.exception("Collection failed: %s", exc)
        sys.exit(1)
