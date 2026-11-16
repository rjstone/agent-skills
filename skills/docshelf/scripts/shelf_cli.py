"""docshelf command line: the command table, parser and main()."""
import argparse
import sys
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

import shelf_core
from shelf_core import CLIError, Config


@dataclass
class Param:
    flags: Tuple[str, ...]
    help: str
    kind: str = "str"  # "str", "int" or "flag"
    nargs: Optional[str] = None
    repeat: bool = False
    rare: bool = False
    default: Any = None


@dataclass
class Command:
    name: str
    summary: str
    func: Callable[[Config, argparse.Namespace], int]
    params: List[Param]
    mcp: bool = True


class _Parser(argparse.ArgumentParser):
    def format_help(self):
        return "docshelf %s\n\n%s" % (shelf_core.VERSION, super().format_help())


def cmd_where(cfg: Config, args: argparse.Namespace) -> int:
    def src(source, var):
        return "(%s)" % var if source == "env" else "(default)"

    if cfg.project_note:
        print("note: " + cfg.project_note, file=sys.stderr)
    print("cache: %s %s" % (cfg.cache_dir, src(cfg.cache_source, "DOCSHELF_CACHE_DIR")))
    print("notes: %s %s" % (cfg.notes_dir, src(cfg.notes_source, "DOCSHELF_NOTES_DIR")))
    print("project: %s" % (cfg.project_file or "none"))
    return 0


COMMANDS: List[Command] = [
    Command("where", "Show the cache, notes and project file in use.", cmd_where, []),
]


def _add_param(parser, p: Param):
    kwargs = {"help": p.help}
    if p.kind == "flag":
        kwargs["action"] = "store_true"
    else:
        if p.kind == "int":
            kwargs["type"] = int
        if p.nargs:
            kwargs["nargs"] = p.nargs
        if p.repeat:
            kwargs["action"] = "append"
        if p.default is not None:
            kwargs["default"] = p.default
    parser.add_argument(*p.flags, **kwargs)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="docshelf",
                     description="Offline, version-pinned DevDocs documentation.")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    for c in COMMANDS:
        sp = sub.add_parser(c.name, help=c.summary, description=c.summary)
        for p in c.params:
            _add_param(sp, p)
        sp.set_defaults(_command=c)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    try:
        return args._command.func(shelf_core.load_config(), args)
    except CLIError as e:
        print(str(e), file=sys.stderr)
        return e.code
