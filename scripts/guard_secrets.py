#!/usr/bin/env python3
"""Secret scanner. Walks the repository and flags potential API keys.

Exits 0 if clean, 1 if any potential secret is detected.
Run from project root:

    py -3.9 scripts/guard_secrets.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()

EXCLUDE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}
EXCLUDE_SUFFIXES = {
    ".pdf", ".pkl", ".pyc",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".webp",
    ".so", ".dll", ".exe", ".bin",
    ".tar", ".zip", ".gz", ".7z",
    ".woff", ".woff2", ".ttf", ".otf",
    ".docx", ".xlsx", ".pptx",
}

ANTHROPIC_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")
GENERIC_SK_RE = re.compile(r"sk-[A-Za-z0-9]{20,}")
AWS_RE = re.compile(r"AKIA[A-Z0-9]{16}")

KEYWORD_RE = re.compile(
    r"(api[_\-]?key|apikey|secret|password|token|credential)"
    r"\s*[=:]\s*"
    r"['\"]?([^\s'\"\n,;)\]}]{10,})",
    re.IGNORECASE,
)

BASE64_RE = re.compile(r"[A-Za-z0-9+/=]{40,}")
KEY_OR_SECRET_RE = re.compile(r"(?i)\b(key|secret)\b")

SAFE_VALUE_RE = re.compile(
    r"^(YOUR[_A-Z]+|REPLACE[_A-Z]*|EXAMPLE[A-Z_]*|PLACEHOLDER[A-Z_]*|"
    r"TODO[A-Z_]*|FIXME[A-Z_]*|"
    r"None|null|true|false|[0-9]+|"
    r"<[^>]+>|\$\{[^}]+\}|\$[A-Z_]+|"
    r"os\.environ.*|os\.getenv.*|getenv\(.*|"
    r"self\..*|cls\..*|this\..*|"
    r"config\..*|cfg\..*|settings\..*|"
    r"\.\.+/.*|/.*|[A-Z]:.*|"
    r"[A-Za-z0-9_]+\(.*\)|"
    r"[\"']?[A-Z_][A-Z0-9_]*[\"']?|"
    r"array.*|string|integer|boolean|object|null|float[^,]*|"
    r"REF-[0-9]+.*|CONV-[0-9]+.*|LAW-[A-Z0-9]+.*|"
    r"DELTA-[0-9]+.*|TF-[0-9]+.*|PREC-[0-9]+.*)$"
)

HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def should_scan(path: Path) -> bool:
    if path == SELF:
        return False
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return False
    parts = set(path.parts)
    if parts & EXCLUDE_DIRS:
        return False
    return True


def is_safe_value(value: str) -> bool:
    v = value.strip("'\"")
    if not v:
        return True
    if SAFE_VALUE_RE.match(v):
        return True
    if HEX_RE.match(v) and len(v) in (7, 8, 40, 64):
        return True
    if UUID_RE.match(v):
        return True
    return False


def scan_line(line: str):
    findings = []

    if ANTHROPIC_RE.search(line):
        findings.append("Anthropic key pattern (sk-ant-...)")
    if not ANTHROPIC_RE.search(line) and GENERIC_SK_RE.search(line):
        findings.append("sk-prefixed key pattern (sk-...)")
    if AWS_RE.search(line):
        findings.append("AWS access key pattern (AKIA...)")

    for kw_match in KEYWORD_RE.finditer(line):
        keyword = kw_match.group(1)
        value = kw_match.group(2)
        if is_safe_value(value):
            continue
        snippet = value[:16] + ("..." if len(value) > 16 else "")
        findings.append(f"keyword assignment: {keyword}={snippet}")

    if KEY_OR_SECRET_RE.search(line):
        for b64_match in BASE64_RE.finditer(line):
            b64_val = b64_match.group(0)
            if HEX_RE.match(b64_val) and len(b64_val) in (40, 64):
                continue
            findings.append("long base64-like string near 'key' or 'secret'")
            break

    return findings


def main():
    blocked = 0
    scanned = 0
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if not should_scan(path):
            continue
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for reason in scan_line(line):
                rel = path.relative_to(ROOT).as_posix()
                print(f"BLOCKED {rel}:{lineno} {reason}")
                blocked += 1

    if blocked:
        print(f"\nguard_secrets: {blocked} potential secret(s) detected across {scanned} file(s).")
        sys.exit(1)
    print(f"guard_secrets: clean ({scanned} file(s) scanned)")
    sys.exit(0)


if __name__ == "__main__":
    main()
