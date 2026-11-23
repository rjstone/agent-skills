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

from build_archive import (docname_of, fetch_archive, find_build, find_source_archive,  # noqa: E402
                           is_singlehtml, split_singlehtml, unpack)  # noqa: E402
from build_detect import describe, detect, offline  # noqa: E402
from build_classify import apply_choices, counts, parse_choices, review_lines, run_rules  # noqa: E402
from build_core import (NAME_RE, VERSION, CLIError, built_dir, cache_dir, plans_dir, src_dir,  # noqa: E402
                        warn)
from build_docvol import check_name, derive_name, write_docvol, write_llms_docvol  # noqa: E402
from build_doxygen import DoxygenFormatError, read_doxygen  # noqa: E402
from build_fetch import (FetchError, PageCache, fetch_llms, fetch_pages, index_getter,  # noqa: E402
                         open_source, open_url_source)
from build_inventory import parse_inventory  # noqa: E402
from build_llms import is_llms_source, read_tree  # noqa: E402
from build_markdown import front_matter, page_signals  # noqa: E402
from build_plan import (load_plan, make_llms_plan, make_plan, save_plan,  # noqa: E402
                        summarize, summarize_llms)

DESCRIPTION = """\
Build a docshelf docvol from a Sphinx site's objects.inv (Sphinx, PyDoctor,
MkDocs with mkdocstrings), a Doxygen HTML site (its search index or
menudata.js) or a site's llms.txt page list (Mintlify, Starlight and
others). Sphinx and Doxygen: reference pages are kept in full, guide pages
become stubs with a link. llms.txt: every listed page is kept in full; narrow
with a sub-index as SOURCE or --stub. Usual loop:
  detect URL                  which type the site supports, and the SOURCE
  plan SOURCE --name NAME     read the inventory, write and summarize the plan
  plan SOURCE --name NAME --full 'group/*'   keep a prose group in full
  build NAME                  fetch the full pages, write the docvol
  classify NAME               (llms.txt) sort reference from guides after a build;
                              --apply FILE --model ID records an agent's choices
  build SOURCE [plan options] plan and build in one step
Then look things up with docshelf (the docvol is listed as "built").
SOURCE is the site's base URL or a local Sphinx or Doxygen HTML build
folder, or the URL (or local file) of an llms.txt."""


def _plan_path(cache: str, name: str) -> str:
    return os.path.join(plans_dir(cache), name + ".json")


def _read_inventory(source, data: Optional[bytes] = None):
    data = source.inventory() if data is None else data
    header, entries = parse_inventory(data)
    return hashlib.sha256(data).hexdigest(), header, entries


def _cached_getter(source):
    """source.file with each answer kept, so probing a file and then reading
    it costs one request."""
    cache: dict = {}

    def get(rel: str) -> Optional[bytes]:
        if rel not in cache:
            cache[rel] = source.file(rel)
        return cache[rel]
    return get


def _has_doxygen(get) -> bool:
    return get("search/searchdata.js") is not None or get("menudata.js") is not None


def _read_doxygen(get):
    """(sha, header, entries, index) with the reader's warnings printed (the
    first 10, then a count); a site whose index cannot be read is exit 3."""
    try:
        sha, header, entries, idx = read_doxygen(get)
    except DoxygenFormatError as e:
        raise CLIError("Doxygen index: %s" % e, 3)
    for w in idx.warnings[:10]:
        warn(w)
    if len(idx.warnings) > 10:
        warn("... and %d more index warnings" % (len(idx.warnings) - 10))
    return sha, header, entries, idx


def _plan_doxygen(cache: str, args, source, get) -> str:
    sha, header, entries, idx = _read_doxygen(get)
    name = args.name or derive_name(header)
    check_name(cache, name)
    path = _plan_path(cache, name)
    old = load_plan(path) if os.path.isfile(path) else None
    plan = make_plan(source.base, sha, header, entries, list(args.overrides or []), old=old,
                     reset=args.reset, base_url=args.base_url, kind="doxygen")
    plan["index"] = idx.kind
    save_plan(path, plan)
    _print(summarize(plan, old))
    _summary_tail(path)
    return name


def _print(lines: List[str]) -> None:
    for line in lines:
        print(line)


def _summary_tail(path: str) -> None:
    print("plan: %s (edit \"keep\" and set \"why\": \"manual\" to pin a page)" % path)


def do_plan_llms(cache: str, args, opener, sleep) -> str:
    if args.base_url:
        raise CLIError("--base-url is only for Sphinx sources", 2)
    source = open_url_source(opener=opener, sleep=sleep)
    src = args.source
    if not src.startswith(("http://", "https://")):
        src = os.path.abspath(src)
    tree = read_tree(src, index_getter(source))
    name = args.name or derive_name({"project": tree.title})
    check_name(cache, name)
    path = _plan_path(cache, name)
    old = load_plan(path) if os.path.isfile(path) else None
    plan = make_llms_plan(src, tree, list(args.overrides or []), old=old,
                          reset=args.reset)
    save_plan(path, plan)
    _print(summarize_llms(plan, old))
    _summary_tail(path)
    return name


def _check_txt_exists(arg: str) -> None:
    if arg.lower().endswith(".txt") and not arg.startswith(("http://", "https://")) \
            and not os.path.isfile(arg):
        raise CLIError("no such llms.txt file: %s" % arg, 2)


def do_plan(cache: str, args, opener=None, sleep=None) -> str:
    """Write the plan; return the docvol name."""
    _check_txt_exists(args.source)
    if is_llms_source(args.source):
        return do_plan_llms(cache, args, opener, sleep)
    source = open_source(args.source, base_url=args.base_url, opener=opener, sleep=sleep)
    get = _cached_getter(source)
    inv = get("objects.inv")
    if inv is None and _has_doxygen(get):
        return _plan_doxygen(cache, args, source, get)
    sha, header, entries = _read_inventory(source, inv)
    name = args.name or derive_name(header)
    check_name(cache, name)
    path = _plan_path(cache, name)
    old = load_plan(path) if os.path.isfile(path) else None
    overrides = list(args.overrides or [])
    plan = make_plan(source.base, sha, header, entries, overrides, old=old,
                     reset=args.reset, base_url=args.base_url)
    archive = find_source_archive(source)
    if archive:
        plan["archive"] = archive
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
    for key, (text, kind) in list(raw.items()):
        page = pages[key]
        try:
            page["signals"] = page_signals(text, kind)
        except (ValueError, RecursionError) as e:
            errors[key] = "convert failed: " + type(e).__name__
            page["fetch_error"] = errors[key]
            del raw[key]
            continue
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


def _archive_source(cache: str, name: str, plan: dict, source, refetch: bool):
    """A local Source on the unpacked archive of the plan, or None (with a
    warning) when it cannot be fetched or unpacked."""
    dest = os.path.join(src_dir(cache), name, "archive")
    os.makedirs(dest, exist_ok=True)
    site = os.path.join(dest, "site")
    try:
        path, fresh = fetch_archive(plan["archive"], dest, source, refetch, source.head_url)
        if fresh or not os.path.isdir(site):
            build = unpack(path, site)
        else:
            build = find_build(site) or site
        return open_source(build, base_url=source.base)
    except (FetchError, CLIError) as e:
        warn("archive not used (%s); fetching page by page" % getattr(e, "reason", e))
        return None


def _split_single_page(local, uris: list, html: dict, errors: dict) -> None:
    """A single-page (singlehtml) archive holds every document in index.html:
    replace html/errors in place with the per-page chunks (pages without a
    marker stay in errors, so they are fetched over HTTP)."""
    index = html.get("index.html")
    if index is None or not is_singlehtml(index):
        return
    # a real single-page archive lacks (nearly) every page but index.html; extra
    # files (genindex, search, _modules/) say nothing about that
    others = [u for u in uris if u != "index.html"]
    if not others or sum(1 for u in others if u in errors) * 2 < len(others):
        return
    names = {docname_of(u): u for u in uris}
    chunks = split_singlehtml(index, list(names))
    for u in uris:
        html.pop(u, None)
    for doc, page in chunks.items():
        html[names[doc]] = page
        errors.pop(names[doc], None)
    for u in uris:
        if u not in html:
            errors[u] = "no marker in the single-page archive"


def do_build(cache: str, name: str, workers: int, refetch: bool = False, opener=None,
             sleep=None, no_archive: bool = False) -> None:
    path = _plan_path(cache, name)
    if not os.path.isfile(path):
        raise CLIError("no plan for %s; run: docshelf-build plan SOURCE --name %s" % (name, name), 2)
    plan = load_plan(path)
    if plan.get("kind") == "llms":
        return do_build_llms(cache, name, plan, path, workers, refetch, opener, sleep)
    source = open_source(plan["source"], base_url=plan.get("base_url"), workers=workers,
                         opener=opener, sleep=sleep)
    kind = plan.get("kind", "sphinx")
    if kind == "doxygen":
        sha, header, entries, idx = _read_doxygen(_cached_getter(source))
    else:
        sha, header, entries = _read_inventory(source)
    if sha != plan["inventory_sha256"]:
        old, plan = plan, make_plan(plan["source"], sha, header, entries, [], old=plan, kind=kind)
        if old.get("archive"):
            plan["archive"] = old["archive"]
        if kind == "doxygen":
            plan["index"] = idx.kind
        save_plan(path, plan)
        print("the inventory changed since the plan:")
        _print(summarize(plan, old))
    uris = [p["uri"] for p in plan["pages"].values() if p["keep"] == "full"]
    local = None
    if plan.get("archive") and source.is_url and not no_archive and uris:
        local = _archive_source(cache, name, plan, source, refetch)
    if local is not None:
        html, errors = fetch_pages(local, uris)
        _split_single_page(local, uris, html, errors)
        missing = sorted(errors)
        html_n = len(html)
        errors = {}
        if missing:
            warn("fetching %d pages missing from the archive from %s"
                 % (len(missing), source.base))
            more, errors = fetch_pages(source, missing)
            html.update(more)
        print("%d pages from the archive, %d over HTTP" % (html_n, len(missing)))
    else:
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


def do_classify(cache: str, args) -> None:
    name = args.name
    path = _plan_path(cache, name)
    if not os.path.isfile(path):
        raise CLIError("no plan for %s; run: docshelf-build plan SOURCE --name %s" % (name, name), 2)
    plan = load_plan(path)
    if plan.get("kind") != "llms":
        raise CLIError("classify works on llms.txt docvols; Sphinx plans use the role rule", 2)
    if not any(isinstance(p.get("signals"), dict) for p in plan["pages"].values()):
        raise CLIError("no page has signals yet; run: docshelf-build build %s first" % name, 2)
    if args.limit < 1:
        raise CLIError("classify: --limit must be 1 or more", 2)
    if args.apply:
        if not args.model.strip() or args.model.startswith("rules-"):
            raise CLIError("classify: --model must be non-empty and not start with 'rules-' "
                           "(that id belongs to the rules)", 2)
        if args.apply == "-":
            text = sys.stdin.read()
        else:
            try:
                with open(args.apply, encoding="utf-8") as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError) as e:
                raise CLIError("cannot read %s: %s" % (args.apply, e), 2)
        choices, errors = parse_choices(text)
        for err in errors:
            print(err)
        if not choices:
            raise CLIError("no choices parsed; nothing applied", 2)
        applied, messages = apply_choices(plan, choices, args.model)
        save_plan(path, plan)
        print("applied %d" % applied)
        _print(messages)
        print("left for review: %d" % counts(plan)["review"])
        if applied == 0:
            raise CLIError("nothing applied; check the keys (copy them from the listing)", 2)
        return
    run_rules(plan)
    save_plan(path, plan)
    c = counts(plan)
    print("reference %d, stub %d, review %d, decided by a person %d, by an agent %d, "
          "no signals %d" % (c["reference"], c["stub"], c["review"], c["person"], c["agent"],
                             c["no signals"]))
    cache_pages = PageCache(os.path.join(src_dir(cache), name))
    offset, limit = max(0, args.offset), args.limit
    _print(review_lines(plan, cache_pages.get, offset, limit))
    if c["review"] == 0:
        print("nothing left to review; run: build %s" % name)
        return
    print('next: write one line per page to a file: "full KEY" or "stub KEY [short description]",')
    print("then run: classify %s --apply FILE --model YOUR_MODEL_ID, then classify %s again"
          % (name, name))
    if offset + limit < c["review"]:
        print("more: classify %s --offset %d" % (name, offset + limit))


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
    if not NAME_RE.match(name):
        raise CLIError("not a docvol name: %r" % name, 2)
    folder = os.path.join(built_dir(cache), name)
    plan = _plan_path(cache, name)
    pages = os.path.join(src_dir(cache), name)
    if os.path.basename(folder) != name:
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
                        "(llms.txt sources), or the site's HTML archive again")
    b.add_argument("--no-archive", action="store_true",
                   help="Sphinx: fetch pages one by one even when the site has an HTML archive")
    d = sub.add_parser("detect", help="which build type a site supports (objects.inv "
                       "or llms.txt), and the SOURCE to plan")
    d.add_argument("source", metavar="URL_OR_PATH")
    c = sub.add_parser("classify", help="llms.txt: sort reference pages from guides by rules, "
                       "list the undecided pages, record an agent's choices")
    c.add_argument("name", metavar="NAME")
    c.add_argument("--offset", type=int, default=0, help="first review page to list (default 0)")
    c.add_argument("--limit", type=int, default=25, help="review pages to list (default 25)")
    c.add_argument("--apply", metavar="FILE", help="apply 'full KEY' / 'stub KEY [text]' lines "
                   "from FILE ('-' = stdin)")
    c.add_argument("--model", default="agent", help="id recorded with --apply (default agent)")
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
            _check_txt_exists(args.source)
            if _is_source(args.source) or is_llms_source(args.source):
                name = do_plan(cache, args, opener, sleep)
            else:
                if args.overrides or args.reset or args.base_url or args.name:
                    raise CLIError("plan options need a SOURCE; to change the plan of "
                                   "%s run: plan SOURCE --name %s ..." % (args.source,
                                                                         args.source), 2)
                name = args.source
            do_build(cache, name, args.workers, args.refetch, opener, sleep, args.no_archive)
        elif args.command == "detect":
            found = detect(args.source, opener=opener, sleep=sleep)
            if found.kind is None:
                raise CLIError("no objects.inv or llms.txt found (and no Doxygen index); tried: %s"
                               % ", ".join("%s (%s)" % t for t in found.tried),
                               4 if offline(found) else 3)
            _print(describe(found))
        elif args.command == "classify":
            do_classify(cache, args)
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
