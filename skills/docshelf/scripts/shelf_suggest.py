"""docshelf suggest: read a project's build files for languages and libraries."""
import fnmatch
import json
import os
import re
import sys
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

import shelf_backends
import shelf_devdocs
from shelf_core import Config, Docvol

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

SKIP_DIRS = frozenset({"node_modules", "venv", ".venv", "env", "build", "dist",
                       "target", "vendor"})
_NUM = re.compile(r"\d+(?:\.\d+)*")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class Finding(NamedTuple):
    kind: str  # "lang" or "lib"
    names: Tuple[str, ...]  # candidates, most specific first, normalized
    version: str  # "" when none or not a plain number
    source: str  # path relative to the scan root, "/" separators


def normalize(name: str) -> str:
    """Lowercase, with each run of '-', '_' and '.' collapsed to '-'."""
    return re.sub(r"[-_.]+", "-", name.lower())


def _lang(name: str, version: str = "") -> Finding:
    return Finding("lang", (name,), version, "")


def _lib(*names: str, version: str = "") -> Finding:
    return Finding("lib", tuple(normalize(n) for n in names), version, "")


def _first_number(text: str) -> str:
    m = _NUM.search(text)
    return m.group(0) if m else ""


def _version_token(text: str) -> str:
    """A plain version after an optional 'v'; '' for lts/iron, system, ..."""
    m = re.match(r"v?(\d+(?:\.\d+)*)", text.strip())
    return m.group(1) if m else ""


def _plain_python_version(spec: str) -> str:
    """Only '==X.Y[...]' or a bare 'X.Y' counts; '>=3.10' gives ''."""
    m = re.fullmatch(r"\s*(?:==\s*)?(\d+\.\d+(?:\.\d+)*)(?:\.\*)?\s*", spec)
    return m.group(1) if m else ""


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list:
    return value if isinstance(value, list) else []


def _load_toml(text: str) -> dict:
    if tomllib is None:
        raise ValueError("reading TOML needs Python 3.11 or newer")
    return tomllib.loads(text)


_RANGE_SKIP = ("workspace:", "file:", "link:", "portal:", "patch:", "npm:",
               "github:", "gitlab:", "bitbucket:", "git+", "git:", "http:",
               "https:")


def _range_version(spec: object) -> str:
    """First number of an npm, composer, Cargo or Poetry version range;
    '' for *, latest, tags, paths, aliases, git and URL specs."""
    if not isinstance(spec, str):
        return ""
    spec = spec.strip()
    if spec.lower().startswith(_RANGE_SKIP) or "/" in spec or "://" in spec:
        return ""
    return _first_number(spec)


def _table_version(value: object) -> str:
    """Cargo / Poetry: a version string or a table with a "version" key."""
    if isinstance(value, dict):
        value = value.get("version")
    return _range_version(value)


def _npm_names(name: str) -> Tuple[str, ...]:
    """'@types/x' -> x; '@scope/pkg' -> the whole name when ALIASES has it,
    else the scope only ('@sentry/node' is not node)."""
    if name.startswith("@types/"):
        return (name[len("@types/"):],)
    if name.startswith("@") and "/" in name:
        full = normalize(name[1:])
        return (full,) if full in ALIASES else (name[1:].split("/", 1)[0],)
    return (name,)


def parse_package_json(text: str) -> List[Finding]:
    data = _dict(json.loads(text))
    out = [_lang("javascript")]
    engines = _dict(data.get("engines"))
    if "node" in engines:
        out.append(_lang("node", _first_number(str(engines["node"]))))
    for section in ("dependencies", "devDependencies"):
        for name, spec in _dict(data.get(section)).items():
            out.append(_lib(*_npm_names(name), version=_range_version(spec)))
    return out


_DIRECT_REF = re.compile(r"\s*[A-Za-z0-9][A-Za-z0-9._-]*\s*(?:\[[^\]]*\])?\s*@")


def _requirement(line: str) -> Optional[Finding]:
    """A lib finding for a PEP 508 requirement: the first number of its
    first specifier that is not '!=' ('>=4.2,<5' -> 4.2); none for a direct
    reference ('foo @ https://...')."""
    line = line.split(";", 1)[0].split(" --", 1)[0].strip()
    m = _NAME.match(line)
    if not m:
        return None
    rest = re.sub(r"^\s*\[[^\]]*\]", "", line[m.end():])
    version = ""
    if not rest.lstrip().startswith("@"):
        clauses = [c.strip() for c in rest.split(",")]
        version = next((_first_number(c) for c in clauses
                        if c and not c.startswith("!=")), "")
    return _lib(m.group(0), version=version)


def parse_pyproject(text: str) -> List[Finding]:
    data = _load_toml(text)
    project = _dict(data.get("project"))
    poetry = _dict(_dict(data.get("tool")).get("poetry"))
    poetry_deps = _dict(poetry.get("dependencies"))
    spec = project.get("requires-python")
    if spec is None and isinstance(poetry_deps.get("python"), str):
        spec = poetry_deps["python"]
    out = [_lang("python", _plain_python_version(spec)
                 if isinstance(spec, str) else "")]
    reqs: List[str] = [r for r in _list(project.get("dependencies"))
                       if isinstance(r, str)]
    groups = (list(_dict(project.get("optional-dependencies")).values())
              + list(_dict(data.get("dependency-groups")).values()))  # PEP 735
    for group in groups:
        reqs.extend(r for r in _list(group) if isinstance(r, str))
    for req in reqs:
        found = _requirement(req)
        if found:
            out.append(found)
    tables = [poetry_deps] + [_dict(_dict(g).get("dependencies")) for g in
                              _dict(poetry.get("group")).values()]
    for table in tables:
        for name, spec in table.items():
            if name.lower() != "python":
                out.append(_lib(name, version=_table_version(spec)))
    return out


def parse_requirements(text: str) -> List[Finding]:
    out = [_lang("python")]
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-") \
                or ("://" in line and not _DIRECT_REF.match(line)):
            continue
        found = _requirement(line)
        if found:
            out.append(found)
    return out


def parse_cmake(text: str) -> List[Finding]:
    out = [_lang("cmake")]
    text = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    if re.search(r"(?i)\bCMAKE_CXX_STANDARD\b", text):
        out.append(_lang("cpp"))
    for m in re.finditer(r"(?i)\bfind_package\s*\(\s*([A-Za-z0-9_.+-]+)", text):
        out.append(_lib(m.group(1)))
    return out


def parse_cargo(text: str) -> List[Finding]:
    data = _load_toml(text)
    out = [_lang("rust")]
    tables = [_dict(data.get("dependencies")), _dict(data.get("dev-dependencies")),
              _dict(_dict(data.get("workspace")).get("dependencies"))]
    for table in tables:
        for name, spec in table.items():
            out.append(_lib(name, version=_table_version(spec)))
    return out


def parse_go_mod(text: str) -> List[Finding]:
    m = re.search(r"^go\s+(\d+(?:\.\d+)*)", text, re.M)
    return [_lang("go", m.group(1) if m else "")]


def parse_gemfile(text: str) -> List[Finding]:
    m = re.search(r"^\s*ruby\s+['\"]([^'\"]+)['\"]", text, re.M)
    out = [_lang("ruby", _first_number(m.group(1)) if m else "")]
    for g in re.finditer(r"^\s*gem\s+['\"]([^'\"]+)['\"]"
                         r"(?:\s*,\s*['\"]([^'\"]+)['\"])?", text, re.M):
        out.append(_lib(g.group(1), version=_first_number(g.group(2) or "")))
    return out


def parse_composer(text: str) -> List[Finding]:
    data = _dict(json.loads(text))
    out = [_lang("php")]
    for section in ("require", "require-dev"):
        for name, spec in _dict(data.get(section)).items():
            if name == "php" or name.startswith("ext-"):
                continue
            vendor, _, pkg = name.partition("/")
            version = _range_version(spec)
            out.append(_lib(pkg, vendor, version=version) if pkg
                       else _lib(vendor, version=version))
    return out


def _image_finding(ref: str) -> Optional[Finding]:
    """A lib finding for an image reference like 'docker.io/library/node:20'."""
    ref = ref.split("@", 1)[0]
    parts = ref.split("/")
    if len(parts) > 1 and (any(c in parts[0] for c in ".:")
                           or parts[0] == "localhost"):
        parts = parts[1:]
    if len(parts) > 1 and parts[0] == "library":
        parts = parts[1:]
    image, _, tag = parts[-1].partition(":")
    if not image or "$" in image:
        return None
    return _lib(image, version=_version_token(tag))


def parse_dockerfile(text: str) -> List[Finding]:
    out = [_lang("docker")]
    stages = set()
    for m in re.finditer(
            r"^\s*FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\S+))?", text,
            re.M | re.I):
        ref, stage = m.group(1), m.group(2)
        if stage:
            stages.add(stage.lower())
        if ref.lower() == "scratch" or ref.lower() in stages:
            continue
        found = _image_finding(ref)
        if found:
            out.append(found)
    return out


def parse_compose(text: str) -> List[Finding]:
    out = [_lang("docker")]
    for m in re.finditer(r"^\s*(?:-\s*)?image:\s*['\"]?([^\s'\"#]+)", text,
                         re.M):
        found = _image_finding(m.group(1))
        if found:
            out.append(found)
    return out


def _version_file(lang: str, strip_prefix: str = "") -> Callable[[str], List[Finding]]:
    def parse(text: str) -> List[Finding]:
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                if strip_prefix and line.startswith(strip_prefix):
                    line = line[len(strip_prefix):]
                return [_lang(lang, _version_token(line))]
        return [_lang(lang)]
    return parse


_TOOL_VERSIONS = {"nodejs": "node", "python": "python", "ruby": "ruby",
                  "golang": "go", "rust": "rust"}


def parse_tool_versions(text: str) -> List[Finding]:
    out = []
    for raw in text.splitlines():
        parts = raw.split("#", 1)[0].split()
        if parts and parts[0] in _TOOL_VERSIONS:
            out.append(_lang(_TOOL_VERSIONS[parts[0]],
                             _version_token(parts[1]) if len(parts) > 1 else ""))
    return out


# Each parser takes a file's text; scan_project fills in Finding.source.
PARSERS: Dict[str, Callable[[str], List[Finding]]] = {
    "package.json": parse_package_json,
    "pyproject.toml": parse_pyproject,
    "CMakeLists.txt": parse_cmake,
    "Cargo.toml": parse_cargo,
    "go.mod": parse_go_mod,
    "Gemfile": parse_gemfile,
    "composer.json": parse_composer,
    "Dockerfile": parse_dockerfile,
    "docker-compose.yml": parse_compose,
    "docker-compose.yaml": parse_compose,
    "compose.yml": parse_compose,
    "compose.yaml": parse_compose,
    ".nvmrc": _version_file("node"),
    ".node-version": _version_file("node"),
    ".python-version": _version_file("python"),
    ".ruby-version": _version_file("ruby", "ruby-"),
    ".tool-versions": parse_tool_versions,
}
REQUIREMENTS_PATTERN = "requirements*.txt"
DOCKERFILE_PATTERNS = ("Dockerfile.*", "*.Dockerfile")


def _parser_for(name: str) -> Optional[Callable[[str], List[Finding]]]:
    if name in PARSERS:
        return PARSERS[name]
    if fnmatch.fnmatchcase(name, REQUIREMENTS_PATTERN):
        return parse_requirements
    if any(fnmatch.fnmatchcase(name, p) for p in DOCKERFILE_PATTERNS) \
            and not name.endswith(".dockerignore"):
        return parse_dockerfile
    return None


def _scan_dir(folder: str, rel: str, findings: List[Finding],
              notes: List[str]) -> None:
    for name in sorted(os.listdir(folder)):
        parser = _parser_for(name)
        path = os.path.join(folder, name)
        if parser is None or not os.path.isfile(path):
            continue
        source = rel + name
        try:
            with open(path, encoding="utf-8-sig") as f:
                text = f.read()
            found = parser(text)
        except (OSError, ValueError, TypeError) as e:  # incl. JSON, TOML, Unicode
            notes.append("note: skipped %s: %s" % (source, e))
            continue
        findings.extend(f._replace(source=source) for f in found)


def _has_parser_file(folder: str) -> bool:
    try:
        return any(_parser_for(n) and os.path.isfile(os.path.join(folder, n))
                   for n in os.listdir(folder))
    except OSError:
        return False


MONOREPO_DIRS = ("packages", "apps")  # their children are scanned too


def _subdirs(folder: str) -> List[str]:
    """Sorted names of folders in folder that a scan may enter."""
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    return [n for n in names
            if not n.startswith(".") and n not in SKIP_DIRS
            and os.path.isdir(os.path.join(folder, n))]


def _walk(root: str, findings: List[Finding], notes: List[str]) -> None:
    for name in _subdirs(root):
        child = os.path.join(root, name)
        if _has_parser_file(child):
            _scan_dir(child, name + "/", findings, notes)
        if name in MONOREPO_DIRS:
            for sub in _subdirs(child):
                if _has_parser_file(os.path.join(child, sub)):
                    _scan_dir(os.path.join(child, sub),
                              "%s/%s/" % (name, sub), findings, notes)


def scan_project(root: str) -> Tuple[List[Finding], List[str]]:
    """Findings from the build files in root, its direct child folders and
    the children of packages/ and apps/, plus notes about skipped files."""
    findings: List[Finding] = []
    notes: List[str] = []
    try:
        _scan_dir(root, "", findings, notes)
    except OSError as e:
        return findings, ["note: skipped %s: %s" % (root, e)]
    _walk(root, findings, notes)
    return findings, notes


# Normalized dependency name -> DevDocs family (checked against the DevDocs
# list in 2026-11). Names that equal a family need no entry; the identity
# entries below are the common ones. A scoped npm name is listed without
# its '@' ("tanstack/react-query").
ALIASES: Dict[str, str] = {
    "react-dom": "react",
    "react-native": "react_native", "react-router-dom": "react_router",
    "react-router": "react_router", "react-bootstrap": "react_bootstrap",
    "vue-router": "vue_router", "vue": "vue", "typescript": "typescript",
    "next": "nextjs", "tanstack/react-query": "tanstack_query",
    "postgres": "postgresql", "golang": "go", "httpd": "apache_http_server",
    "qt6": "qt", "qt5": "qt", "eigen": "eigen3",
    "jquery-ui": "jqueryui", "djangorestframework": "django_rest_framework",
    "jinja2": "jinja", "scikit-learn": "scikit_learn", "sklearn": "scikit_learn",
    "scikit-image": "scikit_image", "torch": "pytorch",
    "numpy": "numpy", "pandas": "pandas", "django": "django", "flask": "flask",
}


class Suggestion(NamedTuple):
    name: str  # docvol or slug to list
    status: str  # "installed", "docset" or "available"
    sources: List[str]
    note: str  # "" or e.g. "no 3.9 docs; newest is 3.14"


def _agrees(wanted: str, have: str) -> bool:
    """Equal on as many of the first two numbers as both have."""
    x, y = shelf_backends._major_minor(wanted), shelf_backends._major_minor(have)
    n = min(len(x), len(y))
    return x[:n] == y[:n]


def _row_version(row: dict) -> str:
    version = row.get("version")
    if version:
        return str(version)
    slug = row["slug"]
    return slug.split("~", 1)[1].replace("_", " ") if "~" in slug else ""


def _suggest_for(finding: Finding, installed: List[Docvol],
                 manifest: Optional[List[dict]]
                 ) -> Optional[Tuple[str, Suggestion]]:
    """(family, suggestion) for the first candidate name with docs."""
    v = finding.version
    for n in finding.names:
        family = normalize(ALIASES.get(n, n))
        have = [d for d in installed
                if normalize(d.family) == family
                or family in {normalize(a) for a in d.aliases}]
        rows = [r for r in manifest or []
                if normalize(r["slug"].split("~")[0]) == family
                or normalize(str(r.get("alias") or "")) == family]
        pools = ((have, lambda d: d.version), (rows, _row_version))
        for pool, version_of in pools:  # installed beats available
            found = next((c for c in pool
                          if not v or _agrees(v, version_of(c))), None)
            if found is not None:
                return family, _make(found, "", finding.source)
        for pool, version_of in pools:  # nothing agrees: the newest
            if pool:
                if pool is have:  # list order is not version order
                    pool = sorted(have, reverse=True, key=lambda d:
                                  shelf_backends._major_minor(d.version))
                newest = version_of(pool[0])
                note = ("no %s docs; newest is %s" % (v, newest) if newest
                        else "no %s docs listed" % v)
                return family, _make(pool[0], note, finding.source)
    return None


def _make(candidate, note: str, source: str) -> Suggestion:
    if isinstance(candidate, dict):
        return Suggestion(candidate["slug"], "available", [source], note)
    return Suggestion(candidate.name,
                      "docset" if candidate.read_only else "installed",
                      [source], note)


def match(findings: List[Finding], installed: List[Docvol],
          manifest: Optional[List[dict]]) -> Tuple[List[Suggestion], int]:
    """Suggestions (one per family and per name, in the order first found,
    sources merged in finding order) and the number of distinct library
    names that matched no docvol. Versioned findings are resolved first, so
    a family gets one version: a later or unversioned finding for it only
    adds its source."""
    out: Dict[str, Suggestion] = {}  # suggestion name -> suggestion
    name_of: Dict[str, str] = {}  # family -> suggestion name
    found: Dict[str, List[int]] = {}  # suggestion name -> finding indexes
    unmatched = set()
    order = sorted(range(len(findings)), key=lambda i: not findings[i].version)
    for i in order:
        f = findings[i]
        result = _suggest_for(f, installed, manifest)
        if result is None:
            if f.kind == "lib":
                unmatched.add(f.names)
            continue
        family, s = result
        name = name_of.get(family, s.name)
        name_of.setdefault(family, name)
        out.setdefault(name, s)
        found.setdefault(name, []).append(i)
    result_list = []
    for name in sorted(out, key=lambda n: min(found[n])):
        sources: List[str] = []
        for i in sorted(found[name]):
            if findings[i].source not in sources:
                sources.append(findings[i].source)
        result_list.append(out[name]._replace(sources=sources))
    return result_list, len(unmatched)


def _git_top(folder: str) -> Optional[str]:
    """The nearest folder at or above folder that has a .git entry."""
    d = os.path.abspath(folder)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def scan_root(cfg: Config, cwd: str) -> str:
    """The project file's folder when it was found from cwd upward (not by
    a fallback) and is cwd or in cwd's git work tree; else cwd."""
    cwd = os.path.abspath(cwd)
    if not cfg.project_file or cfg.project_note:
        return cwd
    project = os.path.dirname(os.path.abspath(cfg.project_file))
    if project == cwd:
        return project
    top = _git_top(cwd)
    if top and os.path.commonpath([project, top]) == top:
        return project
    return cwd


def cmd_suggest(cfg: Config, args) -> int:
    root = scan_root(cfg, os.getcwd())
    findings, notes = scan_project(root)
    notes.insert(0, "note: scanned %s" % root)
    manifest = shelf_devdocs.cached_manifest(cfg)
    if manifest is None:
        notes.append("note: no DevDocs list cached; run sources (network) "
                     "to find more")
    suggestions, unmatched = match(
        findings, shelf_backends.installed_docvols(cfg), manifest)
    names = [s.name for s in suggestions]
    if args.json:  # the notes are in the JSON only
        print(json.dumps({
            "suggestions": [s._asdict() for s in suggestions],
            "docvols": names, "unmatched": unmatched, "notes": notes}, indent=2))
        return 0
    for note in notes:
        print(note, file=sys.stderr)
    for s in suggestions:
        print("%-9s %s  (%s)%s" % (s.status, s.name, ", ".join(s.sources),
                                   "  " + s.note if s.note else ""))
    print('"docvols": %s' % json.dumps(names))
    if unmatched:
        print("%d dependencies matched no docvol" % unmatched)
    return 0
