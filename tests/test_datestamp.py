from datetime import datetime

from PIL import Image

from opendyeprint.datestamp import STYLES, capture_date, date_text, stamp, text_width
from opendyeprint.model import PhotoItem
from opendyeprint.render import SRGB, RenderSettings, compose_cell, compose_sheet


def with_date(img, when="2026:03:03 08:11:53"):
    exif = Image.Exif()
    exif.get_ifd(0x8769)[0x9003] = when
    img.info["exif"] = exif.tobytes()
    return img


def test_date_text_is_dd_mm_yyyy():
    assert date_text(datetime(2026, 3, 3)) == "03/03/2026"


def test_capture_date_from_exif(tmp_path):
    p = tmp_path / "x.jpg"
    exif = Image.Exif()
    exif.get_ifd(0x8769)[0x9003] = "2026:03:03 08:11:53"
    Image.new("RGB", (10, 10)).save(p, exif=exif)
    assert capture_date(Image.open(p)) == datetime(2026, 3, 3, 8, 11, 53)


def test_capture_date_missing_or_garbage():
    assert capture_date(Image.new("RGB", (4, 4))) is None
    assert capture_date(with_date(Image.new("RGB", (4, 4)), "not a date")) is None


def test_thumbnail_keeps_date(tmp_path):
    p = tmp_path / "x.jpg"
    exif = Image.Exif()
    exif.get_ifd(0x8769)[0x9003] = "2026:03:03 08:11:53"
    Image.new("RGB", (400, 300)).save(p, exif=exif)
    from opendyeprint.render import load
    img = load(p)
    img.thumbnail((100, 100))
    assert capture_date(img) == datetime(2026, 3, 3, 8, 11, 53)


def test_every_style_draws_in_bottom_right():
    for key in STYLES:
        out = stamp(Image.new("RGB", (1000, 600), (0, 0, 0)), datetime(2026, 3, 3), key)
        bbox = out.getbbox()
        assert bbox is not None, key
        assert bbox[0] > 500 and bbox[1] > 450, (key, bbox)  # right side, near the bottom
        assert bbox[2] <= 1000 - 15 and bbox[3] <= 600 - 15, (key, bbox)  # margin minus glow


def test_text_width_grows_with_height():
    assert text_width("03/03/2026", 40) == 2 * text_width("03/03/2026", 20)


def test_compose_stamps_only_when_style_and_date():
    img = with_date(Image.new("RGB", (400, 600), (0, 0, 0)))
    plain = compose_cell(img, 400, 600, PhotoItem("x"), RenderSettings(), SRGB)[0]
    stamped = compose_cell(img, 400, 600, PhotoItem("x"), RenderSettings(date_style="orange"), SRGB)[0]
    assert plain.getbbox() is None and stamped.getbbox() is not None
    no_date = compose_cell(Image.new("RGB", (400, 600)), 400, 600, PhotoItem("x"),
                           RenderSettings(date_style="orange"), SRGB)[0]
    assert no_date.getbbox() is None


def test_stamp_stays_bottom_right_of_photo_when_rotated_onto_sheet():
    # Landscape photo on a portrait cell is turned clockwise; the stamp must still sit
    # at the photo's own bottom-right, which after the turn is the cell's bottom-left.
    img = with_date(Image.new("RGB", (600, 400), (0, 0, 0)))
    out, info = compose_cell(img, 400, 600, PhotoItem("x"), RenderSettings(date_style="orange"), SRGB)
    assert info.rotated
    l, t, r, b = out.getbbox()
    assert r < 200 and b > 300


def test_polaroid_sheet_has_square_photo_and_cut_line():
    img = Image.new("RGB", (300, 400), (255, 0, 0))
    sheet, infos = compose_sheet([(img, PhotoItem("a"))], 1181, 1748, 0,
                                 RenderSettings(polaroid=True), SRGB)
    c = infos[0].cell
    assert c.w == c.h and c.y > 0
    assert sheet.getpixel((c.x + c.w // 2, c.y + c.h // 2)) == (255, 0, 0)
    assert sheet.getpixel((c.x // 2, c.y + 10)) == (255, 255, 255)  # white side border
    from opendyeprint.layout import polaroid_frame
    cut = polaroid_frame(1181, 1748).cut_y
    assert sheet.getpixel((5, cut)) != (255, 255, 255)  # dashed line starts at the edge
    assert sheet.getpixel((5, cut + 20)) == (255, 255, 255)
