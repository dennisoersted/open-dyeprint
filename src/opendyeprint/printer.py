"""High-level printing: build the job DEVMODE and send rendered photos."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from . import winprint
from .layout import PageGeometry
from .model import PhotoItem
from .render import RenderSettings, render_sheet_for_print

_BORDERLESS_RE = re.compile(r'(<psf:Feature name="psk:PageBorderless">\s*<psf:Option name=")([^"]+)')


@dataclass(frozen=True)
class JobSettings:
    printer: str
    paper_id: int | None = None  # None = keep the driver/base setting
    borderless: bool = True
    base_devmode: bytes | None = None  # from "Printer properties…"; None = driver default


def set_ticket_borderless(ticket: str, on: bool) -> tuple[str, bool]:
    """Return (ticket, supported). Unsupported tickets are returned unchanged."""
    if not _BORDERLESS_RE.search(ticket):
        return ticket, False
    value = "psk:Borderless" if on else "psk:None"
    return _BORDERLESS_RE.sub(lambda m: m.group(1) + value, ticket, count=1), True


def ticket_borderless(ticket: str) -> bool | None:
    m = _BORDERLESS_RE.search(ticket)
    return None if m is None else m.group(2) == "psk:Borderless"


def build_devmode(job: JobSettings) -> bytes:
    """DEVMODE for the job: portrait, colour, Windows ICM off, chosen paper + borderless.

    Colour management is done by Open DyePrint, so the driver must not apply its own.
    """
    dm = job.base_devmode or winprint.default_devmode(job.printer)
    fields = dict(orientation=winprint.DMORIENT_PORTRAIT, copies=1,
                  color=winprint.DMCOLOR_COLOR, icm_method=winprint.DMICMMETHOD_NONE)
    if job.paper_id is not None:
        fields["paper_size"] = job.paper_id
    dm = winprint.validate_devmode(job.printer, winprint.devmode_with(dm, **fields))
    try:
        ticket = winprint.devmode_to_ticket(job.printer, dm)
        new_ticket, supported = set_ticket_borderless(ticket, job.borderless)
        if supported and new_ticket != ticket:
            dm = winprint.ticket_to_devmode(job.printer, new_ticket)
    except winprint.PrintError:
        pass  # driver without print-ticket support: keep what the dialog/defaults set
    # The ticket round trip may reset public fields; enforce ICM off once more.
    return winprint.devmode_with(dm, icm_method=winprint.DMICMMETHOD_NONE)


def geometry(job: JobSettings) -> PageGeometry:
    return winprint.page_geometry(job.printer, build_devmode(job))


def supports_borderless(printer: str) -> bool:
    try:
        ticket = winprint.devmode_to_ticket(printer, winprint.default_devmode(printer))
    except winprint.PrintError:
        return False
    return ticket_borderless(ticket) is not None


def print_sheets(job: JobSettings, sheet_list: list[list[PhotoItem | None]], render: RenderSettings,
                 on_page: Callable[[int], None] | None = None,
                 cancelled: Callable[[], bool] | None = None,
                 output_file: str | None = None) -> tuple[int, int]:
    """Print sheets (each a list of photos per cell). Returns (sheets sent, spooler job id)."""
    dm = build_devmode(job)
    geom = winprint.page_geometry(job.printer, dm)

    def pages():
        for items in sheet_list:
            if cancelled and cancelled():
                raise InterruptedError("cancelled")
            yield render_sheet_for_print(items, geom.printable_w, geom.printable_h, geom.dpi_x, render)

    count = 0

    def _counted(n):
        nonlocal count
        count = n
        if on_page:
            on_page(n)

    job_id = winprint.print_pages(job.printer, dm, pages(), doc_name="Open DyePrint",
                                  output_file=output_file, on_page=_counted)
    return count, job_id
