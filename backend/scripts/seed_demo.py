"""Seed the demo workspace with a request and the sample quotations."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API = os.getenv("API_BASE_URL", "http://127.0.0.1:8000") + "/api/v1"
SAMPLES = Path(__file__).resolve().parents[1] / "samples"
EMAIL = os.getenv("DEMO_EMAIL", "soham.demo@vishwakarma-eng.com")
PASSWORD = os.getenv("DEMO_PASSWORD", "DemoPassw0rd!")  # demo-only account

MIME = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
}


def main() -> int:
    client = httpx.Client(timeout=120.0)
    token = client.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()[
        "access_token"
    ]
    auth = {"Authorization": f"Bearer {token}"}

    existing = client.get(f"{API}/procurement-requests", headers=auth).json()
    if existing["total"] > 0:
        request_id = existing["items"][0]["id"]
        print(f"Reusing request {request_id}")
    else:
        created = client.post(
            f"{API}/procurement-requests",
            headers=auth,
            json={
                "title": "Plumbing materials — Unit 2 expansion",
                "description": "100 units of 2-inch PVC pipe with fittings and solvent cement.",
                "department": "Maintenance",
                "currency": "INR",
                "status": "open",
                "items": [
                    {"name": "PVC Pipe, 2 inch", "quantity": 100, "unit": "Nos",
                     "specifications": "Class-2, 6 metre lengths"},
                    {"name": "PVC Elbow 2 inch", "quantity": 40, "unit": "Nos"},
                    {"name": "Solvent Cement 500 ml", "quantity": 10, "unit": "Bottle"},
                ],
            },
        )
        created.raise_for_status()
        request_id = created.json()["id"]
        print(f"Created request {request_id}")

    quotations = client.get(f"{API}/quotations", headers=auth).json()
    if quotations["total"] == 0:
        for path in sorted(SAMPLES.glob("*")):
            with path.open("rb") as handle:
                response = client.post(
                    f"{API}/documents/upload",
                    headers=auth,
                    files={"file": (path.name, handle, MIME.get(path.suffix.lower(), "application/octet-stream"))},
                    data={"procurement_request_id": request_id},
                )
            print(f"  upload {path.name}: {response.status_code}")

        print("waiting for processing…")
        deadline = time.time() + 180
        while time.time() < deadline:
            rows = client.get(f"{API}/quotations", headers=auth).json()["items"]
            if all(r["processing_status"] in ("COMPLETED", "REQUIRES_REVIEW", "FAILED") for r in rows):
                break
            time.sleep(3)
        for row in client.get(f"{API}/quotations", headers=auth).json()["items"]:
            print(f"  {row['source']['original_filename']}: {row['processing_status']}")
    else:
        print(f"{quotations['total']} quotations already present")

    comparison = client.post(
        f"{API}/comparisons/procurement-requests/{request_id}",
        headers=auth, json={"include_ai_explanation": True},
    )
    print(f"comparison: {comparison.status_code}")
    for s in comparison.json().get("suppliers", []):
        print(f"  #{s['rank']} {s['supplier_name']:<36} {s['overall_score']:.3f}")
    print(f"\nRequest id: {request_id}")
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
