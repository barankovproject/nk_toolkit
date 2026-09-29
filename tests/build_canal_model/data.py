"""Shared test input data for build_canal_model tests."""

from __future__ import annotations

# --- _rib_records inputs ---
# one gabion segment 0..20 m with ribs, type 5
SEG = {"from": "PK0+00.00", "to": "PK0+20.00", "type": 5, "ribs": True}
# type → cross-section params (only bottom_w is read by _rib_records)
CFG = {"5": {"bottom_w": 2.0}}
# widening with staggered ribs (b=5 → n_a=2, n_b=1, rib_len=2.0)
WIDENING = {"b": 5.0, "length": 10.0, "ribs": True}
