"""Background work: loading photos, printing, watching the print queue."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
from PySide6.QtCore import QObject, QTimer, Signal

from .. import printer as tprinter
from .. import winprint
from ..render import load

THUMB_LONG_SIDE = 1400  # big enough for a sharp preview, small enough to stay snappy


class ThumbLoader(QObject):
    """Loads photos in the background; emits (path, preview image, original size)."""

    loaded = Signal(str, object, object)
    failed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self._pool = ThreadPoolExecutor(max_workers=3)

    def request(self, path: str) -> None:
        self._pool.submit(self._load, path)

    def _load(self, path: str) -> None:
        try:
            img = load(path)
            size = img.size
            icc = img.info.get("icc_profile")
            img.thumbnail((THUMB_LONG_SIDE, THUMB_LONG_SIDE), Image.Resampling.LANCZOS)
            if icc:
                img.info["icc_profile"] = icc
            self.loaded.emit(path, img, size)
        except Exception as e:  # noqa: BLE001 - shown to the user
            self.failed.emit(path, str(e))


class PrintWorker(QObject):
    progress = Signal(int)
    finished = Signal(int, int)  # sheets, job id
    failed = Signal(str)

    def __init__(self, job, sheet_list, render, output_file):
        super().__init__()
        self.job, self.sheet_list, self.render, self.output_file = job, sheet_list, render, output_file
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            n, job_id = tprinter.print_sheets(self.job, self.sheet_list, self.render,
                                              on_page=self.progress.emit,
                                              cancelled=self._cancel.is_set,
                                              output_file=self.output_file)
            self.finished.emit(n, job_id)
        except InterruptedError:
            self.failed.emit("Printing cancelled.")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class JobWatcher(QObject):
    """Polls the Windows print queue for a job and reports its state."""

    status = Signal(str, bool)  # message, is_problem
    done = Signal(str)
    _result = Signal(bool, str)

    POLL_MS = 2000
    MAX_POLLS = 450  # ~15 minutes

    def __init__(self, printer: str, job_id: int, parent=None):
        super().__init__(parent)
        self.printer, self.job_id = printer, job_id
        self._polls = 0
        self._last = None
        self._busy = False
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._timer = QTimer(self, interval=self.POLL_MS)
        self._timer.timeout.connect(self._tick)
        self._result.connect(self._on_result)

    def start(self):
        self._timer.start()
        self._tick()

    def stop(self):
        self._timer.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _tick(self):
        self._polls += 1
        if self._polls > self.MAX_POLLS:
            self.stop()
            return
        if self._busy:
            return
        self._busy = True
        self._pool.submit(self._query)

    def _query(self):
        try:
            finished, text = winprint.job_state(self.printer, self.job_id)
        except Exception as e:  # noqa: BLE001
            finished, text = True, f"Could not read print queue: {e}"
        self._result.emit(finished, text)

    def _on_result(self, finished: bool, text: str):
        self._busy = False
        if finished:
            self.stop()
            self.done.emit(text)
            return
        if text != self._last:
            self._last = text
            self.status.emit(text, text.startswith("Printer:"))
