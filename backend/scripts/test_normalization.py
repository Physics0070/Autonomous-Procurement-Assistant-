"""Stage test: deterministic normalisation + fuzzy similarity."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.services.procurement.normalization import (  # noqa: E402
    convert_quantity, normalize_text, normalize_unit, similarity,
)

VARIANTS = [
    "PVC Pipe 2 inch",
    '2" PVC PIPE',
    "PVC PIPE - 2 INCH",
    "PVC \u092a\u093e\u0907\u092a 2 \u0907\u0902\u091a",
    '2" PVC PIPE CLASS 2',
    "PVCPIPE-2INCH",
]

DIFFERENT = [
    ("PVC Pipe 2 inch", "PVC Pipe 3 inch"),
    ("PVC Pipe 2 inch", "PVC Elbow 2 inch"),
    ("PVC Pipe 2 inch", "Solvent Cement 500ml"),
    ("PVC Pipe 2 inch", "GI Pipe 2 inch"),
]

UNITS = ["Nos", "PCS", "BOTTLE", "Btl", "\u0928\u0917", "kgs", "Ltr", "ML", "inch", '"', "dozen", "banana"]


def main() -> int:
    print("=" * 78)
    print("LAYER 1 - deterministic normalisation")
    print("=" * 78)
    for v in VARIANTS:
        print(f"  {v!r:34s} -> {normalize_text(v)!r}")

    print("\n" + "=" * 78)
    print("UNIT normalisation + base conversion")
    print("=" * 78)
    for u in UNITS:
        qty, base = convert_quantity(10, u)
        print(f"  {u!r:10s} -> canonical={normalize_unit(u)!r:10s} 10{u} = {qty} {base}")

    print("\n" + "=" * 78)
    print("LAYER 2 - similarity of EQUIVALENT products (expect high)")
    print("=" * 78)
    base = VARIANTS[0]
    ok = True
    for v in VARIANTS[1:]:
        s = similarity(base, v)
        flag = "OK " if s >= 0.62 else "LOW"
        if s < 0.62:
            ok = False
        print(f"  [{flag}] {s:.3f}  {base!r} ~ {v!r}")

    print("\n" + "=" * 78)
    print("Similarity of DIFFERENT products (expect low)")
    print("=" * 78)
    for a, b in DIFFERENT:
        s = similarity(a, b)
        flag = "OK " if s < 0.86 else "HIGH"
        if s >= 0.86:
            ok = False
        print(f"  [{flag}] {s:.3f}  {a!r} ~ {b!r}")

    print("\nRESULT:", "PASS" if ok else "NEEDS TUNING")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
