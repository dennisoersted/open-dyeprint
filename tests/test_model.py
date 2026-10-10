from opendyeprint.model import PhotoItem, sheet_index_of, sheets


def test_one_per_sheet_expands_copies():
    a, b = PhotoItem("a", copies=2), PhotoItem("b")
    assert sheets([a, b], 1) == [[a], [a], [b]]


def test_two_up_pairs_in_order_and_odd_last_photo_gets_own_sheet():
    a, b, c = PhotoItem("a"), PhotoItem("b"), PhotoItem("c")
    assert sheets([a, b, c], 2) == [[a, b], [c]]


def test_two_up_odd_copies():
    a, b = PhotoItem("a", copies=2), PhotoItem("b")
    assert sheets([a, b], 2) == [[a, a], [b]]


def test_two_up_single_photo_two_copies_shares_sheet():
    a = PhotoItem("a", copies=2)
    assert sheets([a], 2) == [[a, a]]


def test_sheet_index_of():
    a, b, c = PhotoItem("a"), PhotoItem("b"), PhotoItem("c")
    assert sheet_index_of([a, b, c], 2, c) == 1
    assert sheet_index_of([a, b, c], 1, b) == 1
    assert sheet_index_of([a], 1, b) is None


def test_empty():
    assert sheets([], 2) == []
