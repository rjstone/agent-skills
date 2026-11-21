"""docshelf-build shared bits: version, errors, cache locations, names."""
import os
import re
import sys

VERSION = "0.1.0"
# the built-docvol format written to meta.json; docshelf reads formats up to
# the one it knows. Bump it only for a change older docshelf cannot read.
DOCVOL_FORMAT = 1
# docshelf's own rule for docvol names (shelf_devdocs.SLUG_RE)
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._~+-]*$", re.IGNORECASE)


class CLIError(Exception):
    """A user-facing failure with an exit code (2 usage/name, 3 bad
    inventory, 4 network)."""

    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def warn(msg: str) -> None:
    print("docshelf-build: " + msg, file=sys.stderr)


def cache_dir(env=None) -> str:
    """docshelf's cache folder, by docshelf's rules (shelf_core._default_cache):
    DOCSHELF_CACHE_DIR, else %LOCALAPPDATA%/docshelf/cache on Windows, else
    ~/.cache/docshelf."""
    env = os.environ if env is None else env
    if env.get("DOCSHELF_CACHE_DIR"):
        return os.path.normpath(env["DOCSHELF_CACHE_DIR"])
    if sys.platform == "win32" and env.get("LOCALAPPDATA"):
        return os.path.join(env["LOCALAPPDATA"], "docshelf", "cache")
    home = env.get("HOME") or env.get("USERPROFILE") or os.path.expanduser("~")
    return os.path.join(home, ".cache", "docshelf")


def built_dir(cache: str) -> str:
    return os.path.join(cache, "built")


def src_dir(cache: str) -> str:
    return os.path.join(cache, "built-src")


def plans_dir(cache: str) -> str:
    return os.path.join(cache, "built-plans")
