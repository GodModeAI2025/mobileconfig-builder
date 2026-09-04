#!/usr/bin/env python3
"""Packt das Release-Artefakt von mobileconfig-builder.

Aufruf:

    python3 scripts/package_release.py dist/mobileconfig-builder.zip

Das Skript laeuft ohne Netz und ohne GitHub. Es fragt `git ls-files` nach den
versionierten Dateien, nimmt davon die Teile, die zum ausgelieferten Skill
gehoeren, und schreibt sie in ein ZIP mit dem Wurzelverzeichnis
`mobileconfig-builder/`.

Zwei Laeufe hintereinander ergeben dieselbe Datei, Byte fuer Byte: die
Eintraege sind nach Namen sortiert, jeder Eintrag traegt einen festen
Zeitstempel und einen aus dem Git-Modus abgeleiteten Rechte-Satz, und im
Archiv steht kein Bauzeitpunkt.

Die Auswahl ueber `git ls-files` erbt .gitignore. Erzeugte Profile
(*.mobileconfig), Signier-Material (*.pem, *.key, *.p12, *.pfx, *.cer, *.crt)
und __pycache__ sind dort ausgeschlossen und koennen deshalb nicht ins Archiv
rutschen, auch wenn sie im Arbeitsverzeichnis liegen. Zusaetzlich prueft
`_pruefe_auswahl` die Liste noch einmal gegen dieselben Muster, damit eine
geloeschte Zeile in .gitignore auffaellt.
"""

import argparse
import hashlib
import os
import re
import subprocess
import sys
import zipfile

# Wurzelverzeichnis im Archiv. Der Name entspricht dem `name` im Frontmatter
# von SKILL.md, damit `unzip -d ~/.claude/skills/` direkt am richtigen Ort
# landet.
ARCHIV_WURZEL = "mobileconfig-builder"

# Was ausgeliefert wird. Pfade relativ zum Repo-Root, an `git ls-files`
# uebergeben.
QUELLEN = [
    "SKILL.md",
    "LICENSE",
    "NOTICE",
    "VERSION",
    "assets",
    "evals",
    "references",
    "scripts",
]

# Was nicht ausgeliefert wird, obwohl es unter einem Pfad aus QUELLEN liegt.
# Dieses Skript baut das Release, im installierten Skill hat es nichts zu tun.
AUSGENOMMEN = {
    "scripts/package_release.py",
}

# Muster, die im Archiv nichts verloren haben. Repo-Innereien, die
# Landingpage, erzeugte Profile, Schluesselmaterial, Python-Cache.
VERBOTEN = re.compile(
    r"(^|/)\.git(/|$)"
    r"|(^|/)\.github(/|$)"
    r"|(^|/)__pycache__(/|$)"
    r"|(^|/)index\.html$"
    r"|(^|/)course\.html$"
    r"|\.mobileconfig$"
    r"|\.(pem|key|p12|pfx|cer|crt)$"
    r"|\.py[co]$"
)

# Ohne diese Dateien ist das Archiv kein brauchbares Release.
PFLICHT_DATEIEN = [
    "SKILL.md",
    "VERSION",
    "LICENSE",
    "NOTICE",
    "scripts/build_mobileconfig.py",
    "scripts/fetch_schema.py",
    "scripts/inspect_payload.py",
    "evals/run_tests.py",
    "evals/evals.json",
]

# Verzeichnisse, die mit mindestens einer Datei vertreten sein muessen.
PFLICHT_VERZEICHNISSE = ["assets/", "evals/", "references/", "scripts/"]

# Fester Zeitstempel fuer jeden Eintrag: 1980-01-01 00:00:00, der frueheste
# Wert, den das ZIP-Format kennt.
ZEITSTEMPEL = (1980, 1, 1, 0, 0, 0)


class PackFehler(Exception):
    """Abbruchgrund, der als Meldung statt als Traceback rausgeht."""


def repo_root():
    """Repo-Root aus dem Ort dieses Skripts, unabhaengig vom Arbeitsverzeichnis."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def lies_version(root):
    pfad = os.path.join(root, "VERSION")
    if not os.path.isfile(pfad):
        raise PackFehler(
            "VERSION fehlt. Die Version steht in dieser einen Datei im "
            "Repo-Root."
        )
    with open(pfad, "r", encoding="utf-8") as fh:
        version = fh.read().strip()
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        raise PackFehler(
            "VERSION enthaelt %r, erwartet ist eine Zeile der Form 1.2.3."
            % version
        )
    return version


def git_dateien(root):
    """Versionierte Dateien unter QUELLEN, mit ihrem Git-Modus."""
    try:
        roh = subprocess.run(
            ["git", "ls-files", "-s", "-z", "--"] + QUELLEN,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except FileNotFoundError:
        raise PackFehler("git nicht gefunden. Das Skript braucht git im PATH.")
    except subprocess.CalledProcessError as exc:
        raise PackFehler(
            "git ls-files ist fehlgeschlagen: %s"
            % exc.stderr.decode("utf-8", "replace").strip()
        )

    dateien = []
    for eintrag in roh.stdout.decode("utf-8").split("\0"):
        if not eintrag:
            continue
        # Format: "<modus> <sha> <stage>\t<pfad>"
        kopf, _, pfad = eintrag.partition("\t")
        modus = kopf.split()[0]
        dateien.append((pfad, modus))
    return dateien


def _pruefe_auswahl(pfade):
    treffer = sorted(p for p in pfade if VERBOTEN.search(p))
    if treffer:
        raise PackFehler(
            "Diese Pfade gehoeren nicht ins Archiv:\n  " + "\n  ".join(treffer)
        )

    fehlend = [p for p in PFLICHT_DATEIEN if p not in pfade]
    if fehlend:
        raise PackFehler(
            "Im Archiv fehlen Pflichtdateien:\n  "
            + "\n  ".join(fehlend)
            + "\n\nSind sie schon versioniert? git ls-files sieht nur, was "
            "mit git add aufgenommen wurde."
        )

    leer = [
        d
        for d in PFLICHT_VERZEICHNISSE
        if not any(p.startswith(d) for p in pfade)
    ]
    if leer:
        raise PackFehler(
            "Diese Verzeichnisse waeren leer im Archiv: " + ", ".join(leer)
        )


def baue(ziel, ausfuehrlich=True):
    root = repo_root()
    version = lies_version(root)

    eintraege = [
        (pfad, modus)
        for pfad, modus in git_dateien(root)
        if pfad not in AUSGENOMMEN
    ]
    eintraege.sort(key=lambda paar: paar[0])
    pfade = {pfad for pfad, _ in eintraege}
    _pruefe_auswahl(pfade)

    ziel = os.path.abspath(ziel)
    ordner = os.path.dirname(ziel)
    if ordner:
        os.makedirs(ordner, exist_ok=True)

    with zipfile.ZipFile(
        ziel, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as zf:
        for pfad, modus in eintraege:
            quelle = os.path.join(root, pfad)
            if not os.path.isfile(quelle):
                raise PackFehler(
                    "%s ist versioniert, liegt aber nicht im "
                    "Arbeitsverzeichnis." % pfad
                )
            with open(quelle, "rb") as fh:
                inhalt = fh.read()

            rechte = 0o755 if modus == "100755" else 0o644
            info = zipfile.ZipInfo(
                filename="%s/%s" % (ARCHIV_WURZEL, pfad),
                date_time=ZEITSTEMPEL,
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3  # Unix, unabhaengig vom Bau-Rechner
            info.external_attr = (0o100000 | rechte) << 16
            zf.writestr(info, inhalt)

    with open(ziel, "rb") as fh:
        pruefsumme = hashlib.sha256(fh.read()).hexdigest()

    if ausfuehrlich:
        print("Version:   %s" % version)
        print("Artefakt:  %s" % ziel)
        print("Dateien:   %d" % len(eintraege))
        print("Groesse:   %d Bytes" % os.path.getsize(ziel))
        print("SHA-256:   %s" % pruefsumme)
    return ziel


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Baut das Release-Artefakt aus den versionierten Dateien. "
            "Braucht kein Netz."
        )
    )
    parser.add_argument(
        "ausgabe",
        metavar="AUSGABEPFAD",
        help="Pfad der zu schreibenden ZIP-Datei, etwa "
        "dist/mobileconfig-builder.zip",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Nur im Fehlerfall etwas ausgeben",
    )
    args = parser.parse_args(argv)

    try:
        baue(args.ausgabe, ausfuehrlich=not args.quiet)
    except PackFehler as fehler:
        print("FEHLER: %s" % fehler, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
