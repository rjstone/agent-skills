#!/usr/bin/env python3
"""Install Dash docsets and search them offline (stdlib only)."""
import argparse
import sys

SUBCOMMANDS = {
    "where": "show the docset store location",
    "sources": "list docset sources",
    "install": "install a docset",
    "update": "update installed docsets",
    "list": "list installed docsets",
    "remove": "remove an installed docset",
    "search": "search a docset's index",
    "show": "show a documentation page",
    "fts": "full-text search a docset",
    "index-text": "build the full-text index",
    "notes": "read or write notes for a docset",
}


def not_implemented(args):
    print("not implemented: " + args.command, file=sys.stderr)
    return 2


def build_parser():
    parser = argparse.ArgumentParser(prog="docset.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    for name, help_text in SUBCOMMANDS.items():
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.add_argument("args", nargs="*")
        p.set_defaults(handler=not_implemented)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help()
        return 2
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
