import System

from Autodesk.AutoCAD.DatabaseServices import (
    IdMapping,
    ObjectIdCollection,
    OpenMode,
    ResultBuffer,
    TypedValue,
)
from Autodesk.AutoCAD.Geometry import Matrix3d, Vector3d


class BlockManager:
    """Manages cloning and placement of cross-section and GSI number blocks."""

    def __init__(
        self, tx, ms, db, source_br_oid, source_gnum_oid, errors, regapp=None, scope=""
    ):
        self.tx = tx
        self.ms = ms
        self.db = db
        self.source_br_oid = source_br_oid
        self.source_gnum_oid = source_gnum_oid
        self.errors = errors
        self.regapp = regapp  # RegApp name tagged on every clone for idempotent re-runs
        self.scope = (
            scope  # canal name stored in the tag so a re-run purges only THIS canal
        )
        src = tx.GetObject(source_br_oid, OpenMode.ForRead)
        self._src_pos = src.Position
        if source_gnum_oid is not None:
            gnum = tx.GetObject(source_gnum_oid, OpenMode.ForRead)
            self._gnum_pos = gnum.Position
        else:
            self._gnum_pos = None

    def _clone(self, src_oid):
        ids = ObjectIdCollection()
        ids.Add(src_oid)
        id_map = IdMapping()
        self.db.DeepCloneObjects(ids, self.db.CurrentSpaceId, id_map, False)
        for pair in id_map:
            if pair.Key == src_oid:
                return pair.Value
        return None

    def _tag(self, br):
        if self.regapp is None:
            return
        try:
            # 1001 = RegApp name, 1000 = the canal name (scope). The 1000 value both makes the
            # XData persist AND lets a re-run purge only THIS canal's blocks, not every canal's.
            br.XData = ResultBuffer(
                TypedValue(1001, self.regapp), TypedValue(1000, self.scope)
            )
        except Exception as e:
            self.errors.append(f"tag XData: {e}")

    def _set_block_params(self, br, flip, pos1x, pos1y):
        for prop in br.DynamicBlockReferencePropertyCollection:
            if prop.ReadOnly:
                continue
            n = prop.PropertyName
            try:
                if n == "Отраженное состояние1":
                    try:
                        prop.Value = System.Int16(int(flip))
                    except Exception:
                        prop.Value = System.Boolean(bool(flip))
                elif n == "Положение1 X":
                    prop.Value = float(pos1x)
                elif n == "Положение1 Y":
                    prop.Value = float(pos1y)
            except Exception as e:
                self.errors.append(f"set {n}: {e}")

    def add_block_ref(self, p, flip, pos1x, pos1y, layer, num=None):
        new_oid = self._clone(self.source_br_oid)
        if new_oid is None:
            self.errors.append(f"DeepClone failed at ({p.X:.1f}, {p.Y:.1f})")
            return
        src_pos = self._src_pos
        br = self.tx.GetObject(new_oid, OpenMode.ForWrite)
        br.Layer = layer
        delta = Vector3d(p.X - src_pos.X, p.Y - src_pos.Y, p.Z - src_pos.Z)
        br.TransformBy(Matrix3d.Displacement(delta))
        self._set_block_params(br, flip, pos1x, pos1y)
        self._tag(br)
        if num is not None:
            # write the point label "т.<n>" into the block attribute (tag Т.NN)
            try:
                for attr_oid in br.AttributeCollection:
                    attr = self.tx.GetObject(attr_oid, OpenMode.ForWrite)
                    attr.TextString = "т.{}".format(num)
            except Exception as e:
                self.errors.append(f"set point num {num}: {e}")

    def add_gnum_ref(self, p, ang, num, layer):
        if self.source_gnum_oid is None:
            return
        new_oid = self._clone(self.source_gnum_oid)
        if new_oid is None:
            self.errors.append(f"DeepClone gnum failed at ({p.X:.1f}, {p.Y:.1f})")
            return
        gnum_pos = self._gnum_pos
        br = self.tx.GetObject(new_oid, OpenMode.ForWrite)
        br.Layer = layer
        delta = Vector3d(p.X - gnum_pos.X, p.Y - gnum_pos.Y, p.Z - gnum_pos.Z)
        br.TransformBy(Matrix3d.Displacement(delta))
        br.Rotation = ang
        self._tag(br)
        try:
            for attr_oid in br.AttributeCollection:
                attr = self.tx.GetObject(attr_oid, OpenMode.ForWrite)
                attr.TextString = str(num)
        except Exception:
            pass
