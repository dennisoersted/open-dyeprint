"""Main window: photo list | sheet preview | settings."""

from __future__ import annotations

import base64
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QByteArray, Qt, QThread, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider,
    QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from .. import adjust as tadjust
from .. import printer as tprinter
from .. import settings as tsettings
from .. import shell, winprint
from ..color import (ColorSettings, Intent, list_system_profiles, monitor_profile,
                     profile_color_space, profile_description)
from ..datestamp import STYLES as DATE_STYLES
from ..datestamp import date_text, photo_date
from ..layout import FitMode, PageGeometry, max_zoom, polaroid_frame, should_rotate
from ..model import PhotoItem, sheet_index_of, sheets
from ..render import IMAGE_EXTS, SRGB, RenderSettings, gap_pixels, photo_cells, turns_onto_cell
from .adjust_panel import AdjustPanel
from .layout_picker import LayoutPicker
from .photo_list import PhotoList
from .preview import PreviewWidget, pil_to_qimage, render_preview
from .workers import JobWatcher, PrintWorker, ThumbLoader

TWO_UP_GAP_MM = 1.0
POLAROID = 3  # Sheet combo value for the Polaroid layout  # white line between the two photos, for cutting

IMAGE_FILTER = "Images (" + " ".join(f"*{e}" for e in sorted(IMAGE_EXTS)) + ")"

INTENTS = [
    ("Perceptual", Intent.PERCEPTUAL),
    ("Relative colorimetric", Intent.RELATIVE_COLORIMETRIC),
    ("Saturation", Intent.SATURATION),
    ("Absolute colorimetric", Intent.ABSOLUTE_COLORIMETRIC),
]


class MainWindow(QMainWindow):
    def __init__(self, initial_files: list[str] | None = None):
        super().__init__()
        self.setWindowTitle("Open DyePrint")
        self.resize(1360, 860)
        self.setAcceptDrops(True)

        self.s = tsettings.load()
        self.thumbs: dict[str, Image.Image] = {}
        self.sizes: dict[str, tuple[int, int]] = {}
        self._geom_cache: dict[tuple, PageGeometry] = {}
        self._print_thread: QThread | None = None
        self._watcher: JobWatcher | None = None
        self._loading = True
        self._monitor_profile = monitor_profile()

        self.loader = ThumbLoader()
        self.loader.loaded.connect(self._on_thumb)
        self.loader.failed.connect(self._on_thumb_failed)

        self._preview_timer = QTimer(self, singleShot=True, interval=60)
        self._preview_timer.timeout.connect(self._update_preview)

        self._build_ui()
        self._build_menu()
        self._populate_printers()
        self._populate_profiles()
        self._apply_settings_to_ui()
        self._restore_window_state()
        self._loading = False
        self._settings_changed()

        if initial_files:
            self.add_files(initial_files)

    # ================= UI construction =================

    def _build_ui(self):
        # ---- left: photos ----
        self.list = PhotoList()
        self.list.files_dropped.connect(self.add_files)
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.list.model().rowsMoved.connect(lambda *_: (self._update_print_button(), self._schedule_preview()))
        QShortcut(QKeySequence.StandardKey.Delete, self.list, self._remove_selected)

        add_btn = QPushButton("Add photos…")
        add_btn.clicked.connect(self._choose_files)
        rm_btn = QPushButton("Remove")
        rm_btn.clicked.connect(self._remove_selected)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear)
        btns = QHBoxLayout()
        for b in (add_btn, rm_btn, clear_btn):
            btns.addWidget(b)

        self.copies_spin = QSpinBox()
        self.copies_spin.setRange(1, 99)
        self.copies_spin.setToolTip("Copies of the selected photo(s)")
        self.copies_spin.valueChanged.connect(self._copies_changed)
        crow = QHBoxLayout()
        crow.addWidget(QLabel("Copies of selected:"))
        crow.addWidget(self.copies_spin)
        crow.addStretch(1)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(6, 6, 6, 6)
        lv.addLayout(btns)
        lv.addWidget(self.list, 1)
        lv.addLayout(crow)
        hint = QLabel("Drag photos in from Explorer. Drag within the list to change the order.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")
        lv.addWidget(hint)

        # ---- centre: preview ----
        self.preview = PreviewWidget()
        self.preview.photo_clicked.connect(self._select_photo)
        self.preview.crop_dragging.connect(self._crop_dragging)
        self.preview.crop_dropped.connect(self._crop_dropped)
        self.preview.zoom_wheel.connect(self._zoom_wheel)

        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(100, 100)
        self.zoom_slider.setToolTip("Zoom into the photo (or use the mouse wheel over it). "
                                    "Stops where the photo's own resolution runs out.")
        self.zoom_slider.valueChanged.connect(self._zoom_slider_changed)
        self.zoom_label = QLabel()
        self.zoom_label.setMinimumWidth(170)
        self.upright_btn = QPushButton("Crop upright")
        self.upright_btn.setCheckable(True)
        self.upright_btn.setToolTip("Crop this photo in its own orientation (e.g. a portrait slice of a "
                                    "landscape photo) instead of turning it 90° to fit the sheet")
        self.upright_btn.toggled.connect(self._upright_toggled)
        self.reset_crop_btn = QPushButton("Reset crop")
        self.reset_crop_btn.setToolTip("Back to the centred, un-zoomed, un-turned crop")
        self.reset_crop_btn.clicked.connect(self._reset_crop)
        zrow = QHBoxLayout()
        zrow.setContentsMargins(12, 0, 12, 0)
        zrow.addWidget(QLabel("Zoom"))
        zrow.addWidget(self.zoom_slider, 1)
        zrow.addWidget(self.zoom_label)
        zrow.addWidget(self.upright_btn)
        zrow.addWidget(self.reset_crop_btn)

        self.sheet_label = QLabel()
        self.sheet_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sheet_label.setStyleSheet("color: gray")
        centre = QWidget()
        cv = QVBoxLayout(centre)
        cv.setContentsMargins(0, 0, 0, 6)
        cv.addWidget(self.preview, 1)
        cv.addLayout(zrow)
        cv.addWidget(self.sheet_label)

        # ---- right: settings ----
        self.printer_combo = QComboBox()
        self.props_btn = QPushButton("Properties…")
        self.props_btn.setToolTip("Open the printer driver's own settings dialog. "
                                  "Open DyePrint keeps those settings, but always sets paper, "
                                  "borderless and colour management itself.")
        self.props_btn.clicked.connect(self._edit_driver_settings)
        prow = QHBoxLayout()
        prow.addWidget(self.printer_combo, 1)
        prow.addWidget(self.props_btn)
        self.paper_combo = QComboBox()
        self.borderless_chk = QCheckBox("Borderless")

        self.per_sheet_combo = LayoutPicker()
        self.per_sheet_combo.addItem("Single", 1, "One photo per sheet")
        self.per_sheet_combo.addItem("Two-up", 2, "Two photos side by side on one sheet, with a 1 mm cutting line")
        self.per_sheet_combo.addItem("Polaroid", POLAROID,
                                     "Square photo in a Polaroid-style frame. Cut off the bottom of the "
                                     "sheet along the dashed line.")
        self.date_combo = QComboBox()
        self.date_combo.addItem("Off", None)
        for key, style in DATE_STYLES.items():
            self.date_combo.addItem(style.label, key)
        self.date_combo.setToolTip("Imprint the date the photo was taken (dd/mm/yyyy), like a "
                                   "film camera. Photos without a recorded date are left as they are.")
        self.fit_combo = QComboBox()
        self.fit_combo.addItem("Fill (crop – drag photo to adjust)", FitMode.FILL.value)
        self.fit_combo.addItem("Fit whole photo", FitMode.FIT.value)
        self.rotate_chk = QCheckBox("Auto-rotate to match sheet")

        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumContentsLength(18)
        self.profile_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_profile)
        crow2 = QHBoxLayout()
        crow2.addWidget(self.profile_combo, 1)
        crow2.addWidget(browse_btn)
        self.intent_combo = QComboBox()
        for label, intent in INTENTS:
            self.intent_combo.addItem(label, int(intent))
        self.bpc_chk = QCheckBox("Black point compensation")

        sheet_box = QGroupBox("Printer && sheet")
        f1 = QFormLayout(sheet_box)
        f1.addRow("Printer", prow)
        f1.addRow("Paper", self.paper_combo)
        f1.addRow("", self.borderless_chk)

        layout_box = QGroupBox("Layout")
        f3 = QFormLayout(layout_box)
        f3.addRow("Sheet", self.per_sheet_combo)
        f3.addRow("Photo", self.fit_combo)
        f3.addRow("", self.rotate_chk)
        f3.addRow("Date stamp", self.date_combo)

        color_box = QGroupBox("Colour management")
        f2 = QFormLayout(color_box)
        f2.addRow("Profile", crow2)
        f2.addRow("Intent", self.intent_combo)
        f2.addRow("", self.bpc_chk)

        self.adjust_panel = AdjustPanel()
        self.adjust_panel.changed.connect(self._adjust_changed)
        self.adjust_panel.auto_requested.connect(self._auto_adjust)

        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        settings_widget = QWidget()
        rv = QVBoxLayout(settings_widget)
        rv.setContentsMargins(6, 6, 6, 6)
        for w in (sheet_box, layout_box, self.adjust_panel, color_box, self.info):
            rv.addWidget(w)
        rv.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(settings_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.print_sel_btn = QPushButton("Print selected")
        self.print_btn = QPushButton("Print all")
        for b in (self.print_sel_btn, self.print_btn):
            b.setMinimumHeight(44)
            f = b.font()
            f.setPointSize(f.pointSize() + 1)
            f.setBold(True)
            b.setFont(f)
        self.print_sel_btn.setToolTip("Print only the photos selected in the list (Ctrl+Shift+P)")
        self.print_btn.setToolTip("Print every photo in the list (Ctrl+P)")
        self.print_sel_btn.clicked.connect(lambda: self._print(selected_only=True))
        self.print_btn.clicked.connect(lambda: self._print(selected_only=False))
        print_row = QHBoxLayout()
        print_row.addWidget(self.print_sel_btn)
        print_row.addWidget(self.print_btn)

        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 6, 6)
        rlay.addWidget(scroll, 1)
        rlay.addLayout(print_row)
        right.setMinimumWidth(360)

        self.split = QSplitter()
        self.split.addWidget(left)
        self.split.addWidget(centre)
        self.split.addWidget(right)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 0)
        self.split.setSizes([300, 660, 400])
        self.setCentralWidget(self.split)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.hide()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.cancel_btn)

        self.printer_combo.currentIndexChanged.connect(self._printer_changed)
        for w in (self.paper_combo, self.fit_combo, self.profile_combo, self.intent_combo,
                  self.per_sheet_combo, self.date_combo):
            w.currentIndexChanged.connect(self._settings_changed)
        for w in (self.borderless_chk, self.rotate_chk, self.bpc_chk):
            w.toggled.connect(self._settings_changed)

    def _build_menu(self):
        m = self.menuBar().addMenu("&File")
        a = m.addAction("Add photos…", self._choose_files)
        a.setShortcut(QKeySequence.StandardKey.Open)
        a = m.addAction("Print all", lambda: self._print(selected_only=False))
        a.setShortcut(QKeySequence.StandardKey.Print)
        a = m.addAction("Print selected", lambda: self._print(selected_only=True))
        a.setShortcut(QKeySequence("Ctrl+Shift+P"))
        m.addSeparator()
        m.addAction("Exit", self.close)

        m = self.menuBar().addMenu("&View")
        self.monitor_act = QAction("Colour-managed preview (use monitor profile)", self, checkable=True)
        self.monitor_act.setEnabled(self._monitor_profile is not None)
        self.monitor_act.setToolTip(self._monitor_profile or "Windows reports no monitor profile")
        self.monitor_act.toggled.connect(self._settings_changed)
        m.addAction(self.monitor_act)

        m = self.menuBar().addMenu("&Tools")
        self.shell_act = QAction("Show “Print with Open DyePrint” in Explorer's right-click menu", self,
                                 checkable=True)
        self.shell_act.setChecked(shell.is_registered())
        self.shell_act.toggled.connect(self._toggle_shell)
        m.addAction(self.shell_act)

    # ================= populate =================

    def _populate_printers(self):
        self.printer_combo.blockSignals(True)
        self.printer_combo.clear()
        names = winprint.list_printers()
        selphy_first = sorted(names, key=lambda n: (0 if "selphy" in n.lower() else 1, n.lower()))
        self.printer_combo.addItems(selphy_first)
        want = self.s.printer if self.s.printer in names else (selphy_first[0] if selphy_first else None)
        if want:
            self.printer_combo.setCurrentText(want)
        self.printer_combo.blockSignals(False)
        self._populate_papers()

    def _populate_papers(self):
        self.paper_combo.blockSignals(True)
        self.paper_combo.clear()
        name = self.printer_combo.currentText()
        if name:
            try:
                papers = winprint.list_papers(name)
            except Exception as e:  # noqa: BLE001
                papers = []
                self.statusBar().showMessage(f"Could not read paper sizes: {e}", 8000)
            for paper in papers:
                self.paper_combo.addItem(paper.label, paper.id)
            idx = self.paper_combo.findData(self.s.paper_id) if self.s.printer == name else -1
            if idx < 0:
                try:
                    current = winprint.devmode_paper_size(
                        self.s.devmode_for(name) or winprint.default_devmode(name))
                    idx = self.paper_combo.findData(current)
                except Exception:  # noqa: BLE001
                    idx = -1
            self.paper_combo.setCurrentIndex(max(idx, 0))
            supported = tprinter.supports_borderless(name)
            self.borderless_chk.setEnabled(supported)
            self.borderless_chk.setToolTip("" if supported else "This printer driver has no borderless option.")
        self.paper_combo.blockSignals(False)

    def _populate_profiles(self):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("None – send sRGB (printer manages colour)", None)
        seen = set()
        for p in [Path(p) for p in self.s.extra_profiles] + list_system_profiles():
            key = str(p).lower()
            if key in seen or not p.exists():
                continue
            seen.add(key)
            try:
                if profile_color_space(p).strip() != "RGB":
                    continue
            except Exception:  # noqa: BLE001
                continue
            desc = profile_description(p)
            label = desc if desc.lower() == p.name.lower() else f"{desc}  —  {p.name}"
            self.profile_combo.addItem(label, str(p))
            self.profile_combo.setItemData(self.profile_combo.count() - 1, str(p), Qt.ItemDataRole.ToolTipRole)
        self.profile_combo.blockSignals(False)

    def _apply_settings_to_ui(self):
        s = self.s
        self.borderless_chk.setChecked(s.borderless)
        self.per_sheet_combo.setCurrentIndex(max(0, self.per_sheet_combo.findData(s.per_sheet)))
        self.date_combo.setCurrentIndex(max(0, self.date_combo.findData(s.date_style)))
        self.fit_combo.setCurrentIndex(max(0, self.fit_combo.findData(s.fit)))
        self.rotate_chk.setChecked(s.auto_rotate)
        idx = self.profile_combo.findData(s.profile) if s.profile else -1
        if idx < 0:
            idx = self._guess_profile_index()
        self.profile_combo.setCurrentIndex(idx)
        self.intent_combo.setCurrentIndex(max(0, self.intent_combo.findData(s.intent)))
        self.bpc_chk.setChecked(s.black_point_compensation)
        self.monitor_act.setChecked(s.monitor_preview and self._monitor_profile is not None)

    def _guess_profile_index(self) -> int:
        """First run: pick a profile that looks like it belongs to the chosen printer."""
        if self.s.printer is not None:  # user has run the app before and chose "None"
            return 0
        model = "".join(ch for ch in self.printer_combo.currentText().lower() if ch.isalnum())
        for i in range(1, self.profile_combo.count()):
            text = "".join(ch for ch in self.profile_combo.itemText(i).lower() if ch.isalnum())
            if "cp1500" in text and "cp1500" in model:
                return i
        return 0

    def _restore_window_state(self):
        try:
            if self.s.window_geometry:
                self.restoreGeometry(QByteArray(base64.b64decode(self.s.window_geometry)))
            if self.s.splitter_state:
                self.split.restoreState(QByteArray(base64.b64decode(self.s.splitter_state)))
        except (ValueError, TypeError):
            pass

    # ================= state =================

    def _job(self) -> tprinter.JobSettings:
        name = self.printer_combo.currentText()
        return tprinter.JobSettings(
            printer=name,
            paper_id=self.paper_combo.currentData(),
            borderless=self.borderless_chk.isChecked() and self.borderless_chk.isEnabled(),
            base_devmode=self.s.devmode_for(name),
        )

    def _render_settings(self) -> RenderSettings:
        return RenderSettings(
            fit=FitMode(self.fit_combo.currentData()),
            auto_rotate=self.rotate_chk.isChecked(),
            color=ColorSettings(
                printer_profile=self.profile_combo.currentData(),
                intent=Intent(self.intent_combo.currentData()),
                black_point_compensation=self.bpc_chk.isChecked(),
            ),
            per_sheet=self._per_sheet(),
            gap_mm=TWO_UP_GAP_MM,
            polaroid=self._polaroid(),
            date_style=self.date_combo.currentData(),
        )

    def _polaroid(self) -> bool:
        return self.per_sheet_combo.currentData() == POLAROID

    def _per_sheet(self) -> int:
        """Photos per sheet (Polaroid is always one)."""
        return 2 if self.per_sheet_combo.currentData() == 2 else 1

    def _preview_target(self) -> ColorSettings:
        if self.monitor_act.isChecked() and self._monitor_profile:
            return ColorSettings(self._monitor_profile, Intent.RELATIVE_COLORIMETRIC, True)
        return SRGB

    def _geometry(self) -> PageGeometry | None:
        job = self._job()
        if not job.printer:
            return None
        key = (job.printer, job.paper_id, job.borderless, job.base_devmode)
        if key not in self._geom_cache:
            try:
                self._geom_cache[key] = tprinter.geometry(job)
            except Exception as e:  # noqa: BLE001
                self.statusBar().showMessage(f"Printer error: {e}", 8000)
                return None
        return self._geom_cache[key]

    def _printer_changed(self):
        if self._loading:
            return
        self._populate_papers()
        self._settings_changed()

    def _settings_changed(self, *_):
        if self._loading:
            return
        s = self.s
        s.printer = self.printer_combo.currentText() or None
        s.paper_id = self.paper_combo.currentData()
        s.borderless = self.borderless_chk.isChecked()
        s.per_sheet = self.per_sheet_combo.currentData() or 1
        s.date_style = self.date_combo.currentData()
        s.fit = self.fit_combo.currentData()
        s.auto_rotate = self.rotate_chk.isChecked()
        s.profile = self.profile_combo.currentData()
        s.intent = self.intent_combo.currentData()
        s.black_point_compensation = self.bpc_chk.isChecked()
        s.monitor_preview = self.monitor_act.isChecked()
        self.bpc_chk.setEnabled(s.profile is not None)
        self.intent_combo.setEnabled(s.profile is not None)
        tsettings.save(s)
        self._clamp_zooms()
        self._sync_zoom_ui()
        self._update_print_button()
        self._schedule_preview()

    # ================= photos =================

    def _choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add photos", self.s.last_folder or "", IMAGE_FILTER)
        if files:
            self.s.last_folder = str(Path(files[0]).parent)
            tsettings.save(self.s)
            self.add_files(files)

    def add_files(self, files):
        expanded = []
        for f in files:
            p = Path(f)
            if p.is_dir():
                expanded += sorted(str(x) for x in p.iterdir() if x.suffix.lower() in IMAGE_EXTS)
            else:
                expanded.append(str(p))
        existing = {it.path for it in self.list.items()}
        new_items = []
        for p in expanded:
            if p in existing or Path(p).suffix.lower() not in IMAGE_EXTS:
                continue
            photo = PhotoItem(p)
            self.list.add(photo)
            existing.add(p)
            new_items.append(photo)
            self.loader.request(p)
        if new_items and self.list.currentItem() is None:
            self._select_photo(new_items[0])
        self._update_print_button()
        self._schedule_preview()

    def bring_to_front_with(self, files):
        """Files handed over by a second launch (Explorer right-click)."""
        self.add_files(files)
        self.setWindowState((self.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()

    def _on_thumb(self, path, img, size):
        self.thumbs[path] = img
        self.sizes[path] = size
        icon_img = img.convert("RGB")
        icon_img.thumbnail((192, 192))
        icon = QIcon(QPixmap.fromImage(pil_to_qimage(icon_img)))
        for photo in self.list.items():
            if photo.path == path:
                self.list.widget_item(photo).setIcon(icon)
        self._sync_zoom_ui()
        self._schedule_preview()

    def _on_thumb_failed(self, path, msg):
        for photo in self.list.items():
            if photo.path == path:
                self.list.takeItem(self.list.row(self.list.widget_item(photo)))
        QMessageBox.warning(self, "Could not open photo", f"{path}\n\n{msg}")
        self._update_print_button()

    def _remove_selected(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))
        self._prune_thumbs()
        self._update_print_button()
        self._schedule_preview()

    def _clear(self):
        self.list.clear()
        self._prune_thumbs()
        self._update_print_button()
        self._schedule_preview()

    def _prune_thumbs(self):
        keep = {it.path for it in self.list.items()}
        for p in list(self.thumbs):
            if p not in keep:
                self.thumbs.pop(p, None)
                self.sizes.pop(p, None)

    def _select_photo(self, photo: PhotoItem):
        it = self.list.widget_item(photo)
        if it is not None:
            self.list.clearSelection()
            self.list.setCurrentItem(it)
            it.setSelected(True)

    def _targets(self) -> list[PhotoItem]:
        """Photos that edits apply to: the selection, or the current photo."""
        sel = self.list.selected()
        if sel:
            return sel
        cur = self.list.current()
        return [cur] if cur else []

    def _selection_changed(self):
        cur = self.list.current()
        targets = self._targets()
        if cur is not None:
            self.adjust_panel.set_value(cur.adjust)
            self.copies_spin.blockSignals(True)
            self.copies_spin.setValue(cur.copies)
            self.copies_spin.blockSignals(False)
        self.adjust_panel.setEnabled(bool(targets))
        self.copies_spin.setEnabled(bool(targets))
        title = "Adjust photo" if len(targets) <= 1 else f"Adjust {len(targets)} photos"
        self.adjust_panel.setTitle(title)
        self._sync_zoom_ui()
        self._update_print_button()
        self._schedule_preview()

    def _copies_changed(self, n: int):
        for photo in self._targets():
            photo.copies = n
            self.list.refresh(photo)
        self._update_print_button()
        self._schedule_preview()

    def _adjust_changed(self, adj):
        for photo in self._targets():
            photo.adjust = adj
            self.list.refresh(photo)
        self._schedule_preview(immediate=True)

    def _auto_adjust(self):
        missing = 0
        for photo in self._targets():
            thumb = self.thumbs.get(photo.path)
            if thumb is None:
                missing += 1
                continue
            photo.adjust = tadjust.auto(thumb)
            self.list.refresh(photo)
        cur = self.list.current()
        if cur is not None:
            self.adjust_panel.set_value(cur.adjust)
        if missing:
            self.statusBar().showMessage(f"{missing} photo(s) still loading – try Auto again in a moment.", 5000)
        self._schedule_preview()

    def _crop_dragging(self, photo: PhotoItem, center):
        photo.center = center
        self._update_preview(fast=True)

    def _crop_dropped(self, photo: PhotoItem, center):
        photo.center = center
        self.list.refresh(photo)
        self._update_preview()

    # ---- zoom ----

    def _print_cell(self, photo: PhotoItem):
        """The cell (in printer pixels) the photo will be printed into; None if unknown."""
        geom = self._geometry()
        if geom is None:
            return None
        rs = self._render_settings()
        on_sheet = next((len(sh) for sh in sheets(self.list.items(), rs.per_sheet)
                         if any(p is photo for p in sh)), 1)
        return photo_cells(geom.printable_w, geom.printable_h, on_sheet,
                           gap_pixels(rs.gap_mm, geom.dpi_x), rs.polaroid)[0]

    def _max_zoom_for(self, photo: PhotoItem) -> float | None:
        """Zoom limit for a photo where it currently sits; None if not known yet."""
        if photo.path not in self.sizes or self.fit_combo.currentData() != FitMode.FILL.value:
            return None
        cell = self._print_cell(photo)
        if cell is None:
            return None
        sw, sh_ = self.sizes[photo.path]
        if turns_onto_cell(photo, self._render_settings(), sw, sh_, cell.w, cell.h):
            sw, sh_ = sh_, sw
        return max_zoom(sw, sh_, cell.w, cell.h)

    def _clamp_zooms(self):
        """Layout changes (paper, two-up, rotation) can lower a photo's limit."""
        for photo in self.list.items():
            limit = self._max_zoom_for(photo)
            if limit is not None and photo.zoom > limit:
                photo.zoom = limit
                self.list.refresh(photo)

    def _sync_zoom_ui(self):
        photo = self.list.current()
        limit = self._max_zoom_for(photo) if photo else None
        self.zoom_slider.blockSignals(True)
        if photo is None or limit is None:
            self.zoom_slider.setRange(100, 100)
            self.zoom_slider.setValue(100)
            self.zoom_slider.setEnabled(False)
            fill = self.fit_combo.currentData() == FitMode.FILL.value
            self.zoom_label.setText("" if fill or photo is None else "Zoom needs Fill layout")
        else:
            self.zoom_slider.setRange(100, max(100, int(limit * 100)))
            self.zoom_slider.setValue(round(photo.zoom * 100))
            self.zoom_slider.setEnabled(limit > 1.0)
            self.zoom_label.setText(
                f"{photo.zoom * 100:.0f}%  (max {int(limit * 100)}%)" if limit > 1.0 else
                "No room – photo resolution fully used")
        self.zoom_slider.blockSignals(False)
        self._sync_upright_button(photo)
        self.reset_crop_btn.setEnabled(photo is not None and (
            photo.zoom > 1.0 or photo.center != (0.5, 0.5) or photo.turn is not None))

    def _sync_upright_button(self, photo: PhotoItem | None):
        """Only offered when the photo's orientation doesn't match its cell."""
        cell = self._print_cell(photo) if photo and photo.path in self.sizes else None
        mismatch = cell is not None and should_rotate(*self.sizes[photo.path], cell.w, cell.h)
        self.upright_btn.blockSignals(True)
        self.upright_btn.setEnabled(mismatch)
        self.upright_btn.setChecked(mismatch and not turns_onto_cell(
            photo, self._render_settings(), *self.sizes[photo.path], cell.w, cell.h))
        self.upright_btn.blockSignals(False)

    def _upright_toggled(self, upright: bool):
        photo = self.list.current()
        if photo is None:
            return
        want_turn = not upright
        # Store only a difference from the global Auto-rotate setting.
        photo.turn = None if want_turn == self.rotate_chk.isChecked() else want_turn
        limit = self._max_zoom_for(photo)
        if limit is not None:
            photo.zoom = min(photo.zoom, limit)
        self.list.refresh(photo)
        self._sync_zoom_ui()
        self._schedule_preview(immediate=True)

    def _set_zoom(self, photo: PhotoItem, zoom: float):
        limit = self._max_zoom_for(photo)
        if limit is None:
            return
        photo.zoom = max(1.0, min(limit, zoom))
        self.list.refresh(photo)
        self._sync_zoom_ui()
        self._schedule_preview(immediate=True)

    def _zoom_slider_changed(self, value: int):
        photo = self.list.current()
        if photo is not None:
            self._set_zoom(photo, value / 100)

    def _zoom_wheel(self, photo: PhotoItem, steps: float):
        if self.list.current() is not photo:
            self._select_photo(photo)
        self._set_zoom(photo, photo.zoom * 1.12 ** steps)

    def _reset_crop(self):
        photo = self.list.current()
        if photo is None:
            return
        photo.zoom, photo.center, photo.turn = 1.0, (0.5, 0.5), None
        self.list.refresh(photo)
        self._sync_zoom_ui()
        self._schedule_preview(immediate=True)

    def _update_print_button(self):
        per_sheet = self._per_sheet()
        idle = self._print_thread is None

        def label(prefix: str, n: int) -> str:
            return prefix if n == 0 else f"{prefix} ({n} sheet{'s' if n != 1 else ''})"

        n_all = len(sheets(self.list.items(), per_sheet))
        n_sel = len(sheets(self.list.selected(), per_sheet))
        self.print_btn.setText(label("Print all", n_all))
        self.print_btn.setEnabled(n_all > 0 and idle)
        self.print_sel_btn.setText(label("Print selected", n_sel))
        self.print_sel_btn.setEnabled(n_sel > 0 and idle)

    # ================= preview =================

    def _schedule_preview(self, immediate: bool = False):
        if immediate:
            self._preview_timer.start(0)
        else:
            self._preview_timer.start(60)

    def _update_preview(self, fast: bool = False):
        geom = self._geometry()
        if geom is None:
            self.preview.set_sheet(None, "No printer available")
            self.info.setText("")
            self.sheet_label.setText("")
            return
        items = self.list.items()
        rs = self._render_settings()
        all_sheets = sheets(items, rs.per_sheet)
        cur = self.list.current()
        idx = sheet_index_of(items, rs.per_sheet, cur) if cur else None
        if idx is None:
            idx = 0
        sheet_items = all_sheets[idx] if all_sheets else [None]
        photos = [(self.thumbs[it.path], it) if it is not None and it.path in self.thumbs else None
                  for it in sheet_items]
        try:
            ps = render_preview(photos, geom, rs, self._job().borderless, self._preview_target(), fast=fast)
        except Exception as e:  # noqa: BLE001
            self.preview.set_sheet(None, f"Preview failed: {e}")
            return
        self.preview.set_sheet(ps)
        self.sheet_label.setText(f"Sheet {idx + 1} of {len(all_sheets)}" if all_sheets else
                                 "Add photos to get started")
        if not fast:
            self.info.setText(self._info_text(geom, rs, cur, len(sheet_items)))

    def _info_text(self, geom: PageGeometry, rs: RenderSettings, photo: PhotoItem | None,
                   on_sheet: int) -> str:
        w_mm, h_mm = geom.physical_mm
        lines = [
            f"<b>Sheet</b> {w_mm:.0f} × {h_mm:.0f} mm at {geom.dpi_x} dpi"
            + (" · borderless" if geom.offset_x == 0 and geom.offset_y == 0 else ""),
        ]
        cell = photo_cells(geom.printable_w, geom.printable_h, on_sheet,
                           gap_pixels(rs.gap_mm, geom.dpi_x), rs.polaroid)[0]
        cw_mm, ch_mm = cell.w / geom.dpi_x * 25.4, cell.h / geom.dpi_y * 25.4
        lines.append(f"<b>Photo area</b> {min(cw_mm, ch_mm):.0f} × {max(cw_mm, ch_mm):.0f} mm "
                     f"({cell.w} × {cell.h} px)")
        if rs.polaroid:
            frame = polaroid_frame(geom.printable_w, geom.printable_h)
            cut_mm = (geom.offset_y + frame.cut_y) / geom.dpi_y * 25.4
            lines.append(f"<b>Polaroid</b> cut along the dashed line, {cut_mm:.0f} mm from the top")
        if photo and photo.path in self.sizes:
            sw, sh = self.sizes[photo.path]
            if turns_onto_cell(photo, rs, sw, sh, cell.w, cell.h):
                sw, sh = sh, sw
            fill = rs.fit is FitMode.FILL
            scale = max(cell.w / sw, cell.h / sh) if fill else min(cell.w / sw, cell.h / sh)
            if fill:
                scale *= photo.zoom
            eff_dpi = geom.dpi_x / scale
            lines.append(f"<b>{Path(photo.path).name}</b> {self.sizes[photo.path][0]} × "
                         f"{self.sizes[photo.path][1]} px → {eff_dpi:.0f} ppi on paper")
            if eff_dpi < 150:
                lines.append("<span style='color:#c0392b'>Low resolution – may look soft.</span>")
        if rs.date_style and photo and photo.path in self.thumbs:
            when = photo_date(self.thumbs[photo.path], photo)
            lines.append(f"<b>Date stamp</b> {date_text(when)}" if when else
                         "<span style='color:#d68910'>This photo has no recorded date, "
                         "so it gets no date stamp.</span>")
        if rs.color.printer_profile is None:
            lines.append("<i>No printer profile: colours are sent as sRGB.</i>")
        return "<br>".join(lines)

    # ================= driver dialog / profile / shell =================

    def _edit_driver_settings(self):
        name = self.printer_combo.currentText()
        if not name:
            return
        try:
            dm = tprinter.build_devmode(self._job())
            new = winprint.edit_devmode(name, dm, int(self.winId()))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Printer properties", str(e))
            return
        if new is None:
            return
        self.s.set_devmode(name, new)
        idx = self.paper_combo.findData(winprint.devmode_paper_size(new))
        try:
            bl = tprinter.ticket_borderless(winprint.devmode_to_ticket(name, new))
        except Exception:  # noqa: BLE001
            bl = None
        self._loading = True
        if idx >= 0:
            self.paper_combo.setCurrentIndex(idx)
        if bl is not None:
            self.borderless_chk.setChecked(bl)
        self._loading = False
        self._settings_changed()

    def _browse_profile(self):
        start = str(Path(self.profile_combo.currentData()).parent) if self.profile_combo.currentData() else ""
        path, _ = QFileDialog.getOpenFileName(self, "Choose printer ICC profile", start,
                                              "ICC profiles (*.icc *.icm)")
        if not path:
            return
        try:
            space = profile_color_space(path).strip()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Profile", f"Not a usable ICC profile:\n{e}")
            return
        if space != "RGB":
            QMessageBox.warning(self, "Profile", f"This profile is for {space} data. "
                                "Photo printers driven through Windows need an RGB profile.")
            return
        path = str(Path(path))
        if path not in self.s.extra_profiles:
            self.s.extra_profiles.insert(0, path)
        self._populate_profiles()
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(path)))

    def _toggle_shell(self, on: bool):
        try:
            shell.register() if on else shell.unregister()
            self.statusBar().showMessage(
                "Added “Print with Open DyePrint” to Explorer's right-click menu." if on else
                "Removed “Print with Open DyePrint” from Explorer.", 6000)
        except OSError as e:
            QMessageBox.warning(self, "Explorer menu", str(e))

    # ================= printing =================

    def _print(self, selected_only: bool = False):
        items = self.list.selected() if selected_only else self.list.items()
        if not items or self._print_thread is not None:
            return
        rs = self._render_settings()
        sheet_list = sheets(items, rs.per_sheet)
        job = self._job()
        output_file = None
        try:
            if winprint.printer_port(job.printer).upper().startswith("PORTPROMPT"):
                output_file, _ = QFileDialog.getSaveFileName(self, "Print to file", "opendyeprint.pdf",
                                                             "PDF (*.pdf);;All files (*)")
                if not output_file:
                    return
        except Exception:  # noqa: BLE001
            pass
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
        total = len(sheet_list)
        worker = PrintWorker(job, sheet_list, rs, output_file)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(lambda n: (self.progress.setValue(n),
                                           self.statusBar().showMessage(f"Sent sheet {n} of {total}…")))
        worker.finished.connect(lambda n, job_id: self._print_done(job.printer, n, job_id))
        worker.failed.connect(lambda msg: self._print_failed(msg))
        self.cancel_btn.clicked.connect(worker.cancel)
        self._worker, self._print_thread = worker, thread
        self.progress.setRange(0, total)
        self.progress.setValue(0)
        self.progress.show()
        self.cancel_btn.show()
        self._update_print_button()
        self.statusBar().showMessage("Rendering…")
        thread.start()

    def _finish_thread(self):
        thread = self._print_thread
        if thread:
            thread.quit()
            thread.wait()
        try:
            self.cancel_btn.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self._print_thread = None
        self._worker = None
        self.progress.hide()
        self.cancel_btn.hide()
        self._update_print_button()

    def _print_done(self, printer: str, n: int, job_id: int):
        self._finish_thread()
        self.statusBar().showMessage(f"Sent {n} sheet{'s' if n != 1 else ''} to {printer}.", 10000)
        if job_id > 0:
            w = JobWatcher(printer, job_id, self)
            w.status.connect(self._job_status)
            w.done.connect(lambda text: self.statusBar().showMessage(text, 15000))
            self._watcher = w
            w.start()

    def _job_status(self, text: str, problem: bool):
        self.statusBar().showMessage(text)
        if problem:
            QMessageBox.warning(self, "Printer", text)

    def _print_failed(self, message: str):
        self._finish_thread()
        self.statusBar().showMessage(message, 10000)
        if message != "Printing cancelled.":
            QMessageBox.warning(self, "Printing", message)

    # ================= window =================

    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):  # noqa: N802
        self.add_files([u.toLocalFile() for u in e.mimeData().urls()])

    def closeEvent(self, e):  # noqa: N802
        if self._print_thread is not None:
            QMessageBox.information(self, "Open DyePrint", "Please wait until printing has finished.")
            e.ignore()
            return
        if self._watcher:
            self._watcher.stop()
        self.s.window_geometry = base64.b64encode(bytes(self.saveGeometry())).decode("ascii")
        self.s.splitter_state = base64.b64encode(bytes(self.split.saveState())).decode("ascii")
        tsettings.save(self.s)
        super().closeEvent(e)

