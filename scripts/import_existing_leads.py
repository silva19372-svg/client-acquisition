from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "client_acquisition" / "leads.json"


def main() -> int:
    base_url = str(os.getenv("PORTAL_API_URL") or "").rstrip("/")
    secret = str(os.getenv("PORTAL_SHARED_SECRET") or "")
    if not base_url or not secret:
        raise RuntimeError("Set PORTAL_API_URL and PORTAL_SHARED_SECRET for this one-time import.")
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    leads = list((payload.get("leads") or {}).values()) if isinstance(payload, dict) else []
    body = json.dumps({"leads": leads}).encode("utf-8")
    request = urllib.request.Request(
        base_url + "/v1/internal/import",
        data=body,
        method="POST",
        headers={"content-type": "application/json", "x-portal-secret": secret},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Import failed with HTTP {exc.code}: {detail}") from exc
    print(f"Imported {int(result.get('imported') or 0)} public-business leads.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
