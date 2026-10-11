"""Per-photo state and how photos are grouped onto sheets."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .adjust import Adjustments


@dataclass
class PhotoItem:
    path: str
    copies: int = 1
    center: tuple[float, float] = (0.5, 0.5)  # crop centre, fraction of the photo
    zoom: float = 1.0  # Fill mode only; capped so the print never drops below printer resolution
    # Turn the photo 90° when its orientation doesn't match the cell? None = use the
    # global "Auto-rotate" setting; False = crop it upright instead ("Crop upright").
    turn: bool | None = None
    adjust: Adjustments = field(default_factory=Adjustments)
    # When the photo was taken, read once from EXIF (see photo_date); the file doesn't change.
    taken: datetime | None = None
    taken_checked: bool = False


def sheets(items: list[PhotoItem], per_sheet: int) -> list[list[PhotoItem | None]]:
    """Expand copies in list order, then fill sheets.

    Two-up with one photo x 2 copies -> both halves of one sheet show that photo.
    When the count is odd, the last sheet holds just one photo, printed full size.
    """
    flat = [it for it in items for _ in range(max(1, it.copies))]
    per_sheet = max(1, per_sheet)
    return [list(flat[i:i + per_sheet]) for i in range(0, len(flat), per_sheet)]


def sheet_index_of(items: list[PhotoItem], per_sheet: int, item: PhotoItem) -> int | None:
    """Index of the first sheet that shows `item`."""
    for i, sheet in enumerate(sheets(items, per_sheet)):
        if any(s is item for s in sheet):
            return i
    return None
