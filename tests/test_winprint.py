import struct

from PIL import Image

from opendyeprint.winprint import DM_ICMMETHOD, DM_PAPERSIZE, dib_bytes, devmode_icm_method, devmode_paper_size, devmode_with


def test_devmode_with_sets_fields_and_flags():
    dm = bytes(220 + 10)
    out = devmode_with(dm, paper_size=43, icm_method=1)
    assert devmode_paper_size(out) == 43
    assert devmode_icm_method(out) == 1
    flags = struct.unpack_from("<I", out, 72)[0]
    assert flags & DM_PAPERSIZE and flags & DM_ICMMETHOD
    assert len(out) == len(dm)


def test_dib_rows_padded_and_bottom_up():
    img = Image.new("RGB", (3, 2), (0, 0, 0))
    img.putpixel((0, 1), (10, 20, 30))  # bottom-left
    data, hdr = dib_bytes(img)
    assert hdr.biWidth == 3 and hdr.biHeight == 2 and hdr.biBitCount == 24
    assert len(data) == 2 * 12  # 9 bytes rounded up to 12
    assert data[0:3] == bytes([30, 20, 10])  # first row in memory = bottom row, BGR


def test_describe_problems():
    from opendyeprint.winprint import describe_problems
    assert describe_problems(0, 0) == []
    assert describe_problems(0x40, 0) == ["out of paper or ink cassette"]
    assert describe_problems(0, 0x80) == ["offline"]
    assert describe_problems(0x20, 0x80) == ["printer offline"]  # no duplicate
