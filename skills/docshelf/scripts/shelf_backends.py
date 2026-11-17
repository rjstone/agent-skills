"""docshelf backends: the one place that lists installed docvols."""
from typing import List

import shelf_devdocs
from shelf_core import Config, Docvol


def installed_docvols(cfg: Config) -> List[Docvol]:
    """Every installed docvol, whatever its backend."""
    return list(shelf_devdocs.installed_docvols(cfg))
