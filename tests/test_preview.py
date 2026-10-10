import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from opendyeprint.layout import FitMode, PageGeometry  # noqa: E402
from opendyeprint.model import PhotoItem  # noqa: E402
from opendyeprint.render import SRGB, RenderSettings  # noqa: E402
from opendyeprint.ui.preview import PREVIEW_LONG_SIDE, dragged_center, render_preview  # noqa: E402

POSTCARD = PageGeometry(300, 300, 1181, 1748, 30, 44, 1122, 1661)
BORDERLESS = PageGeometry(300, 300, 1181, 1748, 0, 0, 1181, 1748)


def preview(photos, geom=POSTCARD, **kw):
    return render_preview(photos, geom, RenderSettings(**kw), borderless=geom is BORDERLESS, target=SRGB)


def test_portrait_photo_gives_portrait_sheet():
    p = preview([(Image.new("RGB", (400, 600)), PhotoItem("a"))])
    assert p.image.height == PREVIEW_LONG_SIDE and not p.turned


def test_landscape_photo_turns_sheet_for_display():
    p = preview([(Image.new("RGB", (600, 400)), PhotoItem("a"))])
    assert p.image.width == PREVIEW_LONG_SIDE and p.turned


def test_bordered_sheet_has_white_margin_and_photo():
    p = preview([(Image.new("RGB", (400, 600), (255, 0, 0)), PhotoItem("a"))])
    assert p.image.getpixel((5, 5)) == (255, 255, 255)
    assert p.image.getpixel((p.image.width // 2, p.image.height // 2)) == (255, 0, 0)


def test_two_up_portrait_photos_turn_sheet_side_by_side():
    a, b = PhotoItem("a"), PhotoItem("b")
    p = preview([(Image.new("RGB", (300, 400), (255, 0, 0)), a),
                 (Image.new("RGB", (300, 400), (0, 0, 255)), b)], BORDERLESS, per_sheet=2)
    assert p.turned and p.image.width > p.image.height
    w, h = p.image.size
    # Shown turned counter-clockwise: first photo (top cell) reads on the left.
    assert p.cell_at(w * 0.25, h / 2).item is a
    assert p.cell_at(w * 0.75, h / 2).item is b
    assert p.image.getpixel((int(w * 0.25), h // 2)) == (255, 0, 0)


def test_cell_hit_test_unturned():
    a = PhotoItem("a")
    p = preview([(Image.new("RGB", (400, 600)), a)], BORDERLESS)
    assert p.cell_at(10, 10).item is a


def test_drag_right_moves_crop_left():
    item = PhotoItem("a")
    p = preview([(Image.new("RGB", (1200, 400)), item)], BORDERLESS, auto_rotate=False)
    info = p.infos[0]
    u, v = dragged_center(info, (0.5, 0.5), 50, 0)
    assert u < 0.5 and v == pytest.approx(0.5)


def test_drag_clamps_to_photo_edge():
    item = PhotoItem("a")
    p = preview([(Image.new("RGB", (1200, 400)), item)], BORDERLESS, auto_rotate=False)
    u, _ = dragged_center(p.infos[0], (0.5, 0.5), 100000, 0)
    l, t, r, b = p.infos[0].placement.crop
    assert u == pytest.approx((r - l) / 2 / 1200)  # crop pinned to the left edge


def test_drag_on_rotated_photo_maps_back_to_original_axes():
    # Landscape photo is turned clockwise onto the portrait sheet: its right edge is at
    # the bottom. Dragging the photo up reveals more of the bottom == the right side.
    item = PhotoItem("a")
    p = preview([(Image.new("RGB", (1500, 400)), item)], BORDERLESS)
    info = p.infos[0]
    assert info.rotated
    u, v = dragged_center(info, (0.5, 0.5), 0, -50)
    assert u > 0.5 and v == pytest.approx(0.5)


def test_drag_in_turned_display_maps_to_sheet():
    # Two-up portrait photos: display is turned. Dragging horizontally on screen moves the
    # photo along the sheet's vertical axis, where 3:4 photos in these cells have slack.
    item = PhotoItem("a")
    p = preview([(Image.new("RGB", (300, 400)), item), None], BORDERLESS, per_sheet=2)
    sdx, sdy = p.display_delta_to_sheet(40, 0)
    assert sdx == 0 and sdy == 40
    u, v = dragged_center(p.infos[0], (0.5, 0.5), sdx, sdy)
    assert (u, v) != (0.5, 0.5)
