import io

import pytest
from PIL import Image, ImageCms

from opendyeprint.color import ColorSettings, Intent, system_profile_dir, to_printer, to_working_rgb
from opendyeprint.layout import FitMode
from opendyeprint.adjust import Adjustments
from opendyeprint.model import PhotoItem
from opendyeprint.render import SRGB, RenderSettings, compose_cell, compose_sheet, gap_pixels, load


def _srgb_bytes():
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


@pytest.fixture
def srgb_profile_path(tmp_path):
    p = tmp_path / "srgb.icc"
    p.write_bytes(_srgb_bytes())
    return str(p)


def compose(img, w, h, settings, item=None):
    return compose_cell(img, w, h, item or PhotoItem("x"), settings, settings.color)[0]


ADOBE = system_profile_dir() / "AdobeRGB1998.icc"


def test_compose_exact_size_and_white_borders():
    img = Image.new("RGB", (2000, 1000), (255, 0, 0))
    out = compose(img, 500, 500, RenderSettings(fit=FitMode.FIT, auto_rotate=False))
    assert out.size == (500, 500)
    assert out.getpixel((250, 10)) == (255, 255, 255)
    assert out.getpixel((250, 250)) == (255, 0, 0)


def test_compose_fill_has_no_white():
    img = Image.new("RGB", (2000, 1000), (0, 0, 255))
    out = compose(img, 300, 500, RenderSettings(fit=FitMode.FILL))
    assert out.getextrema() == ((0, 0), (0, 0), (255, 255))


def test_auto_rotate_landscape_to_portrait():
    img = Image.new("RGB", (200, 100), (0, 0, 0))
    img.paste((255, 255, 255), (0, 0, 100, 100))  # left half white
    out = compose(img, 100, 200, RenderSettings(fit=FitMode.FILL, auto_rotate=True))
    # Turned clockwise: the left half ends up at the top.
    assert out.getpixel((50, 10)) == (255, 255, 255)
    assert out.getpixel((50, 190)) == (0, 0, 0)


def test_identity_profile_keeps_colours(srgb_profile_path):
    img = Image.new("RGB", (10, 10), (200, 100, 50))
    out = to_printer(img, None, ColorSettings(srgb_profile_path, Intent.RELATIVE_COLORIMETRIC))
    r, g, b = out.getpixel((5, 5))
    assert abs(r - 200) <= 2 and abs(g - 100) <= 2 and abs(b - 50) <= 2


def test_no_profile_and_no_embedded_is_passthrough():
    img = Image.new("RGB", (2, 2), (1, 2, 3))
    assert to_printer(img, None, ColorSettings(None)) is img


@pytest.mark.skipif(not ADOBE.exists(), reason="AdobeRGB1998.icc not installed")
def test_conversion_into_wider_space_desaturates_numbers():
    img = Image.new("RGB", (1, 1), (0, 255, 0))
    r, g, b = to_printer(img, None, ColorSettings(str(ADOBE), Intent.RELATIVE_COLORIMETRIC)).getpixel((0, 0))
    assert r > 100 and g > 240  # sRGB green sits well inside Adobe RGB


@pytest.mark.skipif(not ADOBE.exists(), reason="AdobeRGB1998.icc not installed")
def test_embedded_source_profile_is_honoured():
    img = Image.new("RGB", (1, 1), (0, 255, 0))
    adobe_bytes = ADOBE.read_bytes()
    # Adobe green -> sRGB (no printer profile) is clipped to pure-ish green.
    r, g, b = to_printer(img, adobe_bytes, ColorSettings(None)).getpixel((0, 0))
    assert r < 10 and g > 240


def test_working_rgb_flattens_alpha():
    img = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    rgb, _ = to_working_rgb(img)
    assert rgb.mode == "RGB" and rgb.getpixel((0, 0)) == (255, 255, 255)


def test_load_applies_exif_and_keeps_icc(tmp_path):
    img = Image.new("RGB", (40, 20), (10, 20, 30))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 CW on display
    path = tmp_path / "x.jpg"
    img.save(path, exif=exif, icc_profile=_srgb_bytes())
    loaded = load(path)
    assert loaded.size == (20, 40)
    assert loaded.info.get("icc_profile")


def test_two_up_sheet_has_both_photos_and_gap():
    red = Image.new("RGB", (400, 300), (255, 0, 0))
    blue = Image.new("RGB", (400, 300), (0, 0, 255))
    rs = RenderSettings(per_sheet=2)
    sheet, infos = compose_sheet([(red, PhotoItem("r")), (blue, PhotoItem("b"))], 300, 420, 20, rs, SRGB)
    assert sheet.getpixel((150, 100)) == (255, 0, 0)
    assert sheet.getpixel((150, 320)) == (0, 0, 255)
    assert sheet.getpixel((150, 210)) == (255, 255, 255)  # the gap
    assert [i.rotated for i in infos] == [False, False]


def test_two_up_rotates_portrait_photos_into_landscape_cells():
    img = Image.new("RGB", (300, 400), (0, 255, 0))
    _, infos = compose_sheet([(img, PhotoItem("a")), None], 300, 420, 0, RenderSettings(per_sheet=2), SRGB)
    assert infos[0].rotated and infos[1].item is None


def test_crop_center_shifts_content():
    img = Image.new("RGB", (300, 100), (0, 0, 0))
    img.paste((255, 255, 255), (0, 0, 100, 100))  # white left third
    left = compose(img, 100, 100, RenderSettings(auto_rotate=False), PhotoItem("x", center=(0.0, 0.5)))
    mid = compose(img, 100, 100, RenderSettings(auto_rotate=False), PhotoItem("x"))
    assert left.getpixel((50, 50)) == (255, 255, 255)
    assert mid.getpixel((50, 50)) == (0, 0, 0)


def test_adjustments_are_applied():
    img = Image.new("RGB", (50, 50), (100, 100, 100))
    out = compose(img, 50, 50, RenderSettings(), PhotoItem("x", adjust=Adjustments(exposure=1.0)))
    assert out.getpixel((25, 25))[0] > 120


def test_gap_pixels():
    assert gap_pixels(2.54, 300) == 30


def test_heic_loads_with_profile_and_date():
    from pathlib import Path

    from opendyeprint.datestamp import capture_date
    from opendyeprint.render import HEIF_SUPPORTED
    if not HEIF_SUPPORTED:
        pytest.skip("pi-heif not installed")
    loaded = load(Path(__file__).parent / "data" / "sample.heic")
    assert loaded.size == (64, 48) and loaded.info.get("icc_profile")
    assert capture_date(loaded) is not None


def test_single_photo_on_two_up_sheet_fills_whole_sheet():
    img = Image.new("RGB", (300, 400), (255, 0, 0))
    sheet, infos = compose_sheet([(img, PhotoItem("a"))], 300, 420, 12, RenderSettings(per_sheet=2), SRGB)
    assert len(infos) == 1 and (infos[0].cell.w, infos[0].cell.h) == (300, 420)
    assert sheet.getpixel((150, 210)) == (255, 0, 0)  # no gap in the middle


def test_print_render_caps_zoom_at_printer_resolution():
    img = Image.new("RGB", (600, 800), (0, 0, 0))
    img.paste((255, 255, 255), (290, 390, 310, 410))  # small white square in the middle
    item = PhotoItem("x", zoom=50.0)
    _, info = compose_cell(img, 300, 400, item, RenderSettings(auto_rotate=False), SRGB, cap_zoom=True)
    l, t, r, b = info.placement.crop
    assert r - l == pytest.approx(300)  # capped: 1 photo px per printer px (zoom 2)
    _, info = compose_cell(img, 300, 400, item, RenderSettings(auto_rotate=False), SRGB)
    assert info.placement.crop[2] - info.placement.crop[0] == pytest.approx(12)  # preview: uncapped


def test_crop_upright_keeps_landscape_photo_unturned_on_portrait_cell():
    img = Image.new("RGB", (4000, 3000), (0, 0, 255))
    _, info = compose_cell(img, 1181, 1748, PhotoItem("x", turn=False), RenderSettings(), SRGB)
    assert not info.rotated
    l, t, r, b = info.placement.crop
    assert (r - l) / (b - t) == pytest.approx(1181 / 1748, rel=1e-3)  # portrait slice of the photo


def test_per_photo_turn_overrides_global_setting():
    img = Image.new("RGB", (4000, 3000))
    _, info = compose_cell(img, 1181, 1748, PhotoItem("x", turn=True), RenderSettings(auto_rotate=False), SRGB)
    assert info.rotated
    _, info = compose_cell(img, 1181, 1748, PhotoItem("x"), RenderSettings(auto_rotate=False), SRGB)
    assert not info.rotated


def test_turns_onto_cell_helper():
    from opendyeprint.render import turns_onto_cell
    rs = RenderSettings()
    assert turns_onto_cell(PhotoItem("x"), rs, 4000, 3000, 1181, 1748)
    assert not turns_onto_cell(PhotoItem("x", turn=False), rs, 4000, 3000, 1181, 1748)
    assert not turns_onto_cell(PhotoItem("x", turn=True), rs, 3000, 4000, 1181, 1748)  # already fits
