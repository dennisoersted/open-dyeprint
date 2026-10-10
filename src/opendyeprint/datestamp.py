"""Retro date imprint, like a 90s compact camera with a date back.

Digits are drawn as glowing seven-segment glyphs (no font files needed), sized
relative to the photo so the stamp looks the same in preview and print.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from PIL import Image, ImageDraw, ImageFilter

EXIF_IFD = 0x8769
DATETIME_ORIGINAL = 0x9003
DATETIME = 0x0132


def capture_date(img: Image.Image) -> datetime | None:
    """When the photo was taken, from EXIF (None if the file doesn't say).

    Tries DateTimeOriginal first and falls back to DateTime, so a blank or broken
    original date doesn't hide a good one.
    """
    try:
        exif = img.getexif()
        candidates = (exif.get_ifd(EXIF_IFD).get(DATETIME_ORIGINAL), exif.get(DATETIME))
    except Exception:  # noqa: BLE001 - broken EXIF is common; just no date
        return None
    for raw in candidates:
        when = parse_exif_date(raw) if raw else None
        if when is not None:
            return when
    return None


def photo_date(img: Image.Image, item) -> datetime | None:
    """capture_date, remembered on the PhotoItem so previews don't re-read EXIF every frame."""
    if not item.taken_checked:
        item.taken = capture_date(img)
        item.taken_checked = True
    return item.taken


# YYYY?MM?DD, optionally followed by " HH:MM[:SS]" or "THH:MM[:SS]". EXIF uses ":" in the
# date, some apps (e.g. RapidRaw) use "-", and not everyone zero-pads.
_DATE_RE = re.compile(r"(\d{4})[:\-/](\d{1,2})[:\-/](\d{1,2})(?:[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?")


def parse_exif_date(raw) -> datetime | None:
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", errors="ignore")
    m = _DATE_RE.match(str(raw).strip("\x00 "))
    if not m:
        return None
    y, mo, d, h, mi, s = (int(v) if v else 0 for v in m.groups())
    try:
        return datetime(y, mo, d, h, mi, s)
    except ValueError:
        try:  # a broken time shouldn't throw away a good date
            return datetime(y, mo, d)
        except ValueError:
            return None


def date_text(d: datetime) -> str:
    return f"{d:%d/%m/%Y}"


@dataclass(frozen=True)
class StampStyle:
    label: str
    glyphs: str  # "segments" (LCD) or "dots" (dot matrix)
    core: tuple[int, int, int]  # bright centre of the digits
    glow: tuple[int, int, int]  # halo colour


STYLES: dict[str, StampStyle] = {
    "orange": StampStyle("Orange LCD", "segments", (255, 160, 50), (255, 90, 0)),
    "red": StampStyle("Red LCD", "segments", (255, 80, 60), (220, 20, 10)),
    "yellow": StampStyle("Yellow LCD", "segments", (255, 225, 90), (255, 170, 0)),
    "dots": StampStyle("Orange dot matrix", "dots", (255, 170, 60), (255, 100, 0)),
}

# 5 x 7 dot-matrix glyphs (rows top to bottom, "#" = lit dot).
_DOTS = {
    "0": [".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."],
    "1": ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "2": [".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"],
    "3": ["#####", "...#.", "..#..", "...#.", "....#", "#...#", ".###."],
    "4": ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."],
    "5": ["#####", "#....", "####.", "....#", "....#", "#...#", ".###."],
    "6": ["..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."],
    "7": ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
    "8": [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."],
    "9": [".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."],
    "/": ["....#", "....#", "...#.", "..#..", ".#...", "#....", "#...."],
}

# Seven-segment layout: which segments light up for each digit.
_SEGMENTS = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd",
             "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg"}

DIGIT_W = 0.5  # digit width as a fraction of its height
STROKE = 0.15  # segment thickness as a fraction of height
SLANT = 0.1


def _bar(x1, y1, x2, y2, t):
    """Segment with pointed ends between two points (horizontal or vertical)."""
    if y1 == y2:
        return [(x1, y1), (x1 + t / 2, y1 - t / 2), (x2 - t / 2, y1 - t / 2), (x2, y1),
                (x2 - t / 2, y1 + t / 2), (x1 + t / 2, y1 + t / 2)]
    return [(x1, y1), (x1 + t / 2, y1 + t / 2), (x1 + t / 2, y2 - t / 2), (x1, y2),
            (x1 - t / 2, y2 - t / 2), (x1 - t / 2, y1 + t / 2)]


def _advance(ch: str, h: float, glyphs: str = "segments") -> float:
    if glyphs == "dots":
        return h / 7 * 6  # 5 dots + 1 dot of spacing
    w, t = h * DIGIT_W, h * STROKE
    if ch == " ":
        return w * 1.1
    if ch in "'.":
        return t * 2.2
    if ch == "/":
        return w * 0.7 + t * 2.2
    return w + t * 2.2


def text_width(text: str, h: float, glyphs: str = "segments") -> float:
    return sum(_advance(c, h, glyphs) for c in text)


def draw_dots(d: ImageDraw.ImageDraw, x: float, y: float, h: float, text: str, fill) -> None:
    pitch = h / 7
    r = pitch * 0.42
    for ch in text:
        for row, line in enumerate(_DOTS.get(ch, [])):
            for col, c in enumerate(line):
                if c == "#":
                    cx = x + col * pitch + pitch / 2 + SLANT * (h - row * pitch)
                    cy = y + row * pitch + pitch / 2
                    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)
        x += _advance(ch, h, "dots")


def draw_digits(d: ImageDraw.ImageDraw, x: float, y: float, h: float, text: str, fill) -> None:
    w, t = h * DIGIT_W, h * STROKE
    g = t * 0.25  # small gap between segments

    for ch in text:
        def P(px, py, x=x):
            return (x + px + SLANT * (h - py), y + py)

        if ch == "'":
            d.polygon([P(t * 0.2, 0), P(t * 1.2, 0), P(t * 0.6, h * 0.32), P(-t * 0.2, h * 0.32)], fill=fill)
        elif ch == ".":
            d.polygon([P(0, h - t), P(t, h - t), P(t, h), P(0, h)], fill=fill)
        elif ch == "/":
            sw = w * 0.7
            d.polygon([P(sw - t * 0.6, 0), P(sw + t * 0.4, 0), P(t * 0.6, h), P(-t * 0.4, h)], fill=fill)
        elif ch in _SEGMENTS:
            m = h / 2
            segs = {
                "a": _bar(g, 0, w - g, 0, t), "g": _bar(g, m, w - g, m, t), "d": _bar(g, h, w - g, h, t),
                "f": _bar(0, g, 0, m - g, t), "e": _bar(0, m + g, 0, h - g, t),
                "b": _bar(w, g, w, m - g, t), "c": _bar(w, m + g, w, h - g, t),
            }
            for s in _SEGMENTS[ch]:
                d.polygon([P(px, py) for px, py in segs[s]], fill=fill)
        x += _advance(ch, h)


def stamp(img: Image.Image, when: datetime, style_key: str) -> Image.Image:
    """Return a copy of an upright RGB photo with the date in its bottom-right corner."""
    style = STYLES[style_key]
    text = date_text(when)
    short = min(img.size)
    h = max(6.0, short * 0.035)  # digit height: 3.5 % of the short side
    margin = short * 0.05
    x0 = img.width - margin - text_width(text, h, style.glyphs)
    y0 = img.height - margin - h

    mask = Image.new("L", img.size, 0)
    draw = draw_dots if style.glyphs == "dots" else draw_digits
    draw(ImageDraw.Draw(mask), x0, y0, h, text, 255)
    halo = mask.filter(ImageFilter.GaussianBlur(h * 0.18)).point(lambda v: int(v * 0.8))
    out = Image.composite(Image.new("RGB", img.size, style.glow), img, halo)
    core = mask.filter(ImageFilter.GaussianBlur(max(0.6, h * 0.02)))
    out = Image.composite(Image.new("RGB", img.size, style.core), out, core)
    out.info = dict(img.info)
    return out
