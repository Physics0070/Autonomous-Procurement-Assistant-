"""Measure API latency against a running backend, plus the end-to-end time to read an uploaded quotation.

Usage (from backend/):  python scripts/measure_latency.py [--ai]
Logs in as the demo user (DEMO_EMAIL / DEMO_PASSWORD environment variables) and writes ml/artifacts/latency.json.
Times are wall-clock seconds from the client over 127.0.0.1, so they include JSON encoding but no internet to the user.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
OUT = Path(__file__).resolve().parent.parent / "ml" / "artifacts" / "latency.json"
SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 3)


def summarize(values: list[float], errors: int) -> dict:
    return {"n": len(values) + errors, "errors": errors, "p50_s": pct(values, 0.5) if values else None,
            "p95_s": pct(values, 0.95) if values else None, "max_s": round(max(values), 3) if values else None,
            "mean_s": round(statistics.mean(values), 3) if values else None}


def timed(client: httpx.Client, method: str, path: str, n: int, **kw) -> dict:
    times, errors = [], 0
    for _ in range(n):
        t = time.perf_counter()
        try:
            r = client.request(method, path if path.startswith("http") else BASE + path, timeout=120, **kw)
            ok = r.status_code < 400
        except httpx.HTTPError:
            ok = False
        (times if ok else []).append(time.perf_counter() - t) if ok else None
        errors += 0 if ok else 1
    return summarize(times, errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ai", action="store_true", help="also time the endpoints that call a language model")
    parser.add_argument("--uploads", action="store_true", help="also upload the sample files (adds quotations to the demo organization)")
    args = parser.parse_args()
    client = httpx.Client()
    login = client.post(BASE + "/auth/login", json={"email": os.environ["DEMO_EMAIL"], "password": os.environ["DEMO_PASSWORD"]})
    login.raise_for_status()
    body = login.json()
    token = body.get("access_token") or body["data"]["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"

    quotes = client.get(BASE + "/quotations?limit=50").json()
    rows = quotes.get("items") or quotes
    qid = next(r["id"] for r in rows if (r.get("source") or {}).get("mime_type", "").startswith("image/"))
    requests = client.get(BASE + "/procurement-requests").json()
    rid = (requests.get("items") or requests)[0]["id"]

    result: dict = {"measured_at": time.strftime("%Y-%m-%d %H:%M"), "endpoints": {}}
    E = result["endpoints"]
    result["login"] = timed(httpx.Client(), "POST", "/auth/login", 8, json={"email": os.environ["DEMO_EMAIL"], "password": os.environ["DEMO_PASSWORD"]})
    for name, path in (("health", "http://127.0.0.1:8000/health"), ("dashboard", "/dashboard/summary"), ("quotations list", "/quotations?limit=50"),
                       ("quotation detail", f"/quotations/{qid}"), ("original file", f"/quotations/{qid}/file"),
                       ("purchase requests", "/procurement-requests"), ("suppliers", "/suppliers"), ("comparison", f"/comparisons/procurement-requests/{rid}"),
                       ("purchase orders", "/purchase-orders"), ("emails", "/communications"),
                       ("reports: spend", "/analytics/spend"), ("reports: forecast", "/analytics/forecast"), ("reports: models", "/analytics/models")):
        E[name] = timed(client, "GET", path, 30)

    # Concurrency: 20 users loading the dashboard at once, five times over.
    def hit(_):
        t = time.perf_counter()
        ok = client.get(BASE + "/dashboard/summary", timeout=120).status_code < 400
        return time.perf_counter() - t, ok

    started = time.perf_counter()
    with ThreadPoolExecutor(20) as pool:
        out = [r for _ in range(5) for r in pool.map(hit, range(20))]
    result["concurrency_20_dashboard"] = {**summarize([t for t, ok in out if ok], sum(1 for _, ok in out if not ok)),
                                          "requests_per_second": round(len(out) / (time.perf_counter() - started), 1)}

    if args.ai:
        E["HSN suggestion (model)"] = timed(client, "GET", "/analytics/hsn?item=PVC pipe 2 inch", 12)
        times, errors = [], 0
        for question in ("how many quotations do we have", "who quoted plastic tubing", "which supplier is cheapest for the plumbing request",
                         "what was our total spend", "list my open purchase requests", "show suppliers with late deliveries"):
            t = time.perf_counter()
            r = client.post(BASE + "/assistant/messages", json={"message": question}, timeout=180)
            (times if r.status_code < 400 else []).append(time.perf_counter() - t) if r.status_code < 400 else None
            errors += 0 if r.status_code < 400 else 1
        E["assistant answer (model + tools)"] = summarize(times, errors)
        uploads = {}
        for name in () if not args.uploads else ("quotation_maruti_traders.xlsx", "quotation_new_bharat.pdf", "quotation_balaji_scanned.pdf", "quotation_balaji_hardware.png"):
            path = SAMPLES / name
            t = time.perf_counter()
            r = client.post(BASE + "/documents/upload", files={"file": (name, path.read_bytes())}, timeout=120)
            if r.status_code >= 400:
                uploads[name] = {"error": r.status_code}
                continue
            doc = r.json()
            doc = doc.get("data", doc)
            quote_id = doc.get("id") or (doc.get("quotation") or {}).get("id") or doc.get("quotation_id")
            status = None
            while time.perf_counter() - t < 180:
                status = client.get(BASE + f"/quotations/{quote_id}").json().get("processing_status")
                if status in ("COMPLETED", "REQUIRES_REVIEW", "FAILED"):
                    break
                time.sleep(0.5)
            uploads[name] = {"seconds_to_ready": round(time.perf_counter() - t, 1), "final_status": status}
        result["upload_to_ready"] = uploads

    OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
