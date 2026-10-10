"""Explorer right-click menu: "Print with Open DyePrint" for photo files (current user only)."""

from __future__ import annotations

import sys
import winreg
from pathlib import Path

VERB = "OpenDyePrint"
LEGACY_VERBS = ("Tintype",)  # menu entries written under the app's earlier name
LABEL = "Print with Open DyePrint"
EXTENSIONS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".webp")
_BASE = r"Software\Classes\SystemFileAssociations\{ext}\shell\{verb}"


def launch_command() -> tuple[str, str]:
    """(command line with %1, icon path) for the current way Open DyePrint is running."""
    if getattr(sys, "frozen", False):  # PyInstaller build
        exe = sys.executable
        return f'"{exe}" "%1"', exe
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pythonw if pythonw.exists() else Path(sys.executable))
    return f'"{exe}" -m opendyeprint "%1"', exe


def is_registered() -> bool:
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, _BASE.format(ext=EXTENSIONS[0], verb=VERB)).Close()
        return True
    except OSError:
        return False


def register() -> None:
    _remove_verbs(LEGACY_VERBS)
    command, icon = launch_command()
    for ext in EXTENSIONS:
        key = _BASE.format(ext=ext, verb=VERB)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, LABEL)
            winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, icon)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\command") as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, command)


def unregister() -> None:
    _remove_verbs((VERB, *LEGACY_VERBS))


def _remove_verbs(verbs) -> None:
    for verb in verbs:
        for ext in EXTENSIONS:
            key = _BASE.format(ext=ext, verb=verb)
            for sub in (key + r"\command", key):
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
                except OSError:
                    pass
