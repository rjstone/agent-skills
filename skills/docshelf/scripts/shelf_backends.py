"""docshelf backends: the one place that lists installed docvols."""
import re
from typing import List, Tuple

import shelf_dash
import shelf_devdocs
from shelf_core import Config, Docvol, warn


def installed_docvols(cfg: Config) -> List[Docvol]:
    """Every installed docvol, whatever its backend: built (docshelf-build),
    DevDocs, then docsets. A built docvol wins a name clash: it was made on
    purpose."""
    docvols: List[Docvol] = list(shelf_devdocs.installed_built(cfg))
    names = {d.name for d in docvols}
    for d in shelf_devdocs.installed_docvols(cfg):
        if d.name in names:
            warn("skipping DevDocs docvol %s: a built docvol has the same name"
                 % d.name)
            continue
        docvols.append(d)
        names.add(d.name)
    for d in shelf_dash.installed_docsets(cfg):
        if d.name in names:
            warn("skipping docset %s (%s): DevDocs docvol %s has the same name"
                 % (d.path, d.source, d.name))
            continue
        docvols.append(d)
    return docvols


def _major_minor(version: str) -> Tuple[int, ...]:
    """The first two numbers in a version string: '3.12.1' -> (3, 12)."""
    return tuple(int(n) for n in re.findall(r"\d+", version or "")[:2])


def same_documentation(a, b) -> bool:
    """True when a DevDocs docvol and a docset document the same thing: same
    family, exactly one of them read-only, and equal versions, compared on
    as many of the first two numbers as both have (docset "3" matches 3.12
    and 3.11; "3.12" and "3.13" differ; an unknown version matches all).
    Reads only family, version and read_only, so a manifest row wrapped in a
    namespace works too."""
    if a.family != b.family or bool(a.read_only) == bool(b.read_only):
        return False
    x, y = _major_minor(a.version), _major_minor(b.version)
    n = min(len(x), len(y))
    return x[:n] == y[:n]
