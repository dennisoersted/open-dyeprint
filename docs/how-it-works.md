# How it works

This is the long version: how Open DyePrint gets a photo onto the paper without anything
along the way messing with the colours or the sharpness. Grab a coffee.

Most of it was figured out the hard way on a Canon SELPHY CP1500 on Wi-Fi, but only the
borderless trick is SELPHY-specific.

## The pipeline

For every sheet:

1. **Load** the photo with Pillow (HEIC through `pi-heif`), apply the EXIF rotation and
   keep the embedded ICC profile. No profile means sRGB.
2. **Place** it: work out the crop for the photo's cell (fill or fit, the crop position you
   dragged, the zoom) and turn it 90° if it fits the cell better that way.
3. **Resample once** with Lanczos, straight from the original pixels to the exact number of
   printer pixels the cell covers. The printer never rescales anything, which is exactly
   how I like it.
4. **Adjust**: exposure, contrast and so on, as one lookup table per channel (fast).
5. **Date stamp**, drawn in the photo's own upright orientation.
6. **Colour convert** from the photo's profile to the printer profile with LittleCMS
   (through Pillow's `ImageCms`), using the rendering intent and black point compensation
   you picked.
7. **Print** the finished sheet as a 24-bit bitmap, drawn 1:1 at the printer's resolution.

The preview runs the same code on a smaller copy of the photo, converted to your monitor
profile instead of the printer profile.

## Talking to Windows

The printing layer (`winprint.py`) uses `ctypes` against `winspool.drv`, `gdi32` and
`prntvpt.dll`. Yes, Win32 APIs from Python. It works, and it's surprisingly little code.
It does four things:

**1. Build the job settings (DEVMODE).** Paper size, portrait orientation, colour, one
copy, and `dmICMMethod = DMICMMETHOD_NONE`. That last one switches off Windows' own colour
management (ICM), so the printer gets the RGB values that came out of your ICC profile,
untouched. DEVMODEs are kept as raw bytes, so the driver's private settings survive and
can be saved (that's what *Printer properties...* stores).

**2. Read the real printable area.** Paper sizes come from the driver
(`DeviceCapabilities`), and the printable area and resolution come from the device context
(`GetDeviceCaps`: `PHYSICALWIDTH`, `HORZRES`, `LOGPIXELSX`, ...). Nothing is hard-coded,
because the driver knows better than I do.
For a SELPHY postcard:

| | Printable area | Resolution |
|---|---|---|
| With border | 1122 × 1661 px | 300 dpi |
| Borderless | 1181 × 1748 px (the whole 100 × 148 mm) | 300 dpi |

**3. Print.** `StartDoc`, then for every sheet `StartPage`, one `StretchDIBits` with
source and destination the same size, `EndPage`. ICM is also switched off on the device
context (`SetICMMode`).

**4. Watch the queue.** After printing, the job is polled with `GetJob`, and the job and
printer status bits are turned into messages like "out of paper or ink cassette".

## The SELPHY CP1500 specifically

On Wi-Fi, Windows installs the SELPHY with the generic **Microsoft IPP Class Driver**.
Canon doesn't make a Windows driver for it, and that turns out to be fine: the class driver
does 300 dpi RGB, and with ICM off it passes the colours straight through. Other
colour-managed apps print through the same driver.

**Borderless.** This one took a while. The class driver doesn't expose borderless in the
DEVMODE. It's hiding in the *print ticket* (the XML version of the job settings), as
`psk:PageBorderless`. So
Open DyePrint converts the DEVMODE to a print ticket (`PTConvertDevModeToPrintTicket`),
changes `psk:PageBorderless` to `psk:Borderless`, and converts it back
(`PTConvertPrintTicketToDevMode`). After that, the printable area is the whole sheet.

**Finish (glossy, semi-gloss, matte).** Not available from Windows. The printer's IPP
attributes only list one media type (`photographic`), one print quality and no finishings,
so there's nothing to set. Believe me, I looked. The finish is chosen on the printer itself
or in Canon's phone app.

**The tear-off tabs** on SELPHY paper are outside the 100 × 148 mm page, so layouts
(including the Polaroid cut line) never need to worry about them. One less thing.

## Zoom limit

Zoom stops when the crop would have fewer photo pixels than the printer prints, i.e. at
1 photo pixel per printer pixel (300 ppi on the SELPHY). Past that, the photo would have to
be upscaled and the print would get softer, and nobody wants that. The limit is shown on
the zoom slider and enforced again at print time using the full-resolution photo.

## Polaroid layout

A classic Polaroid (600 / i-Type) is 88 × 107 mm with a 79 mm square photo. Open DyePrint
scales that frame to the full width of the paper, so the left, right and top edges are the
paper's own edges and you only cut once, along the dashed line at the bottom of the frame.
On a postcard that's a 100 × 122 mm Polaroid with a 90 mm photo.

## Date stamp

The date comes from the photo's EXIF (`DateTimeOriginal`, falling back to `DateTime`).
The digits aren't a font: they're drawn as seven-segment or 5 × 7 dot-matrix glyphs with a
soft glow, sized relative to the photo, so the stamp looks the same in the preview and on
paper. Bonus: no font licence to worry about, and I got to draw digits like it's 1995.

## Code map

```
src/opendyeprint/
  layout.py          geometry: fill/fit, crop, zoom, rotation, two-up cells, Polaroid frame
  render.py          load -> place -> resample -> adjust -> stamp -> colour convert
  color.py           ICC conversion, system profiles, monitor profile
  adjust.py          adjustment lookup tables and Auto
  datestamp.py       capture date and the date imprint
  model.py           a photo's settings (copies, crop, zoom, adjustments) and sheets
  winprint.py        ctypes: winspool, GDI, print tickets, queue status
  printer.py         job DEVMODE (paper, borderless, ICM off) and the print loop
  settings.py        settings in %APPDATA%\Open DyePrint\settings.json
  single_instance.py one window: later launches hand their files to it
  shell.py           Explorer "Print with Open DyePrint" menu (current user only)
  ui/                PySide6 window, preview, photo list, adjust panel, background workers
packaging/           icon, PyInstaller entry point and licence collector (used by build.bat)
```

The geometry, rendering, colour, adjustment and date-stamp code is plain Python (Pillow
only), so it's easy to test. The tests in `tests/` cover that, plus the parts of the
printing layer that can be checked without sending anything to a printer.
