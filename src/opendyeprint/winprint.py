"""Thin ctypes layer over winspool / GDI / prntvpt.

DEVMODEs are handled as raw bytes so the driver-private part (which holds
things like the IPP class driver's borderless flag) survives round trips and
can be saved to the settings file.
"""

from __future__ import annotations

import ctypes
import struct
from ctypes import wintypes as wt
from dataclasses import dataclass

from PIL import Image

from .layout import PageGeometry

winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# --- DEVMODEW public-field offsets -------------------------------------------
_OFF_SIZE = 68
_OFF_DRIVER_EXTRA = 70
_OFF_FIELDS = 72
_OFF_ORIENTATION = 76
_OFF_PAPER_SIZE = 78
_OFF_COPIES = 86
_OFF_COLOR = 92
_OFF_ICM_METHOD = 188
_OFF_ICM_INTENT = 192

DM_ORIENTATION = 0x00000001
DM_PAPERSIZE = 0x00000002
DM_COPIES = 0x00000100
DM_COLOR = 0x00000800
DM_ICMMETHOD = 0x00010000

DMORIENT_PORTRAIT = 1
DMCOLOR_COLOR = 2
DMICMMETHOD_NONE = 1

DM_OUT_BUFFER = 2
DM_IN_PROMPT = 4
DM_IN_BUFFER = 8
IDOK = 1

# GetDeviceCaps indices
HORZRES, VERTRES = 8, 10
LOGPIXELSX, LOGPIXELSY = 88, 90
PHYSICALWIDTH, PHYSICALHEIGHT = 110, 111
PHYSICALOFFSETX, PHYSICALOFFSETY = 112, 113

DC_PAPERS, DC_PAPERSIZE, DC_PAPERNAMES = 2, 3, 16


class PrintError(RuntimeError):
    pass


def _check(ok, what: str):
    if not ok:
        raise PrintError(f"{what} failed (Windows error {ctypes.get_last_error()})")
    return ok


# --- DEVMODE helpers ---------------------------------------------------------

def devmode_get(dm: bytes, off: int, fmt: str = "<h"):
    return struct.unpack_from(fmt, dm, off)[0]


def devmode_with(dm: bytes, **fields) -> bytes:
    """Set public DEVMODE fields: orientation, paper_size, copies, color, icm_method."""
    buf = bytearray(dm)
    flags = struct.unpack_from("<I", buf, _OFF_FIELDS)[0]
    table = {
        "orientation": (_OFF_ORIENTATION, "<h", DM_ORIENTATION),
        "paper_size": (_OFF_PAPER_SIZE, "<h", DM_PAPERSIZE),
        "copies": (_OFF_COPIES, "<h", DM_COPIES),
        "color": (_OFF_COLOR, "<h", DM_COLOR),
        "icm_method": (_OFF_ICM_METHOD, "<I", DM_ICMMETHOD),
    }
    for name, value in fields.items():
        off, fmt, flag = table[name]
        struct.pack_into(fmt, buf, off, value)
        flags |= flag
    struct.pack_into("<I", buf, _OFF_FIELDS, flags)
    return bytes(buf)


def devmode_paper_size(dm: bytes) -> int:
    return devmode_get(dm, _OFF_PAPER_SIZE)


def devmode_icm_method(dm: bytes) -> int:
    return devmode_get(dm, _OFF_ICM_METHOD, "<I")


# --- printers ----------------------------------------------------------------

winspool.OpenPrinterW.argtypes = [wt.LPCWSTR, ctypes.POINTER(wt.HANDLE), ctypes.c_void_p]
winspool.ClosePrinter.argtypes = [wt.HANDLE]
winspool.DocumentPropertiesW.argtypes = [wt.HWND, wt.HANDLE, wt.LPCWSTR, ctypes.c_void_p,
                                         ctypes.c_void_p, wt.DWORD]
winspool.DocumentPropertiesW.restype = wt.LONG
winspool.DeviceCapabilitiesW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, wt.WORD, ctypes.c_void_p,
                                         ctypes.c_void_p]
winspool.DeviceCapabilitiesW.restype = ctypes.c_int


def list_printers() -> list[str]:
    import win32print  # pywin32; enumeration is painful in raw ctypes

    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return [p[2] for p in win32print.EnumPrinters(flags)]


def printer_port(name: str) -> str:
    import win32print

    h = win32print.OpenPrinter(name)
    try:
        return win32print.GetPrinter(h, 2)["pPortName"] or ""
    finally:
        win32print.ClosePrinter(h)


def default_printer() -> str | None:
    import win32print

    try:
        return win32print.GetDefaultPrinter()
    except Exception:
        return None


class _Printer:
    def __init__(self, name: str):
        self.name = name
        self.handle = wt.HANDLE()

    def __enter__(self):
        _check(winspool.OpenPrinterW(self.name, ctypes.byref(self.handle), None),
               f"OpenPrinter({self.name!r})")
        return self.handle

    def __exit__(self, *exc):
        winspool.ClosePrinter(self.handle)


def _document_properties(name: str, dm_in: bytes | None, prompt: bool, hwnd: int = 0) -> bytes | None:
    with _Printer(name) as h:
        size = winspool.DocumentPropertiesW(hwnd, h, name, None, None, 0)
        if size <= 0:
            raise PrintError("DocumentProperties could not size the DEVMODE")
        out = ctypes.create_string_buffer(size)
        mode = DM_OUT_BUFFER
        inbuf = None
        if dm_in is not None:
            inbuf = ctypes.create_string_buffer(dm_in, len(dm_in))
            mode |= DM_IN_BUFFER
        if prompt:
            mode |= DM_IN_PROMPT
        res = winspool.DocumentPropertiesW(hwnd, h, name, out, inbuf, mode)
        if res < 0:
            raise PrintError("DocumentProperties failed")
        if prompt and res != IDOK:
            return None  # user cancelled
        total = devmode_get(out.raw, _OFF_SIZE, "<H") + devmode_get(out.raw, _OFF_DRIVER_EXTRA, "<H")
        return out.raw[:total]


def default_devmode(name: str) -> bytes:
    return _document_properties(name, None, prompt=False)


def validate_devmode(name: str, dm: bytes) -> bytes:
    """Let the driver merge/validate a DEVMODE (e.g. after we changed public fields)."""
    return _document_properties(name, dm, prompt=False)


def edit_devmode(name: str, dm: bytes, hwnd: int = 0) -> bytes | None:
    """Show the driver's own properties dialog. Returns None on cancel."""
    return _document_properties(name, dm, prompt=True, hwnd=hwnd)


@dataclass(frozen=True)
class Paper:
    id: int
    name: str
    size_mm: tuple[float, float]  # width, height in mm (portrait)

    @property
    def label(self) -> str:
        return f"{self.name}  ({self.size_mm[0]:g} × {self.size_mm[1]:g} mm)"


def list_papers(name: str) -> list[Paper]:
    import win32con
    import win32print

    port = printer_port(name)
    ids = win32print.DeviceCapabilities(name, port, win32con.DC_PAPERS)
    names = win32print.DeviceCapabilities(name, port, win32con.DC_PAPERNAMES)
    sizes = win32print.DeviceCapabilities(name, port, win32con.DC_PAPERSIZE)
    return [Paper(int(i), str(n).strip("\x00 "), (s["x"] / 10, s["y"] / 10))
            for i, n, s in zip(ids, names, sizes)]


# --- GDI ---------------------------------------------------------------------

gdi32.CreateDCW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, ctypes.c_void_p]
gdi32.CreateDCW.restype = wt.HDC
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.GetDeviceCaps.argtypes = [wt.HDC, ctypes.c_int]


class DOCINFOW(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_int), ("lpszDocName", wt.LPCWSTR),
                ("lpszOutput", wt.LPCWSTR), ("lpszDatatype", wt.LPCWSTR),
                ("fwType", wt.DWORD)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


gdi32.StartDocW.argtypes = [wt.HDC, ctypes.POINTER(DOCINFOW)]
gdi32.StartPage.argtypes = [wt.HDC]
gdi32.EndPage.argtypes = [wt.HDC]
gdi32.EndDoc.argtypes = [wt.HDC]
gdi32.AbortDoc.argtypes = [wt.HDC]
gdi32.SetICMMode.argtypes = [wt.HDC, ctypes.c_int]
gdi32.StretchDIBits.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_void_p, ctypes.POINTER(BITMAPINFOHEADER), wt.UINT,
                                wt.DWORD]
ICM_OFF = 1
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0


class _DC:
    def __init__(self, name: str, dm: bytes):
        self.name, self.dm = name, dm
        self._dmbuf = ctypes.create_string_buffer(dm, len(dm))
        self.hdc = None

    def __enter__(self):
        self.hdc = gdi32.CreateDCW("WINSPOOL", self.name, None, self._dmbuf)
        _check(self.hdc, f"CreateDC({self.name!r})")
        return self.hdc

    def __exit__(self, *exc):
        gdi32.DeleteDC(self.hdc)


def _geometry(hdc) -> PageGeometry:
    c = lambda i: gdi32.GetDeviceCaps(hdc, i)  # noqa: E731
    return PageGeometry(
        dpi_x=c(LOGPIXELSX), dpi_y=c(LOGPIXELSY),
        physical_w=c(PHYSICALWIDTH), physical_h=c(PHYSICALHEIGHT),
        offset_x=c(PHYSICALOFFSETX), offset_y=c(PHYSICALOFFSETY),
        printable_w=c(HORZRES), printable_h=c(VERTRES),
    )


def page_geometry(name: str, dm: bytes) -> PageGeometry:
    with _DC(name, dm) as hdc:
        return _geometry(hdc)


def dib_bytes(img: Image.Image) -> tuple[bytes, BITMAPINFOHEADER]:
    """24-bit bottom-up DIB with 4-byte row padding."""
    if img.mode != "RGB":
        raise ValueError("expected RGB")
    w, h = img.size
    stride = (w * 3 + 3) & ~3
    data = img.tobytes("raw", "BGR", stride, -1)
    hdr = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, h, 1, 24, 0, len(data), 0, 0, 0, 0)
    return data, hdr


def print_pages(name: str, dm: bytes, pages, doc_name: str = "Open DyePrint",
                output_file: str | None = None, on_page=None) -> int:
    """Print an iterable of RGB images, each drawn 1:1 at the printable-area origin.

    `pages` may be a generator so rendering happens page by page. `output_file`
    is for print-to-file drivers (e.g. Microsoft Print to PDF) to avoid a prompt.
    Returns the spooler job id.
    """
    with _DC(name, dm) as hdc:
        gdi32.SetICMMode(hdc, ICM_OFF)
        geom = _geometry(hdc)
        di = DOCINFOW(ctypes.sizeof(DOCINFOW), doc_name, output_file, None, 0)
        job_id = gdi32.StartDocW(hdc, ctypes.byref(di))
        if job_id <= 0:
            raise PrintError(f"StartDoc failed (Windows error {ctypes.get_last_error()})")
        try:
            for i, img in enumerate(pages):
                if img.size != (geom.printable_w, geom.printable_h):
                    raise PrintError(f"page {i + 1} is {img.size}, printer expects "
                                     f"{(geom.printable_w, geom.printable_h)}")
                data, hdr = dib_bytes(img)
                _check(gdi32.StartPage(hdc) > 0, "StartPage")
                w, h = img.size
                lines = gdi32.StretchDIBits(hdc, 0, 0, w, h, 0, 0, w, h, data,
                                            ctypes.byref(hdr), DIB_RGB_COLORS, SRCCOPY)
                _check(lines != 0, "StretchDIBits")
                _check(gdi32.EndPage(hdc) > 0, "EndPage")
                if on_page:
                    on_page(i + 1)
        except BaseException:
            gdi32.AbortDoc(hdc)
            raise
        _check(gdi32.EndDoc(hdc) > 0, "EndDoc")
        return job_id


# --- Print tickets (borderless) ---------------------------------------------

prntvpt = ctypes.WinDLL("prntvpt")
_HPTPROVIDER = ctypes.c_void_p
prntvpt.PTOpenProvider.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.POINTER(_HPTPROVIDER)]
prntvpt.PTOpenProvider.restype = ctypes.c_long
prntvpt.PTCloseProvider.argtypes = [_HPTPROVIDER]
prntvpt.PTConvertDevModeToPrintTicket.argtypes = [_HPTPROVIDER, wt.ULONG, ctypes.c_void_p,
                                                  ctypes.c_int, ctypes.c_void_p]
prntvpt.PTConvertDevModeToPrintTicket.restype = ctypes.c_long
prntvpt.PTConvertPrintTicketToDevMode.argtypes = [_HPTPROVIDER, ctypes.c_void_p, ctypes.c_int,
                                                  ctypes.c_int, ctypes.POINTER(wt.ULONG),
                                                  ctypes.POINTER(ctypes.c_void_p),
                                                  ctypes.POINTER(ctypes.c_void_p)]
prntvpt.PTConvertPrintTicketToDevMode.restype = ctypes.c_long
prntvpt.PTReleaseMemory.argtypes = [ctypes.c_void_p]
ole32.CreateStreamOnHGlobal.argtypes = [ctypes.c_void_p, wt.BOOL, ctypes.POINTER(ctypes.c_void_p)]
ole32.CreateStreamOnHGlobal.restype = ctypes.c_long

kPTJobScope = 2
kUserDefaultDevmode = 0


def _hr(hr: int, what: str):
    if hr < 0:
        raise PrintError(f"{what} failed (HRESULT 0x{hr & 0xFFFFFFFF:08X})")


def _vcall(obj, index, restype, *args_and_types):
    """Call COM vtable method `index` on raw interface pointer `obj`."""
    argtypes = [t for _, t in args_and_types]
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])
    return fn(obj, *[a for a, _ in args_and_types])


class _Stream:
    """Minimal IStream on an HGLOBAL."""

    def __init__(self, data: bytes = b""):
        self.ptr = ctypes.c_void_p()
        _hr(ole32.CreateStreamOnHGlobal(None, True, ctypes.byref(self.ptr)), "CreateStreamOnHGlobal")
        if data:
            written = wt.ULONG()
            buf = ctypes.create_string_buffer(data, len(data))
            _hr(_vcall(self.ptr, 4, ctypes.c_long, (buf, ctypes.c_void_p),
                       (len(data), wt.ULONG), (ctypes.byref(written), ctypes.c_void_p)), "IStream.Write")
            self.rewind()

    def rewind(self):
        _hr(_vcall(self.ptr, 5, ctypes.c_long, (0, ctypes.c_longlong), (0, wt.DWORD),
                   (None, ctypes.c_void_p)), "IStream.Seek")

    def read_all(self) -> bytes:
        end = ctypes.c_ulonglong()
        _hr(_vcall(self.ptr, 5, ctypes.c_long, (0, ctypes.c_longlong), (2, wt.DWORD),
                   (ctypes.byref(end), ctypes.c_void_p)), "IStream.Seek")
        self.rewind()
        buf = ctypes.create_string_buffer(end.value)
        got = wt.ULONG()
        _hr(_vcall(self.ptr, 3, ctypes.c_long, (buf, ctypes.c_void_p), (end.value, wt.ULONG),
                   (ctypes.byref(got), ctypes.c_void_p)), "IStream.Read")
        return buf.raw[:got.value]

    def close(self):
        if self.ptr:
            _vcall(self.ptr, 2, wt.ULONG)
            self.ptr = ctypes.c_void_p()


class _Provider:
    def __init__(self, name: str):
        self.name = name
        self.h = _HPTPROVIDER()

    def __enter__(self):
        _hr(prntvpt.PTOpenProvider(self.name, 1, ctypes.byref(self.h)), "PTOpenProvider")
        return self.h

    def __exit__(self, *exc):
        prntvpt.PTCloseProvider(self.h)


def devmode_to_ticket(name: str, dm: bytes) -> str:
    with _Provider(name) as h:
        s = _Stream()
        try:
            buf = ctypes.create_string_buffer(dm, len(dm))
            _hr(prntvpt.PTConvertDevModeToPrintTicket(h, len(dm), buf, kPTJobScope, s.ptr),
                "PTConvertDevModeToPrintTicket")
            return s.read_all().decode("utf-8")
        finally:
            s.close()


def ticket_to_devmode(name: str, ticket_xml: str) -> bytes:
    with _Provider(name) as h:
        s = _Stream(ticket_xml.encode("utf-8"))
        try:
            size = wt.ULONG()
            pdm = ctypes.c_void_p()
            err = ctypes.c_void_p()
            _hr(prntvpt.PTConvertPrintTicketToDevMode(h, s.ptr, kUserDefaultDevmode, kPTJobScope,
                                                      ctypes.byref(size), ctypes.byref(pdm),
                                                      ctypes.byref(err)),
                "PTConvertPrintTicketToDevMode")
            try:
                return ctypes.string_at(pdm, size.value)
            finally:
                prntvpt.PTReleaseMemory(pdm)
        finally:
            s.close()


# --- queue status --------------------------------------------------------------

_JOB_PROBLEMS = [
    (0x40, "out of paper or ink cassette"),
    (0x20, "printer offline"),
    (0x400, "printer needs attention"),
    (0x2, "error"),
    (0x200, "blocked"),
    (0x1, "paused"),
]
_PRINTER_PROBLEMS = [
    (0x10, "out of paper"),
    (0x8, "paper jam"),
    (0x40000, "out of ink"),
    (0x400000, "cover open"),
    (0x80, "offline"),
    (0x1000, "not available"),
    (0x100000, "needs attention"),
    (0x2, "error"),
    (0x1, "paused"),
]


def describe_problems(job_status: int, printer_status: int) -> list[str]:
    found = [text for bit, text in _JOB_PROBLEMS if job_status & bit]
    found += [text for bit, text in _PRINTER_PROBLEMS
              if printer_status & bit and text not in " ".join(found)]
    return found


def job_state(name: str, job_id: int) -> tuple[bool, str]:
    """(finished, human-readable state) for a spooled job."""
    import win32print

    h = win32print.OpenPrinter(name)
    try:
        printer_status = win32print.GetPrinter(h, 2)["Status"]
        try:
            job = win32print.GetJob(h, job_id, 1)
        except Exception:  # noqa: BLE001 - job left the queue
            problems = describe_problems(0, printer_status)
            return True, ("Printer reports: " + ", ".join(problems)) if problems else "Printed."
        status = job["Status"]
        problems = describe_problems(status, printer_status)
        if job.get("pStatus"):
            problems.insert(0, job["pStatus"])
        if problems:
            return False, "Printer: " + ", ".join(problems)
        if status & (0x80 | 0x1000):
            return True, "Printed."
        if status & 0x10:
            return False, "Printing…"
        return False, "Waiting in print queue…"
    finally:
        win32print.ClosePrinter(h)
