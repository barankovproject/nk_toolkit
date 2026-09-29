"""Create a print layout: DWG To PDF, A1 full-bleed (no margins), landscape,
no viewport, frame block ('Ramka') sized to A1 via its dynamic Длина/Высота params,
plot area = Window around the frame extents.

See memory reference_pdf_layout_api for the API gotchas behind this recipe.
"""

from __future__ import annotations

import clr, datetime, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    BlockReference,
    Extents2d,
    LayoutManager,
    OpenMode,
    PlotPaperUnit,
    PlotRotation,
    PlotSettings,
    PlotSettingsValidator,
    PlotType,
)
from Autodesk.AutoCAD.Geometry import Point2d, Point3d, Scale3d

LOG_DIR = r"C:\Arhyz\automation\scripts\help_make_pdf_sheet\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"help_make_pdf_sheet_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

FRAME = "Рамка"  # frame block name (Cyrillic)
LAYOUT_NAME = "TEST_PDF"
A1_LEN, A1_HGT = 841.0, 594.0  # mm, set via dynamic Длина/Высота


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database

lock = doc.LockDocument()
try:
    psv = PlotSettingsValidator.Current
    dwg2pdf = next(
        (d for d in psv.GetPlotDeviceList() if "DWG TO PDF" in d.upper()), None
    )
    log(f"device: {dwg2pdf!r}")

    lm = LayoutManager.Current
    if lm.LayoutExists(LAYOUT_NAME):
        lm.DeleteLayout(LAYOUT_NAME)
    layout_id = lm.CreateLayout(LAYOUT_NAME)
    log(f"created layout '{LAYOUT_NAME}'")

    tx = db.TransactionManager.StartTransaction()
    try:
        layout = tx.GetObject(layout_id, OpenMode.ForWrite)
        ps_btr = tx.GetObject(layout.BlockTableRecordId, OpenMode.ForWrite)

        # --- insert frame first (need its extents for the plot window) ---
        bt = tx.GetObject(db.BlockTableId, OpenMode.ForRead)
        frame_id = None
        for boid in bt:
            if tx.GetObject(boid, OpenMode.ForRead).Name == FRAME:
                frame_id = boid
                break

        fr_min = fr_max = None
        if frame_id is not None:
            br = BlockReference(Point3d(0.0, 0.0, 0.0), frame_id)
            br.ScaleFactors = Scale3d(1.0, 1.0, 1.0)
            ps_btr.AppendEntity(br)
            tx.AddNewlyCreatedDBObject(br, True)
            if br.IsDynamicBlock:
                for p in br.DynamicBlockReferencePropertyCollection:
                    if p.ReadOnly:
                        continue
                    if p.PropertyName == "Длина":
                        p.Value = A1_LEN
                    elif p.PropertyName == "Высота":
                        p.Value = A1_HGT
            ext = br.GeometricExtents
            fr_min, fr_max = ext.MinPoint, ext.MaxPoint
            log(f"frame extents: {fr_min} .. {fr_max}")
        else:
            log(f"block {FRAME!r} NOT found")

        # --- plot settings: device, A1 full-bleed, landscape, window = frame ---
        ps = PlotSettings(layout.ModelType)
        ps.CopyFrom(layout)
        if dwg2pdf:
            psv.SetPlotConfigurationName(ps, dwg2pdf, None)
            psv.RefreshLists(ps)
        media = list(psv.GetCanonicalMediaNameList(ps))
        a1 = next((m for m in media if "iso_full_bleed_a1_(841" in m.lower()), None)
        if a1:
            psv.SetCanonicalMediaName(ps, a1)
        psv.SetPlotPaperUnits(ps, PlotPaperUnit.Millimeters)
        psv.SetPlotRotation(
            ps, PlotRotation.Degrees000
        )  # media 841x594 is landscape natively
        if fr_min is not None:
            # window area must be set BEFORE switching plot type to Window (else eInvalidInput)
            psv.SetPlotWindowArea(
                ps, Extents2d(Point2d(fr_min.X, fr_min.Y), Point2d(fr_max.X, fr_max.Y))
            )
            psv.SetPlotType(ps, PlotType.Window)
            log(
                f"plot window: ({fr_min.X:.2f},{fr_min.Y:.2f}) .. ({fr_max.X:.2f},{fr_max.Y:.2f})"
            )
        layout.CopyFrom(ps)
        log(f"media={a1!r}  rotation=0 (landscape)  type=Window")
        log(f"paper: {layout.PlotPaperSize}  margins: {layout.PlotPaperMargins}")

        # --- remove the auto-added viewport(s) (keep overall #1) ---
        to_erase = []
        for oid in ps_btr:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            if type(ent).__name__ == "Viewport" and ent.Number != 1:
                to_erase.append(oid)
        for oid in to_erase:
            tx.GetObject(oid, OpenMode.ForWrite).Erase()
        log(f"erased {len(to_erase)} auto viewport(s)")

        tx.Commit()
        log("transaction committed")
    except Exception as e:
        log(f"ERROR: {e}")
        log(traceback.format_exc())
        tx.Abort()
    finally:
        tx.Dispose()

    lm.CurrentLayout = LAYOUT_NAME
    log(f"set current layout: {LAYOUT_NAME}")
finally:
    lock.Dispose()

log("\n=== DONE ===")
OUT = LOG_FILE
