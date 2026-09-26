"""Entry point used by the packaged app (PyInstaller) and for running from source."""
import sys

from latent.app import main

if __name__ == "__main__":
    sys.exit(main())
