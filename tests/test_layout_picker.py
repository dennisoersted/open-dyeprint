import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from opendyeprint.ui.layout_picker import LayoutPicker  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def picker(app):
    p = LayoutPicker()
    p.addItem("Single", 1)
    p.addItem("Two-up", 2)
    p.addItem("Polaroid", 3)
    return p


def test_first_item_selected_by_default(picker):
    assert picker.currentIndex() == 0 and picker.currentData() == 1 and picker.currentText() == "Single"


def test_find_and_set_restores_saved_layout(picker):
    picker.setCurrentIndex(max(0, picker.findData(3)))  # how the main window restores settings
    assert picker.currentData() == 3 and picker.currentText() == "Polaroid"
    assert picker.findData(99) == -1


def test_signal_fires_once_per_change_and_not_when_blocked(picker):
    seen = []
    picker.currentIndexChanged.connect(seen.append)
    picker.setCurrentIndex(1)
    picker.setCurrentIndex(1)  # no change, no signal (like QComboBox)
    assert seen == [1]
    picker.blockSignals(True)
    picker.setCurrentIndex(2)
    picker.blockSignals(False)
    assert seen == [1] and picker.currentData() == 3


def test_buttons_are_exclusive(picker):
    picker.setCurrentIndex(2)
    picker.setCurrentIndex(0)
    checked = [b.isChecked() for b in picker._group.buttons()]
    assert checked == [True, False, False]
