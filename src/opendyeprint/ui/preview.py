"""Sheet preview: paper, printable area, the composed photos, and crop dragging."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..color import ColorSettings
from ..layout import FitMode, PageGeometry, effective_center, rotate_center, unrotate_center
from ..model import PhotoItem
from ..render import CellInfo, RenderSettings, compose_sheet, gap_pixels

PREVIEW_LONG_SIDE = 1100  # pixels; plenty for a sharp on-screen sheet


def pil_to_qimage(img: Image.Image) -> QImage:
    img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    return QImage(data, img.width, img.height, img.width * 3, QImage.Format.Format_RGB888).copy()


@dataclass
class PreviewSheet:
    image: Image.Image  # what is displayed (possibly turned to landscape)
    sheet_size: tuple[int, int]  # unturned sheet size in preview pixels
    turned: bool  # displayed turned 90° counter-clockwise
    infos: list[CellInfo]  # cells in unturned sheet coordinates
    fit: FitMode

    def display_to_sheet(self, x: float, y: float) -> tuple[float, float]:
        if not self.turned:
            return x, y
        pw, _ = self.sheet_size
        return pw - 1 - y, x

    def display_delta_to_sheet(self, dx: float, dy: float) -> tuple[float, float]:
        return (-dy, dx) if self.turned else (dx, dy)

    def cell_at(self, x: float, y: float) -> CellInfo | None:
        sx, sy = self.display_to_sheet(x, y)
        for info in self.infos:
            c = info.cell
            if c.x <= sx < c.x + c.w and c.y <= sy < c.y + c.h:
                return info
        return None


def render_preview(photos: list[tuple[Image.Image, PhotoItem] | None], geom: PageGeometry,
                   settings: RenderSettings, borderless: bool, target: ColorSettings,
                   fast: bool = False) -> PreviewSheet:
    """Scaled picture of the whole sheet. Turned to landscape when the first photo was
    rotated onto the sheet, so photos read upright on screen."""
    s = PREVIEW_LONG_SIDE / max(geom.physical_w, geom.physical_h)
    pw, ph = max(1, round(geom.physical_w * s)), max(1, round(geom.physical_h * s))
    ax, ay = round(geom.offset_x * s), round(geom.offset_y * s)
    aw, ah = max(1, round(geom.printable_w * s)), max(1, round(geom.printable_h * s))
    gap = round(gap_pixels(settings.gap_mm, geom.dpi_x) * s)

    sheet = Image.new("RGB", (pw, ph), (255, 255, 255))
    resample = Image.Resampling.BILINEAR if fast else Image.Resampling.LANCZOS
    area, infos = compose_sheet(photos, aw, ah, gap, settings, target, resample)
    sheet.paste(area, (ax, ay))
    for info in infos:  # to sheet coordinates
        c = info.cell
        info.cell = type(c)(c.x + ax, c.y + ay, c.w, c.h)

    d = ImageDraw.Draw(sheet)
    if not borderless and (ax or ay or aw != pw or ah != ph):
        _dashed_rect(d, ax, ay, aw, ah)
    for info in infos:
        if info.item is None:  # empty half of a two-up sheet
            c = info.cell
            _dashed_rect(d, c.x + 6, c.y + 6, c.w - 12, c.h - 12)

    turned = next((i.rotated for i in infos if i.item is not None), False)
    shown = sheet.transpose(Image.Transpose.ROTATE_90) if turned else sheet
    return PreviewSheet(shown, (pw, ph), turned, infos, settings.fit)


def _dashed_rect(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int) -> None:
    col = (170, 170, 170)
    for xx in range(x, x + w, 12):
        d.line((xx, y, min(xx + 6, x + w), y), fill=col)
        d.line((xx, y + h - 1, min(xx + 6, x + w), y + h - 1), fill=col)
    for yy in range(y, y + h, 12):
        d.line((x, yy, x, min(yy + 6, y + h)), fill=col)
        d.line((x + w - 1, yy, x + w - 1, min(yy + 6, y + h)), fill=col)


def dragged_center(info: CellInfo, start_center: tuple[float, float],
                   dx_sheet: float, dy_sheet: float) -> tuple[float, float]:
    """New crop centre after dragging the photo by (dx, dy) sheet pixels.

    Dragging moves the photo with the mouse, so the crop window moves the other way.
    """
    w, h = info.src_size
    if info.rotated:
        w, h = h, w
        center = rotate_center(start_center)
    else:
        center = start_center
    l, t, r, b = info.placement.crop
    dw, dh = info.placement.dest_size
    photo_px_per_cell_px = (r - l) / dw if dw else 0.0
    u = center[0] - dx_sheet * photo_px_per_cell_px / w
    v = center[1] - dy_sheet * ((b - t) / dh if dh else 0.0) / h
    u, v = effective_center(w, h, info.cell.w, info.cell.h, (u, v), info.item.zoom)
    return unrotate_center((u, v)) if info.rotated else (u, v)


class PreviewWidget(QWidget):
    """Shows a PreviewSheet; click selects a photo, drag moves its crop (Fill mode)."""

    photo_clicked = Signal(object)  # PhotoItem
    crop_dragging = Signal(object, tuple)  # PhotoItem, new centre (live)
    crop_dropped = Signal(object, tuple)  # PhotoItem, final centre
    zoom_wheel = Signal(object, float)  # PhotoItem, wheel steps (+ = zoom in)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sheet: PreviewSheet | None = None
        self._image: QImage | None = None
        self._target = QRectF()
        self._message = "Add photos to get started"
        self._drag: tuple[CellInfo, QPointF, tuple[float, float]] | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(320, 320)
        self.setMouseTracking(True)

    def set_sheet(self, sheet: PreviewSheet | None, message: str = "") -> None:
        self._sheet = sheet
        self._image = pil_to_qimage(sheet.image) if sheet is not None else None
        self._message = message
        self.update()

    def is_dragging(self) -> bool:
        return self._drag is not None

    # -- geometry --

    def _layout(self) -> QRectF:
        if self._image is None:
            return QRectF()
        margin = 24
        s = min((self.width() - 2 * margin) / self._image.width(),
                (self.height() - 2 * margin) / self._image.height())
        w, h = self._image.width() * s, self._image.height() * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _to_image(self, p: QPointF) -> tuple[float, float] | None:
        r = self._layout()
        if r.isEmpty() or not r.contains(p):
            return None
        k = self._image.width() / r.width()
        return (p.x() - r.x()) * k, (p.y() - r.y()) * k

    def _scale(self) -> float:
        r = self._layout()
        return self._image.width() / r.width() if r.width() else 1.0

    # -- events --

    def paintEvent(self, event):  # noqa: N802 (Qt naming)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), self.palette().window().color().darker(108))
        if self._image is None:
            p.setPen(self.palette().text().color())
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._message)
            return
        target = self._layout()
        p.fillRect(target.translated(4, 4), QColor(0, 0, 0, 60))  # drop shadow
        p.drawImage(target, self._image)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton or self._sheet is None:
            return
        pt = self._to_image(e.position())
        info = self._sheet.cell_at(*pt) if pt else None
        if info is None or info.item is None:
            return
        self.photo_clicked.emit(info.item)
        if self._sheet.fit is FitMode.FILL and info.placement is not None:
            self._drag = (info, e.position(), info.item.center)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag is None:
            self._update_hover_cursor(e.position())
            return
        info, start, start_center = self._drag
        k = self._scale()
        dx, dy = (e.position().x() - start.x()) * k, (e.position().y() - start.y()) * k
        sdx, sdy = self._sheet.display_delta_to_sheet(dx, dy)
        self.crop_dragging.emit(info.item, dragged_center(info, start_center, sdx, sdy))

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self._drag is None:
            return
        info, start, start_center = self._drag
        k = self._scale()
        dx, dy = (e.position().x() - start.x()) * k, (e.position().y() - start.y()) * k
        sdx, sdy = self._sheet.display_delta_to_sheet(dx, dy)
        self._drag = None
        self._update_hover_cursor(e.position())
        self.crop_dropped.emit(info.item, dragged_center(info, start_center, sdx, sdy))

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        """Double-click re-centres the crop."""
        pt = self._to_image(e.position()) if self._sheet else None
        info = self._sheet.cell_at(*pt) if pt else None
        if info and info.item is not None:
            self._drag = None
            self.crop_dropped.emit(info.item, (0.5, 0.5))

    def wheelEvent(self, e):  # noqa: N802
        """Mouse wheel over a photo zooms it (Fill mode)."""
        pt = self._to_image(e.position()) if self._sheet else None
        info = self._sheet.cell_at(*pt) if pt else None
        if info is None or info.item is None or self._sheet.fit is not FitMode.FILL:
            return super().wheelEvent(e)
        self.zoom_wheel.emit(info.item, e.angleDelta().y() / 120)
        e.accept()

    def _update_hover_cursor(self, pos: QPointF):
        pt = self._to_image(pos) if self._sheet else None
        info = self._sheet.cell_at(*pt) if pt else None
        if info and info.item is not None and self._sheet.fit is FitMode.FILL:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()
