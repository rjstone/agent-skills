"""Doxygen HTML sites: read the client-side search index (search/*.js) or,
without one, menudata.js and the typed index pages, into InvEntry rows that
the Sphinx plan/build path already knows how to use."""
import re


class DoxygenFormatError(ValueError):
    """An index file that is not the JavaScript Doxygen writes."""


_BLOCKED = ("got an HTML page instead of a Doxygen index file; the site may be "
            "blocking automated requests")
_IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_INT = re.compile(r"-?\d+")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


class _Reader:
    """Recursive-descent reader for the literal subset Doxygen writes:
    arrays, objects (quoted or bare keys), strings, integers, booleans."""

    def __init__(self, text: str, pos: int):
        self.text, self.pos = text, pos

    def fail(self, what: str) -> DoxygenFormatError:
        return DoxygenFormatError("%s at offset %d" % (what, self.pos))

    def skip(self) -> None:
        t = self.text
        while self.pos < len(t):
            c = t[self.pos]
            if c.isspace():
                self.pos += 1
            elif t.startswith("/*", self.pos):
                end = t.find("*/", self.pos + 2)
                if end < 0:
                    raise self.fail("unterminated comment")
                self.pos = end + 2
            elif t.startswith("//", self.pos):
                end = t.find("\n", self.pos)
                self.pos = len(t) if end < 0 else end + 1
            else:
                return

    def peek(self) -> str:
        self.skip()
        if self.pos >= len(self.text):
            raise self.fail("unexpected end")
        return self.text[self.pos]

    def value(self) -> object:
        c = self.peek()
        if c == "[":
            return self.array()
        if c == "{":
            return self.obj()
        if c in "'\"":
            return self.string()
        m = _INT.match(self.text, self.pos)
        if m:
            self.pos = m.end()
            return int(m.group())
        for word, val in (("true", True), ("false", False)):
            if self.text.startswith(word, self.pos):
                self.pos += len(word)
                return val
        raise self.fail("unexpected %r" % c)

    def _items(self, close: str, item) -> None:
        self.pos += 1
        if self.peek() == close:
            self.pos += 1
            return
        while True:
            item()
            c = self.peek()
            self.pos += 1
            if c == close:
                return
            if c != ",":
                raise self.fail("expected ',' or %r" % close)
            if self.peek() == close:  # trailing comma
                self.pos += 1
                return

    def array(self) -> list:
        out: list = []
        self._items("]", lambda: out.append(self.value()))
        return out

    def obj(self) -> dict:
        out: dict = {}

        def item():
            c = self.peek()
            if c in "'\"":
                key = self.string()
            else:
                m = _IDENT.match(self.text, self.pos) or _INT.match(self.text, self.pos)
                if not m:
                    raise self.fail("bad key")
                key, self.pos = m.group(), m.end()
            if self.peek() != ":":
                raise self.fail("expected ':'")
            self.pos += 1
            out[key] = self.value()
        self._items("}", item)
        return out

    def string(self) -> str:
        t, quote = self.text, self.text[self.pos]
        i, out = self.pos + 1, []
        while i < len(t):
            c = t[i]
            if c == quote:
                self.pos = i + 1
                return "".join(out)
            if c == "\\":
                if i + 1 >= len(t):
                    break
                n = t[i + 1]
                if n == "u":
                    try:
                        out.append(chr(int(t[i + 2:i + 6], 16)))
                    except ValueError:
                        raise self.fail("bad \\u escape")
                    i += 6
                    continue
                out.append(_ESCAPES.get(n, n))
                i += 2
                continue
            if c == "\n":
                break
            out.append(c)
            i += 1
        raise self.fail("unterminated string")


def js_value(text: str, var: str) -> object:
    """The literal assigned by `var <var> = ...` in a Doxygen .js file."""
    if text.lstrip().startswith("<"):
        raise DoxygenFormatError(_BLOCKED)
    m = re.search(r"\bvar\s+%s\s*=" % re.escape(var), text)
    if not m:
        raise DoxygenFormatError("no 'var %s =' in the file" % var)
    return _Reader(text, m.end()).value()
