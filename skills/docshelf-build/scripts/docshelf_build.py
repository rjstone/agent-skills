"""docshelf-build: turn a Sphinx site (objects.inv) or an llms.txt page list
into a trimmed docshelf docvol. Run `python scripts/docshelf_build.py --help`."""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from typing import Callable, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_core import (VERSION, CLIError, built_dir, cache_dir, plans_dir, src_dir,  # noqa: E402
                        warn)
from build_docvol import check_name, derive_name, write_docvol, write_llms_docvol  # noqa: E402
from build_fetch import (PageCache, fetch_llms, fetch_pages, index_getter,  # noqa: E402
                         open_source, open_url_source)
from build_inventory import parse_inventory  # noqa: E402
from build_llms import is_llms_source, read_tree  # noqa: E402
from build_markdown import front_matter, page_signals  # noqa: E402
from build_plan import (load_plan, make_llms_plan, make_plan, save_plan,  # noqa: E402
                        summarize, summarize_llms)

DESCRIPTION = """\
Build a docshelf docvol from a Sphinx site's objects.inv (Sphinx, PyDoctor,
MkDocs with mkdocstrings) or from a site's llms.txt page list (Mintlify,
Starlight and others). Sphinx: reference pages are kept in full, guide pages
become stubs with a link. llms.txt: every listed page is kept in full; narrow
with a sub-index as SOURCE or --stub. Usual loop:
  plan SOURCE --name NAME     read the inventory, write and summarize the plan
  plan SOURCE --name NAME --full 'group/*'   keep a prose group in full
  build NAME                  fetch the full pages, write the docvol
  build SOURCE [plan options] plan and build in one step
Then look things up with docshelf (the docvol is listed as "built").
SOURCE is the site's base URL or a local Sphinx HTML build folder, or the
URL (or local file) of an llms.txt."""


def _plan_path(cache: str, name: str) -> str:
    return os.path.join(plans_dir(cache), name + ".json")


def _read_inventory(source):
    data = source.inventory()
    header, entries = parse_inventory(data)
    return hashlib.sha256(data).hexdigest(), header, entries


def _print(lines: List[str]) -> None:
    for line in lines:
        print(line)


def _summary_tail(path: str) -> None:
    print("plan: %s (edit \"keep\" and set \"why\": \"manual\" to pin a page)" % path)


def do_plan_llms(cache: str, args, opener, sleep) -> str:
    if args.base_url:
        raise CLIError("--base-url is only for Sphinx sources", 2)
    source = open_url_source(opener=opener, sleep=sleep)
    tree = read_tree(args.source, index_getter(source))
    name = args.name or derive_name({"project": tree.title})
    check_name(cache, name)
    path = _plan_path(cache, name)
    old = load_plan(path) if os.path.isfile(path) else None
    plan = make_llms_plan(args.source, tree, list(args.overrides or []), old=old,
                          reset=args.reset)
    save_plan(path, plan)
    _print(summarize_llms(plan, old))
    _summary_tail(path)
    return name


def do_plan(cache: str, args, opener=None, sleep=None) -> str:
    """Write the plan; return the docvol name."""
    if is_llms_source(args.source):
        return do_plan_llms(cache, args, opener, sleep)
    source = open_source(args.source, base_url=args.base_url, opener=opener, sleep=sleep)
    sha, header, entries = _read_inventory(source)
    name = args.name or derive_name(header)
    check_name(cache, name)
    path = _plan_path(cache, name)
    old = load_plan(path) if os.path.isfile(path) else None
    overrides = list(args.overrides or [])
    plan = make_plan(source.base, sha, header, entries, overrides, old=old,
                     reset=args.reset, base_url=args.base_url)
    save_plan(path, plan)
    _print(summarize(plan, old))
    _summary_tail(path)
    return name


def _fail_lines(errors: dict, kept: int) -> None:
    for uri in sorted(errors)[:10]:
        print("  failed %s: %s" % (uri, errors[uri]))
    if len(errors) > 10:
        print("  ... %d more" % (len(errors) - 10))
    if errors:
        warn("%d page%s failed; kept the previous copy of %d, the rest are stubs with "
             "the error (rebuild later to retry)" % (len(errors), "" if len(errors) == 1
                                                     else "s", kept))


def do_build_llms(cache: str, name: str, plan: dict, path: str, workers: int, refetch: bool,
                  opener, sleep) -> None:
    source = open_url_source(workers=workers, opener=opener, sleep=sleep)
    tree = read_tree(plan["source"], index_getter(source))
    if tree.sha256 != plan.get("index_sha256"):
        old, plan = plan, make_llms_plan(plan["source"], tree, [], old=plan)
        save_plan(path, plan)
        print("the index changed since the plan:")
        _print(summarize_llms(plan, old))
    pages = plan["pages"]
    full = [k for k, p in pages.items() if p["keep"] == "full"]
    warn("fetching %d pages%s" % (len(full), "" if refetch else " (cached pages are reused)"))
    cache_root = PageCache(os.path.join(src_dir(cache), name))
    now = time.time()
    raw, errors, fetched = fetch_llms(source, [(k, pages[k]["uri"]) for k in full],
                                      cache_root, refetch, now)
    lost = [k for k in full if k in errors and k not in raw]
    if full and len(lost) == len(full):
        first = sorted(errors)[0]
        raise CLIError("every page failed to download (e.g. %s: %s); nothing written, "
                       "the previous docvol (if any) is kept" % (first, errors[first]), 4)
    for key, (text, kind) in raw.items():
        page = pages[key]
        page["signals"] = page_signals(text, kind)
        if key in fetched:
            page["fetched"] = fetched[key]
        if key in errors:
            page["fetch_error"] = errors[key]
        else:
            page.pop("fetch_error", None)
        if kind == "md" and (page.get("description") is None or not page.get("title")):
            meta, _ = front_matter(text)
            if page.get("description") is None and meta.get("description"):
                page["description"] = meta["description"]
            if not page.get("title") and meta.get("title"):
                page["title"] = meta["title"]
    for key in lost:
        pages[key]["fetch_error"] = errors[key]
    save_plan(path, plan)
    meta = write_llms_docvol(cache, name, plan, raw, errors, now=now)
    print("built %s: %d full, %d stub, %d failed; %d entries (%s)"
          % (name, len(full) - len(errors), len(pages) - len(full), len(errors),
             meta["entry_count"], os.path.join(built_dir(cache), name)))
    _fail_lines(errors, len(meta["reused"]))


def do_build(cache: str, name: str, workers: int, refetch: bool = False, opener=None,
             sleep=None) -> None:
    path = _plan_path(cache, name)
    if not os.path.isfile(path):
        raise CLIError("no plan for %s; run: docshelf-build plan SOURCE --name %s" % (name, name), 2)
    plan = load_plan(path)
    if plan.get("kind") == "llms":
        return do_build_llms(cache, name, plan, path, workers, refetch, opener, sleep)
    source = open_source(plan["source"], base_url=plan.get("base_url"), workers=workers,
                         opener=opener, sleep=sleep)
    sha, header, entries = _read_inventory(source)
    if sha != plan["inventory_sha256"]:
        old, plan = plan, make_plan(plan["source"], sha, header, entries, [], old=plan)
        save_plan(path, plan)
        print("the inventory changed since the plan:")
        _print(summarize(plan, old))
    uris = [p["uri"] for p in plan["pages"].values() if p["keep"] == "full"]
    warn("fetching %d pages from %s" % (len(uris), source.base))
    html, errors = fetch_pages(source, uris)
    if uris and len(errors) == len(uris):
        first = sorted(errors)[0]
        raise CLIError("every page failed to download (e.g. %s: %s); nothing written, "
                       "the previous docvol (if any) is kept" % (first, errors[first]), 4)
    meta = write_docvol(cache, name, plan, entries, html, errors, now=time.time())
    stub = len(plan["pages"]) - len(uris)
    print("built %s: %d full, %d stub, %d failed; %d entries (%s)"
          % (name, len(uris) - len(errors), stub, len(errors), meta["entry_count"],
             os.path.join(built_dir(cache), name)))
    _fail_lines(errors, len(meta["reused"]))


def do_list(cache: str) -> None:
    names = set()
    for root, suffix in ((built_dir(cache), ""), (plans_dir(cache), ".json")):
        try:
            names |= {n[: len(n) - len(suffix)] for n in os.listdir(root)
                      if n.endswith(suffix) and not n.startswith(".")}
        except OSError:
            pass
    if not names:
        print("nothing built or planned")
        return
    for name in sorted(names):
        meta_path = os.path.join(built_dir(cache), name, "meta.json")
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            print("%s  %d entries  built %s  from %s" % (name, meta.get("entry_count", 0),
                                                       meta.get("installedAt", "?"),
                                                       meta.get("source", "?")))
        except (OSError, ValueError):
            try:
                src = load_plan(_plan_path(cache, name)).get("source", "?")
            except (OSError, ValueError):
                src = "?"
            print("%s  planned, not built  from %s" % (name, src))


def do_remove(cache: str, name: str, with_plan: bool) -> None:
    folder = os.path.join(built_dir(cache), name)
    plan = _plan_path(cache, name)
    pages = os.path.join(src_dir(cache), name)
    if os.path.basename(folder) != name or not name:
        raise CLIError("not a docvol name: %r" % name, 2)
    did = []
    if os.path.isdir(folder):
        shutil.rmtree(folder)
        did.append("docvol")
    if os.path.isdir(pages):
        shutil.rmtree(pages)
        did.append("page cache")
    if with_plan and os.path.isfile(plan):
        os.unlink(plan)
        did.append("plan")
    if not did:
        raise CLIError("nothing to remove for %s" % name, 2)
    kept = "" if with_plan or not os.path.isfile(plan) else "; plan kept: %s" % plan
    print("removed %s (%s)%s" % (name, " and ".join(did), kept))


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="docshelf-build", description=DESCRIPTION,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version="docshelf-build " + VERSION)
    sub = p.add_subparsers(dest="command", required=True)

    def plan_options(sp, source_help):
        sp.add_argument("source", metavar="SOURCE", help=source_help)
        sp.add_argument("--name", help="docvol name (default: from the project and version)")
        sp.add_argument("--full", dest="overrides", action="append", metavar="PAT",
                        type=lambda v: ("full", v), help="keep pages matching PAT in full")
        sp.add_argument("--stub", dest="overrides", action="append", metavar="PAT",
                        type=lambda v: ("stub", v), help="make pages matching PAT stubs")
        sp.add_argument("--all", dest="overrides", action="append_const", const=("full", "*"),
                        help="keep every page in full")
        sp.add_argument("--reset", action="store_true", help="forget stored overrides first")
        sp.add_argument("--base-url", help="live URL of a local build, for stub links")

    plan_options(sub.add_parser("plan", help="read objects.inv, write the plan"),
                 "site base URL or local Sphinx HTML folder")
    b = sub.add_parser("build", help="fetch the full pages and write the docvol")
    plan_options(b, "NAME of a planned docvol, or a SOURCE to plan and build")
    b.add_argument("--workers", type=int, default=1, help="parallel fetches, 1-4 (default 1)")
    b.add_argument("--refetch", action="store_true",
                   help="download pages again instead of using the page cache "
                        "(llms.txt sources; Sphinx builds have no page cache)")
    sub.add_parser("list", help="built and planned docvols")
    r = sub.add_parser("remove", help="delete a built docvol (the plan stays)")
    r.add_argument("name", metavar="NAME")
    r.add_argument("--plan", action="store_true", help="delete the plan too")
    return p


def _is_source(arg: str) -> bool:
    return "/" in arg or ":" in arg or os.sep in arg or os.path.isdir(arg)


def main(argv: Optional[List[str]] = None, env=None, opener=None,
         sleep: Optional[Callable[[float], None]] = None) -> int:
    """opener and sleep are test hooks passed to every fetch source."""
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    cache = cache_dir(env)
    try:
        if args.command == "plan":
            do_plan(cache, args, opener, sleep)
        elif args.command == "build":
            if _is_source(args.source) or is_llms_source(args.source):
                name = do_plan(cache, args, opener, sleep)
            else:
                if args.overrides or args.reset or args.base_url or args.name:
                    raise CLIError("plan options need a SOURCE; to change the plan of "
                                   "%s run: plan SOURCE --name %s ..." % (args.source,
                                                                         args.source), 2)
                name = args.source
            do_build(cache, name, args.workers, args.refetch, opener, sleep)
        elif args.command == "list":
            do_list(cache)
        else:
            do_remove(cache, args.name, args.plan)
    except CLIError as e:
        warn(str(e))
        return e.code
    return 0


if __name__ == "__main__":
    sys.exit(main())
