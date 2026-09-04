#!/usr/bin/env python3
"""
build_mobileconfig.py — Erzeugt eine .mobileconfig (Apple Configuration Profile)
auf Basis eines Schema-validierten Payload-Inputs.

Workflow:
  1. Liest eine Spec-Datei (JSON oder YAML) mit:
        meta:           Top-Level-Felder (PayloadDisplayName, Identifier, …)
        payloads:       Liste von Payload-Dicts, jeweils mit
                          PayloadType: com.apple.…
                          + payload-spezifische Keys
  2. Validiert die Top-Level-Felder gegen TopLevel.yaml und jede Payload
     gegen ihr Schema (required keys, types, ranges).
  3. Ergänzt fehlende Pflichtfelder (PayloadIdentifier, PayloadUUID, PayloadVersion)
     deterministisch.
  4. Schreibt eine binäre+lesbare XML-Plist mit Endung .mobileconfig.
  5. (Optional) Signiert das Profil, entweder mit PEM-Dateien über OpenSSL
     oder über eine Identität im macOS-Schlüsselbund.

Usage:
    python3 build_mobileconfig.py spec.json -o profile.mobileconfig
    python3 build_mobileconfig.py spec.yaml -o profile.mobileconfig --validate-strict
    python3 build_mobileconfig.py spec.json -o p.mobileconfig --sign-cert cert.pem --sign-key key.pem
    python3 build_mobileconfig.py spec.json -o p.mobileconfig --sign-identity "Profil-Signer"
"""
from __future__ import annotations
import argparse
import json
import os
import plistlib
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_schema import (  # noqa: E402
    MANIFESTS_REF,
    ensure_yaml,
    load_manifest_schema,
    load_schema_map,
)

ALLOWED_TYPES = {
    "<string>": (str,),
    "<integer>": (int,),
    "<real>": (float, int),
    "<boolean>": (bool,),
    "<data>": (bytes, bytearray),
    "<array>": (list,),
    "<dictionary>": (dict,),
    "<any>": object,
    "<date>": (datetime, str),
}


class SchemaError(Exception):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Schema lookup
# ─────────────────────────────────────────────────────────────────────────────
_SCHEMA_CACHE: dict[str, dict] = {}


def load_all_schemas(branch: str, refresh: bool = False,
                     offline: bool = False) -> dict[str, dict]:
    """payloadtype → Schema-Dokument.

    Die Auflösung mehrfach vergebener payloadtypes liegt in
    fetch_schema.load_schema_map, damit inspect_payload.py und dieses
    Skript garantiert dasselbe Schema sehen.
    """
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE and not refresh:
        return _SCHEMA_CACHE
    _SCHEMA_CACHE = load_schema_map(branch, refresh=refresh, offline=offline)
    return _SCHEMA_CACHE


def get_schema(payloadtype: str, branch: str,
               manifeste: dict | None = None) -> dict | None:
    """Schema zu einem PayloadType, Apple zuerst.

    `manifeste` ist entweder None (nur Apple) oder ein Dict mit den Optionen
    fuer ProfileManifests. Apple gewinnt immer: die zweite Quelle wird nur
    gefragt, wenn Apple den PayloadType ueberhaupt nicht kennt. Zusammengefuehrt
    wird nichts. Ein PayloadType, den beide beschreiben, wird ausschliesslich
    gegen Apple geprueft, damit nie unklar ist, welche Regel gegolten hat.
    """
    schema = load_all_schemas(branch).get(payloadtype)
    if schema is not None or manifeste is None:
        return schema
    return load_manifest_schema(payloadtype, **manifeste)


# ─────────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────────
def _check_value(value, key_def: dict, path: str, errors: list[str],
                 strict: bool):
    expected = key_def.get("type", "<any>")
    accepted = ALLOWED_TYPES.get(expected)

    # bool is subclass of int — special-case so int doesn't accept True/False
    if expected == "<integer>" and isinstance(value, bool):
        errors.append(f"{path}: expected <integer>, got <boolean>")
        return
    if expected == "<boolean>" and not isinstance(value, bool):
        errors.append(f"{path}: expected <boolean>, got {type(value).__name__}")
        return
    if accepted is object:
        return
    if accepted and not isinstance(value, accepted):
        errors.append(
            f"{path}: expected {expected}, got {type(value).__name__}"
        )
        return

    # rangelist
    if "rangelist" in key_def and value not in key_def["rangelist"]:
        errors.append(
            f"{path}: value {value!r} not in allowed list "
            f"{key_def['rangelist']!r}"
        )
    # range
    if "range" in key_def and isinstance(value, (int, float)):
        r = key_def["range"]
        if "min" in r and value < r["min"]:
            errors.append(f"{path}: {value} < min {r['min']}")
        if "max" in r and value > r["max"]:
            errors.append(f"{path}: {value} > max {r['max']}")
    # format (regex)
    if strict and "format" in key_def and isinstance(value, str):
        try:
            if not re.fullmatch(key_def["format"], value):
                errors.append(
                    f"{path}: value {value!r} does not match regex "
                    f"{key_def['format']!r}"
                )
        except re.error:
            pass  # invalid regex in schema — skip
    # nested
    if expected == "<dictionary>" and "subkeys" in key_def \
            and isinstance(value, dict):
        _check_keys(value, key_def["subkeys"], path, errors, strict)
    if expected == "<array>" and "subkeys" in key_def \
            and isinstance(value, list):
        # subkeys for array typically describes the item shape (single subkey)
        if key_def["subkeys"]:
            item_def = key_def["subkeys"][0]
            for i, item in enumerate(value):
                _check_value(item, item_def, f"{path}[{i}]", errors, strict)


def _check_keys(values: dict, defs: list[dict], path: str,
                errors: list[str], strict: bool):
    """Validate dict `values` against list of key-definitions `defs`."""
    by_name = {d["key"]: d for d in defs if isinstance(d, dict)
               and d.get("key") and d.get("key") != "ANY"}
    has_any = any(d.get("key") == "ANY" for d in defs if isinstance(d, dict))

    # required check
    for kdef in defs:
        if not isinstance(kdef, dict):
            continue
        kname = kdef.get("key")
        if kname == "ANY":
            continue
        if kdef.get("presence") == "required" and kname not in values:
            errors.append(f"{path}: required key '{kname}' missing")

    # type/value check + unknown-key check
    for vname, v in values.items():
        if vname in by_name:
            sub_path = f"{path}.{vname}" if path else vname
            _check_value(v, by_name[vname], sub_path, errors, strict)
        elif not has_any and strict:
            errors.append(
                f"{path}: unknown key '{vname}' (not defined in schema)"
            )


def get_common_keys(branch: str) -> list[dict]:
    """Returns the keys from CommonPayloadKeys.yaml — these are inherited
    by every payload but defined separately in the Apple schema."""
    schemas = load_all_schemas(branch)
    # CommonPayloadKeys.yaml has payloadtype 'CommonPayloadKeys'
    common = schemas.get("CommonPayloadKeys")
    if not common:
        return []
    return common.get("payloadkeys", []) or []


def validate_payload(payload: dict, branch: str,
                     strict: bool = False,
                     manifeste: dict | None = None) -> list[str]:
    """Returns list of error strings; empty means valid."""
    errors: list[str] = []
    ptype = payload.get("PayloadType")
    if not ptype:
        return ["payload: missing PayloadType"]
    schema = get_schema(ptype, branch, manifeste=manifeste)
    if schema is None:
        hinweis = ""
        if manifeste is None and not ptype.startswith("com.apple."):
            hinweis = (". Apples Schema beschreibt nur Apple-Domains, "
                       "fuer Drittanbieter --manifests versuchen")
        elif manifeste is not None and manifeste.get("offline"):
            hinweis = (". Mit --offline wird nur der Manifest-Cache gelesen, "
                       "und dort liegt diese Domain nicht. Einmal ohne "
                       "--offline laufen lassen")
        return [
            f"payload: unknown PayloadType '{ptype}' "
            f"(no schema in branch '{branch}'){hinweis}"
        ]
    # Combine payload-specific keys with the CommonPayloadKeys
    # so PayloadType/UUID/Identifier/etc. are not flagged as "unknown".
    keydefs = list(schema.get("payloadkeys", []) or [])
    keydefs += get_common_keys(branch)
    _check_keys(payload, keydefs, ptype, errors, strict)
    return errors


TOP_LEVEL_TYPE = "TopLevel"


def get_top_level_keys(branch: str) -> list[dict]:
    """Die Keys aus TopLevel.yaml, ohne deren `subkeys`.

    Die subkeys fallen bewusst weg: PayloadContent beschreibt im Schema nur
    einen Platzhalter namens PayloadContentItem, die einzelnen Payloads
    prüfen wir ohnehin separat gegen ihr eigenes Schema. ConsentText benutzt
    denselben Platzhalter-Trick für beliebige Sprachcodes und würde sonst
    jeden echten Sprachcode als unbekannten Key melden.
    """
    schema = get_schema(TOP_LEVEL_TYPE, branch)
    if not schema:
        return []
    return [{k: v for k, v in kdef.items() if k != "subkeys"}
            for kdef in schema.get("payloadkeys", []) or []
            if isinstance(kdef, dict)]


def validate_top_level(profile: dict, branch: str,
                       strict: bool = False) -> list[str]:
    """Prüft die Profil-Ebene gegen TopLevel.yaml.

    Ohne diese Prüfung passieren erfundene Keys wie 'TotallyMadeUpKey' die
    strikte Validierung folgenlos, obwohl das Projekt zusagt, gegen Apples
    Schema zu validieren.
    """
    keydefs = get_top_level_keys(branch)
    if not keydefs:
        return [f"top-level: kein Schema für {TOP_LEVEL_TYPE} im Cache "
                f"(branch '{branch}')"]
    errors: list[str] = []
    _check_keys(profile, keydefs, "top-level", errors, strict)
    return errors


# ─────────────────────────────────────────────────────────────────────────────
# Build profile
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_TOP_KEYS = {
    "PayloadType": "Configuration",
    "PayloadVersion": 1,
}


def deterministic_uuid(seed: str) -> str:
    """Stable UUID v5 from a string — useful so re-runs produce the same UUIDs."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, seed))


def build_profile(spec: dict, branch: str = "release",
                  strict: bool = False,
                  validate: bool = True,
                  offline: bool = False,
                  manifeste: dict | None = None) -> tuple[dict, list[str]]:
    # Pre-load schemas once with the offline flag if needed
    if validate:
        load_all_schemas(branch, offline=offline)
    meta = dict(spec.get("meta", {}))
    payloads_in = spec.get("payloads", [])
    if not payloads_in:
        raise SchemaError("spec.payloads is empty")

    # Top-level required by Apple TopLevel.yaml: PayloadIdentifier,
    # PayloadUUID, PayloadType, PayloadVersion, PayloadContent
    if "PayloadIdentifier" not in meta:
        raise SchemaError(
            "meta.PayloadIdentifier is required "
            "(reverse-DNS, e.g. 'com.example.myprofile')"
        )
    meta.setdefault("PayloadType", "Configuration")
    meta.setdefault("PayloadVersion", 1)
    if "PayloadUUID" not in meta:
        meta["PayloadUUID"] = deterministic_uuid(meta["PayloadIdentifier"])
    meta.setdefault(
        "PayloadDisplayName",
        meta.get("PayloadDisplayName", meta["PayloadIdentifier"]),
    )

    # Validate + finalize each inner payload
    all_errors: list[str] = []
    final_payloads: list[dict] = []
    for i, p in enumerate(payloads_in):
        if not isinstance(p, dict):
            all_errors.append(f"payloads[{i}] is not a dict")
            continue
        ptype = p.get("PayloadType")
        if not ptype:
            all_errors.append(f"payloads[{i}]: missing PayloadType")
            continue
        # Auto-fill the common keys (CommonPayloadKeys.yaml)
        p.setdefault("PayloadVersion", 1)
        p.setdefault(
            "PayloadIdentifier",
            f"{meta['PayloadIdentifier']}.{ptype}.{i}",
        )
        p.setdefault(
            "PayloadUUID",
            deterministic_uuid(f"{meta['PayloadIdentifier']}/{ptype}/{i}"),
        )
        p.setdefault("PayloadDisplayName", ptype)
        if validate:
            errs = validate_payload(p, branch, strict=strict,
                                    manifeste=manifeste)
            for e in errs:
                all_errors.append(f"payloads[{i}] {e}")
        final_payloads.append(p)

    profile = dict(meta)
    profile["PayloadContent"] = final_payloads
    if validate:
        all_errors = validate_top_level(profile, branch,
                                        strict=strict) + all_errors
    return profile, all_errors


# ─────────────────────────────────────────────────────────────────────────────
# Optional signing
# ─────────────────────────────────────────────────────────────────────────────
# Fester Pfad statt PATH-Suche. Was ein Profil signiert, soll nicht davon
# abhängen, was sonst noch `security` heißt.
SECURITY_TOOL = "/usr/bin/security"

# Warum nicht `-p codesigning`: `security find-identity` kennt zwölf Policies,
# und codesigning ist die falsche davon. Ein Signer-Zertifikat für
# Konfigurationsprofile trägt die EKU emailProtection (S/MIME) oder gar keine
# einschränkende EKU und fällt damit nicht unter die Code-Signing-Policy. Auf
# einem eingerichteten Firmen-Mac sind die Listen nachweislich verschieden:
#   -p codesigning  zeigt das Apple-Development-Zertifikat und ein selbst
#                   signiertes, nicht aber die Identität aus der internen CA
#   -p smime        zeigt genau die Identität aus der internen CA
#   -p basic        zeigt beide CA-Identitäten, nicht aber das selbst signierte
# Keine Liste enthält die andere, deshalb fragt list_identities beide
# brauchbaren Policies ab und vereinigt das Ergebnis.
IDENTITY_POLICIES = ("smime", "basic")

# Zeilenformat von `security find-identity`:
#   "  1) 9AC1…CE2C \"Profil-Signer\""
# Ohne -v haengt hinter dem Namen noch der Grund, warum die Identitaet nicht
# als gueltig zaehlt, etwa "(CSSMERR_TP_NOT_TRUSTED)". Deshalb kein Anker am
# Zeilenende.
_IDENTITY_ZEILE = re.compile(r'^\s*\d+\)\s+([0-9A-Fa-f]{40})\s+"(.*?)"')

_SHA1_HEX = re.compile(r"^[0-9A-Fa-f]{40}$")

# Auf einem Mac mit Endpoint-Security-Agent kann ein einzelner
# security-Aufruf unter Last Minuten brauchen. Das darf einen Bau nicht
# aufhängen, die Liste ist nur Beiwerk fuer die Fehlermeldung.
IDENTITY_TIMEOUT = 30

# Fuer die Frage "gibt es das Zertifikat ueberhaupt" zaehlt jede Policy und
# auch eine Identitaet, der noch niemand vertraut. Ein frisch importiertes
# Signaturzertifikat meldet `(CSSMERR_TP_NOT_TRUSTED)` und laesst sich
# trotzdem zum Signieren benutzen: Signieren braucht den Schluessel, nicht
# das Vertrauen.
IDENTITY_POLICIES_ALLE = ("smime", "basic", "codesigning")

_IDENTITY_CACHE: dict[tuple[str, bool], list] = {}


def _find_identity(keychain: Path | None, policies: tuple,
                   nur_gueltige: bool) -> list:
    gefunden: list = []
    gesehen: set = set()
    for policy in policies:
        cmd = [SECURITY_TOOL, "find-identity"]
        if nur_gueltige:
            cmd.append("-v")
        cmd += ["-p", policy]
        if keychain:
            cmd.append(str(keychain))
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=IDENTITY_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired):
            break
        for zeile in proc.stdout.splitlines():
            treffer = _IDENTITY_ZEILE.match(zeile)
            if not treffer:
                continue
            sha1 = treffer.group(1).upper()
            if sha1 in gesehen:
                continue
            gesehen.add(sha1)
            gefunden.append((sha1, treffer.group(2)))
    return gefunden


def list_identities(keychain: Path | None = None,
                    nur_gueltige: bool = True) -> list[tuple[str, str]]:
    """Signier-Identitäten aus dem Schlüsselbund als [(SHA-1, Name)].

    Mit `nur_gueltige` (Vorgabe) die Liste, die einem Menschen etwas sagt:
    was unter den Policies smime und basic gerade als gültig durchgeht. Ohne
    das die vollständige Liste über alle drei Policies, inklusive der
    Zertifikate, denen noch niemand vertraut. Die zweite Form beantwortet die
    Frage, ob `security cms` überhaupt etwas finden kann.

    Das Ergebnis wird gemerkt. Ein Lauf fragt sonst dasselbe mehrfach, einmal
    beim Auflösen der Angabe und einmal beim Berichten des Fehlschlags.
    """
    schluessel = (str(keychain or ""), nur_gueltige)
    if schluessel in _IDENTITY_CACHE:
        return _IDENTITY_CACHE[schluessel]
    policies = IDENTITY_POLICIES if nur_gueltige else IDENTITY_POLICIES_ALLE
    gefunden = _find_identity(keychain, policies, nur_gueltige)
    _IDENTITY_CACHE[schluessel] = gefunden
    return gefunden


def _identitaeten_text(identitaeten: list[tuple[str, str]]) -> str:
    policies = ", ".join(IDENTITY_POLICIES)
    if not identitaeten:
        return (f"Der Schlüsselbund meldet unter den Policies {policies} "
                f"keine gültige Identität.")
    zeilen = [f"Zur Auswahl stehen (Policies {policies}):"]
    for sha1, name in identitaeten:
        zeilen.append(f'  {sha1}  "{name}"')
    zeilen.append("Die Liste ist gefiltert: find-identity zeigt nur, was zur "
                  "Policy passt und gültig ist.")
    return "\n".join(zeilen)


def _mehrdeutig(name: str, alle: list[tuple[str, str]],
                gueltige: list[tuple[str, str]]) -> SchemaError:
    """Die Absage, wenn zwei Zertifikate denselben Namen tragen.

    `security cms -N` wählt allein über den Namen. Steht der Name zweimal im
    Schlüsselbund, entscheidet `security`, welches der beiden unterschreibt,
    und sagt es nicht. Ein Fingerabdruck hilft dort nicht weiter: die Option
    nimmt keinen entgegen. Deshalb endet der Bau hier, statt zu signieren und
    hinterher einen Signierer zu melden, der es vielleicht nicht war.
    """
    betroffen = sorted(sha1 for sha1, kandidat in alle if kandidat == name)
    zeilen = [
        f'Der Schlüsselbund hat {len(betroffen)} Zertifikate mit dem Namen '
        f'"{name}":',
    ]
    zeilen += [f"  {sha1}" for sha1 in betroffen]
    zeilen.append(
        "Welches davon signiert, lässt sich nicht bestimmen: `security cms "
        "-N` wählt nur über den Namen, ein Fingerabdruck ist dort keine "
        "Auswahl. Deshalb wird nicht signiert.")
    zeilen.append(
        "Es bleiben zwei Wege: das nicht mehr gebrauchte Zertifikat aus dem "
        "Schlüsselbund nehmen, oder über --sign-cert/--sign-key mit "
        "PEM-Dateien signieren, wo das Zertifikat selbst angegeben wird.")
    zeilen.append(_identitaeten_text(gueltige))
    return SchemaError("\n".join(zeilen))


def resolve_identity(wunsch: str, keychain: Path | None = None) -> str:
    """Übersetzt die Angabe aus --sign-identity in den Namen für `cms -N`.

    Drei Dinge passieren hier, und alle drei aus einem konkreten Grund.

    `security cms` nimmt einen Zertifikatsnamen, keinen Fingerabdruck. Wer
    einen SHA-1 angibt, bekommt ihn hier aufgelöst.

    Ein Name, der auf mehrere Zertifikate passt, wird abgelehnt statt geraten,
    und zwar auf beiden Wegen hinein. Über den Namen war das immer so. Über
    den SHA-1 nicht: der wurde auf den Namen zurückübersetzt und ungeprüft an
    `cms -N` gereicht, das ausschließlich nach Namen wählt. Gemessen an einem
    Wegwerf-Schlüsselbund mit zwei Zertifikaten namens „Doppel-Signer":
    angefragt war 5CBEAAAA…, signiert hat C7AF8CB6…, und der Lauf meldete
    Exit 0 samt dem angefragten Fingerabdruck. Ein Fingerabdruck ist für
    `cms -N` keine Auswahl, deshalb ist er auch hier keine.

    Und ein Name, den der Schlüsselbund gar nicht kennt, wird abgelehnt, bevor
    `security cms` überhaupt startet. Mit einer unbekannten Identität meldet
    das Werkzeug zwar sofort `failed to encode data`, bleibt danach aber unter
    Last minutenlang stehen, statt sich zu beenden. Ein Tippfehler im
    Identitätsnamen darf keinen Bau aufhängen.
    """
    alle = list_identities(keychain=keychain, nur_gueltige=False)
    gueltige = list_identities(keychain=keychain)
    if _SHA1_HEX.match(wunsch):
        name = next((kandidat for sha1, kandidat in alle
                     if sha1 == wunsch.upper()), None)
        if name is None:
            raise SchemaError(
                f"Kein Zertifikat mit dem SHA-1 {wunsch} im Schlüsselbund.\n"
                + _identitaeten_text(gueltige))
        if sum(1 for _, kandidat in alle if kandidat == name) > 1:
            raise _mehrdeutig(name, alle, gueltige)
        return name
    passend = {sha1 for sha1, name in alle if name == wunsch}
    if len(passend) > 1:
        raise _mehrdeutig(wunsch, alle, gueltige)
    if not passend:
        raise SchemaError(
            f"Der Schlüsselbund kennt keine Identität namens '{wunsch}'. "
            f"security cms würde hier ohne brauchbare Meldung stehenbleiben, "
            f"deshalb bricht der Bau vorher ab.\n"
            + _identitaeten_text(gueltige))
    return wunsch


def _aufraeumen(pfad: Path, bestand_vorher: bool) -> None:
    """Löscht eine Ausgabedatei, die erst dieser Lauf angelegt hat.

    Beide Signier-Werkzeuge legen ihre Ausgabedatei an, bevor sie scheitern.
    Zurück bleibt sonst eine leere oder halbe .mobileconfig, die aussieht wie
    ein fertiges Profil.
    """
    if bestand_vorher:
        return
    try:
        pfad.unlink()
    except OSError:
        pass


def _signieren(cmd: list[str], profil: bytes, signed_path: Path,
               werkzeug: str, nachspann: str = "") -> None:
    """Ruft das Signier-Werkzeug und schickt das Profil über stdin.

    Über stdin, damit das unsignierte Profil mit seinen Klartext-Passwörtern
    gar nicht erst auf die Platte kommt. Vorher schrieb main() eine
    `<output>.unsigned.mobileconfig` daneben und löschte sie nach dem
    Signieren. Scheiterte der Aufruf, blieb sie mit Modus 0644 liegen, samt
    WLAN-Passwort im Klartext.
    """
    bestand_vorher = signed_path.exists()
    try:
        proc = subprocess.run(cmd, input=profil, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    except OSError as fehler:
        _aufraeumen(signed_path, bestand_vorher)
        raise SchemaError(f"{cmd[0]} ließ sich nicht starten: {fehler}")

    meldung = proc.stderr.decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        _aufraeumen(signed_path, bestand_vorher)
        text = f"{werkzeug} ist mit Exit {proc.returncode} gescheitert."
        if meldung:
            text += f"\n{meldung}"
        if nachspann:
            text += f"\n{nachspann}"
        raise SchemaError(text)
    # Der Exit-Code allein ist kein Beleg: `security cms -S` beendet sich mit
    # 0, auch wenn es die Identität nicht findet, meldet den Fehler nur auf
    # stderr und legt eine Datei mit null Bytes an. Deshalb wird das Ergebnis
    # nachgesehen statt geglaubt.
    if not signed_path.exists() or signed_path.stat().st_size == 0:
        _aufraeumen(signed_path, bestand_vorher)
        text = f"{werkzeug} meldet Exit 0, hat aber nichts nach " \
               f"{signed_path} geschrieben."
        if meldung:
            text += f"\n{meldung}"
        if nachspann:
            text += f"\n{nachspann}"
        raise SchemaError(text)
    # CMS im DER-Format fängt mit einer ASN.1-SEQUENCE an (0x30). Was damit
    # nicht anfängt, ist keine Signatur, sondern durchgereichter Input.
    with signed_path.open("rb") as fh:
        erstes_byte = fh.read(1)
    if erstes_byte != b"\x30":
        _aufraeumen(signed_path, bestand_vorher)
        raise SchemaError(
            f"{werkzeug} hat nach {signed_path} etwas geschrieben, das nicht "
            f"mit einer ASN.1-SEQUENCE anfängt (erstes Byte "
            f"{erstes_byte!r}). Das ist keine PKCS#7-Signatur.")


def sign_profile(profil: bytes, signed_path: Path,
                 cert: Path, key: Path,
                 ca_chain: Path | None = None) -> None:
    """Signiert mit `openssl smime` (CMS / PKCS#7, DER, eingebettetes XML).

    `profil` sind die Bytes der unsignierten Plist. Sie gehen über stdin an
    openssl, es gibt keine unsignierte Zwischendatei.
    """
    cmd = [
        "openssl", "smime", "-sign", "-signer", str(cert),
        "-inkey", str(key), "-nodetach", "-outform", "der",
        "-out", str(signed_path),
    ]
    if ca_chain:
        cmd += ["-certfile", str(ca_chain)]
    _signieren(cmd, profil, signed_path, "openssl smime -sign")


def sign_profile_keychain(profil: bytes, signed_path: Path, identity: str,
                          keychain: Path | None = None) -> None:
    """Signiert über eine Identität im macOS-Schlüsselbund.

    `openssl` kann einen Schlüssel im Schlüsselbund nicht lesen, deshalb läuft
    dieser Weg über `security cms -S`. Der private Schlüssel verlässt den
    Schlüsselbund nicht, was in Unternehmen der übliche Fall ist. Der Preis
    ist ein zweiter Code-Pfad, den es nur auf macOS gibt.

    `-H SHA256` ist gesetzt, weil `security cms` sonst SHA-1 nimmt.
    """
    if sys.platform != "darwin":
        raise SchemaError(
            f"--sign-identity signiert über den macOS-Schlüsselbund und läuft "
            f"nur auf macOS. Auf {sys.platform} bleibt der Weg über "
            f"--sign-cert und --sign-key mit PEM-Dateien.")
    nickname = resolve_identity(identity, keychain=keychain)
    cmd = [SECURITY_TOOL, "cms", "-S", "-N", nickname, "-H", "SHA256",
           "-o", str(signed_path)]
    if keychain:
        cmd += ["-k", str(keychain)]
    _signieren(cmd, profil, signed_path, "security cms -S",
               nachspann=(f"Angefragt war: {identity}\n"
                          + _identitaeten_text(list_identities(
                              keychain=keychain))))
    _pruefe_cms_inhalt(profil, signed_path)


def _pruefe_cms_inhalt(profil: bytes, signed_path: Path) -> None:
    """Packt die Signatur wieder aus und vergleicht mit dem Original.

    `security cms -S` ist beim Melden von Fehlern unzuverlässig: es endet mit
    Exit 0, auch wenn nichts signiert wurde. Beim Nachstellen einer
    erfundenen Identität sind außerdem zwei von sieben Läufen mit einer
    Ausgabedatei durchgelaufen, während zwanzig direkte Aufrufe von
    `security cms` mit derselben Identität sämtlich nichts geschrieben haben.
    Statt dem Werkzeug zu glauben, wird die fertige Datei mit
    `security cms -D` wieder ausgepackt. Stimmt der Inhalt nicht Byte für
    Byte mit dem Profil überein, fliegt die Datei raus.
    """
    proc = subprocess.run([SECURITY_TOOL, "cms", "-D", "-i", str(signed_path)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0 or proc.stdout != profil:
        try:
            signed_path.unlink()
        except OSError:
            pass
        meldung = proc.stderr.decode("utf-8", "replace").strip()
        raise SchemaError(
            "Die Signatur lässt sich nicht wieder auspacken oder enthält "
            "nicht das gebaute Profil. Die Ausgabedatei wurde gelöscht."
            + (f"\n{meldung}" if meldung else ""))


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def load_spec(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        ensure_yaml()
        import yaml
        return yaml.safe_load(text)
    return json.loads(text)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("spec", type=Path,
                    help="Spec-Datei (JSON oder YAML) mit meta + payloads")
    ap.add_argument("-o", "--output", type=Path, required=True,
                    help="Ausgabepfad (.mobileconfig)")
    ap.add_argument("--branch", default="release")
    ap.add_argument("--offline", action="store_true",
                    help="Nur Cache benutzen, kein Netz-Zugriff")
    ap.add_argument("--validate-strict", action="store_true",
                    help="Strikte Validierung (unbekannte Keys → Fehler, "
                         "Regex-Format-Checks aktiv)")
    ap.add_argument("--no-validate", action="store_true",
                    help="Schema-Validierung überspringen (NICHT empfohlen)")
    ap.add_argument("--manifests", action="store_true",
                    help="Zweite Schema-Quelle ProfileManifests zulassen, "
                         "fuer PayloadTypes, die Apple nicht kennt "
                         "(Chrome, Office, Zoom …). Wird zur Laufzeit "
                         "geladen, nichts davon liegt im Repo.")
    ap.add_argument("--manifests-ref", default=MANIFESTS_REF,
                    help=f"Branch, Tag oder Commit von ProfileManifests "
                         f"(default: {MANIFESTS_REF})")
    ap.add_argument("--sign-cert", type=Path,
                    help="X.509-Zertifikat (PEM) zum Signieren")
    ap.add_argument("--sign-key", type=Path,
                    help="Privater Schlüssel (PEM) zum Signieren")
    ap.add_argument("--sign-ca", type=Path,
                    help="CA-Chain (PEM, optional)")
    ap.add_argument("--sign-identity",
                    help="Name oder SHA-1 einer Identität im macOS-"
                         "Schlüsselbund. Signiert über `security cms`, der "
                         "private Schlüssel bleibt im Schlüsselbund. "
                         "Kandidaten zeigt "
                         "`security find-identity -v -p smime` "
                         "(nicht -p codesigning).")
    ap.add_argument("--keychain", type=Path,
                    help="Schlüsselbund-Datei, in der --sign-identity gesucht "
                         "wird (Vorgabe: die Suchliste des Benutzers)")
    args = ap.parse_args()

    # Flag-Kombinationen zuerst, damit ein Tippfehler nicht erst nach der
    # Schema-Validierung auffällt.
    if args.sign_identity and (args.sign_cert or args.sign_key or args.sign_ca):
        sys.exit("FEHLER: --sign-identity und --sign-cert/--sign-key/--sign-ca "
                 "sind zwei getrennte Wege. Entweder der Schlüssel bleibt im "
                 "Schlüsselbund, oder er liegt als PEM-Datei vor.")
    if bool(args.sign_cert) != bool(args.sign_key):
        sys.exit("FEHLER: --sign-cert und --sign-key gehören zusammen.")
    if args.keychain and not args.sign_identity:
        sys.exit("FEHLER: --keychain wirkt nur zusammen mit --sign-identity.")

    manifeste = None
    if args.manifests:
        manifeste = {"ref": args.manifests_ref, "offline": args.offline}

    spec = load_spec(args.spec)
    profile, errors = build_profile(
        spec, branch=args.branch,
        strict=args.validate_strict,
        validate=not args.no_validate,
        offline=args.offline,
        manifeste=manifeste,
    )

    # Wer gegen die zweite Quelle geprueft hat, soll das sehen. Die Angabe
    # steht auf stderr, damit sie eine Pipe auf stdout nicht verschmutzt.
    if manifeste is not None and not args.no_validate:
        aus_manifest = sorted({
            p["PayloadType"] for p in profile.get("PayloadContent", [])
            if isinstance(p, dict) and p.get("PayloadType")
            and load_all_schemas(args.branch).get(p["PayloadType"]) is None
            and get_schema(p["PayloadType"], args.branch,
                           manifeste=manifeste) is not None
        })
        if aus_manifest:
            print("Hinweis: geprueft gegen ProfileManifests statt gegen "
                  "Apples Schema: " + ", ".join(aus_manifest),
                  file=sys.stderr)
            print("  Die Sammlung ist von Mac-Admins gepflegt, nicht von "
                  "Apple, und hat keine Lizenzangabe.", file=sys.stderr)

    if errors:
        print("Validation issues:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        if args.validate_strict:
            sys.exit(2)
        else:
            print("(continuing because --validate-strict is off)",
                  file=sys.stderr)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Einmal serialisieren, dann je nach Weg weiterreichen. Die Bytes gehen an
    # das Signier-Werkzeug über stdin, damit kein unsigniertes Zwischenprodukt
    # auf der Platte landet.
    profil_bytes = plistlib.dumps(profile, fmt=plistlib.FMT_XML)

    try:
        if args.sign_identity:
            sign_profile_keychain(profil_bytes, args.output,
                                  args.sign_identity, keychain=args.keychain)
            print(f"✓ Signed profile written to {args.output}")
            print(f"  (Schlüsselbund-Identität: {args.sign_identity})")
        elif args.sign_cert:
            sign_profile(profil_bytes, args.output, args.sign_cert,
                         args.sign_key, args.sign_ca)
            print(f"✓ Signed profile written to {args.output}")
        else:
            args.output.write_bytes(profil_bytes)
            print(f"✓ Unsigned profile written to {args.output}")
            print("  (Apple-Geräte zeigen 'Nicht signiert' beim Install. "
                  "Produktiv wird signiert, siehe --sign-cert/--sign-key "
                  "oder --sign-identity.)")
    except SchemaError as fehler:
        print(f"FEHLER: {fehler}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
