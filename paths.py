"""Config/data file locations for this toolkit's own scripts -- built on top
of `common/env.py`'s generic `project.env` reader. Only paths this toolkit's
own scripts actually reference; `tube_toolkit` (В-* culverts) has its own
separate registry, not this one.
"""

from __future__ import annotations

import os

from env import data_root

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_DATA_ROOT = data_root(_REPO_ROOT)

CANALS_DIR = os.path.join(_DATA_ROOT, "config", "canals")
TYPES_FILE = os.path.join(_DATA_ROOT, "config", "canal_types.json")
TROUGH_TYPES_FILE = os.path.join(_DATA_ROOT, "config", "trough_types.json")
# Separate gabion type table for Stage 1 (Этап 1) canals -- its key numbers ("10",
# "11", ...) are chosen independently of Stage 2's, and Stage 2 already uses those
# same numbers for trough types in TROUGH_TYPES_FILE (27 existing config/canals/*.json
# reference them). Kept as its own file/dict so the two numbering schemes never merge
# or collide -- see .agents/prompts/canal-model-stage1-type-table.md.
TYPES_FILE_STAGE1 = os.path.join(_DATA_ROOT, "config", "canal_types_stage1.json")
CANALS_DATA_DIR = os.path.join(_DATA_ROOT, "data", "canals")
ALIGNMENT_REPORT_DIR = os.path.join(_DATA_ROOT, "data", "alignment_report")
GSI_BASKETS_FILE = os.path.join(_DATA_ROOT, "config", "gsi_baskets.json")
REPORT_CONFIG_FILE = os.path.join(_DATA_ROOT, "config", "report_config.json")
REPORTS_DIR = os.path.join(_DATA_ROOT, "data", "reports")
