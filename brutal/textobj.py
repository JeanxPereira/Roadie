"""The engine's text object format, used by Material, MeshSet, Stance, Outfit and most data
resources: u32 length, then `<version>Class{Key=Value;...}`.

Values:  number | "string" | <a,b,c> tuple | @path (`@` alone = none) | [v, v, ...] | Class{...} | bare word
Objects come back as dicts with the class name under '_class'.
"""

from __future__ import annotations

import struct


WS = " \t\r\n"


class ParseError(ValueError):
    pass


class _P:
    def __init__(self, s: str):
        self.s, self.i = s, 0

    def peek(self) -> str:
        return self.s[self.i] if self.i < len(self.s) else ""

    def expect(self, c: str):
        if self.peek() != c:
            raise ParseError(f"expected {c!r} at {self.i}, got {self.s[self.i:self.i + 20]!r}")
        self.i += 1

    def word(self, stops: str) -> str:
        j = self.i
        while self.i < len(self.s) and self.s[self.i] not in stops:
            self.i += 1
        return self.s[j:self.i]

    def obj(self, cls: str) -> dict:
        self.expect("{")
        out: dict = {"_class": cls}
        self.ws()
        while self.peek() != "}":
            key = self.word("=}").strip()
            self.expect("=")
            out[key] = self.value(";}")
            if self.peek() == ";":
                self.i += 1
            self.ws()
        self.expect("}")
        return out

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in WS:
            self.i += 1

    def vector(self):
        self.expect("<")
        items = []  # tuples: numbers, but also refs, names, nested tuples
        self.ws()
        while self.peek() != ">":
            items.append(self.value(",>"))
            if self.peek() == ",":
                self.i += 1
            self.ws()
        self.i += 1
        return tuple(items)

    def value(self, stops: str):
        self.ws()
        c = self.peek()
        if c == "[":
            self.i += 1
            items = []
            self.ws()
            while self.peek() != "]":
                items.append(self.value(",]"))
                if self.peek() == ",":
                    self.i += 1
                self.ws()
            self.i += 1
            return items
        if c == "<":
            return self.vector()
        if c == '"':
            self.i += 1
            out = []
            while self.i < len(self.s) and self.s[self.i] != '"':
                if self.s[self.i] == "\\":
                    self.i += 1
                out.append(self.s[self.i])
                self.i += 1
            self.i += 1
            return "".join(out)
        if c == "@":
            self.i += 1
            return self.word(stops) or None
        w = self.word(stops + "{")
        if self.peek() == "{":
            return self.obj(w.strip())
        try:
            return float(w)
        except ValueError:
            return w.strip()


def is_textobj(d: bytes) -> bool:
    if len(d) < 6:
        return False
    (n,) = struct.unpack_from("<I", d, 0)
    if 4 + n > len(d) or not d[4:5].isdigit():
        return False
    head = d[4:4 + 64].split(b"{", 1)
    return len(head) == 2 and head[0].lstrip(b"0123456789").isalnum()


def parse(d: bytes) -> dict:
    (n,) = struct.unpack_from("<I", d, 0)
    text = d[4:4 + n].decode("latin-1").rstrip("\0 \r\n")
    k = 0
    while k < len(text) and text[k].isdigit():
        k += 1
    p = _P(text)
    p.i = text.index("{")
    o = p.obj(text[k:p.i])
    o["_version"] = int(text[:k]) if k else None
    return o
