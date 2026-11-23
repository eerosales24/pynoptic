"""Reading a submission from disk, in the one place that has to get it right.

A submission is not a file the project wrote. It comes from a web form, a
Windows editor, a database column or an export, and three things about it
are routinely wrong in ways that look like a syntax error:

- **A byte-order mark.** Reading UTF-8 strictly leaves ``\\ufeff`` as the
  first character of the source, and ``ast.parse`` rejects it. ``utf-8-sig``
  strips it when present and is identical when it is not, so there is no
  reason to ever use plain ``utf-8`` here.
- **Bytes that are not UTF-8 at all.** ``errors="replace"`` keeps the rest
  of the submission readable rather than losing the file to one character
  in a comment.
- **Carriage returns.** They are harmless to the parser and noisy in
  evidence, where a trailing ``\\r`` ends up inside the quoted line.

Getting this wrong fails closed in the worst way: the submission is
recorded as not parsing, and a corpus run reports a clean sheet for code
nobody looked at.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["decode_source", "read_source"]


def decode_source(raw: bytes) -> str:
    """Decode submission bytes into source text.

    Parameters:
        - raw: The file's bytes.

    Returns:
        - The text, without a byte-order mark and with newlines normalised.
    """
    return raw.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def read_source(path: str | Path) -> str:
    """Read one submission from disk.

    Parameters:
        - path: The file to read.

    Returns:
        - The source text, ready to parse.

    Raises:
        - OSError: When the file cannot be read. Callers report that as a
          diagnostic rather than letting it escape.
    """
    return decode_source(Path(path).read_bytes())
