#!/usr/bin/env python3
"""
run_tests.py — Automatischer Regressions-Test für mobileconfig-builder.

Führt jeden Eval aus evals/evals.json aus und prüft die expectations
programmatisch. Exit-Code 0 = alle Tests grün, sonst Anzahl Fehler.

Diese Tests stellen sicher, dass die drei Skripte (fetch/inspect/build)
weiter so funktionieren wie vom Skill versprochen — nach jeder Änderung
am Skill kurz durchlaufen lassen, dann weiß man Bescheid.

Usage:
    python3 evals/run_tests.py                  # alle Tests
    python3 evals/run_tests.py --eval-id 2      # nur einen
    python3 evals/run_tests.py -v               # ausführlicher Output
"""
from __future__ import annotations
import argparse
import json
import plistlib
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
ASSETS = SKILL_ROOT / "assets"

sys.path.insert(0, str(SCRIPTS))


# ─── ANSI helpers ──────────────────────────────────────────────────────────
def green(s): return f"\033[32m{s}\033[0m"
def red(s):   return f"\033[31m{s}\033[0m"
def dim(s):   return f"\033[2m{s}\033[0m"
def bold(s):  return f"\033[1m{s}\033[0m"


# ─── Test result helpers ───────────────────────────────────────────────────
class TestCase:
    def __init__(self, eval_id: int, name: str):
        self.id = eval_id
        self.name = name
        self.checks: list[tuple[str, bool, str]] = []  # (label, passed, detail)

    def check(self, label: str, condition: bool, detail: str = ""):
        self.checks.append((label, bool(condition), detail))

    @property
    def passed(self) -> int:
        return sum(1 for _, ok, _ in self.checks if ok)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def all_green(self) -> bool:
        return all(ok for _, ok, _ in self.checks)

    def report(self, verbose: bool = False) -> None:
        marker = green("PASS") if self.all_green else red("FAIL")
        print(f"  [{marker}] eval-{self.id}: {self.name}  "
              f"({self.passed}/{self.total} checks)")
        if not self.all_green or verbose:
            for label, ok, detail in self.checks:
                tick = green("✓") if ok else red("✗")
                line = f"      {tick} {label}"
                if detail and (not ok or verbose):
                    line += dim(f"  — {detail}")
                print(line)


# ─── Helpers shared by tests ───────────────────────────────────────────────
def run_build(spec_path: Path, out_path: Path, *,
              strict: bool = True, expect_fail: bool = False,
              zusatz: list[str] | None = None
              ) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable, str(SCRIPTS / "build_mobileconfig.py"),
        str(spec_path),
        "-o", str(out_path),
        "--offline",
    ]
    if strict:
        cmd.append("--validate-strict")
    cmd += zusatz or []
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def run_build_signiert(spec_path: Path, out_path: Path,
                       zusatz: list[str]) -> subprocess.CompletedProcess:
    """Build mit Signier-Flags.

    Grosszuegiges Timeout mit Grund: `security cms -S` kann sich aufhaengen,
    etwa wenn der Schluesselbund gesperrt ist und der Freigabe-Dialog kein
    Fenster hat. Der Fehlerpfad hier laeuft zwar bewusst so, dass es dazu
    nicht kommt, aber ein Timeout, das kuerzer ist als der Fehlerfall, macht
    aus einem Befund einen Rateschluss."""
    cmd = [
        sys.executable, str(SCRIPTS / "build_mobileconfig.py"),
        str(spec_path), "-o", str(out_path), "--offline", "--validate-strict",
    ] + zusatz
    return subprocess.run(cmd, capture_output=True, text=True, timeout=600)


def load_plist(path: Path) -> dict:
    with path.open("rb") as f:
        return plistlib.load(f)


def plist_parses(path: Path) -> tuple[bool, str]:
    """Gibt (parsebar?, Detail) zurück. Ein kaputtes Plist soll ein roter
    Check sein, kein Absturz des Runners."""
    try:
        load_plist(path)
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def is_uuid(s) -> bool:
    if not isinstance(s, str):
        return False
    try:
        uuid.UUID(s)
        return True
    except (ValueError, AttributeError):
        return False


def is_reverse_dns(s) -> bool:
    return isinstance(s, str) and "." in s and " " not in s


def find_payload(plist: dict, ptype: str) -> dict | None:
    for p in plist.get("PayloadContent", []):
        if isinstance(p, dict) and p.get("PayloadType") == ptype:
            return p
    return None


# ─── Test implementations ──────────────────────────────────────────────────
def test_eval_1_wifi_guest(workdir: Path) -> TestCase:
    tc = TestCase(1, "wifi-guest")
    spec = ASSETS / "examples" / "wifi_guest.json"
    out = workdir / "wifi_guest.mobileconfig"
    proc = run_build(spec, out, strict=True)

    tc.check("Strict-mode build exits 0", proc.returncode == 0,
             proc.stderr.strip() or proc.stdout.strip())
    if proc.returncode != 0:
        return tc

    p = load_plist(out)
    tc.check("Top-Level PayloadType == 'Configuration'",
             p.get("PayloadType") == "Configuration",
             repr(p.get("PayloadType")))
    tc.check("Top-Level PayloadVersion == 1",
             p.get("PayloadVersion") == 1, repr(p.get("PayloadVersion")))
    tc.check("Top-Level PayloadIdentifier matches spec",
             p.get("PayloadIdentifier") == "com.example.wifi.guest",
             repr(p.get("PayloadIdentifier")))
    tc.check("Top-Level PayloadUUID is valid UUID",
             is_uuid(p.get("PayloadUUID")), repr(p.get("PayloadUUID")))
    tc.check("PayloadContent has exactly 1 entry",
             len(p.get("PayloadContent", [])) == 1,
             f"len={len(p.get('PayloadContent', []))}")

    inner = find_payload(p, "com.apple.wifi.managed")
    tc.check("Inner payload type == com.apple.wifi.managed",
             inner is not None)
    if inner:
        tc.check("Inner SSID_STR == 'GuestNet'",
                 inner.get("SSID_STR") == "GuestNet",
                 repr(inner.get("SSID_STR")))
        tc.check("Inner EncryptionType in allowed list",
                 inner.get("EncryptionType") in
                 {"WEP", "WPA", "WPA2", "WPA3", "Any", "None"},
                 repr(inner.get("EncryptionType")))
        tc.check("Inner AutoJoin is real bool",
                 isinstance(inner.get("AutoJoin"), bool),
                 f"type={type(inner.get('AutoJoin')).__name__}")
        tc.check("Inner Password preserved",
                 inner.get("Password") == "supersecret123")
        tc.check("Inner has its own valid PayloadUUID",
                 is_uuid(inner.get("PayloadUUID")))
        tc.check("Inner has reverse-DNS PayloadIdentifier",
                 is_reverse_dns(inner.get("PayloadIdentifier")))
    return tc


def test_eval_2_disable_apple_intelligence(workdir: Path) -> TestCase:
    tc = TestCase(2, "disable-apple-intelligence")
    spec = workdir / "ai_off.json"
    spec.write_text(json.dumps({
        "meta": {
            "PayloadIdentifier": "com.zimmermann.disable-apple-intelligence",
            "PayloadDisplayName": "Apple Intelligence aus",
            "PayloadScope": "System",
        },
        "payloads": [{
            "PayloadType": "com.apple.applicationaccess",
            "allowWritingTools": False,
            "allowImagePlayground": False,
            "allowGenmoji": False,
            "allowMailSummary": False,
            "allowExternalIntelligenceIntegrations": False,
            "allowAppleIntelligenceReport": False,
        }],
    }))
    out = workdir / "ai_off.mobileconfig"
    proc = run_build(spec, out, strict=True)

    tc.check("Strict build exits 0", proc.returncode == 0,
             proc.stderr.strip() or proc.stdout.strip())
    if proc.returncode != 0:
        return tc

    ok, detail = plist_parses(out)
    tc.check("Output is a valid plist parseable by plistlib", ok, detail)
    if not ok:
        return tc

    p = load_plist(out)
    inner = find_payload(p, "com.apple.applicationaccess")
    tc.check("applicationaccess payload exists", inner is not None)
    if not inner:
        return tc

    required_keys_false = [
        "allowWritingTools", "allowImagePlayground", "allowGenmoji",
        "allowMailSummary", "allowExternalIntelligenceIntegrations",
        "allowAppleIntelligenceReport",
    ]
    for k in required_keys_false:
        v = inner.get(k, "<missing>")
        tc.check(f"{k} is exactly the boolean False",
                 v is False, f"got={v!r} (type={type(v).__name__})")

    # No iOS-only key sneaks in (since user asked for macOS via deduction)
    tc.check("No allowImageWand key (iOS-only) accidentally added",
             "allowImageWand" not in inner)

    # Ensure no AI-allow key is True
    ai_keys = [k for k in inner.keys()
               if k.startswith("allow") and "intelligence" in k.lower()
               or k in {"allowGenmoji", "allowImagePlayground",
                        "allowImageWand", "allowMailSummary",
                        "allowWritingTools"}]
    all_off = all(inner[k] is False for k in ai_keys)
    tc.check(f"All {len(ai_keys)} AI-related allow* keys are False",
             all_off, f"keys checked: {ai_keys}")
    return tc


def test_eval_3_classroom_ipad(workdir: Path) -> TestCase:
    tc = TestCase(3, "classroom-ipad-multi-payload")
    spec = ASSETS / "examples" / "classroom_ipad.json"
    out = workdir / "classroom.mobileconfig"
    proc = run_build(spec, out, strict=True)

    tc.check("Strict build exits 0", proc.returncode == 0,
             proc.stderr.strip() or proc.stdout.strip())
    if proc.returncode != 0:
        return tc

    ok, detail = plist_parses(out)
    tc.check("Output is a valid plist parseable by plistlib", ok, detail)
    if not ok:
        return tc

    p = load_plist(out)
    pc = p.get("PayloadContent", [])
    tc.check("PayloadContent has exactly 2 entries", len(pc) == 2,
             f"len={len(pc)}")

    types = [item.get("PayloadType") for item in pc if isinstance(item, dict)]
    tc.check("Contains com.apple.wifi.managed",
             "com.apple.wifi.managed" in types, f"types={types}")
    tc.check("Contains com.apple.applicationaccess",
             "com.apple.applicationaccess" in types, f"types={types}")

    wifi = find_payload(p, "com.apple.wifi.managed")
    if wifi:
        tc.check("WiFi SSID == 'School-Net'",
                 wifi.get("SSID_STR") == "School-Net",
                 repr(wifi.get("SSID_STR")))
        tc.check("WiFi EncryptionType == 'WPA2'",
                 wifi.get("EncryptionType") == "WPA2",
                 repr(wifi.get("EncryptionType")))
    rest = find_payload(p, "com.apple.applicationaccess")
    if rest:
        tc.check("Restrictions: allowAppInstallation == False",
                 rest.get("allowAppInstallation") is False)
        tc.check("Restrictions: allowCamera == True",
                 rest.get("allowCamera") is True)
        tc.check("Restrictions: allowInAppPurchases == False",
                 rest.get("allowInAppPurchases") is False)

    uuids = [item.get("PayloadUUID") for item in pc if isinstance(item, dict)]
    tc.check("Both inner UUIDs distinct",
             len(uuids) == len(set(uuids)), f"uuids={uuids}")
    ids = [item.get("PayloadIdentifier") for item in pc if isinstance(item, dict)]
    tc.check("Both inner identifiers reverse-DNS",
             all(is_reverse_dns(i) for i in ids), f"ids={ids}")
    return tc


def test_eval_4_invalid_input_rejected(workdir: Path) -> TestCase:
    tc = TestCase(4, "invalid-input-rejected")
    spec = workdir / "bad.json"
    spec.write_text(json.dumps({
        "meta": {"PayloadIdentifier": "com.example.bad"},
        "payloads": [{
            "PayloadType": "com.apple.wifi.managed",
            "EncryptionType": "SUPERWPA",
            "AutoJoin": "ja",
        }],
    }))
    out = workdir / "bad.mobileconfig"
    if out.exists():
        out.unlink()
    proc = run_build(spec, out, strict=True)
    err = proc.stderr

    # Exit-Code 2 ist der dokumentierte Validierungs-Fehlschlag. Ein
    # beliebiger Absturz liefert 1 und darf diesen Negativtest nicht
    # erfuellen, deshalb haengt jeder Check an der erwarteten Meldung.
    tc.check("Build exits with code 2 (validation failure, not a crash)",
             proc.returncode == 2, f"returncode={proc.returncode}")
    tc.check("Error output is a validation report, not a traceback",
             "Validation issues:" in err
             and "Traceback (most recent call last)" not in err,
             dim(err[:200]))
    tc.check("Error mentions 'EncryptionType'", "EncryptionType" in err,
             dim(err[:200]))
    tc.check("Error mentions allowed values or invalid value",
             "SUPERWPA" in err or "WPA2" in err or "WPA3" in err)
    tc.check("Error mentions 'AutoJoin'", "AutoJoin" in err)
    tc.check("Error mentions boolean type mismatch",
             "boolean" in err.lower() or "<boolean>" in err)
    tc.check("No output file was created", not out.exists())
    tc.check("Errors go to stderr, not stdout",
             "EncryptionType" not in proc.stdout,
             dim(proc.stdout[:200]))
    return tc


def test_eval_5_list_payload_types(workdir: Path) -> TestCase:
    tc = TestCase(5, "list-payload-types")
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "fetch_schema.py"),
         "--list", "--offline"],
        capture_output=True, text=True, timeout=30,
    )
    tc.check("fetch_schema.py --list exits 0", proc.returncode == 0,
             proc.stderr[:200])
    out = proc.stdout
    tc.check("Output mentions com.apple.wifi.managed",
             "com.apple.wifi.managed" in out)
    tc.check("Output mentions com.apple.applicationaccess",
             "com.apple.applicationaccess" in out)
    tc.check("Output mentions com.apple.vpn.managed",
             "com.apple.vpn.managed" in out)

    payload_lines = [l for l in out.splitlines()
                     if re.match(r"^\s+(com\.apple|\.GlobalPreferences|"
                                 r"CommonPayloadKeys|TopLevel)", l)]
    tc.check(f"At least 50 payload entries listed (got {len(payload_lines)})",
             len(payload_lines) >= 50)

    marker = re.compile(r"^\s+\S+\s+\[[^\]]*\]")
    without_marker = [l for l in payload_lines if not marker.match(l)]
    tc.check("Every listed entry shows an OS support marker like [iOS,macOS]",
             not without_marker, f"without marker: {without_marker[:3]}")

    com_apple_lines = [l for l in payload_lines if "com.apple" in l]
    types_in_order = [l.strip().split()[0] for l in com_apple_lines]
    tc.check("com.apple.* entries appear sorted",
             types_in_order == sorted(types_in_order),
             f"first 5: {types_in_order[:5]}")
    return tc


def test_eval_6_unknown_top_level_key(workdir: Path) -> TestCase:
    tc = TestCase(6, "unknown-top-level-key-rejected")
    spec = workdir / "bad_top.json"
    spec.write_text(json.dumps({
        "meta": {
            "PayloadIdentifier": "com.example.badtop",
            "PayloadDisplayName": "Erfundener Top-Level-Key",
            "TotallyMadeUpKey": "nope",
        },
        "payloads": [{
            "PayloadType": "com.apple.applicationaccess",
            "allowCamera": False,
        }],
    }))
    out = workdir / "bad_top.mobileconfig"
    if out.exists():
        out.unlink()
    proc = run_build(spec, out, strict=True)
    err = proc.stderr + proc.stdout

    tc.check("Strict build exits with code 2 (validation failure)",
             proc.returncode == 2,
             f"returncode={proc.returncode}: {err[:200]}")
    tc.check("Error names the invented key 'TotallyMadeUpKey'",
             "TotallyMadeUpKey" in err, dim(err[:200]))
    tc.check("Finding is reported on the top level, not on a payload",
             "top-level: unknown key 'TotallyMadeUpKey'" in err,
             dim(err[:200]))
    tc.check("No output file was created in strict mode", not out.exists())

    lax_out = workdir / "bad_top_lax.mobileconfig"
    lax = run_build(spec, lax_out, strict=False)
    tc.check("Same spec still builds without --validate-strict",
             lax.returncode == 0 and lax_out.exists(),
             f"returncode={lax.returncode}: {lax.stderr.strip()[:200]}")

    good = ASSETS / "examples" / "wifi_guest.json"
    good_out = workdir / "top_level_ok.mobileconfig"
    ok = run_build(good, good_out, strict=True)
    tc.check("Own example with only TopLevel.yaml keys still builds strictly",
             ok.returncode == 0, ok.stderr.strip()[:200])
    return tc


def test_eval_7_signing_error_paths(workdir: Path) -> TestCase:
    """Fehlerpfade der Signierung, auf jeder Plattform pruefbar.

    Der Erfolgsfall des Schluesselbund-Wegs laesst sich hier nicht pruefen: er
    braucht eine Identitaet im Schluesselbund, und auf einem Linux-Runner gibt
    es weder `security` noch einen Schluesselbund. Was sich pruefen laesst, ist
    das Verhalten, wenn es schiefgeht, und genau daran hing der Fehler mit der
    liegengebliebenen unsignierten Zwischendatei.

    Was welcher Check deckt, damit niemand mehr daraus liest als drinsteht:

    Die Checks 1 bis 4 pruefen die Vorabpruefung, nicht das Aufraeumen.
    resolve_identity lehnt die erfundene Identitaet ab, bevor irgendeine Datei
    angelegt wird. "Keine Ausgabedatei nach dem Fehlschlag" ist dort deshalb
    trivial wahr und waere auch ohne jedes Aufraeumen gruen. Der Wert dieser
    Checks liegt woanders: der Bau bricht mit Meldung ab, statt in `security
    cms` haengenzubleiben.

    Die Checks 6 bis 8 pruefen den Ausgabepfad wirklich. Sie gehen ueber
    `openssl`, das erst startet und dann scheitert, also genau die Lage
    herstellt, in der frueher etwas liegenblieb. Check 8 nimmt den zweiten Bau
    auf denselben Pfad dazu: `openssl -out` kuerzt seine Ausgabedatei schon
    beim Oeffnen, und bis Welle 5 war das zuvor dort liegende gueltige Profil
    danach weg.
    """
    tc = TestCase(7, "signing-error-paths")
    spec = ASSETS / "examples" / "wifi_guest.json"

    # 1-4: unbekannte Identitaet
    kc_dir = workdir / "keychain"
    kc_dir.mkdir(exist_ok=True)
    out = kc_dir / "keychain.mobileconfig"
    unbekannt = "mobileconfig-builder-gibt-es-nicht-4711"
    proc = run_build_signiert(spec, out, ["--sign-identity", unbekannt])
    err = proc.stderr + proc.stdout

    tc.check("Unbekannte Identitaet endet mit Exit 2",
             proc.returncode == 2, f"returncode={proc.returncode}: {err[:200]}")
    tc.check("Keine Ausgabedatei nach dem Fehlschlag", not out.exists())
    tc.check("Meldung statt Traceback",
             "Traceback (most recent call last)" not in err
             and "FEHLER:" in err, dim(err[:200]))
    if sys.platform == "darwin":
        tc.check("Meldung nennt das Werkzeug und die angefragte Identitaet",
                 "security cms" in err and unbekannt in err, dim(err[:300]))
    else:
        tc.check("Meldung nennt macOS und den PEM-Weg als Alternative",
                 "macOS" in err and "--sign-cert" in err, dim(err[:300]))

    # 5: die beiden Signier-Wege schliessen sich aus
    misch = run_build_signiert(
        spec, kc_dir / "misch.mobileconfig",
        ["--sign-identity", unbekannt, "--sign-cert", str(kc_dir / "c.pem")])
    misch_err = misch.stderr + misch.stdout
    tc.check("--sign-identity und --sign-cert zusammen werden abgelehnt",
             misch.returncode != 0
             and "Traceback (most recent call last)" not in misch_err,
             f"returncode={misch.returncode}: {misch_err[:200]}")

    # 6-7: gescheitertes PEM-Signieren laesst nichts liegen. Das ist die
    # Regression zum eigentlichen Fehler: frueher blieb
    # <output>.unsigned.mobileconfig mit dem WLAN-Passwort im Klartext liegen.
    pem_dir = workdir / "pemleck"
    pem_dir.mkdir(exist_ok=True)
    pem = run_build_signiert(
        spec, pem_dir / "leak.mobileconfig",
        ["--sign-cert", str(pem_dir / "gibtsnicht.pem"),
         "--sign-key", str(pem_dir / "gibtsnicht.key")])
    zurueck = sorted(p.name for p in pem_dir.iterdir())
    klartext = [p.name for p in pem_dir.iterdir()
                if p.is_file() and b"supersecret123" in p.read_bytes()]
    tc.check("Gescheitertes PEM-Signieren laesst kein Klartext-Passwort "
             "zurueck", not klartext, f"gefunden in {klartext}")
    tc.check("Gescheitertes PEM-Signieren laesst gar keine Datei zurueck",
             not zurueck,
             f"returncode={pem.returncode}, uebrig: {zurueck}")

    # 8: der zweite Bau auf denselben Pfad. Das ist der haeufigste Fall, und
    # der einzige, in dem am Zielpfad ueberhaupt etwas zu verlieren ist.
    zweit_dir = workdir / "zweiterlauf"
    zweit_dir.mkdir(exist_ok=True)
    ziel = zweit_dir / "profil.mobileconfig"
    erst = run_build(spec, ziel, strict=True)
    vorher = ziel.read_bytes() if ziel.exists() else b""
    run_build_signiert(
        spec, ziel,
        ["--sign-cert", str(zweit_dir / "gibtsnicht.pem"),
         "--sign-key", str(zweit_dir / "gibtsnicht.key")])
    nachher = ziel.read_bytes() if ziel.exists() else b""
    tc.check("Gescheitertes Signieren laesst ein vorhandenes Profil am "
             "Zielpfad unveraendert",
             erst.returncode == 0 and vorher and nachher == vorher,
             f"vorher {len(vorher)} Bytes, nachher {len(nachher)} Bytes, "
             f"uebrig: {sorted(p.name for p in zweit_dir.iterdir())}")
    return tc


# Ein erfundenes Manifest, kein echtes. ProfileManifests hat keine Lizenz,
# also liegt hier keine Datei aus dem fremden Repo, auch nicht als Fixture.
# Geprueft wird die Uebersetzung, und die haengt nicht am Inhalt.
EVAL_MANIFEST_REF = "_eval_fixture"
EVAL_MANIFEST = {
    "pfm_domain": "com.example.testapp",
    "pfm_title": "Test-App",
    "pfm_description": "Erfundenes Manifest fuer die Eval-Suite.",
    "pfm_platforms": ["macOS"],
    "pfm_format_version": 1,
    "pfm_subkeys": [
        # Faellt raus: CommonPayloadKeys sind Apples Zustaendigkeit.
        {"pfm_name": "PayloadType", "pfm_type": "string",
         "pfm_require": "always"},
        # Faellt raus: Bedienelement von ProfileCreator, kein Preference-Key.
        {"pfm_name": "PFC_SegmentedControl_0", "pfm_type": "string",
         "pfm_require": "always",
         "pfm_segments": {"Allgemein": ["UpdateChannel"]}},
        {"pfm_name": "UpdateChannel", "pfm_type": "string",
         "pfm_title": "Update-Kanal", "pfm_require": "always",
         "pfm_range_list": ["stable", "beta"]},
        {"pfm_name": "CacheSizeMB", "pfm_type": "integer",
         "pfm_range_min": 10, "pfm_range_max": 4096},
        {"pfm_name": "LicenseKey", "pfm_type": "string",
         "pfm_format": "^[A-Z]{4}-[0-9]{4}$"},
        {"pfm_name": "BlockedHosts", "pfm_type": "array",
         "pfm_subkeys": [{"pfm_type": "string"}]},
        {"pfm_name": "Proxy", "pfm_type": "dictionary", "pfm_subkeys": [
            {"pfm_name": "Host", "pfm_type": "string",
             "pfm_require": "always"},
            {"pfm_name": "Port", "pfm_type": "integer"},
        ]},
        # Unbekannter Typ: lieber ungeprueft durchlassen als falsch ablehnen.
        {"pfm_name": "Sonderfall", "pfm_type": "union policy"},
    ],
}


def test_eval_8_profilemanifests_normalisierung(workdir: Path) -> TestCase:
    """Uebersetzung eines ProfileManifests in Apples Schema-Form.

    Ohne Netz: das erfundene Manifest wird in den Manifest-Cache gelegt und
    von dort gelesen, genau wie ein echtes.
    """
    tc = TestCase(8, "profilemanifests-normalisierung")
    from fetch_schema import manifest_cache_dir, manifest_to_schema

    schema = manifest_to_schema(EVAL_MANIFEST, ref=EVAL_MANIFEST_REF,
                                quelle="testapp.plist")
    keys = {k["key"]: k for k in schema["payloadkeys"]}

    tc.check("Domain und Plattform uebernommen",
             schema["payload"]["payloadtype"] == "com.example.testapp"
             and list(schema["payload"]["supportedOS"]) == ["macOS"]
             and schema["_origin"] == "ProfileManifests",
             f"{schema['payload']}")

    tc.check("Typen uebersetzt, unbekannter Typ wird <any>",
             keys["UpdateChannel"]["type"] == "<string>"
             and keys["CacheSizeMB"]["type"] == "<integer>"
             and keys["BlockedHosts"]["type"] == "<array>"
             and keys["Proxy"]["type"] == "<dictionary>"
             and keys["Sonderfall"]["type"] == "<any>",
             f"{[(k, v['type']) for k, v in keys.items()]}")

    tc.check("Pflicht nur bei pfm_require always",
             keys["UpdateChannel"]["presence"] == "required"
             and keys["CacheSizeMB"]["presence"] == "optional",
             f"{[(k, v.get('presence')) for k, v in keys.items()]}")

    tc.check("rangelist, range und format uebernommen",
             keys["UpdateChannel"]["rangelist"] == ["stable", "beta"]
             and keys["CacheSizeMB"]["range"] == {"min": 10, "max": 4096}
             and keys["LicenseKey"]["format"] == "^[A-Z]{4}-[0-9]{4}$",
             f"{keys['CacheSizeMB']}")

    array_item = keys["BlockedHosts"]["subkeys"][0]
    proxy_keys = {k["key"] for k in keys["Proxy"]["subkeys"]}
    tc.check("Verschachtelung und Array-Item-Form uebernommen",
             array_item["type"] == "<string>"
             and proxy_keys == {"Host", "Port"},
             f"array_item={array_item}, proxy={proxy_keys}")

    tc.check("ProfileCreator-Pseudokeys und CommonPayloadKeys fallen raus",
             "PFC_SegmentedControl_0" not in keys
             and "PayloadType" not in keys,
             f"{sorted(keys)}")

    # Ueber die CLI, offline, aus dem Manifest-Cache.
    cache = manifest_cache_dir(EVAL_MANIFEST_REF)
    ziel = cache / "com.example.testapp.plist"
    try:
        cache.mkdir(parents=True, exist_ok=True)
        with ziel.open("wb") as fh:
            plistlib.dump(EVAL_MANIFEST, fh)

        gut = workdir / "manifest_gut.json"
        gut.write_text(json.dumps({
            "meta": {"PayloadIdentifier": "com.example.manifest.ok"},
            "payloads": [{
                "PayloadType": "com.example.testapp",
                "UpdateChannel": "beta",
                "CacheSizeMB": 512,
                "BlockedHosts": ["a.invalid"],
                "Proxy": {"Host": "proxy.invalid", "Port": 8080},
            }],
        }))
        schlecht = workdir / "manifest_schlecht.json"
        schlecht.write_text(json.dumps({
            "meta": {"PayloadIdentifier": "com.example.manifest.bad"},
            "payloads": [{
                "PayloadType": "com.example.testapp",
                "UpdateChannel": "nightly",
                "GibtEsNicht": True,
            }],
        }))
        zusatz = ["--manifests", "--manifests-ref", EVAL_MANIFEST_REF]
        aus = workdir / "manifest_gut.mobileconfig"
        ok = run_build(gut, aus, strict=True, zusatz=zusatz)
        nein = run_build(schlecht, workdir / "manifest_schlecht.mobileconfig",
                         strict=True, zusatz=zusatz)
        nein_err = nein.stderr + nein.stdout

        tc.check("Spec gegen das Manifest baut strikt durch",
                 ok.returncode == 0 and aus.exists(),
                 f"returncode={ok.returncode}: {ok.stderr.strip()[:200]}")
        tc.check("Erfundener Key und unerlaubter Wert werden abgelehnt",
                 nein.returncode == 2
                 and "GibtEsNicht" in nein_err
                 and "nightly" in nein_err,
                 f"returncode={nein.returncode}: {nein_err[:250]}")
        tc.check("Die Herkunft steht in der Meldung",
                 "ProfileManifests" in (ok.stderr + ok.stdout),
                 dim((ok.stderr + ok.stdout)[:200]))
    finally:
        try:
            ziel.unlink()
            cache.rmdir()
        except OSError:
            pass
    return tc


# ─── Runner ────────────────────────────────────────────────────────────────
def load_declared_expectations() -> dict[int, int]:
    """eval-id → Anzahl der in evals.json deklarierten Erwartungen."""
    data = json.loads((Path(__file__).resolve().parent / "evals.json")
                      .read_text(encoding="utf-8"))
    return {e["id"]: len(e.get("expectations", [])) for e in data["evals"]}


def check_expectation_coverage(tc: TestCase, declared: dict[int, int]) -> None:
    """Hält evals.json und run_tests.py in Deckung.

    evals.json hat schon einmal 50 Erwartungen deklariert, während
    run_tests.py 46 davon geprüft hat. Der Abgleich läuft nur bei sonst
    grünem Eval, weil ein fehlgeschlagener Test früh zurückkehrt und dann
    naturgemäß weniger Checks hat.
    """
    want = declared.get(tc.id)
    if want is None:
        tc.check(f"eval-{tc.id} is declared in evals.json", False,
                 "no matching entry in evals.json")
        return
    if tc.all_green and tc.total != want:
        tc.check(f"Implements all {want} expectations declared in evals.json",
                 False, f"implemented {tc.total}")


TESTS = {
    1: test_eval_1_wifi_guest,
    2: test_eval_2_disable_apple_intelligence,
    3: test_eval_3_classroom_ipad,
    4: test_eval_4_invalid_input_rejected,
    5: test_eval_5_list_payload_types,
    6: test_eval_6_unknown_top_level_key,
    7: test_eval_7_signing_error_paths,
    8: test_eval_8_profilemanifests_normalisierung,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval-id", type=int, help="Run one specific eval")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    eval_ids = [args.eval_id] if args.eval_id else sorted(TESTS.keys())
    declared = load_declared_expectations()

    print(bold(f"\nRunning mobileconfig-builder test suite "
               f"({len(eval_ids)} evals)\n"))

    cases: list[TestCase] = []
    with tempfile.TemporaryDirectory(prefix="mobileconfig-test-") as tdir:
        workdir = Path(tdir)
        for eid in eval_ids:
            try:
                tc = TESTS[eid](workdir)
            except Exception as e:
                tc = TestCase(eid, f"crashed: {type(e).__name__}")
                tc.check("Test runner did not crash", False, str(e))
            check_expectation_coverage(tc, declared)
            cases.append(tc)

    for tc in cases:
        tc.report(verbose=args.verbose)

    total_checks = sum(c.total for c in cases)
    total_passed = sum(c.passed for c in cases)
    failed_evals = sum(1 for c in cases if not c.all_green)

    print()
    if failed_evals == 0:
        print(green(bold(
            f"All {len(cases)} evals green  ({total_passed}/{total_checks} "
            f"checks passed)"
        )))
        return 0
    else:
        print(red(bold(
            f"{failed_evals} of {len(cases)} evals failed  "
            f"({total_passed}/{total_checks} checks passed)"
        )))
        return failed_evals


if __name__ == "__main__":
    sys.exit(main())
