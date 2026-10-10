"""ICC colour conversion via LittleCMS (Pillow's ImageCms)."""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from enum import IntEnum
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageCms


class Intent(IntEnum):
    PERCEPTUAL = 0
    RELATIVE_COLORIMETRIC = 1
    SATURATION = 2
    ABSOLUTE_COLORIMETRIC = 3


@dataclass(frozen=True)
class ColorSettings:
    printer_profile: str | None  # path to .icc/.icm; None = no conversion (send sRGB)
    intent: Intent = Intent.PERCEPTUAL
    black_point_compensation: bool = True


def system_profile_dir() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "spool" / "drivers" / "color"


def list_system_profiles() -> list[Path]:
    d = system_profile_dir()
    if not d.is_dir():
        return []
    return sorted(
        (p for p in d.iterdir() if p.suffix.lower() in (".icc", ".icm")),
        key=lambda p: p.name.lower(),
    )


def profile_description(path: str | Path) -> str:
    try:
        return ImageCms.getProfileDescription(ImageCms.getOpenProfile(str(path))).strip() or Path(path).name
    except (OSError, ImageCms.PyCMSError):
        return Path(path).name


def profile_color_space(path: str | Path) -> str:
    """Returns the profile's data colour space, e.g. 'RGB ' or 'CMYK'."""
    return ImageCms.getOpenProfile(str(path)).profile.xcolor_space


@lru_cache(maxsize=1)
def _srgb() -> ImageCms.ImageCmsProfile:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))


@lru_cache(maxsize=16)
def _transform(src_icc: bytes | None, dst_path: str | None, intent: int, bpc: bool):
    """dst_path None means sRGB."""
    src = ImageCms.ImageCmsProfile(io.BytesIO(src_icc)) if src_icc else _srgb()
    dst = ImageCms.getOpenProfile(dst_path) if dst_path else _srgb()
    flags = ImageCms.Flags.BLACKPOINTCOMPENSATION if bpc else ImageCms.Flags.NONE
    return ImageCms.buildTransform(src, dst, "RGB", "RGB", renderingIntent=intent, flags=flags)


def to_working_rgb(img: Image.Image) -> tuple[Image.Image, bytes | None]:
    """Normalise to an RGB image + the ICC profile describing it (None = sRGB)."""
    icc = img.info.get("icc_profile") or None
    if img.mode == "CMYK" and icc:
        rgb = ImageCms.profileToProfile(
            img, ImageCms.ImageCmsProfile(io.BytesIO(icc)), _srgb(), outputMode="RGB"
        )
        return rgb, None
    if img.mode == "RGB":
        return img, icc
    if img.mode in ("RGBA", "LA", "P", "PA"):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg, icc if img.mode == "RGBA" else None
    # L, I;16, I, F, CMYK without profile, ... -> plain conversion, treat as sRGB
    return img.convert("RGB"), None


def to_printer(img: Image.Image, src_icc: bytes | None, settings: ColorSettings) -> Image.Image:
    """Convert an RGB image (described by src_icc, or sRGB) into printer RGB space.

    Without a printer profile the image is converted to sRGB, which is what the
    printer assumes for unmanaged input.
    """
    if img.mode != "RGB":
        raise ValueError("expected RGB image")
    if not settings.printer_profile and src_icc is None:
        return img
    t = _transform(src_icc, settings.printer_profile or None, int(settings.intent),
                   settings.black_point_compensation)
    return ImageCms.applyTransform(img, t)


def monitor_profile() -> str | None:
    """ICC profile Windows assigns to the primary display (None if unavailable)."""
    try:
        import ctypes
        from ctypes import wintypes as wt

        user32 = ctypes.WinDLL("user32")
        gdi32 = ctypes.WinDLL("gdi32")
        user32.GetDC.restype = wt.HDC
        user32.GetDC.argtypes = [wt.HWND]
        user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
        gdi32.GetICMProfileW.argtypes = [wt.HDC, ctypes.POINTER(wt.DWORD), wt.LPWSTR]
        hdc = user32.GetDC(None)
        try:
            size = wt.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if not gdi32.GetICMProfileW(hdc, ctypes.byref(size), buf):
                return None
        finally:
            user32.ReleaseDC(None, hdc)
        path = buf.value
        if not path or not Path(path).exists() or profile_color_space(path).strip() != "RGB":
            return None
        return path
    except (OSError, AttributeError, ImageCms.PyCMSError):
        return None
