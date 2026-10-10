"""PyInstaller entry point (the package's __main__ uses relative imports)."""

import sys

from opendyeprint.__main__ import main

sys.exit(main())
