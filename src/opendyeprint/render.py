"""Turn photos into the exact pixels for one sheet (for printing or preview)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from . import adjust, datestamp
from .color import ColorSettings, to_printer, to_working_rgb
from .layout import (Cell, FitMode, Placement, cells, max_zoom, place, polaroid_frame, rotate_center,
                     should_rotate)
from .model import PhotoItem

Image.MAX_IMAGE_PIXELS = 400_000_000  # large panoramas are legitimate input

try:  # iPhone HEIC/HEIF support (pi-heif: decode-only build of pillow-heif, no GPL encoder)
    import pi_heif

    pi_heif.register_heif_opener()
    HEIF_SUPPORTED = True
except ImportError:  # pragma: no cover - optional at runtime
    HEIF_SUPPORTED = False

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}
if HEIF_SUPPORTED:
    IMAGE_EXTS |= {".heic", ".heif"}

SRGB = ColorSettings(printer_profile=None)


@dataclass(frozen=True)
class RenderSettings:
    fit: FitMode = FitMode.FILL
    auto_rotate: bool = True
    color: ColorSettings = SRGB
    per_sheet: int = 1
    gap_mm: float = 1.0  # between the photos of a two-up sheet
    polaroid: bool = False  # one square photo in a full-width Polaroid frame
    date_style: str | None = None  # key into datestamp.STYLES; None = no date


@dataclass
class CellInfo:
    """What ended up in one cell — used by the preview for crop dragging."""

    cell: Cell
    item: PhotoItem | None
    rotated: bool = False
    src_size: tuple[int, int] = (0, 0)  # photo size before rotation
    placement: Placement | None = None


def load(path: str | Path) -> Image.Image:
    """Open a photo with EXIF orientation applied; keeps the embedded ICC profile."""
    img = Image.open(path)
    icc = img.info.get("icc_profile")
    img = ImageOps.exif_transpose(img)
    img.load()
    if icc:
        img.info["icc_profile"] = icc
    return img


def compose_cell(img: Image.Image, cw: int, ch: int, item: PhotoItem, settings: RenderSettings,
                 target: ColorSettings, resample=Image.Resampling.LANCZOS,
                 cap_zoom: bool = False) -> tuple[Image.Image, CellInfo]:
    """The photo for one cell, exactly cw x ch on white, converted into `target` space.

    cap_zoom: the cell is in printer pixels and `img` is full resolution, so enforce
    the zoom limit (never fewer photo pixels than printer pixels).
    """
    rgb, icc = to_working_rgb(img)
    src_size = rgb.size
    center = item.center
    rotated = settings.auto_rotate and should_rotate(rgb.width, rgb.height, cw, ch)
    if rotated:
        # Clockwise, so the preview can turn the sheet back counter-clockwise and the
        # first photo of a two-up sheet reads on the left.
        rgb = rgb.transpose(Image.Transpose.ROTATE_270)
        center = rotate_center(center)
    zoom = item.zoom
    if cap_zoom:
        zoom = min(zoom, max_zoom(rgb.width, rgb.height, cw, ch))
    p = place(rgb.width, rgb.height, cw, ch, settings.fit, center, zoom)
    w, h = p.dest_size
    # Lanczos with the crop box: resamples from the original pixels in one pass.
    out = rgb.resize((w, h), resample, box=p.crop, reducing_gap=None)
    out = adjust.apply(out, item.adjust)
    if settings.date_style in datestamp.STYLES:
        when = datestamp.capture_date(img)
        if when is not None:
            # Stamp in the photo's own upright orientation (undo the turn onto the sheet).
            if rotated:
                out = out.transpose(Image.Transpose.ROTATE_90)
            out = datestamp.stamp(out, when, settings.date_style)
            if rotated:
                out = out.transpose(Image.Transpose.ROTATE_270)
    out = to_printer(out, icc, target)
    canvas = Image.new("RGB", (cw, ch), (255, 255, 255))
    canvas.paste(out, p.dest[:2])
    return canvas, CellInfo(Cell(0, 0, cw, ch), item, rotated, src_size, p)


def compose_sheet(photos: list[tuple[Image.Image, PhotoItem] | None], area_w: int, area_h: int,
                  gap_px: int, settings: RenderSettings, target: ColorSettings,
                  resample=Image.Resampling.LANCZOS,
                  cap_zoom: bool = False) -> tuple[Image.Image, list[CellInfo]]:
    """Compose a whole printable area. `photos` has one entry per cell (None = empty);
    a single entry fills the whole sheet, two entries split it."""
    sheet = Image.new("RGB", (area_w, area_h), (255, 255, 255))
    infos = []
    for cell, entry in zip(photo_cells(area_w, area_h, len(photos), gap_px, settings.polaroid), photos):
        if entry is None:
            infos.append(CellInfo(cell, None))
            continue
        img, item = entry
        canvas, info = compose_cell(img, cell.w, cell.h, item, settings, target, resample, cap_zoom)
        sheet.paste(canvas, (cell.x, cell.y))
        info.cell = cell
        infos.append(info)
    if settings.polaroid:
        draw_cut_line(sheet, polaroid_frame(area_w, area_h).cut_y)
    return sheet, infos


def photo_cells(area_w: int, area_h: int, n: int, gap_px: int, polaroid: bool) -> list[Cell]:
    """Where the photos of one sheet go."""
    if polaroid:
        return [polaroid_frame(area_w, area_h).photo]
    return cells(area_w, area_h, n, gap_px)


def draw_cut_line(sheet: Image.Image, y: int) -> None:
    """Thin dashed grey line across the sheet, to cut the Polaroid off along."""
    d = ImageDraw.Draw(sheet)
    dash = max(2, round(sheet.width * 0.03))
    width = max(1, round(sheet.width / 600))
    for x in range(0, sheet.width, dash * 2):
        d.line((x, y, min(x + dash, sheet.width), y), fill=(160, 160, 160), width=width)


def gap_pixels(gap_mm: float, dpi: int) -> int:
    return round(gap_mm / 25.4 * dpi)


def render_sheet_for_print(items: list[PhotoItem | None], area_w: int, area_h: int, dpi: int,
                           settings: RenderSettings) -> Image.Image:
    photos = [(load(it.path), it) if it is not None else None for it in items]
    sheet, _ = compose_sheet(photos, area_w, area_h, gap_pixels(settings.gap_mm, dpi),
                             settings, settings.color, cap_zoom=True)
    return sheet
