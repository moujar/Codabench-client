"""Allow ``python -m codabench ...`` next to the installed ``codabench`` script."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
