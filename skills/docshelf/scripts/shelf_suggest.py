"""docshelf suggest: read a project's build files for languages and libraries."""
import fnmatch
import json
import os
import re
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

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


def _load_toml(text: str) -> dict:
    if tomllib is None:
        raise ValueError("reading TOML needs Python 3.11 or newer")
    return tomllib.loads(text)


def _npm_names(name: str) -> Tuple[str, ...]:
    if name.startswith("@types/"):
        return (name[len("@types/"):],)
    if name.startswith("@") and "/" in name:
        scope, pkg = name[1:].split("/", 1)
        return (scope, pkg)
    return (name,)


def parse_package_json(text: str) -> List[Finding]:
    data = _dict(json.loads(text))
    out = [_lang("javascript")]
    engines = _dict(data.get("engines"))
    if "node" in engines:
        out.append(_lang("node", _first_number(str(engines["node"]))))
    for section in ("dependencies", "devDependencies"):
        for name in _dict(data.get(section)):
            out.append(_lib(*_npm_names(name)))
    return out


def _requirement_name(line: str) -> Optional[str]:
    m = _NAME.match(line.strip())
    return normalize(m.group(0)) if m else None


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
    reqs: List[str] = [r for r in project.get("dependencies") or []
                       if isinstance(r, str)]
    for group in _dict(project.get("optional-dependencies")).values():
        reqs.extend(r for r in group or [] if isinstance(r, str))
    for req in reqs:
        name = _requirement_name(req)
        if name:
            out.append(_lib(name))
    for name in poetry_deps:
        if name.lower() != "python":
            out.append(_lib(name))
    return out


def parse_requirements(text: str) -> List[Finding]:
    out = [_lang("python")]
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name = _requirement_name(line)
        if name:
            out.append(_lib(name))
    return out


def parse_cmake(text: str) -> List[Finding]:
    out = [_lang("cmake")]
    if re.search(r"(?i)\bCMAKE_CXX_STANDARD\b", text):
        out.append(_lang("cpp"))
    for m in re.finditer(r"(?i)\bfind_package\s*\(\s*([A-Za-z0-9_.+-]+)", text):
        out.append(_lib(m.group(1)))
    return out


def parse_cargo(text: str) -> List[Finding]:
    data = _load_toml(text)
    out = [_lang("rust")]
    for section in ("dependencies", "dev-dependencies"):
        for name in _dict(data.get(section)):
            out.append(_lib(name))
    return out


def parse_go_mod(text: str) -> List[Finding]:
    m = re.search(r"^go\s+(\d+(?:\.\d+)*)", text, re.M)
    return [_lang("go", m.group(1) if m else "")]


def parse_gemfile(text: str) -> List[Finding]:
    m = re.search(r"^\s*ruby\s+['\"]([^'\"]+)['\"]", text, re.M)
    out = [_lang("ruby", _first_number(m.group(1)) if m else "")]
    for g in re.finditer(r"^\s*gem\s+['\"]([^'\"]+)['\"]", text, re.M):
        out.append(_lib(g.group(1)))
    return out


def parse_composer(text: str) -> List[Finding]:
    data = _dict(json.loads(text))
    out = [_lang("php")]
    for section in ("require", "require-dev"):
        for name in _dict(data.get(section)):
            if name == "php" or name.startswith("ext-"):
                continue
            vendor, _, pkg = name.partition("/")
            out.append(_lib(pkg, vendor) if pkg else _lib(vendor))
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


def _parser_for(name: str) -> Optional[Callable[[str], List[Finding]]]:
    if name in PARSERS:
        return PARSERS[name]
    if fnmatch.fnmatchcase(name, REQUIREMENTS_PATTERN):
        return parse_requirements
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
            with open(path, encoding="utf-8") as f:
                text = f.read()
            found = parser(text)
        except (OSError, ValueError) as e:  # incl. JSON, TOML, Unicode errors
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
