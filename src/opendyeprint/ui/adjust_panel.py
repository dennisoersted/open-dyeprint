"""Sliders for exposure & co., plus Auto and Reset."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSlider

from ..adjust import Adjustments

# field, label, slider range (in hundredths), value format
SLIDERS = [
    ("exposure", "Exposure", 200, "{:+.2f} EV"),
    ("contrast", "Contrast", 100, "{:+.0f}"),
    ("highlights", "Highlights", 100, "{:+.0f}"),
    ("shadows", "Shadows", 100, "{:+.0f}"),
    ("saturation", "Saturation", 100, "{:+.0f}"),
    ("warmth", "Warmth", 100, "{:+.0f}"),
]


class _ResetLabel(QLabel):
    """Value label; double-click resets its slider."""

    def __init__(self, slider: QSlider):
        super().__init__()
        self._slider = slider
        self.setMinimumWidth(64)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setToolTip("Double-click to reset")

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        self._slider.setValue(0)


class AdjustPanel(QGroupBox):
    """Edits one Adjustments value. Emits `changed` live while sliding."""

    changed = Signal(object)  # Adjustments
    auto_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("Adjust photo", parent)
        self._sliders: dict[str, QSlider] = {}
        self._labels: dict[str, QLabel] = {}
        grid = QGridLayout(self)
        grid.setColumnStretch(1, 1)
        for row, (name, label, rng, _fmt) in enumerate(SLIDERS):
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(-rng, rng)
            s.setSingleStep(5 if name == "exposure" else 2)
            s.setPageStep(25 if name == "exposure" else 10)
            s.valueChanged.connect(self._on_slider)
            v = _ResetLabel(s)
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(s, row, 1)
            grid.addWidget(v, row, 2)
            self._sliders[name], self._labels[name] = s, v
        auto = QPushButton("Auto")
        auto.setToolTip("Gently correct exposure, contrast, shadows and highlights.\n"
                        "Applies to all selected photos; fine-tune afterwards if you like.")
        auto.clicked.connect(self.auto_requested)
        reset = QPushButton("Reset")
        reset.setToolTip("Remove all adjustments from the selected photos")
        reset.clicked.connect(lambda: self.set_value(Adjustments(), emit=True))
        row = QHBoxLayout()
        row.addWidget(auto)
        row.addWidget(reset)
        grid.addLayout(row, len(SLIDERS), 0, 1, 3)
        self.set_value(Adjustments())

    def value(self) -> Adjustments:
        return Adjustments(**{n: self._sliders[n].value() / 100 for n, *_ in SLIDERS})

    def set_value(self, adj: Adjustments, emit: bool = False) -> None:
        for name, *_ in SLIDERS:
            s = self._sliders[name]
            s.blockSignals(True)
            s.setValue(round(getattr(adj, name) * 100))
            s.blockSignals(False)
        self._refresh_labels()
        if emit:
            self.changed.emit(self.value())

    def _refresh_labels(self):
        for name, _label, _rng, fmt in SLIDERS:
            v = self._sliders[name].value()
            self._labels[name].setText(fmt.format(v / 100 if name == "exposure" else v))

    def _on_slider(self, _):
        self._refresh_labels()
        self.changed.emit(self.value())
