"""A row of toggle buttons (Single · Two-up · Polaroid) instead of a hidden dropdown.

Mimics the bits of QComboBox the main window uses, so it's a drop-in replacement.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget


class LayoutPicker(QWidget):
    currentIndexChanged = Signal(int)  # noqa: N815 - same name as QComboBox

    def __init__(self, parent=None):
        super().__init__(parent)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idToggled.connect(self._toggled)
        self._data: list = []
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(4)

    def addItem(self, text: str, data=None, tooltip: str = "") -> None:  # noqa: N802
        b = QPushButton(text)
        b.setCheckable(True)
        b.setToolTip(tooltip)
        self._group.addButton(b, len(self._data))
        self._row.addWidget(b)
        self._data.append(data)
        if len(self._data) == 1:
            b.setChecked(True)

    def _toggled(self, idx: int, checked: bool) -> None:
        if checked:
            self.currentIndexChanged.emit(idx)

    def currentIndex(self) -> int:  # noqa: N802
        return self._group.checkedId()

    def setCurrentIndex(self, idx: int) -> None:  # noqa: N802
        b = self._group.button(idx)
        if b is not None:
            b.setChecked(True)

    def currentData(self):  # noqa: N802
        i = self.currentIndex()
        return self._data[i] if 0 <= i < len(self._data) else None

    def currentText(self) -> str:  # noqa: N802
        b = self._group.checkedButton()
        return b.text() if b else ""

    def findData(self, data) -> int:  # noqa: N802
        return self._data.index(data) if data in self._data else -1
