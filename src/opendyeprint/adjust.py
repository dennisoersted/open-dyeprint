"""Simple photo adjustments: exposure, contrast, shadows, highlights, saturation, warmth.

Everything except saturation is folded into one per-channel 8-bit lookup table, so
applying adjustments is a single fast `Image.point` call.

All sliders run from -1 to +1 (exposure in stops, -2..+2). Curves are designed to
keep black at black and white at white, so nothing clips harshly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace

from PIL import Image, ImageEnhance


@dataclass(frozen=True)
class Adjustments:
    exposure: float = 0.0  # stops, -2..+2
    contrast: float = 0.0  # -1..+1
    shadows: float = 0.0  # -1..+1 (positive lifts dark areas)
    highlights: float = 0.0  # -1..+1 (negative recovers bright areas)
    saturation: float = 0.0  # -1..+1
    warmth: float = 0.0  # -1..+1

    @property
    def is_identity(self) -> bool:
        return all(abs(getattr(self, f.name)) < 1e-6 for f in fields(self))

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict | None) -> "Adjustments":
        if not d:
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: float(v) for k, v in d.items() if k in known})

    def with_(self, **kw) -> "Adjustments":
        return replace(self, **kw)


# --- transfer functions (sRGB / Display P3 share this curve) ------------------

def decode(v: float) -> float:
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def encode(v: float) -> float:
    v = min(1.0, max(0.0, v))
    return v * 12.92 if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


# --- curves -------------------------------------------------------------------

def exposure_curve(x_lin: float, stops: float) -> float:
    """Linear-light exposure with a soft shoulder: slope 2**stops in the shadows,
    but 1.0 still maps to 1.0, so highlights roll off instead of clipping."""
    k = 2.0 ** stops
    return k * x_lin / (1.0 + (k - 1.0) * x_lin)


def tone_curve(v: float, contrast: float, shadows: float, highlights: float) -> float:
    """Contrast / shadows / highlights on a gamma-encoded value in 0..1."""
    v = v + contrast * v * (1 - v) * (2 * v - 1)  # S-curve, monotonic for |c| <= 1
    v = v + 1.5 * shadows * v * (1 - v) ** 2  # peaks at v = 1/3
    v = v + 1.5 * highlights * v * v * (1 - v)  # peaks at v = 2/3
    return min(1.0, max(0.0, v))


def build_lut(adj: Adjustments) -> list[int]:
    # Warmth as a gentle white-balance shift in linear light.
    gains = (1.0 + 0.12 * adj.warmth, 1.0, 1.0 - 0.12 * adj.warmth)
    lut: list[int] = []
    for g in gains:
        for i in range(256):
            x = decode(i / 255.0) * g
            x = min(1.0, x)
            if adj.exposure:
                x = exposure_curve(x, adj.exposure)
            v = encode(x)
            v = tone_curve(v, adj.contrast, adj.shadows, adj.highlights)
            lut.append(round(v * 255))
    return lut


def apply(img: Image.Image, adj: Adjustments) -> Image.Image:
    if adj.is_identity:
        return img
    if img.mode != "RGB":
        raise ValueError("expected RGB image")
    out = img.point(build_lut(adj))
    if abs(adj.saturation) > 1e-6:
        out = ImageEnhance.Color(out).enhance(1.0 + adj.saturation)
    out.info = dict(img.info)
    return out


# --- auto ---------------------------------------------------------------------

def _percentile(hist: list[int], q: float) -> float:
    total = sum(hist)
    target = q * total
    acc = 0
    for i, n in enumerate(hist):
        acc += n
        if acc >= target:
            return i / 255.0
    return 1.0


def auto(img: Image.Image) -> Adjustments:
    """Gentle automatic correction from the luminance histogram.

    Aims the median brightness at a pleasant mid-tone, lifts crushed shadows,
    recovers clipped highlights and adds contrast to flat images. Deliberately
    conservative: a well-exposed phone photo should get (almost) no change.
    Warmth and saturation are left alone (sunsets and candle-light are intended).
    """
    small = img.convert("RGB")
    small.thumbnail((512, 512))
    hist = small.convert("L").histogram()
    p02, p50, p98 = (_percentile(hist, q) for q in (0.02, 0.5, 0.98))
    total = sum(hist)
    dark = sum(hist[:26]) / total  # below ~10%
    bright = sum(hist[246:]) / total  # above ~96%

    # Exposure: leave medians inside a comfortable band alone (phone cameras already
    # expose well); otherwise move toward the nearest band edge, part of the way.
    exposure = 0.0
    low, high = 0.36, 0.62
    target = low if p50 < low else high if p50 > high else None
    m_lin = decode(max(p50, 0.02))
    t_lin = decode(target) if target is not None else m_lin
    if target is not None and 0 < m_lin < 1:
        k = t_lin * (1 - m_lin) / (m_lin * (1 - t_lin))
        stops = math.log2(k) * 0.6
        if abs(stops) > 0.12:
            exposure = max(-1.0, min(1.5, stops))

    shadows = min(0.6, (dark - 0.10) * 3) if dark > 0.10 else 0.0
    highlights = -min(0.6, (bright - 0.03) * 6) if bright > 0.03 else 0.0

    spread = p98 - p02
    contrast = min(0.4, (0.75 - spread) * 1.2) if spread < 0.75 else 0.0

    r = lambda v: round(v, 2) if abs(v) >= 0.05 else 0.0  # noqa: E731 - drop noise
    return Adjustments(exposure=r(exposure), contrast=r(contrast), shadows=r(shadows),
                       highlights=r(highlights))
