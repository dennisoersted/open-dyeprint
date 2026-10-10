"""Copies the licence texts for everything bundled in the .exe into dist/OpenDyePrint/licenses.

Run by build.bat after PyInstaller. Extra licence texts that no installed package ships
with (e.g. the GNU LGPL/GPL for Qt and libheif) go in packaging/licenses/.
"""

import shutil
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "OpenDyePrint" / "licenses"
PACKAGES = {"pillow": "Pillow", "pi-heif": "pi-heif", "pywin32": "pywin32"}


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    shutil.copy(ROOT / "LICENSE", OUT / "OpenDyePrint-LICENSE.txt")
    shutil.copy(ROOT / "THIRD-PARTY-NOTICES.md", OUT / "THIRD-PARTY-NOTICES.md")
    python_licence = Path(sys.base_prefix) / "LICENSE.txt"
    if python_licence.exists():
        shutil.copy(python_licence, OUT / "Python-LICENSE.txt")
    for dist_name, label in PACKAGES.items():
        files = metadata.distribution(dist_name).files or []
        for f in files:
            if "licenses" in f.parts or f.name.upper().startswith(("LICENSE", "COPYING")):
                src = Path(f.locate())
                if src.is_file():
                    flat = "-".join(f.parts[f.parts.index("licenses") + 1:]) if "licenses" in f.parts else f.name
                    shutil.copy(src, OUT / f"{label}-{flat}")
    for extra in (ROOT / "packaging" / "licenses").glob("*"):
        shutil.copy(extra, OUT / extra.name)
    print(f"licences copied to {OUT}")


if __name__ == "__main__":
    main()
