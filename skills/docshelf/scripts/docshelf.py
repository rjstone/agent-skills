"""docshelf entry point: python scripts/docshelf.py <command> ..."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import shelf_cli  # noqa: E402

if __name__ == "__main__":
    sys.exit(shelf_cli.main())
