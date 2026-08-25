"""Readers that extract numeric values from binary artifacts without executing them.

Every reader here is pointed at repositories the tool's operator did not write. Two of the
formats worth reading are code-execution formats by design:

  - `pickle.load` calls `find_class`, imports modules named in the stream and invokes
    `__reduce__`. A pickle is a program. It is never loaded here.
  - R's serialization carries promises and closures, and `load()` on a `.RData` evaluates
    them. `Rscript -e 'readRDS(...)'` is a remote code execution primitive pointed at an
    untrusted file. R is never invoked here.

Both formats are read by parsing their byte streams directly. `pickletools.genops` walks the
opcode stream and yields each opcode with its literal argument; it resolves no names, imports
nothing and calls nothing. The R serialization format is documented and its numeric vectors
are length-prefixed big-endian doubles, which is a parse rather than an evaluation.

Each reader returns the values it recovered and whether it understood the whole file. A
reader that stopped early must say so: the caller turns an incomplete read into `unchecked`
rather than `absent`, because a value this module failed to reach is not a value the
artifact lacks.
"""

from __future__ import annotations

import bz2
import gzip
import lzma
import pathlib
import pickletools
import struct

#: Opcodes carrying a literal number. Everything else in a pickle -- GLOBAL, REDUCE, INST,
#: STACK_GLOBAL -- is skipped rather than resolved, which is what keeps the read inert.
NUMERIC_OPCODES = {
    "BININT",
    "BININT1",
    "BININT2",
    "INT",
    "LONG",
    "LONG1",
    "LONG4",
    "FLOAT",
    "BINFLOAT",
}

#: A pickle or an R file is walked under a hard ceiling on how much it may yield, so a
#: crafted or merely enormous artifact cannot exhaust memory.
MAX_VALUES = 2_000_000


def read_pickle(path: pathlib.Path) -> tuple[list[str], bool]:
    """Literal numbers in a pickle's opcode stream.

    `pickletools.genops` is a disassembler. It reads the stream and yields
    `(opcode, argument, position)` without maintaining a stack of live objects, without
    importing the modules a GLOBAL opcode names, and without calling `__reduce__`. Nothing
    in the file is executed: a stream whose `__reduce__` calls `os.system` yields the
    strings `os` and `system` and runs neither.
    """
    values: list[str] = []
    size = path.stat().st_size
    try:
        with path.open("rb") as handle:
            # `genops` stops at the first STOP opcode. A file may hold several pickles
            # appended, which is how a long run dumps results incrementally, so the walk
            # restarts from wherever the previous one ended until the bytes run out.
            while handle.tell() < size:
                position = handle.tell()
                for opcode, argument, _ in pickletools.genops(handle):
                    if opcode.name in NUMERIC_OPCODES and argument is not None:
                        values.append(
                            repr(argument) if isinstance(argument, float) else str(argument)
                        )
                        if len(values) >= MAX_VALUES:
                            return values, False
                if handle.tell() <= position:
                    break
    except Exception:
        # A truncated or unfamiliar stream yields what was read before it stopped, and the
        # caller is told the read was partial so the remainder is never called absent.
        return values, False
    return values, True


#: R serialization type codes. Only the types below are modelled; the parser stops at
#: anything else rather than guessing, because a wrong width desynchronises every object
#: after it and turns the rest of the file into plausible noise.
NILSXP, SYMSXP, LISTSXP, CHARSXP, LGLSXP = 0, 1, 2, 9, 10
INTSXP, REALSXP, STRSXP, VECSXP = 13, 14, 16, 19

#: Pseudo-types standing for a fixed object -- R's NULL, the global environment, a
#: back-reference to a symbol already read. None carries a payload beyond its flags, except
#: a reference whose index did not fit in the flags word.
NILVALUE_SXP, GLOBALENV_SXP, UNBOUNDVALUE_SXP, MISSINGARG_SXP = 254, 253, 252, 251
BASENAMESPACE_SXP, EMPTYENV_SXP, BASEENV_SXP, REFSXP = 250, 242, 241, 255
ATOMIC_PSEUDO = {
    NILSXP,
    NILVALUE_SXP,
    GLOBALENV_SXP,
    UNBOUNDVALUE_SXP,
    MISSINGARG_SXP,
    BASENAMESPACE_SXP,
    EMPTYENV_SXP,
    BASEENV_SXP,
}

#: Types whose contents are a tag, a head and a tail rather than a length and a payload.
PAIRLIST = {LISTSXP, 3, 4, 5, 6, 17, 18}


def _decompress(raw: bytes) -> bytes:
    """R writes its serialization gzip-, bzip2- or xz-compressed by default."""
    try:
        if raw[:2] == b"\x1f\x8b":
            return gzip.decompress(raw)
        if raw[:3] == b"BZh":
            return bz2.decompress(raw)
        if raw[:6] == b"\xfd7zXZ\x00":
            return lzma.decompress(raw)
    except (OSError, EOFError, lzma.LZMAError, ValueError):
        return b""
    return raw


class _Reader:
    """A cursor over decompressed R serialization, in XDR (big-endian) form."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.at = 0

    def int32(self) -> int:
        value = struct.unpack_from(">i", self.data, self.at)[0]
        self.at += 4
        return value

    def doubles(self, count: int) -> list[float]:
        values = list(struct.unpack_from(f">{count}d", self.data, self.at))
        self.at += 8 * count
        return values

    def ints(self, count: int) -> list[int]:
        values = list(struct.unpack_from(f">{count}i", self.data, self.at))
        self.at += 4 * count
        return values

    def skip(self, count: int) -> None:
        if count < 0 or self.at + count > len(self.data):
            raise struct.error("length runs past the end of the file")
        self.at += count


#: Stems that name a format outright, for archives written as `RData.gz`.
KNOWN_STEMS = {".rdata", ".rds", ".rda"}

#: Single-file compressors. Each wraps one member whose own extension is what decides how
#: to read it, so `RData.gz` is an R workspace and `coords.gz` is not something this module
#: knows. Treating the wrapper as the format leaves the member unread.
COMPRESSORS = {
    ".gz": gzip.decompress,
    ".bz2": bz2.decompress,
    ".xz": lzma.decompress,
    ".lzma": lzma.decompress,
    ".z": gzip.decompress,
}


def unwrap(path: pathlib.Path, out_dir: pathlib.Path) -> pathlib.Path | None:
    """Decompress a single-member archive beside itself, keeping the inner extension.

    Returns the path to the decompressed member, or None where the wrapper holds no
    extension of its own to dispatch on -- in which case the caller records the file as
    unread rather than guessing at its contents.
    """
    suffix = path.suffix.lower()
    if suffix not in COMPRESSORS:
        return None
    inner = pathlib.Path(path.stem)
    if not inner.suffix:
        # `RData.gz` names its format in the stem rather than in a suffix. Renaming it to
        # `.RData` dispatches correctly; a stem that names no format still returns None,
        # because guessing at a member's contents is how a reader invents data.
        if f".{inner.name.lower()}" in KNOWN_STEMS:
            inner = pathlib.Path(f"{inner.name}.{inner.name}")
        else:
            return None
    try:
        data = COMPRESSORS[suffix](path.read_bytes())
    except (OSError, EOFError, lzma.LZMAError, ValueError):
        return None
    target = out_dir / inner.name
    try:
        target.write_bytes(data)
    except OSError:
        return None
    return target


def read_rdata(path: pathlib.Path) -> tuple[list[str], bool]:
    """Numeric vector contents of an `.rds`, `.RData` or `.rda` file.

    `save()` prefixes the stream with `RDX2\n` or `RDX3\n`; `saveRDS()` does not. Both then
    carry a format byte, a newline, and three version integers, and serialization version 3
    adds a length-prefixed native encoding name. Each object opens with a flags word whose
    low byte is its type: a real vector is a length and that many big-endian doubles, a
    pairlist is a tag, a head and a tail, and a generic vector is a length and that many
    further objects.

    No function, promise, closure or environment type is modelled, so nothing here can
    evaluate. Reaching one ends the parse and the file is reported incompletely read.
    """
    try:
        raw = _decompress(path.read_bytes())
    except OSError:
        return [], False
    if raw[:5] in (b"RDX2\n", b"RDX3\n"):
        raw = raw[5:]
    if len(raw) < 16 or raw[:1] not in (b"X", b"A", b"B") or raw[1:2] != b"\n":
        return [], False

    reader = _Reader(raw)
    reader.at = 2
    values: list[str] = []
    complete = True

    try:
        version = reader.int32()
        reader.int32()
        reader.int32()
        if version >= 3:
            reader.skip(reader.int32())
    except struct.error:
        return [], False

    def walk(depth: int) -> None:
        nonlocal complete
        if depth > 256 or len(values) >= MAX_VALUES:
            complete = False
            return
        flags = reader.int32()
        kind = flags & 0xFF

        if kind == REFSXP:
            if flags >> 8 == 0:
                reader.int32()
            return
        if kind in ATOMIC_PSEUDO:
            return

        has_attributes = bool(flags & (1 << 9))
        has_tag = bool(flags & (1 << 10))

        if kind in PAIRLIST:
            # For a pairlist the attributes and tag precede the head and tail; for a vector
            # the attributes follow the payload. Getting the order wrong shifts every
            # subsequent offset.
            if has_attributes:
                walk(depth + 1)
            if has_tag:
                walk(depth + 1)
            walk(depth + 1)
            walk(depth + 1)
            return

        if kind == SYMSXP:
            walk(depth + 1)
            return
        if kind == CHARSXP:
            length = reader.int32()
            if length >= 0:
                reader.skip(length)
        elif kind == REALSXP:
            values.extend(repr(v) for v in reader.doubles(reader.int32()))
        elif kind in (INTSXP, LGLSXP):
            values.extend(str(v) for v in reader.ints(reader.int32()))
        elif kind in (STRSXP, VECSXP):
            for _ in range(reader.int32()):
                if not complete:
                    return
                walk(depth + 1)
        else:
            complete = False
            return

        if has_attributes:
            walk(depth + 1)

    try:
        walk(0)
    except (struct.error, IndexError, RecursionError, MemoryError):
        complete = False
    return values, complete
