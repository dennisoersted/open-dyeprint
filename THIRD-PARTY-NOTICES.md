# Third-party notices

Open DyePrint stands on the shoulders of some excellent open-source projects. Its own code
is MIT licensed (see [LICENSE](LICENSE)), and the Windows download (`OpenDyePrint.exe`)
also contains the libraries below. Their licence texts are in the `licenses` folder next to
the `.exe`. Thank you to everyone who works on them.

| Component | What it's used for | Licence | Source |
|---|---|---|---|
| Python | runs the app | PSF License | https://www.python.org |
| Qt 6 and PySide6 | the user interface | LGPL-3.0 | https://code.qt.io |
| Pillow (incl. LittleCMS, libjpeg-turbo, libpng, libtiff, libwebp, zlib, FreeType) | reading images, colour management | MIT-CMU / HPND, plus the licences in `licenses/Pillow-LICENSE` | https://github.com/python-pillow/Pillow |
| pi-heif | reading HEIC photos | BSD-3-Clause | https://github.com/bigcat88/pillow_heif |
| libheif (in pi-heif) | reading HEIC photos | LGPL-3.0 | https://github.com/strukturag/libheif |
| libde265 (in pi-heif) | decoding HEIC photos | LGPL-3.0 | https://github.com/strukturag/libde265 |
| pywin32 | Windows printing | PSF License | https://github.com/mhammond/pywin32 |
| PyInstaller bootloader | starts the `.exe` | GPL-2.0 with an exception that allows any licence for the bundled app | https://pyinstaller.org |

## About the LGPL libraries

Qt, PySide6, libheif and libde265 are shipped unmodified as separate DLL and `.pyd` files
in the `_internal` folder. You're free to replace them with your own builds of the same
libraries. Their source code is available from the links above. The GNU LGPL-3.0 and GPL-3.0
texts are included as `licenses/GNU-LGPL-3.0.txt` and `licenses/GNU-GPL-3.0.txt`.
