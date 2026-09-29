"""Build an Excel ведомость of ditch quantities from the latest report CSVs.

Reads the newest CSV produced by ditch_06_report_cross (cross ditches) and
ditch_06_report_long (longitudinal ditches), and writes one workbook with
one smeta-style sheet per trasse (the Canal label, e.g. "1а"). Each sheet stacks
the cross block then the long block for that trasse. Run with the system Python
(openpyxl), not inside Dynamo:

    python automation/tools/ditch_volumes_to_excel.py
"""

from __future__ import annotations

import csv
import glob
import os
import re
from typing import Optional

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

_ROOT = r"C:\Arhyz\automation\scripts\ditch"
_CROSS_GLOB = os.path.join(
    _ROOT, "ditch_06_report_cross", "logs", "ditch_volumes_*.csv"
)
_LONG_GLOB = os.path.join(
    _ROOT, "ditch_06_report_long", "logs", "longitudinal_volumes_*.csv"
)
_OUT = r"C:\arhyz_s2_data\data\reports\ditch_volumes.xlsx"


def _latest(pattern: str) -> Optional[str]:
    files = glob.glob(pattern)
    return max(files, key=os.path.getmtime) if files else None


_ZONE_ORDER = ["<2500", ">=2500"]
_ZONE_LABEL = {"<2500": "отм. <2500", ">=2500": "отм. ≥2500"}


def _zone_label(zone: str) -> str:
    """Human label for an elevation band, e.g. '<2500' → 'отм. <2500'."""
    return _ZONE_LABEL.get(zone, f"отм. {zone}" if zone else "")


def _read_groups(path: str) -> dict[tuple[str, str], dict[str, float]]:
    """Return {(trasse, zone): {column: value}} for every non-TOTAL row of a report CSV.

    Columns 1–2 are the trasse label and the elevation band; the rest are numeric
    quantities. The TOTAL summary row is skipped — the Excel sheets are split per
    trasse, with one block per band.
    """
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))
    header = rows[0]
    groups: dict[tuple[str, str], dict[str, float]] = {}
    for row in rows[1:]:
        if not row or row[0] == "TOTAL":
            continue
        trasse = row[0]
        zone = row[1] if len(row) > 1 else ""
        vals: dict[str, float] = {}
        for col, val in zip(header[2:], row[2:]):
            try:
                vals[col] = float(val)
            except ValueError:
                vals[col] = 0.0
        groups[(trasse, zone)] = vals
    return groups


def _sheet_name(trasse: str, used: set[str]) -> str:
    """Excel-safe, unique sheet name (≤31 chars, no : \\ / ? * [ ])."""
    name = re.sub(r"[:\\/?*\[\]]", "-", trasse).strip()[:31] or "—"
    base, i = name, 1
    while name in used:
        suffix = f" ({i})"
        name = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(name)
    return name


_HEADER_FILL = PatternFill("solid", fgColor="D9E1F2")
_TITLE_FILL = PatternFill("solid", fgColor="F2F2F2")
_BOLD = Font(bold=True)
_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
_LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
_THIN = Side(style="thin", color="999999")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


def _set_widths(ws) -> None:
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 62
    ws.column_dimensions["C"].width = 12
    ws.column_dimensions["D"].width = 16


def _block(ws, start_row: int, title: str, items: list[tuple[str, str, object]]) -> int:
    """Write a titled smeta block starting at start_row; return the next free row."""
    ws.merge_cells(start_row=start_row, start_column=1, end_row=start_row, end_column=4)
    t = ws.cell(row=start_row, column=1, value=title)
    t.font = _BOLD
    t.fill = _TITLE_FILL
    t.alignment = _CENTER
    ws.row_dimensions[start_row].height = 24

    head_row = start_row + 1
    for col, h in enumerate(["Поз.", "Наименование", "Ед. изм.", "Кол-во"], 1):
        c = ws.cell(row=head_row, column=col, value=h)
        c.font = _BOLD
        c.fill = _HEADER_FILL
        c.alignment = _CENTER
        c.border = _BORDER

    for i, (name, unit, qty) in enumerate(items, 1):
        r = head_row + i
        cells = [
            ws.cell(row=r, column=1, value=i),
            ws.cell(row=r, column=2, value=name),
            ws.cell(row=r, column=3, value=unit),
            ws.cell(row=r, column=4, value=qty),
        ]
        cells[0].alignment = _CENTER
        cells[1].alignment = _LEFT
        cells[2].alignment = _CENTER
        cells[3].alignment = _CENTER
        for c in cells:
            c.border = _BORDER
        ws.row_dimensions[r].height = 30

    return head_row + len(items) + 2  # one blank spacer row before the next block


def _cross_items(t: dict[str, float]) -> list[tuple[str, str, object]]:
    return [
        (
            "Выемка грунта ИГЭ-26а (откопка) в отвал экскаваторами",
            "м³",
            round(t.get("excavation_m3", 0), 2),
        ),
        (
            "Перемещение вынутого грунта 4 гр. до 1 км",
            "тн",
            round(t.get("move_t", 0), 2),
        ),
        (
            "Укрепление канавы щебнем М600 Ø40-70 F200, В15",
            "м³",
            round(t.get("stone_m3", 0), 2),
        ),
        (
            "Укладка геотекстиля (Дорнит) плотностью 200 г/м²",
            "м²",
            round(t.get("geotextile_m2", 0), 2),
        ),
    ]


def _long_items(t: dict[str, float]) -> list[tuple[str, str, object]]:
    mat = f"{int(t.get('mattress_pcs', 0))} / {round(t.get('mattress_m2', 0), 1)}"
    return [
        (
            "Выемка грунта ИГЭ-26а (откопка) в отвал экскаваторами",
            "м³",
            round(t.get("excavation_m3", 0), 2),
        ),
        (
            "Перемещение вынутого грунта 4 гр. до 1 км",
            "тн",
            round(t.get("move_t", 0), 2),
        ),
        (
            "Укладка геотекстиля (Дорнит) плотностью 200 г/м²",
            "м²",
            round(t.get("geotextile_m2", 0), 2),
        ),
        ("Укладка матрацев «Рено» (3×2×0,2)", "шт./м²", mat),
        ("Устройство забивного анкера Ø8мм А248", "шт.", int(t.get("anchor_pcs", 0))),
        (
            "Заполнение матрацев щебнем М600 Ø40-70 F200, В15",
            "м³",
            round(t.get("stone_m3", 0), 2),
        ),
    ]


def main() -> None:
    cross_csv = _latest(_CROSS_GLOB)
    long_csv = _latest(_LONG_GLOB)
    if cross_csv is None and long_csv is None:
        raise SystemExit("No report CSVs found — run the report scripts first.")

    cross = _read_groups(cross_csv) if cross_csv else {}
    long = _read_groups(long_csv) if long_csv else {}

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    trasses = {t for t, _z in cross} | {t for t, _z in long}
    used: set[str] = set()
    for trasse in sorted(trasses):
        ws = wb.create_sheet(_sheet_name(trasse, used))
        _set_widths(ws)
        row = 1
        # zones present for this trasse, known bands first then any unexpected label
        present = {z for t, z in cross if t == trasse} | {
            z for t, z in long if t == trasse
        }
        zones = [z for z in _ZONE_ORDER if z in present]
        zones += sorted(present - set(_ZONE_ORDER))
        for zone in zones:
            band = _zone_label(zone)
            suffix = f" ({band})" if band else ""
            if (trasse, zone) in cross:
                row = _block(
                    ws,
                    row,
                    f"Устройство поперечных водоотводных канав — трасса {trasse}{suffix}",
                    _cross_items(cross[(trasse, zone)]),
                )
            if (trasse, zone) in long:
                row = _block(
                    ws,
                    row,
                    f"Устройство продольных водоотводных канав. Тип 1 — трасса {trasse}{suffix}",
                    _long_items(long[(trasse, zone)]),
                )

    out = _OUT
    try:
        wb.save(out)
    except PermissionError:
        import datetime

        ts = datetime.datetime.now().strftime("%H%M%S")
        out = _OUT.replace(".xlsx", f"_{ts}.xlsx")
        wb.save(out)
        print("(ditch_volumes.xlsx is open/locked — saved a copy instead)")
    print(f"saved -> {out}  ({len(wb.sheetnames)} trasse sheet(s))")
    if cross_csv:
        print(f"  cross  <- {os.path.basename(cross_csv)}")
    if long_csv:
        print(f"  long   <- {os.path.basename(long_csv)}")


if __name__ == "__main__":
    main()
