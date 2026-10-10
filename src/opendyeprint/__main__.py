"""Entry point: `python -m opendyeprint [photos...]`, the `opendyeprint` script, or OpenDyePrint.exe."""

from __future__ import annotations

import sys


def main() -> int:
    import ctypes

    try:  # own taskbar group
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OpenDyePrint")
    except (AttributeError, OSError):
        pass

    from pathlib import Path

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .single_instance import SingleInstance

    app = QApplication(sys.argv)
    app.setApplicationName("Open DyePrint")
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "opendyeprint.png")))
    files = sys.argv[1:]

    instance = SingleInstance()
    if not instance.is_primary():
        if instance.send(files):
            return 0
        # The other instance is unresponsive: carry on as a normal window.
    instance.listen()

    from .ui.main_window import MainWindow

    win = MainWindow(initial_files=files)
    instance.files_received.connect(win.bring_to_front_with)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
