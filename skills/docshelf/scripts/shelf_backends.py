"""docshelf backends: the one place that lists installed docvols."""
from typing import List

import shelf_dash
import shelf_devdocs
from shelf_core import Config, Docvol, warn


def installed_docvols(cfg: Config) -> List[Docvol]:
    """Every installed docvol, whatever its backend: DevDocs, then docsets."""
    docvols: List[Docvol] = list(shelf_devdocs.installed_docvols(cfg))
    names = {d.name for d in docvols}
    for d in shelf_dash.installed_docsets(cfg):
        if d.name in names:
            warn("skipping docset %s (%s): DevDocs docvol %s has the same name"
                 % (d.path, d.source, d.name))
            continue
        docvols.append(d)
    return docvols
