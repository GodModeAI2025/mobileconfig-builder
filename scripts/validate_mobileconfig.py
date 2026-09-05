#!/usr/bin/env python3
"""
validate_mobileconfig.py — Prüft eine bereits vorhandene .mobileconfig gegen
Apples Schema.

Bis hierher konnte dieses Werkzeug nur prüfen, was es selbst gebaut hat. Ein
Profil aus Jamf, Intune, Kandji oder aus dem Profile Manager liess sich nicht
vorlegen. Dieses Skript nimmt die fertige Datei entgegen, packt sie aus,
zerlegt `PayloadContent` und schickt jeden Eintrag durch dieselbe
Validierung, die `build_mobileconfig.py` beim Bauen benutzt. Die Profil-Ebene
geht zusätzlich gegen `TopLevel.yaml`.

Drei Eingabeformen werden erkannt:

    XML-Plist        die übliche, mit `<?xml` beginnende Datei
    Binär-Plist      beginnt mit `bplist00`
    PKCS#7 (DER)     eine signierte Datei, beginnt mit 0x30

Die signierte Form wird mit `openssl smime -verify -noverify` ausgepackt.
`-noverify` schaltet die Prüfung der Zertifikatskette ab, nicht die der
Signatur: eine nachträglich veränderte Datei fliegt hier auf, ein gültig
signiertes Profil eines Ausstellers, dem niemand vertraut, geht durch. Wem
das Profil gehört, sagt dieses Werkzeug also nicht.

Zwei Stufen, und die Regel dahinter ist eine einzige:

    FEHLER    Das Schema wird verletzt. Pflichtkey fehlt, Typ passt nicht,
              Wert liegt ausserhalb von rangelist oder range, PayloadContent
              fehlt oder ist keine Liste.
    WARNUNG   Das Schema sagt dazu nichts, oder es gibt keins. Unbekannter
              Key, PayloadType ohne Schema, Verstoss gegen eine
              format-Regex, doppelt vergebene PayloadUUID.

Warum die Trennung: ein echtes Profil aus einem MDM trägt regelmässig Keys,
die Apples YAML nicht beschreibt, und Payloads von Drittanbietern, für die
Apple gar kein Schema hat. Wären das Fehler, wäre das Werkzeug auf genau den
Dateien unbrauchbar, für die es gebaut ist. Mit `--strict` werden aus allen
Warnungen Fehler; das ist der Modus für Profile, die aus diesem Repo kommen.

Exit-Codes:

    0   keine Befunde
    1   nur Warnungen
    2   mindestens ein Fehler, oder die Datei liess sich nicht lesen

Usage:
    python3 validate_mobileconfig.py profil.mobileconfig
    python3 validate_mobileconfig.py *.mobileconfig --strict
    python3 validate_mobileconfig.py profil.mobileconfig --format json
    python3 validate_mobileconfig.py profil.mobileconfig --manifests
"""
from __future__ import annotations
import argparse
import json
import plistlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_mobileconfig import (  # noqa: E402
    get_schema,
    load_all_schemas,
    validate_payload,
    validate_top_level,
)
from fetch_schema import MANIFESTS_REF  # noqa: E402

FEHLER = "Fehler"
WARNUNG = "Warnung"

# Wie lange `openssl smime -verify` höchstens brauchen darf. Das Auspacken
# rechnet nichts Aufwendiges, ein Aufruf, der hier stehenbleibt, ist kaputt.
OPENSSL_TIMEOUT = 60


class PruefFehler(Exception):
    """Abbruchgrund für eine einzelne Datei, als Meldung statt Traceback."""


def _oeffne_signiert(pfad: Path) -> bytes:
    """Packt eine PKCS#7-signierte Datei aus.

    `-noverify` bezieht sich auf die Zertifikatskette. Die Signatur selbst
    prüft openssl weiter, deshalb ist ein verändertes Profil hier ein Fehler
    und kein stiller Durchlauf. Ohne die Option bräuchte der Aufruf den
    Aussteller im Vertrauensspeicher, und den hat auf einem beliebigen
    Rechner niemand.
    """
    cmd = ["openssl", "smime", "-verify", "-inform", "der", "-noverify",
           "-in", str(pfad)]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=OPENSSL_TIMEOUT)
    except OSError as fehler:
        raise PruefFehler(
            f"openssl liess sich nicht starten: {fehler}.\n"
            f"Die Datei fängt mit 0x30 an, ist also PKCS#7 im DER-Format. "
            f"Zum Auspacken braucht dieses Skript openssl im PATH.")
    except subprocess.TimeoutExpired:
        raise PruefFehler(
            f"openssl hat nach {OPENSSL_TIMEOUT} Sekunden nichts geliefert.")
    if proc.returncode != 0:
        meldung = proc.stderr.decode("utf-8", "replace").strip()
        raise PruefFehler(
            "Die Datei fängt wie ein PKCS#7-Container an, liess sich aber "
            "nicht auspacken. Entweder ist die Signatur nicht gültig oder "
            "es ist kein CMS-Container."
            + (f"\n{meldung}" if meldung else ""))
    if not proc.stdout:
        raise PruefFehler(
            "openssl hat die Signatur akzeptiert, aber keinen Inhalt "
            "geliefert. In dem Container steckt kein Profil.")
    return proc.stdout


def lade_profil(pfad: Path) -> tuple[dict, str]:
    """Gibt (Profil, Form) zurück. Form ist eine Angabe für den Bericht."""
    try:
        roh = pfad.read_bytes()
    except OSError as fehler:
        raise PruefFehler(f"{fehler.strerror}")
    if not roh:
        raise PruefFehler("Die Datei ist leer.")

    if roh[:1] == b"\x30":
        form = "PKCS#7-signiert"
        roh = _oeffne_signiert(pfad)
    elif roh[:8] == b"bplist00":
        form = "Binär-Plist"
    else:
        form = "XML-Plist"

    try:
        profil = plistlib.loads(roh)
    except Exception as fehler:
        raise PruefFehler(
            f"Der Inhalt ist keine lesbare Property-List ({fehler}).")
    if not isinstance(profil, dict):
        raise PruefFehler(
            f"Die oberste Ebene ist {type(profil).__name__}, erwartet ist "
            f"ein Dictionary.")
    return profil, form


def _differenz(streng: list[str], lax: list[str]) -> list[str]:
    """Die Befunde, die nur der strenge Durchlauf gefunden hat.

    Beide Durchläufe benutzen dieselbe Prüfung, der strenge zusätzlich mit
    `strict=True`. Was in beiden steht, verletzt das Schema und ist ein
    Fehler; was nur im strengen steht, ist eine Warnung. Gezählt wird, damit
    zwei gleichlautende Befunde nicht zu einem verschmelzen.
    """
    rest = list(lax)
    nur_streng = []
    for eintrag in streng:
        if eintrag in rest:
            rest.remove(eintrag)
        else:
            nur_streng.append(eintrag)
    return nur_streng


def _befund(stufe: str, pfad: str, text: str) -> dict:
    return {"stufe": stufe, "pfad": pfad, "text": text}


def _ohne_top_level(text: str) -> str:
    """Nimmt den Pfad aus dem Meldungstext, wenn er dort schon steht.

    `validate_top_level` schreibt `top-level: unknown key ...` und
    `top-level.PayloadScope: value ...`. Der Pfad steht im Bericht ohnehin in
    einer eigenen Spalte, zweimal hintereinander liest sich schlechter als
    einmal.
    """
    for praefix in ("top-level: ", "top-level."):
        if text.startswith(praefix):
            return text[len(praefix):]
    return text


def _payload_pfad(index: int) -> str:
    """Der Pfad, unter dem ein Befund gemeldet wird.

    Der PayloadType steht bewusst nicht darin: die Meldungen aus
    `validate_payload` fangen bereits damit an, und zweimal derselbe Name
    hintereinander liest sich schlechter als einmal. Wo dieses Skript einen
    eigenen Befund erzeugt, nennt es den Typ im Text.
    """
    return f"PayloadContent[{index}]"


def _pruefe_uuids(profil: dict, payloads: list) -> list[dict]:
    """Doppelt vergebene PayloadUUIDs.

    Apple verlangt je Payload eine eigene UUID, beschreibt das aber nicht im
    Schema: `PayloadUUID` ist dort schlicht ein String. Deshalb steht der
    Befund als Warnung da und nicht als Fehler. Gefunden wird er trotzdem,
    weil ein Profil mit zwei gleichen UUIDs auf dem Gerät unzuverlässig
    installiert.
    """
    gesehen: dict = {}
    befunde = []
    oben = profil.get("PayloadUUID")
    if isinstance(oben, str) and oben:
        gesehen[oben] = "top-level"
    for i, p in enumerate(payloads):
        if not isinstance(p, dict):
            continue
        uuid_wert = p.get("PayloadUUID")
        if not isinstance(uuid_wert, str) or not uuid_wert:
            continue
        pfad = _payload_pfad(i)
        if uuid_wert in gesehen:
            befunde.append(_befund(
                WARNUNG, pfad,
                f"PayloadUUID {uuid_wert} ist schon bei {gesehen[uuid_wert]} "
                f"vergeben"))
        else:
            gesehen[uuid_wert] = pfad
    return befunde


def pruefe_profil(profil: dict, branch: str = "release",
                  manifeste: dict | None = None) -> list[dict]:
    """Alle Befunde zu einem geladenen Profil, jeweils mit Stufe und Pfad.

    Die Einstufung passiert hier und nicht erst in der Ausgabe: `--strict`
    verschiebt nur die Grenze, nicht die Befunde.
    """
    befunde: list[dict] = []

    lax = validate_top_level(profil, branch, strict=False)
    streng = validate_top_level(profil, branch, strict=True)
    for text in lax:
        befunde.append(_befund(FEHLER, "top-level",
                               _ohne_top_level(text)))
    for text in _differenz(streng, lax):
        befunde.append(_befund(WARNUNG, "top-level",
                               _ohne_top_level(text)))

    payloads = profil.get("PayloadContent")
    if payloads is None:
        # validate_top_level meldet den fehlenden Pflichtkey bereits. Hier
        # gibt es nur nichts mehr zu zerlegen.
        return befunde
    if not isinstance(payloads, list):
        befunde.append(_befund(
            FEHLER, "PayloadContent",
            f"erwartet ist eine Liste von Payloads, gefunden "
            f"{type(payloads).__name__}"))
        return befunde

    for i, payload in enumerate(payloads):
        if not isinstance(payload, dict):
            befunde.append(_befund(
                FEHLER, f"PayloadContent[{i}]",
                f"kein Dictionary, sondern {type(payload).__name__}"))
            continue
        pfad = _payload_pfad(i)
        ptype = payload.get("PayloadType")
        if not isinstance(ptype, str) or not ptype:
            befunde.append(_befund(FEHLER, pfad, "PayloadType fehlt"))
            continue
        if get_schema(ptype, branch, manifeste=manifeste) is None:
            hinweis = ""
            if manifeste is None and not ptype.startswith("com.apple."):
                hinweis = (", Apples Schema beschreibt nur Apple-Domains; "
                           "fuer Drittanbieter --manifests")
            befunde.append(_befund(
                WARNUNG, pfad,
                f"kein Schema fuer '{ptype}' im Branch '{branch}', der "
                f"Payload wurde nicht geprueft{hinweis}"))
            continue
        lax = validate_payload(payload, branch, strict=False,
                               manifeste=manifeste)
        streng = validate_payload(payload, branch, strict=True,
                                  manifeste=manifeste)
        for text in lax:
            befunde.append(_befund(FEHLER, pfad, text))
        for text in _differenz(streng, lax):
            befunde.append(_befund(WARNUNG, pfad, text))

    befunde += _pruefe_uuids(profil, payloads)
    return befunde


def pruefe_datei(pfad: Path, branch: str, manifeste: dict | None,
                 offline: bool) -> dict:
    """Ein Ergebnis-Dict je Datei, auch im Fehlerfall."""
    ergebnis = {
        "datei": str(pfad),
        "form": None,
        "payloads": 0,
        "befunde": [],
    }
    try:
        profil, form = lade_profil(pfad)
    except PruefFehler as fehler:
        ergebnis["befunde"].append(_befund(FEHLER, "datei", str(fehler)))
        return ergebnis
    ergebnis["form"] = form
    inhalt = profil.get("PayloadContent")
    ergebnis["payloads"] = len(inhalt) if isinstance(inhalt, list) else 0
    ergebnis["befunde"] = pruefe_profil(profil, branch=branch,
                                        manifeste=manifeste)
    return ergebnis


def _zaehle(ergebnisse: list[dict], strict: bool) -> tuple[int, int]:
    """(Fehler, Warnungen) über alle Dateien, unter Beachtung von --strict."""
    fehler = warnungen = 0
    for e in ergebnisse:
        for b in e["befunde"]:
            if b["stufe"] == FEHLER or strict:
                fehler += 1
            else:
                warnungen += 1
    return fehler, warnungen


def _bericht_text(ergebnisse: list[dict], strict: bool) -> str:
    zeilen = []
    for e in ergebnisse:
        kopf = e["datei"]
        if e["form"]:
            kopf += f": {e['form']}, {e['payloads']} Payload(s)"
        zeilen.append(kopf)
        if not e["befunde"]:
            zeilen.append("  keine Befunde")
            continue
        for b in e["befunde"]:
            stufe = FEHLER if strict else b["stufe"]
            marke = "FEHLER " if stufe == FEHLER else "WARNUNG"
            zeilen.append(f"  {marke}  {b['pfad']}: {b['text']}")
    fehler, warnungen = _zaehle(ergebnisse, strict)
    zeilen.append("")
    zeilen.append(f"{len(ergebnisse)} Datei(en), {fehler} Fehler, "
                  f"{warnungen} Warnung(en)")
    if warnungen and not strict:
        zeilen.append("Warnungen sind Stellen, zu denen Apples Schema nichts "
                      "sagt. Mit --strict werden daraus Fehler.")
    return "\n".join(zeilen)


def _bericht_json(ergebnisse: list[dict], strict: bool, code: int) -> str:
    fehler, warnungen = _zaehle(ergebnisse, strict)
    daten = {
        "strict": strict,
        "dateien": [
            {
                "datei": e["datei"],
                "form": e["form"],
                "payloads": e["payloads"],
                "befunde": [
                    {
                        "stufe": (FEHLER if strict else b["stufe"]).lower(),
                        "pfad": b["pfad"],
                        "text": b["text"],
                    }
                    for b in e["befunde"]
                ],
            }
            for e in ergebnisse
        ],
        "fehler": fehler,
        "warnungen": warnungen,
        "exit_code": code,
    }
    return json.dumps(daten, indent=2, ensure_ascii=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("profil", type=Path, nargs="+",
                    help="Eine oder mehrere .mobileconfig-Dateien")
    ap.add_argument("--branch", default="release",
                    help="Schema-Branch von apple/device-management")
    ap.add_argument("--offline", action="store_true",
                    help="Nur den Schema-Cache benutzen, kein Netz-Zugriff")
    ap.add_argument("--strict", action="store_true",
                    help="Warnungen als Fehler werten (unbekannte Keys, "
                         "PayloadTypes ohne Schema, format-Regex, doppelte "
                         "PayloadUUIDs)")
    ap.add_argument("--manifests", action="store_true",
                    help="ProfileManifests als zweite Schema-Quelle zulassen, "
                         "fuer PayloadTypes, die Apple nicht kennt")
    ap.add_argument("--manifests-ref", default=MANIFESTS_REF,
                    help=f"Branch, Tag oder Commit von ProfileManifests "
                         f"(default: {MANIFESTS_REF})")
    ap.add_argument("--format", choices=("text", "json"), default="text",
                    help="Ausgabeformat (default: text)")
    args = ap.parse_args(argv)

    manifeste = None
    if args.manifests:
        manifeste = {"ref": args.manifests_ref, "offline": args.offline}

    # Einmal vorab laden, mit dem offline-Flag. `get_schema` reicht es nicht
    # durch und wuerde sonst bei leerem Cache ans Netz gehen.
    try:
        load_all_schemas(args.branch, offline=args.offline)
    except SystemExit as fehler:
        print(f"FEHLER: {fehler}", file=sys.stderr)
        return 2

    ergebnisse = [pruefe_datei(p, args.branch, manifeste, args.offline)
                  for p in args.profil]
    fehler, warnungen = _zaehle(ergebnisse, args.strict)
    code = 2 if fehler else (1 if warnungen else 0)

    if args.format == "json":
        print(_bericht_json(ergebnisse, args.strict, code))
    else:
        print(_bericht_text(ergebnisse, args.strict))
    return code


if __name__ == "__main__":
    sys.exit(main())
