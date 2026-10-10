# Contributing

Thanks for wanting to help! This is a hobby project made in evenings and weekends, so
don't expect enterprise-grade response times, but bug reports, ideas and pull requests are
all very welcome.

## Reporting a bug

Open an [issue](../../issues) and tell me:

- what you did, what you expected and what happened instead,
- your printer, its driver (*Settings → Printers & scanners → your printer → Printer
  properties*) and the paper size,
- your Windows version and the Open DyePrint version (in the release name or
  `src/opendyeprint/__init__.py`).

For colour problems, also say which ICC profile, rendering intent and black point
compensation setting you used, and what looks wrong (too dark, colour cast, ...). A photo
of the print next to the screen helps a lot. "The colours look weird" helps a little less.

## Setting up

You need Windows and Python 3.10 or newer.

```bat
git clone <this repo>
cd open-dyeprint
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\python -m opendyeprint
```

Or just run `run.bat`, which does the same thing with less typing.

## Before you open a pull request

- Run the tests: `.venv\Scripts\python -m pytest`. They should all pass.
- Add tests for new behaviour. Geometry, rendering and colour code is easy to test without a
  printer; the existing tests show how.
- **Test printing without wasting paper:** pick *Microsoft Print to PDF* as the printer.
  The app asks where to save the PDF, and you can check the result there. Your wallet will
  thank you, SELPHY paper isn't free.
- Keep the code style of the file you're in. Roughly `black`, 110 characters per line.
- One feature or fix per pull request, please.

If you're planning something bigger, open an issue first so we can talk about it before
you put a lot of work in.

## Other printers

Open DyePrint should work with any printer that has a normal Windows driver, but it's only
tested on the Canon SELPHY CP1500, because that's the one sitting on my desk. If you try
another printer, I'd love to hear how it went, good or bad. Useful things to know: does
borderless work, is the printable area right, and do the colours match what you get from
other colour-managed software?

## Building the .exe

```bat
build.bat
```

This creates `dist\OpenDyePrint\OpenDyePrint.exe`. Close the app before building, because
Windows won't let the build replace files that are in use (ask me how I know).
Releasing is described in [docs/releasing.md](docs/releasing.md).
