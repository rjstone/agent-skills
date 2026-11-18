"""docshelf command line: the command table, parser and main()."""
import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

import shelf_core
import shelf_backends
import shelf_dash
import shelf_devdocs
import shelf_lookup
import shelf_notes
import shelf_suggest
from shelf_core import CLIError, Config


@dataclass
class Param:
    flags: Tuple[str, ...]
    help: str
    kind: str = "str"  # "str", "int", "posint" (>= 1), "nonneg" (>= 0) or "flag"
    nargs: Optional[str] = None
    repeat: bool = False
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
    for line in shelf_dash.where_lines(cfg):
        print(line)
    return 0


def cmd_list(cfg: Config, args: argparse.Namespace) -> int:
    docvols = shelf_backends.installed_docvols(cfg)
    if not docvols:
        print("no docvols installed (%s)"
              % shelf_core.hint("install NAME; sources QUERY finds names"))
        return 0
    for d in docvols:
        count = d.entry_count  # a damaged docset counts 0, noting why
        damage = getattr(d, "damage_error", None)
        if damage is not None:
            shelf_core.warn("docvol %s: %s" % (d.name, damage))
        twins = [o.name for o in docvols if shelf_backends.same_documentation(d, o)]
        also = ("  also as %s %s" % ("DevDocs" if d.read_only else "docset",
                                     ", ".join(twins)) if twins else "")
        print("%s  %s  %s  %d entries  %s  %s%s" % (
            d.name, d.display_name,
            d.release, count, "full" if d.full_size else "small",
            d.source, also))
    return 0


COMMANDS: List[Command] = [
    Command("where", "Show the cache, notes and project file in use.",
            cmd_where, [], mcp=False),
    Command("list", "List installed docvols.", cmd_list, []),
    Command("search", "Search entry names, then headings inside pages (exact, prefix, "
            "substring; fuzzy for entries only).",
            shelf_lookup.cmd_search, [
        Param(("query",), "Words to find in entry names or page headings.", nargs="+"),
        Param(("-d", "--docvol"), "Docvol or family to search (repeatable).", repeat=True),
        Param(("--type",), "Only entries of this type (no headings)."),
        Param(("--all",), "Search every installed docvol.", kind="flag"),
        Param(("--max-lines",), "Output line cap.", kind="posint",
              default=20),
        Param(("--json",), "Print JSON (a list of hits; a list as long as "
              "the line cap may be cut).", kind="flag"),
    ]),
    Command("show", "Show a page or section as text.", shelf_lookup.cmd_show, [
        Param(("ref",), "REF from search: <docvol>:<path>[#anchor]."),
        Param(("-d", "--docvol"), "Docvol or family the REF names (optional; "
              "checked against the REF).", repeat=True),
        Param(("--grep",), "Only lines containing this text (repeatable).",
              repeat=True),
        Param(("--full",), "No line cap.", kind="flag"),
        Param(("--max-lines",), "Output line cap.", kind="posint",
              default=40),
        Param(("--offset",), "Skip this many lines first (continue after the cap).",
              kind="nonneg", default=0),
        Param(("--no-notes",), "Do not print notes.", kind="flag"),
    ]),
    Command("toc", "List a page's headings with their REFs.",
            shelf_lookup.cmd_toc, [
        Param(("ref",), "REF from search: <docvol>:<path>[#anchor]."),
        Param(("-d", "--docvol"), "Docvol or family the REF names (optional; "
              "checked against the REF).", repeat=True),
        Param(("--max-lines",), "Output line cap.", kind="posint",
              default=60),
    ]),
    Command("fts", "Full-text search inside pages (SQLite FTS5).",
            shelf_lookup.cmd_fts, [
        Param(("query",), "Words that must all appear in a page.", nargs="+"),
        Param(("-d", "--docvol"), "Docvol or family to search (repeatable).", repeat=True),
        Param(("--all",), "Search every installed docvol.", kind="flag"),
        Param(("--max-lines",), "Output line cap.", kind="posint",
              default=shelf_lookup.FTS_MAX_LINES),
        Param(("--json",), "Print JSON (a list of hits; a list as long as "
              "the line cap may be cut).", kind="flag"),
    ]),
    Command("types", "List each docvol's entry types with counts.",
            shelf_lookup.cmd_types, [
        Param(("-d", "--docvol"), "Docvol or family to list (repeatable).", repeat=True),
        Param(("--all",), "List every installed docvol.", kind="flag"),
    ]),
    Command("index-text", "Build the full-text index of docvols ahead of fts.",
            shelf_lookup.cmd_index_text, [
        Param(("docvol",), "Docvol name (several allowed).", nargs="+"),
    ], mcp=False),
    Command("sources", "Search the DevDocs list of documentations to install.",
            shelf_devdocs.cmd_sources, [
        Param(("query",), "Words in the slug or name.", nargs="+"),
        Param(("--refresh",), "Fetch the list again now.", kind="flag"),
    ]),
    Command("suggest", "Suggest docvols from the project's build files "
            "(package.json, pyproject.toml, CMakeLists.txt, ...).",
            shelf_suggest.cmd_suggest, [
        Param(("--json",), "Print JSON.", kind="flag"),
    ]),
    Command("install", "Download documentations from DevDocs.",
            shelf_devdocs.cmd_install, [
        Param(("names",), "Slug, alias or family (python, python~3.14); "
              "default: the project file's \"docvols\" list.", nargs="*"),
        Param(("--force",), "Download even when a Dash/Zeal docset has the "
              "same documentation.", kind="flag"),
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
    Command("notes", "Find, print, check or write a docvol's notes file.",
            shelf_notes.cmd_notes, [
        Param(("docvol",), "Docvol name or family (python for python~3.13)."),
        Param(("--path",), "Print the notes file path (creates its folder).",
              kind="flag"),
        Param(("--check",), "List which REFs show each section; warn on "
              "oversized notes and headings matching no entry.", kind="flag"),
        Param(("--set",), "Write the section with this heading (exact text "
              "after '## '; General for the general notes); needs a text."),
        Param(("--text",), "Body of the section to write (no '## ' lines)."),
        Param(("--delete",), "Delete the section with this heading."),
    ]),
]


# Top-level --help: a short lookup card. Each command's own --help (argparse,
# with DETAILS as its epilog) documents every option and the rest.
TOP_HELP = """\
docshelf {version}: DevDocs docs and Dash/Zeal docsets, offline.
REF = <docvol>:<path>[#anchor], as search and fts print it (a docset's:
<Name>:<id> or <Name>:page:<path>[#anchor]). -d takes a docvol name (see
list) or a family (all its versions).

Look up:
  search NAME... -d DOCVOL     entry names (and page headings) with all the
                               words; the exact name works best
  show REF                     read a section, 40 lines; the "... more
                               lines" line gives the --offset N to go on
  show REF --grep=TEXT         only the lines with TEXT (repeatable); try
                               it before toc
  fts WORDS... -d DOCVOL       words inside pages; include the function name
  toc REF                      a long page's headings, each with its REF
  list                         installed docvols and versions

Other commands, each with its own --help: types, notes, suggest, sources,
install, update, remove, where, index-text. Also --version, and --mcp
(run as a stdio MCP server).
Exit codes: 0 ok; 1 notes --check found problems; 2 usage or ambiguous
name; 4 scope too wide or unknown -d; 5 not found or damaged; 7 network
or unreadable docset archive.
"""

# What the old top-level help said about each command beyond its summary;
# argparse only (the epilog), so the MCP tool descriptions stay as they are.
DETAILS = {
    "search": "Page headings are listed (marked (heading)) when no entry name "
              "is an exact match; hits are best first, one REF each.",
    "show": "Prints the section and your notes for it. --grep prints only "
            "the matching lines, with their heading, the table header row "
            "and a matching term's definition (plain text, case-insensitive).",
    "toc": "Indented headings, each with the REF that shows that section.",
    "fts": "The 5 best pages with REFs. Include the function name "
           "(fts read_csv skip). The first fts on a docvol builds its index.",
    "types": "Most frequent first; these are the names search --type takes.",
    "notes": "After editing, --check lists which REFs show each section, "
             "then ok; --set writes a section, then prints that report. "
             "Format: references/notes.md in the skill folder.",
    "list": "Version, size class, source (devdocs, zeal, dash) and \"also "
            "as\" when a DevDocs copy and a docset hold the same documentation.",
    "suggest": "Reads the project's build and version files (no network) "
               "and prints a \"docvols\" list to paste into .docshelf.json.",
    "sources": "Documentations DevDocs offers, with sizes, and docsets Dash "
               "or Zeal could download.",
    "install": "A NAME without a version installs the newest; no NAME "
               "installs the project's \"docvols\" list. Documentation already "
               "on disk as a Dash/Zeal docset is skipped unless --force. See "
               "references/getting-docvols.md.",
    "update": "DevDocs docvols only; Dash or Zeal updates docsets.",
    "remove": "DevDocs docvols only: Dash or Zeal manages docsets.",
    "where": "Cache, notes folder, project file, docset folders and the "
             "Dash/Zeal apps found.",
    "index-text": "Builds the fts index now (the first fts builds it "
                  "otherwise).",
}


def top_help() -> str:
    return TOP_HELP.format(version=shelf_core.VERSION)


def positive_int(text):
    try:
        n = int(text)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError("%r: must be an integer >= 1" % text)
    return n


def nonneg_int(text):
    try:
        n = int(text)
    except ValueError:
        n = -1
    if n < 0:
        raise argparse.ArgumentTypeError("%r: must be an integer >= 0" % text)
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
        elif p.kind == "nonneg":
            kwargs["type"] = nonneg_int
        if p.nargs:
            kwargs["nargs"] = p.nargs
        if p.repeat:
            kwargs["action"] = "append"
        default = param_default(p)
        if default is not None:
            kwargs["default"] = default
    parser.add_argument(*p.flags, **kwargs)


def param_dest(p: Param) -> str:
    """The attribute name argparse gives the parameter."""
    if not p.flags[0].startswith("-"):
        return p.flags[0]
    long = [f for f in p.flags if f.startswith("--")] or list(p.flags)
    return long[0].lstrip("-").replace("-", "_")


def param_default(p: Param) -> Any:
    """The default argparse gives the parameter: False for a flag, else
    `default` (None when unset)."""
    return False if p.kind == "flag" else p.default


def param_defaults(c: Command) -> dict:
    """dest -> default for each of the command's parameters, as _add_param
    gives them to argparse."""
    out = {}
    for p in c.params:
        d = param_default(p)
        out[param_dest(p)] = list(d) if isinstance(d, list) else d
    return out


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
        sp = sub.add_parser(c.name, help=c.summary, description=c.summary,
                            epilog=DETAILS.get(c.name))
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


def _closed_stdout() -> int:
    """The reader of our output went away (`show REF | head`): end quietly.
    stdout is pointed at the null device so the flush at exit can't raise
    the same error again."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
    except (OSError, ValueError, AttributeError):
        pass  # not a real file (tests); nothing left to flush
    return 0


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
        damaged = e.docvol and cfg and shelf_devdocs.damaged_message(
            cfg, e.docvol)
        msg = damaged or (e.docvol and cfg and shelf_devdocs.not_installed_message(
            cfg, e.docvol, lambda slug: "docshelf.py install " + slug))
        print(msg or str(e), file=sys.stderr)
        return 5 if damaged else e.code
    except BrokenPipeError:
        return _closed_stdout()
    except (OSError, sqlite3.Error, ValueError) as e:
        print("error: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 2
