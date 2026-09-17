"""GSTIN (Indian GST identification number) rules.

Format: 2-digit state code, 10-character PAN, 1 entity code (1-9 or A-Z),
the letter Z, and a checksum character that can be a letter OR a digit.
"""
from __future__ import annotations

import re
from typing import Optional

GSTIN_PATTERN = r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]"
_GSTIN_RE = re.compile(rf"^{GSTIN_PATTERN}$")
# For finding GSTINs inside free text (case-insensitive; normalise afterwards).
GSTIN_SEARCH_RE = re.compile(rf"\b{GSTIN_PATTERN}\b", re.IGNORECASE)

STATE_CODES: dict[str, str] = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan",
    "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
    "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura",
    "17": "Meghalaya", "18": "Assam", "19": "West Bengal", "20": "Jharkhand",
    "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman and Diu",
    "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra",
    "28": "Andhra Pradesh (before 2014)", "29": "Karnataka", "30": "Goa",
    "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh",
    "38": "Ladakh", "97": "Other Territory", "99": "Centre Jurisdiction",
}


def normalize_gstin(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = re.sub(r"\s+", "", str(value)).upper()
    return cleaned or None


def is_valid_gstin(value: Optional[str]) -> bool:
    normalized = normalize_gstin(value)
    return bool(normalized and _GSTIN_RE.match(normalized))


def state_code(value: Optional[str]) -> Optional[str]:
    normalized = normalize_gstin(value)
    if not normalized or not _GSTIN_RE.match(normalized):
        return None
    return normalized[:2]


def state_name(value: Optional[str]) -> Optional[str]:
    code = state_code(value)
    return STATE_CODES.get(code) if code else None
