"""docshelf command line: the command table, parser and main()."""
import argparse
import sqlite3
import sys
import textwrap
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

import shelf_core
import shelf_devdocs
import shelf_lookup
import shelf_notes
from shelf_core import CLIError, Config


@dataclass
class Param:
    flags: Tuple[str, ...]
    help: str
    kind: str = "str"  # "str", "int", "posint" (>= 1) or "flag"
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


def cmd_list(cfg: Config, args: argparse.Namespace) -> int:
    docvols = shelf_devdocs.installed_docvols(cfg)
    if not docvols:
        print("no docvols installed (install NAME; sources QUERY finds names)")
        return 0
    for d in docvols:
        print("%s  %s  %s  %d entries  %s" % (
            d.name, d.display_name,
            d.release, d.entry_count, "full" if d.full_size else "small"))
    return 0


COMMANDS: List[Command] = [
    Command("where", "Show the cache, notes and project file in use.",
            cmd_where, [], mcp=False),
    Command("list", "List installed docvols.", cmd_list, []),
    Command("search", "Search entry names, then headings inside pages (exact, prefix, "
            "substring; fuzzy for entries only).",
            shelf_lookup.cmd_search, [
        Param(("query",), "Words to find in entry names or page headings.", nargs="+"),
        Param(("-d", "--docvol"), "Docvol to search (repeatable).", repeat=True),
        Param(("--type",), "Only entries of this type (no headings).", rare=True),
        Param(("--all",), "Search every installed docvol.", kind="flag", rare=True),
        Param(("--max-lines",), "Output line cap.", kind="posint", rare=True,
              default=40),
        Param(("--json",), "Print JSON.", kind="flag", rare=True),
    ]),
    Command("show", "Show a page or section as text.", shelf_lookup.cmd_show, [
        Param(("ref",), "REF from search: <docvol>:<path>[#anchor]."),
        Param(("--grep",), "Only lines containing this text (repeatable).",
              repeat=True),
        Param(("--full",), "No line cap.", kind="flag", rare=True),
        Param(("--max-lines",), "Output line cap.", kind="posint", rare=True,
              default=150),
        Param(("--no-notes",), "Do not print notes.", kind="flag", rare=True),
    ]),
    Command("fts", "Full-text search inside pages (SQLite FTS5).",
            shelf_lookup.cmd_fts, [
        Param(("query",), "Words that must all appear in a page.", nargs="+"),
        Param(("-d", "--docvol"), "Docvol to search (repeatable).", repeat=True),
        Param(("--all",), "Search every installed docvol.", kind="flag", rare=True),
        Param(("--max-lines",), "Output line cap.", kind="posint", rare=True,
              default=shelf_lookup.FTS_MAX_LINES),
        Param(("--json",), "Print JSON.", kind="flag", rare=True),
    ]),
    Command("index-text", "Build the full-text index of docvols ahead of fts.",
            shelf_lookup.cmd_index_text, [
        Param(("docvol",), "Docvol name (several allowed).", nargs="+"),
    ], mcp=False),
    Command("sources", "Search the DevDocs list of documentations to install.",
            shelf_devdocs.cmd_sources, [
        Param(("query",), "Words in the slug or name.", nargs="+"),
        Param(("--refresh",), "Fetch the list again now.", kind="flag", rare=True),
    ]),
    Command("install", "Download documentations from DevDocs.",
            shelf_devdocs.cmd_install, [
        Param(("names",), "Slug, alias or family (python, python~3.14).",
              nargs="+"),
    ]),
    Command("update", "Re-download documentations that DevDocs has updated.",
            shelf_devdocs.cmd_update, [
        Param(("names",), "Docvols to update (default: all installed).",
              nargs="*"),
    ], mcp=False),
    Command("remove", "Delete an installed docvol (notes are kept).",
            shelf_devdocs.cmd_remove, [
        Param(("name",), "Docvol name."),
    ]),
    Command("notes", "Find, print or check a docvol's notes file.",
            shelf_notes.cmd_notes, [
        Param(("docvol",), "Docvol name or family (python for python~3.13)."),
        Param(("--path",), "Print the notes file path (creates its folder).",
              kind="flag"),
        Param(("--check",), "List which REFs show each section; warn on "
              "oversized notes and headings matching no entry.", kind="flag"),
    ]),
]


EXIT_CODES = ("0 ok; 1 notes --check found problems; 2 usage error, ambiguous "
              "name or no FTS5; 4 search scope too wide (use -d, a project "
              "list or --all) or unknown -d name; 5 not found (docvol, page "
              "or entry); 7 network (DevDocs could not be reached)")

# Top-level --help: the command lines agents normally need. Options that
# have rare=True in COMMANDS are only named (not described) under "only if
# you need these", generated from the table, so a new option can't be left
# out; `<command> --help` (argparse) describes them.
TOP_HELP = """\
docshelf {version}: look up DevDocs documentation offline (stdlib only).
This is the command reference; `<command> --help` adds only the options
listed at the end. REF = <docvol>:<path>[#anchor], as search and fts print
them; <docvol> is the name `list` prints.
A docvol is a DevDocs documentation plus docshelf's own metadata, indexes
and notes.

Look up (usual order):
  search QUERY... [-d NAME]      entries whose names contain all the words,
                                 and headings inside pages when no entry
                                 name is an exact match; one REF per hit,
                                 best first
  show REF                       that entry's section (max 150 lines) plus
                                 your notes for it
  show REF --grep=TEXT           only lines containing TEXT, with their
                                 heading, table header row, and a matching
                                 term's definition (repeatable; plain text,
                                 not a pattern, case-insensitive)
  fts QUERY... [-d NAME]         words inside pages, 5 best hits with REFs;
                                 include the function name: fts read_csv skip

Notes (format: references/notes.md in the skill folder):
  notes DOCVOL --path            the notes file to edit
  notes DOCVOL --check           after editing: which REFs show each section,
                                 then "ok"

Get and manage docvols (references/getting-docvols.md):
  list                           installed docvols and their versions
  sources QUERY...               documentations DevDocs offers, with sizes
  install NAME...                download one (NAME without a version = the
                                 newest); update [NAME...]; remove NAME
  where                          cache, notes folder and project file
  index-text DOCVOL              build the fts index now

Only if you need these, see `<command> --help`:
{rare}
Global: --version, --mcp (run as a stdio MCP server; references/mcp.md).
{exit_codes}
"""


def top_help() -> str:
    rare = []
    for c in COMMANDS:
        flags = [p.flags[0] for p in c.params if p.rare]
        if flags:
            rare.append("  %-10s %s" % (c.name, " ".join(flags)))
    codes = textwrap.fill("Exit codes: " + EXIT_CODES, width=76,
                          subsequent_indent="  ")
    return TOP_HELP.format(version=shelf_core.VERSION, rare="\n".join(rare),
                           exit_codes=codes)


def positive_int(text):
    try:
        n = int(text)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError("%r: must be an integer >= 1" % text)
    return n


def _add_param(parser, p: Param):
    kwargs = {"help": p.help}
    if p.kind == "flag":
        kwargs["action"] = "store_true"
    else:
        if p.kind == "int":
            kwargs["type"] = int
        elif p.kind == "posint":
            kwargs["type"] = positive_int
        if p.nargs:
            kwargs["nargs"] = p.nargs
        if p.repeat:
            kwargs["action"] = "append"
        if p.default is not None:
            kwargs["default"] = p.default
    parser.add_argument(*p.flags, **kwargs)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="docshelf", add_help=False,
                     description="Offline, version-pinned DevDocs documentation.")
    parser.add_argument("-h", "--help", action="store_true",
                        help="show the command reference")
    parser.add_argument("--version", action="version",
                        version="docshelf %s" % shelf_core.VERSION)
    parser.add_argument("--mcp", action="store_true",
                        help="run as a stdio MCP server")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    for c in COMMANDS:
        sp = sub.add_parser(c.name, help=c.summary, description=c.summary)
        for p in c.params:
            _add_param(sp, p)
        sp.set_defaults(_command=c)
    return parser


def _join_grep_values(argv: List[str]) -> List[str]:
    """`--grep X` -> `--grep=X`, so a value starting with '-' (`--grep --keep`)
    isn't read as an option. A trailing bare --grep stays for argparse, and
    everything after `--` is positional, so it is left as it is."""
    out, i = [], 0
    while i < len(argv):
        if argv[i] == "--":
            return out + argv[i:]
        if argv[i] == "--grep" and i + 1 < len(argv):
            out.append("--grep=" + argv[i + 1])
            i += 2
        else:
            out.append(argv[i])
            i += 1
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--mcp" not in argv:
        argv = _join_grep_values(argv)
    args = parser.parse_args(argv)
    if args.mcp:
        import shelf_mcp
        for stream in (sys.stdin, sys.stdout):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace",
                                   newline="\n")
        return shelf_mcp.serve(sys.stdin, sys.stdout)
    if args.help or not args.command:
        print(top_help(), end="")
        return 0 if args.help else 2
    for stream in (sys.stdout, sys.stderr):  # Windows pipes default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    cfg = None
    try:
        cfg = shelf_core.load_config()
        return args._command.func(cfg, args)
    except CLIError as e:
        msg = (e.docvol and cfg and shelf_devdocs.not_installed_message(
            cfg, e.docvol, lambda slug: "docshelf.py install " + slug))
        print(msg or str(e), file=sys.stderr)
        return e.code
    except (OSError, sqlite3.Error, ValueError) as e:
        print("error: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 2
