"""Pure geometry: where a photo goes on the printable area of a sheet."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FitMode(str, Enum):
    FILL = "fill"  # cover the whole area, crop the overflow (centred)
    FIT = "fit"  # show the whole photo, leave white space


@dataclass(frozen=True)
class PageGeometry:
    """Device geometry in printer pixels, as reported by the driver."""

    dpi_x: int
    dpi_y: int
    physical_w: int
    physical_h: int
    offset_x: int  # left edge of printable area, from the paper edge
    offset_y: int
    printable_w: int
    printable_h: int

    @property
    def physical_mm(self) -> tuple[float, float]:
        return (self.physical_w / self.dpi_x * 25.4, self.physical_h / self.dpi_y * 25.4)


@dataclass(frozen=True)
class Placement:
    """crop: box in source pixels (l, t, r, b); dest: box in printable-area pixels."""

    crop: tuple[float, float, float, float]
    dest: tuple[int, int, int, int]

    @property
    def dest_size(self) -> tuple[int, int]:
        return (self.dest[2] - self.dest[0], self.dest[3] - self.dest[1])


def should_rotate(src_w: int, src_h: int, area_w: int, area_h: int) -> bool:
    """True when the photo's orientation doesn't match the area's (ignoring squares)."""
    if src_w == src_h or area_w == area_h:
        return False
    return (src_w > src_h) != (area_w > area_h)


def place(src_w: int, src_h: int, area_w: int, area_h: int, mode: FitMode,
          center: tuple[float, float] = (0.5, 0.5), zoom: float = 1.0) -> Placement:
    """Where the photo goes in an area.

    center: for FILL, the desired crop centre as a fraction of the photo (0..1 per
    axis); it is clamped so the crop stays inside the photo. Ignored for FIT.
    zoom: for FILL, >= 1 shrinks the crop (zooms in). Ignored for FIT.
    """
    if src_w <= 0 or src_h <= 0 or area_w <= 0 or area_h <= 0:
        raise ValueError("sizes must be positive")
    src_ratio = src_w / src_h
    area_ratio = area_w / area_h

    if mode is FitMode.FILL:
        if src_ratio > area_ratio:  # photo is wider: crop the sides
            crop_w, crop_h = src_h * area_ratio, float(src_h)
        else:  # photo is taller: crop top and bottom
            crop_w, crop_h = float(src_w), src_w / area_ratio
        z = max(1.0, zoom)
        crop_w, crop_h = crop_w / z, crop_h / z
        x0 = _clamp(center[0] * src_w - crop_w / 2, 0.0, src_w - crop_w)
        y0 = _clamp(center[1] * src_h - crop_h / 2, 0.0, src_h - crop_h)
        return Placement((x0, y0, x0 + crop_w, y0 + crop_h), (0, 0, area_w, area_h))

    scale = min(area_w / src_w, area_h / src_h)
    w = max(1, round(src_w * scale))
    h = max(1, round(src_h * scale))
    x = (area_w - w) // 2
    y = (area_h - h) // 2
    return Placement((0.0, 0.0, float(src_w), float(src_h)), (x, y, x + w, y + h))


def effective_center(src_w: int, src_h: int, area_w: int, area_h: int,
                     center: tuple[float, float], zoom: float = 1.0) -> tuple[float, float]:
    """The crop centre FILL would actually use (after clamping)."""
    l, t, r, b = place(src_w, src_h, area_w, area_h, FitMode.FILL, center, zoom).crop
    return ((l + r) / 2 / src_w, (t + b) / 2 / src_h)


def max_zoom(src_w: int, src_h: int, area_w: int, area_h: int) -> float:
    """Largest FILL zoom that still has at least one photo pixel per printer pixel.

    area_* must be in printer pixels. Beyond this the printer would be upscaling the
    photo and the print gets softer, so zoom is capped here (1.0 = no room to zoom).
    """
    l, t, r, b = place(src_w, src_h, area_w, area_h, FitMode.FILL).crop
    return max(1.0, (r - l) / area_w)


def rotate_center(center: tuple[float, float]) -> tuple[float, float]:
    """Map a fractional point of a photo to the same point after turning the photo
    90° clockwise (PIL's ROTATE_270), which is how photos are turned onto a sheet."""
    u, v = center
    return (1.0 - v, u)


def unrotate_center(center: tuple[float, float]) -> tuple[float, float]:
    u, v = center
    return (v, 1.0 - u)


@dataclass(frozen=True)
class Cell:
    x: int
    y: int
    w: int
    h: int


def cells(area_w: int, area_h: int, per_sheet: int, gap: int = 0) -> list[Cell]:
    """Split the printable area into equal cells along its long side."""
    if per_sheet <= 1:
        return [Cell(0, 0, area_w, area_h)]
    if per_sheet != 2:
        raise ValueError("only 1 or 2 photos per sheet are supported")
    gap = max(0, gap)
    if area_h >= area_w:  # portrait sheet: stack top / bottom
        h1 = (area_h - gap) // 2
        return [Cell(0, 0, area_w, h1), Cell(0, area_h - h1, area_w, h1)]
    w1 = (area_w - gap) // 2
    return [Cell(0, 0, w1, area_h), Cell(area_w - w1, 0, w1, area_h)]


# Classic Polaroid (600 / i-Type) frame: 88 x 107 mm with a 79 mm square photo,
# 4.5 mm white at the sides and 5.5 mm at the top; the rest is the wide bottom margin.
POLAROID_W, POLAROID_H, POLAROID_SIDE, POLAROID_TOP = 88.0, 107.0, 4.5, 5.5


@dataclass(frozen=True)
class PolaroidFrame:
    photo: Cell  # the square photo
    x: int  # frame left edge
    w: int  # frame width
    cut_y: int  # bottom edge of the frame: cut the sheet here


def polaroid_frame(area_w: int, area_h: int) -> PolaroidFrame:
    """Polaroid proportions scaled to the full width of the area (top-aligned), so only
    the bottom of the sheet needs cutting off. Falls back to full height if too tall."""
    fw = area_w
    if round(fw * POLAROID_H / POLAROID_W) > area_h:
        fw = int(area_h * POLAROID_W / POLAROID_H)
    x = (area_w - fw) // 2
    side = round(fw * POLAROID_SIDE / POLAROID_W)
    top = round(fw * POLAROID_TOP / POLAROID_W)
    sq = fw - 2 * side
    return PolaroidFrame(Cell(x + side, top, sq, sq), x, fw, round(fw * POLAROID_H / POLAROID_W))


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))
