from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(value: Any, limit: int = 2_000) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean(value).lower()).strip()


def slug(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", norm(value)).strip("-")
    return text[:64] or "business"


def normalise_phone(value: Any) -> str:
    raw = clean(value, 80)
    compact = re.sub(r"[^0-9+]", "", raw)
    digits = re.sub(r"\D", "", compact)
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    if len(digits) == 11 and digits.startswith("0"):
        return "+91" + digits[1:]
    if len(digits) in {12, 13} and digits.startswith("91"):
        return "+" + digits
    return compact if 8 <= len(digits) <= 15 else ""


def public_phone_contacts(items: Any) -> list[dict[str, str]]:
    contacts: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or clean(item.get("type")).lower() != "phone":
            continue
        phone = normalise_phone(item.get("value"))
        if not phone or phone in seen:
            continue
        seen.add(phone)
        contacts.append(
            {
                "type": "phone",
                "value": phone,
                "source": clean(item.get("source"), 700),
                "public_business": "true",
            }
        )
    return contacts


def dedupe_key(name: Any, area: Any, phone: Any) -> str:
    basis = "|".join((norm(name), norm(area), normalise_phone(phone)))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def lead_id(name: Any, key: str) -> str:
    return f"blr-{slug(name)}-{key[:8]}"


def caller_card(record: dict[str, Any]) -> dict[str, Any]:
    """Return exactly the public calling information a caller needs."""
    return {
        "id": clean(record.get("id"), 100),
        "name": clean(record.get("name"), 180),
        "category": clean(record.get("category"), 80),
        "area": clean(record.get("area"), 180),
        "city": clean(record.get("city"), 80),
        "score": int(record.get("score") or 0),
        "score_reasons": [clean(item, 160) for item in record.get("score_reasons", []) if clean(item, 160)][:6],
        "issues": [clean(item, 300) for item in record.get("issues", []) if clean(item, 300)][:6],
        "evidence": [clean(item, 500) for item in record.get("evidence", []) if clean(item, 500)][:5],
        "outreach_pitch": clean(record.get("outreach_pitch"), 3_000),
        "website_url": clean(record.get("website_url"), 700),
        "source_url": clean(record.get("source_url"), 700),
        "contact_channels": public_phone_contacts(record.get("contact_channels")),
    }


def imported_record(raw: dict[str, Any]) -> dict[str, Any] | None:
    name = clean(raw.get("name"), 180)
    contacts = public_phone_contacts(raw.get("contact_channels"))
    if not name or not contacts:
        return None
    area = clean(raw.get("area"), 180) or "Bangalore"
    phone = contacts[0]["value"]
    key = clean(raw.get("dedupe_key"), 80) or dedupe_key(name, area, phone)
    now = now_iso()
    record = {
        "id": clean(raw.get("id"), 100) or lead_id(name, key),
        "name": name,
        "category": clean(raw.get("category"), 80) or "restaurant",
        "area": area,
        "city": clean(raw.get("city"), 80) or "Bangalore",
        "source_url": clean(raw.get("source_url"), 700),
        "source_name": clean(raw.get("source_name"), 180) or "Public business source",
        "website_url": clean(raw.get("website_url"), 700),
        "contact_channels": contacts,
        "issues": [clean(item, 300) for item in raw.get("issues", []) if clean(item, 300)][:8],
        "evidence": [clean(item, 500) for item in raw.get("evidence", []) if clean(item, 500)][:8],
        "score": max(0, min(100, int(raw.get("score") or 0))),
        "score_reasons": [clean(item, 160) for item in raw.get("score_reasons", []) if clean(item, 160)][:8],
        "status": clean(raw.get("status"), 40) or "Found",
        "outreach_pitch": clean(raw.get("outreach_pitch"), 3_000),
        "created_at": clean(raw.get("created_at"), 80) or now,
        "updated_at": now,
        "dedupe_key": key,
    }
    return record


def osm_record(element: dict[str, Any], city: str) -> dict[str, Any] | None:
    tags = element.get("tags") if isinstance(element.get("tags"), dict) else {}
    name = clean(tags.get("name") or tags.get("brand"), 180)
    raw_phone = tags.get("phone") or tags.get("contact:phone") or tags.get("mobile") or tags.get("contact:mobile")
    phone = normalise_phone(raw_phone)
    if not name or not phone:
        return None
    area = clean(
        tags.get("addr:neighbourhood")
        or tags.get("addr:neighborhood")
        or tags.get("addr:suburb")
        or tags.get("addr:street")
        or tags.get("addr:city"),
        180,
    ) or city
    website = clean(tags.get("website") or tags.get("contact:website"), 700)
    element_type = clean(element.get("type"), 20) or "node"
    osm_id = clean(element.get("id"), 80)
    source_url = f"https://www.openstreetmap.org/{element_type}/{osm_id}" if osm_id else "https://www.openstreetmap.org"
    key = dedupe_key(name, area, phone)
    no_site = not website
    issues = [
        "No owned website listed in public business data" if no_site else "Website opportunity should be reviewed manually",
        "Missing obvious menu, ordering, or table-booking flow" if no_site else "Confirm mobile menu, booking, and conversion flow before calling",
    ]
    score = 82 if no_site else 62
    return {
        "id": lead_id(name, key),
        "name": name,
        "category": "restaurant",
        "area": area,
        "city": city,
        "source_url": source_url,
        "source_name": "OpenStreetMap public restaurant data",
        "website_url": website,
        "contact_channels": [{"type": "phone", "value": phone, "source": source_url, "public_business": "true"}],
        "issues": issues,
        "evidence": [f"Public business phone captured from OpenStreetMap: {phone}.", f"Source: {source_url}"],
        "score": score,
        "score_reasons": ["No owned website" if no_site else "Website needs manual opportunity review", "Restaurant commerce gap", "Callable phone captured"],
        "status": "Found",
        "outreach_pitch": (
            f"Hi {name}, I came across your restaurant in {area}. I noticed {issues[0].lower()} and {issues[1].lower()}. "
            "I build fast mobile-first restaurant websites with menu, ordering, and table-booking flows. "
            "If useful, I can share a quick concept for how your site could convert better."
        ),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "dedupe_key": key,
    }
