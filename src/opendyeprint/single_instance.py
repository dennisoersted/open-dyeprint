"""One Open DyePrint window: later launches (e.g. Explorer's "Print with Open DyePrint" on several
files, which starts one process per file) hand their files to the running window."""

from __future__ import annotations

import ctypes
import getpass
import json
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

ERROR_ALREADY_EXISTS = 183


def _name() -> str:
    user = "".join(c for c in getpass.getuser() if c.isalnum()) or "user"
    return f"opendyeprint-{user}"


class SingleInstance(QObject):
    files_received = Signal(list)

    def __init__(self):
        super().__init__()
        self._server: QLocalServer | None = None
        self._mutex = None

    def is_primary(self) -> bool:
        """Claim the instance mutex. False when another Open DyePrint already owns it."""
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        self._mutex = kernel32.CreateMutexW(None, False, "Local\\" + _name())
        return ctypes.get_last_error() != ERROR_ALREADY_EXISTS

    def send(self, files: list[str], timeout_s: float = 10.0) -> bool:
        """Deliver files to the primary instance (waits for it to finish starting)."""
        payload = json.dumps(files).encode("utf-8")
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            sock = QLocalSocket()
            sock.connectToServer(_name())
            if sock.waitForConnected(500):
                sock.write(payload)
                sock.flush()
                sock.waitForBytesWritten(2000)
                sock.disconnectFromServer()
                return True
            time.sleep(0.2)
        return False

    def listen(self) -> None:
        QLocalServer.removeServer(_name())
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        self._server.listen(_name())

    def _on_connection(self):
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            buf = bytearray()

            def read(sock=sock, buf=buf):
                buf.extend(bytes(sock.readAll()))

            def done(sock=sock, buf=buf):
                buf.extend(bytes(sock.readAll()))
                try:
                    files = json.loads(buf.decode("utf-8"))
                except ValueError:
                    files = []
                # Even an empty list matters: it brings the window to the front.
                self.files_received.emit([str(f) for f in files])
                sock.deleteLater()

            sock.readyRead.connect(read)
            sock.disconnected.connect(done)
