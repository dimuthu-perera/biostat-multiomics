from __future__ import annotations
import hashlib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = root / "ORACLE_SOURCE_SHA256.txt"
failures = []
for raw in manifest.read_text(encoding="utf-8").splitlines():
    raw = raw.strip()
    if not raw:
        continue
    digest, rel = raw.split(maxsplit=1)
    rel = rel.lstrip("* ")
    path = root / rel
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != digest:
        failures.append((rel, digest, actual))
if failures:
    for rel, expected, actual in failures:
        print(f"FAIL {rel}: expected {expected}, got {actual}")
    raise SystemExit(1)
print("Frozen oracle hashes: OK")
