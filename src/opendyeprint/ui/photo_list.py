"""Reorderable photo list (order decides two-up pairing) that also accepts file drops."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem

from ..model import PhotoItem

ITEM_ROLE = Qt.ItemDataRole.UserRole


class PhotoList(QListWidget):
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIconSize(QSize(96, 96))
        self.setSpacing(2)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setAcceptDrops(True)

    # -- model access --

    def items(self) -> list[PhotoItem]:
        return [self.item(i).data(ITEM_ROLE) for i in range(self.count())]

    def selected(self) -> list[PhotoItem]:
        """Selected photos in list order (not click order), so two-up pairs are predictable."""
        rows = sorted(self.row(it) for it in self.selectedItems())
        return [self.item(r).data(ITEM_ROLE) for r in rows]

    def current(self) -> PhotoItem | None:
        it = self.currentItem()
        return it.data(ITEM_ROLE) if it else None

    def add(self, photo: PhotoItem) -> QListWidgetItem:
        it = QListWidgetItem()
        it.setData(ITEM_ROLE, photo)
        it.setToolTip(photo.path)
        self.addItem(it)
        self.refresh(photo)
        return it

    def widget_item(self, photo: PhotoItem) -> QListWidgetItem | None:
        for i in range(self.count()):
            if self.item(i).data(ITEM_ROLE) is photo:
                return self.item(i)
        return None

    def refresh(self, photo: PhotoItem) -> None:
        it = self.widget_item(photo)
        if it is None:
            return
        marks = []
        if photo.copies > 1:
            marks.append(f"×{photo.copies}")
        if not photo.adjust.is_identity:
            marks.append("adjusted")
        if photo.turn is False:
            marks.append("cropped upright")
        elif photo.turn is True:
            marks.append("turned")
        if photo.zoom > 1.001:
            marks.append(f"zoom {photo.zoom * 100:.0f}%")
        elif photo.center != (0.5, 0.5):
            marks.append("re-cropped")
        name = Path(photo.path).name
        it.setText(name + ("\n" + " · ".join(marks) if marks else ""))

    # -- external drops --

    def _external(self, e) -> bool:
        return e.source() is None and e.mimeData().hasUrls()

    def dragEnterEvent(self, e):  # noqa: N802
        if self._external(e):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):  # noqa: N802
        if self._external(e):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):  # noqa: N802
        if self._external(e):
            self.files_dropped.emit([u.toLocalFile() for u in e.mimeData().urls()])
            e.acceptProposedAction()
        else:
            super().dropEvent(e)
