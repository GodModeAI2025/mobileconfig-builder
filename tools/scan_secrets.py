#!/usr/bin/env python3
"""
scan_secrets.py — sucht Geheimnisse in den von Git verfolgten Dateien.

Dieses Werkzeug baut Profile, die WLAN-Passwoerter, Shared Secrets und
Kontodaten im Klartext tragen, und signiert sie mit privaten Schluesseln.
Beides gehoert nie ins Repo. Der Scan braucht kein Netz, liest nur, was
`git ls-files` meldet, und nennt zu jedem Fund Datei und Zeile.

Drei Regeln:

1. Verbotene Dateitypen. Erzeugte Profile (.mobileconfig) und Schluessel-
   oder Zertifikatsdateien (.pem, .key, .p12, ...) duerfen nicht verfolgt
   werden. .gitignore deckt sie ab, `git add -f` umgeht .gitignore, und
   der Quick Start schreibt die Ausgabedatei per `-o` ins Repo-Wurzel-
   verzeichnis. Genau dieser Weg wird hier zugemacht.
2. Schluesselmaterial im Text. PEM-Bloecke mit privatem Schluessel oder
   Zertifikat, in beliebiger Textdatei, etwa als "Beispiel" in einer
   Doku-Datei.
3. Passwortfelder. Jeder Wert hinter einem Key wie Password, SharedSecret
   oder Passphrase muss ein dokumentierter Platzhalter sein.

Zu Regel 3 und zum Umgang mit den eigenen Beispielen: die Specs unter
assets/examples/ brauchen ein Passwort, sonst zeigen sie den Aufbau nicht,
den sie zeigen sollen. Sie auf leere Strings umzustellen wuerde die Evals
1 und 3 mitreissen, sie im Repo zu lassen und pauschal zu melden wuerde den
Scan dauerhaft rot fahren. Deshalb steht hier eine Allowlist mit genau den
erfundenen Werten, die vorkommen duerfen. Ein echtes Passwort faellt auf,
weil sein Wert nicht in der Liste steht. Ein neuer Platzhalter kostet eine
Zeile in PLACEHOLDER_VALUES und ist damit eine bewusste Entscheidung.

Grenzen: der Scan kennt keine Entropie-Heuristik und findet nichts in der
Historie, nur im aktuellen Stand. Er ersetzt kein `git-secrets` oder
`gitleaks`, er deckt die Wege ab, die dieses Repo selbst dokumentiert.

Usage:
    python3 tools/scan_secrets.py
    python3 tools/scan_secrets.py --root /pfad/zum/repo

Exit-Codes: 0 sauber, 1 mindestens ein Fund, 2 Aufrufproblem.
"""
from __future__ import annotations
import argparse
import re
import subprocess
import sys
from pathlib import Path

# Regel 1: Dateiendungen, die im Repo nichts verloren haben.
BLOCKED_SUFFIXES = {
    ".mobileconfig": "erzeugtes Profil, enthaelt Klartext-Secrets",
    ".pem": "Schluessel- oder Zertifikatsmaterial",
    ".key": "privater Schluessel",
    ".p12": "PKCS#12-Container",
    ".pfx": "PKCS#12-Container",
    ".cer": "Zertifikat",
    ".crt": "Zertifikat",
    ".der": "DER-kodiertes Schluessel- oder Zertifikatsmaterial",
    ".jks": "Java-Keystore",
    ".keystore": "Keystore",
}

# Regel 2: PEM-Bloecke. Die Marker sind zusammengesetzt, sonst stolpert
# dieser Scanner ueber seinen eigenen Quelltext.
_DASHES = "-" * 5
_PEM_BEGIN = _DASHES + "BEGIN "
PEM_RE = re.compile(
    _PEM_BEGIN + r"(?:[A-Z0-9 ]+ )?PRIVATE KEY" + _DASHES
    + "|" + _PEM_BEGIN + "CERTIFICATE" + _DASHES
)

# Regel 3: Keys, deren Wert ein Geheimnis ist.
SECRET_KEY = (
    r"[A-Za-z0-9_.-]*"
    r"(?:password|passwort|passphrase|sharedsecret|secret|psk|apikey|api_key)"
    r"[A-Za-z0-9_.-]*"
)
# JSON, Markdown, HTML: "Key": "Wert"
QUOTED_RE = re.compile(
    r"[\"'](?P<key>" + SECRET_KEY + r")[\"']\s*:\s*[\"'](?P<value>[^\"']*)[\"']",
    re.IGNORECASE,
)
# YAML: Key: Wert, auch ohne Anfuehrungszeichen.
YAML_RE = re.compile(
    r"^\s*[\"']?(?P<key>" + SECRET_KEY + r")[\"']?\s*:\s*"
    r"(?P<value>[^\s#].*?)\s*$",
    re.IGNORECASE,
)
TAG_RE = re.compile(r"<[^>]+>")

# Die erfundenen Werte, die im Repo stehen duerfen. Jeder andere Wert
# hinter einem Passwort-Key ist ein Fund.
PLACEHOLDER_VALUES = {
    "",
    "...",
    "supersecret123",   # assets/examples/wifi_guest.json, README, evals.json
    "schoolpass2026",   # assets/examples/classroom_ipad.json, evals.json
}

# Regel 3 gilt fuer Dateien, in denen Specs, Profile oder Doku stehen.
SCANNED_SUFFIXES = {
    ".json", ".yaml", ".yml", ".md", ".html", ".htm", ".txt",
    ".py", ".sh", ".plist", ".xml", ".cfg", ".ini", ".toml",
}


def git_files(root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"git ls-files fehlgeschlagen: {proc.stderr.strip()}")
    return [name for name in proc.stdout.split("\0") if name]


def read_text(path: Path) -> str | None:
    """Textinhalt, oder None wenn die Datei binaer oder unlesbar ist."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def normalize(line: str, suffix: str) -> str:
    """HTML-Tags fallen weg, damit ein in <span> zerlegter JSON-Block
    genauso gelesen wird wie die Datei, die er zeigt."""
    if suffix in (".html", ".htm"):
        return TAG_RE.sub("", line)
    return line


def scan_file(root: Path, name: str) -> list[str]:
    findings: list[str] = []
    path = root / name
    suffix = path.suffix.lower()

    reason = BLOCKED_SUFFIXES.get(suffix)
    if reason:
        findings.append(f"{name}: verfolgte Datei vom Typ {suffix} ({reason})")
        return findings

    text = read_text(path)
    if text is None:
        return findings

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = normalize(raw_line, suffix)
        if PEM_RE.search(line):
            findings.append(
                f"{name}:{lineno}: PEM-Block im Text "
                f"({PEM_RE.search(line).group(0)})"
            )
        if suffix not in SCANNED_SUFFIXES:
            continue
        matches = list(QUOTED_RE.finditer(line))
        if not matches and suffix in (".yaml", ".yml"):
            m = YAML_RE.match(line)
            matches = [m] if m else []
        for m in matches:
            value = m.group("value").strip().strip("\"'")
            if value in PLACEHOLDER_VALUES:
                continue
            findings.append(
                f"{name}:{lineno}: Wert hinter '{m.group('key')}' ist kein "
                f"dokumentierter Platzhalter ({value!r})"
            )
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--root", type=Path, default=None,
                    help="Repo-Wurzel (default: Elternverzeichnis von tools/)")
    args = ap.parse_args()

    root = (args.root or Path(__file__).resolve().parent.parent).resolve()
    if not (root / ".git").exists():
        print(f"Kein Git-Repo unter {root}", file=sys.stderr)
        return 2

    files = git_files(root)
    findings: list[str] = []
    for name in files:
        findings.extend(scan_file(root, name))

    if findings:
        print(f"Secret-Scan: {len(findings)} Fund(e) in "
              f"{len(files)} verfolgten Dateien", file=sys.stderr)
        for f in findings:
            print(f"  - {f}", file=sys.stderr)
        print("\nEcht? Wert entfernen und den Schluessel rotieren. "
              "Platzhalter? In PLACEHOLDER_VALUES in tools/scan_secrets.py "
              "eintragen.", file=sys.stderr)
        return 1

    print(f"Secret-Scan sauber: {len(files)} verfolgte Dateien geprueft.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
