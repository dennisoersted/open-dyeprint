import pytest

from opendyeprint.layout import FitMode, place, should_rotate


def test_fill_crops_sides_of_wide_photo():
    p = place(3000, 1000, 1000, 1000, FitMode.FILL)
    assert p.crop == (1000.0, 0.0, 2000.0, 1000.0)
    assert p.dest == (0, 0, 1000, 1000)


def test_fill_crops_top_and_bottom_of_tall_photo():
    p = place(1000, 3000, 1000, 1000, FitMode.FILL)
    assert p.crop == (0.0, 1000.0, 1000.0, 2000.0)


def test_fill_keeps_area_aspect():
    p = place(6000, 4000, 1122, 1661, FitMode.FILL)
    l, t, r, b = p.crop
    assert (r - l) / (b - t) == pytest.approx(1122 / 1661)


def test_fit_letterboxes_and_centres():
    p = place(2000, 1000, 1000, 1000, FitMode.FIT)
    assert p.crop == (0.0, 0.0, 2000.0, 1000.0)
    assert p.dest == (0, 250, 1000, 750)


def test_fit_never_exceeds_area():
    p = place(4000, 3000, 1122, 1661, FitMode.FIT)
    w, h = p.dest_size
    assert w <= 1122 and h <= 1661


def test_should_rotate():
    assert should_rotate(6000, 4000, 1122, 1661)
    assert not should_rotate(4000, 6000, 1122, 1661)
    assert not should_rotate(4000, 4000, 1122, 1661)


def test_rejects_zero_sizes():
    with pytest.raises(ValueError):
        place(0, 10, 10, 10, FitMode.FIT)


def test_fill_center_moves_crop_and_clamps():
    from opendyeprint.layout import effective_center
    left = place(3000, 1000, 1000, 1000, FitMode.FILL, center=(0.0, 0.5))
    assert left.crop == (0.0, 0.0, 1000.0, 1000.0)
    right = place(3000, 1000, 1000, 1000, FitMode.FILL, center=(0.7, 0.5))
    assert right.crop[0] == 1600.0
    assert place(3000, 1000, 1000, 1000, FitMode.FILL, center=(0.9, 0.5)).crop[0] == 2000.0
    assert effective_center(3000, 1000, 1000, 1000, (0.0, 0.2)) == (1 / 6, 0.5)


def test_rotate_center_roundtrip():
    from opendyeprint.layout import rotate_center, unrotate_center
    c = (0.2, 0.7)
    assert unrotate_center(rotate_center(c)) == pytest.approx(c)
    assert rotate_center((0.0, 0.5)) == (0.5, 0.0)  # left edge -> top after a clockwise turn


def test_two_cells_portrait_sheet_stacks():
    from opendyeprint.layout import cells
    a, b = cells(1181, 1748, 2, gap=24)
    assert (a.x, a.y, a.w) == (0, 0, 1181) and a.h == b.h == 862
    assert b.y + b.h == 1748 and b.y - (a.y + a.h) == 24


def test_two_cells_landscape_area_side_by_side():
    from opendyeprint.layout import cells
    a, b = cells(1000, 600, 2)
    assert a.w == b.w == 500 and a.h == 600 and b.x == 500


def test_one_cell_is_whole_area():
    from opendyeprint.layout import Cell, cells
    assert cells(100, 200, 1) == [Cell(0, 0, 100, 200)]


def test_zoom_shrinks_crop_around_center():
    p = place(4000, 3000, 400, 300, FitMode.FILL, zoom=2.0)
    assert p.crop == (1000.0, 750.0, 3000.0, 2250.0)


def test_zoom_ignored_for_fit_and_below_one():
    assert place(4000, 3000, 400, 300, FitMode.FIT, zoom=3.0).crop == (0.0, 0.0, 4000.0, 3000.0)
    assert place(4000, 3000, 400, 300, FitMode.FILL, zoom=0.5).crop == (0.0, 0.0, 4000.0, 3000.0)


def test_zoomed_crop_can_pan_further():
    from opendyeprint.layout import effective_center
    assert effective_center(4000, 3000, 400, 300, (0.0, 0.5)) == (0.5, 0.5)  # no slack unzoomed
    assert effective_center(4000, 3000, 400, 300, (0.0, 0.5), zoom=2.0) == (0.25, 0.5)


def test_max_zoom_keeps_one_photo_pixel_per_printer_pixel():
    from opendyeprint.layout import max_zoom
    # iPhone 4284 x 5712 on a borderless postcard (1181 x 1748 px at 300 dpi)
    z = max_zoom(4284, 5712, 1181, 1748)
    crop = place(4284, 5712, 1181, 1748, FitMode.FILL, zoom=z).crop
    assert crop[2] - crop[0] == pytest.approx(1181)
    assert 3.2 < z < 3.3
    assert max_zoom(1000, 1500, 1181, 1748) == 1.0  # already below printer resolution


def test_polaroid_frame_spans_postcard_width():
    from opendyeprint.layout import polaroid_frame
    f = polaroid_frame(1181, 1748)  # borderless postcard at 300 dpi
    assert f.x == 0 and f.w == 1181
    assert f.photo.w == f.photo.h  # square photo
    assert f.photo.x == 1181 - (f.photo.x + f.photo.w)  # centred
    assert 1430 < f.cut_y < 1440  # ~121.6 mm
    assert f.photo.y < f.photo.x + 20  # thin top border


def test_polaroid_frame_falls_back_when_area_is_short():
    from opendyeprint.layout import polaroid_frame
    f = polaroid_frame(1748, 1181)
    assert f.cut_y <= 1181 and f.x > 0
