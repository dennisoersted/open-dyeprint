"""User settings, stored as JSON in %APPDATA%/Open DyePrint/settings.json."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home())


def settings_path() -> Path:
    return _appdata() / "Open DyePrint" / "settings.json"


def legacy_settings_path() -> Path:
    """Where the app kept settings before it was renamed (it was called Tintype)."""
    return _appdata() / "Tintype" / "settings.json"


@dataclass
class Settings:
    printer: str | None = None
    paper_id: int | None = None
    borderless: bool = True
    fit: str = "fill"
    auto_rotate: bool = True
    profile: str | None = None
    intent: int = 0
    black_point_compensation: bool = True
    per_sheet: int = 1
    monitor_preview: bool = True
    date_style: str | None = None
    window_geometry: str | None = None  # base64 of QWidget.saveGeometry()
    splitter_state: str | None = None
    last_folder: str | None = None
    extra_profiles: list[str] = field(default_factory=list)
    # printer name -> base64 DEVMODE from the driver's properties dialog
    devmodes: dict[str, str] = field(default_factory=dict)

    def devmode_for(self, printer: str) -> bytes | None:
        raw = self.devmodes.get(printer)
        return base64.b64decode(raw) if raw else None

    def set_devmode(self, printer: str, dm: bytes | None) -> None:
        if dm is None:
            self.devmodes.pop(printer, None)
        else:
            self.devmodes[printer] = base64.b64encode(dm).decode("ascii")


def load(path: Path | None = None) -> Settings:
    if path is None:
        path = settings_path()
        if not path.exists() and legacy_settings_path().exists():
            path = legacy_settings_path()  # carried over; saved to the new place next time
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    known = Settings.__dataclass_fields__
    return Settings(**{k: v for k, v in data.items() if k in known})


def save(settings: Settings, path: Path | None = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    tmp.replace(path)
