import itertools

import pytest
from PIL import Image

from opendyeprint.adjust import Adjustments, apply, auto, build_lut


def channels(lut):
    return lut[0:256], lut[256:512], lut[512:768]


def test_identity_lut():
    lut = build_lut(Adjustments())
    for ch in channels(lut):
        assert all(abs(v - i) <= 1 for i, v in enumerate(ch))


def test_identity_apply_returns_same_image():
    img = Image.new("RGB", (2, 2), (10, 20, 30))
    assert apply(img, Adjustments()) is img


@pytest.mark.parametrize("name,value", list(itertools.product(
    ["exposure", "contrast", "shadows", "highlights", "warmth"], [-1.0, 1.0])))
def test_curves_monotonic_and_keep_black(name, value):
    if name == "exposure":
        value *= 2
    lut = build_lut(Adjustments(**{name: value}))
    for ch in channels(lut):
        assert all(b >= a for a, b in zip(ch, ch[1:]))
        assert ch[0] == 0


def test_exposure_brightens_midtones_without_clipping():
    ch = channels(build_lut(Adjustments(exposure=1.0)))[1]
    assert ch[128] > 160
    assert ch[254] < 255 or ch[255] == 255  # soft shoulder, white stays white
    assert ch[200] < 255


def test_shadows_lift_darks_more_than_brights():
    ch = channels(build_lut(Adjustments(shadows=1.0)))[1]
    assert ch[60] - 60 > ch[220] - 220


def test_warmth_raises_red_lowers_blue():
    r, g, b = channels(build_lut(Adjustments(warmth=1.0)))
    assert r[128] > 128 > b[128]
    assert abs(g[128] - 128) <= 1


def test_saturation_zero_gives_grey():
    img = Image.new("RGB", (2, 2), (200, 50, 50))
    r, g, b = apply(img, Adjustments(saturation=-1.0)).getpixel((0, 0))
    assert r == g == b


def test_apply_keeps_icc_profile():
    img = Image.new("RGB", (2, 2), (100, 100, 100))
    img.info["icc_profile"] = b"x"
    assert apply(img, Adjustments(exposure=0.5)).info["icc_profile"] == b"x"


def _gradient(lo, hi):
    img = Image.new("RGB", (256, 16))
    for x in range(256):
        v = round(lo + (hi - lo) * x / 255)
        for y in range(16):
            img.putpixel((x, y), (v, v, v))
    return img


def test_auto_brightens_dark_photo():
    a = auto(_gradient(0, 90))
    assert a.exposure > 0.3


def test_auto_darkens_bright_photo():
    assert auto(_gradient(150, 255)).exposure < 0


def test_auto_leaves_good_photo_mostly_alone():
    a = auto(_gradient(0, 255))
    assert abs(a.exposure) < 0.2 and a.contrast == 0 and a.shadows == 0


def test_auto_adds_contrast_to_flat_photo():
    assert auto(_gradient(90, 170)).contrast > 0


def test_dict_roundtrip_ignores_unknown():
    a = Adjustments(exposure=0.5, warmth=-0.2)
    assert Adjustments.from_dict({**a.to_dict(), "future": 1}) == a
    assert Adjustments.from_dict(None) == Adjustments()
