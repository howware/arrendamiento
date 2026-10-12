"""Guard: no versioned file may carry the owner's documents or data that identifies someone.

    git ls-files -z | xargs -0 python tools/check_private_data.py      # what CI runs
    python tools/check_private_data.py file1 file2 ...

Blocks documents (PDF, invoice XML), real-data folders (estados/, reportes/, .memory/, mxsat-private/), SQLite
databases, CLABEs (with check digit), card numbers (Luhn), RFCs, CURPs and e-mail addresses. The SAT's public
generic RFCs are allowed. Exits 1 if it finds anything; it never prints the value, only file, line and kind.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BLOCKED_PARTS = {"estados", "reportes", ".memory", "corpus", "mxsat-private"}
BLOCKED_SUFFIXES = {".pdf", ".xml", ".sqlite", ".sqlite3", ".db"}
DIGITS = re.compile(r"(?<![\dA-Fa-f])\d{15,18}(?![\dA-Fa-f])")
RFC = re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z\d]{3}\b")
PUBLIC_RFCS = {"XAXX010101000", "XEXX010101000", "SAT970701NN3"}  # público en general, extranjero, the SAT
CURP = re.compile(r"\b[A-Z][AEIOUX][A-Z]{2}\d{6}[HM][A-Z]{5}[A-Z\d]\d\b")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
EMAIL_OK = re.compile(r"@(example\.(com|org)|users\.noreply\.github\.com)$")


def luhn(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def clabe(number: str) -> bool:
    weights = [3, 7, 1] * 6
    check = (10 - sum(int(d) * w % 10 for d, w in zip(number[:17], weights)) % 10) % 10
    return check == int(number[17])


def findings(path: Path) -> list[str]:
    out = []
    if BLOCKED_PARTS & set(path.parts):
        out.append(f"{path}: real-data folder")
    if path.suffix.lower() in BLOCKED_SUFFIXES:
        out.append(f"{path}: blocked file type ({path.suffix})")
    if out or not path.is_file():
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return out
    for n, line in enumerate(text.splitlines(), 1):
        for m in DIGITS.finditer(line):
            digits = m.group()
            if len(digits) == 18 and clabe(digits):
                out.append(f"{path}:{n}: possible CLABE")
            elif len(digits) in (15, 16) and luhn(digits):
                out.append(f"{path}:{n}: possible card number")
        if any(m.group() not in PUBLIC_RFCS for m in RFC.finditer(line)):
            out.append(f"{path}:{n}: possible RFC")
        if CURP.search(line):
            out.append(f"{path}:{n}: possible CURP")
        for m in EMAIL.finditer(line):
            if not EMAIL_OK.search(m.group()):
                out.append(f"{path}:{n}: e-mail address")
    return out


def main(argv: list[str]) -> int:
    problems = [f for arg in argv for f in findings(Path(arg))]
    for p in problems:
        print(p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
