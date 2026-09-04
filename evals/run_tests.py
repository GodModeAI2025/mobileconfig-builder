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
              strict: bool = True, expect_fail: bool = False
              ) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable, str(SCRIPTS / "build_mobileconfig.py"),
        str(spec_path),
        "-o", str(out_path),
        "--offline",
    ]
    if strict:
        cmd.append("--validate-strict")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def load_plist(path: Path) -> dict:
    with path.open("rb") as f:
        return plistlib.load(f)


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

    tc.check("Build exits with non-zero code in strict mode",
             proc.returncode != 0, f"returncode={proc.returncode}")
    err = proc.stderr + proc.stdout
    tc.check("Error mentions 'EncryptionType'", "EncryptionType" in err,
             dim(err[:200]))
    tc.check("Error mentions allowed values or invalid value",
             "SUPERWPA" in err or "WPA2" in err or "WPA3" in err)
    tc.check("Error mentions 'AutoJoin'", "AutoJoin" in err)
    tc.check("Error mentions boolean type mismatch",
             "boolean" in err.lower() or "<boolean>" in err)
    tc.check("No output file was created", not out.exists())
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


# ─── Runner ────────────────────────────────────────────────────────────────
TESTS = {
    1: test_eval_1_wifi_guest,
    2: test_eval_2_disable_apple_intelligence,
    3: test_eval_3_classroom_ipad,
    4: test_eval_4_invalid_input_rejected,
    5: test_eval_5_list_payload_types,
    6: test_eval_6_unknown_top_level_key,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval-id", type=int, help="Run one specific eval")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    eval_ids = [args.eval_id] if args.eval_id else sorted(TESTS.keys())

    print(bold(f"\nRunning mobileconfig-builder test suite "
               f"({len(eval_ids)} evals)\n"))

    cases: list[TestCase] = []
    with tempfile.TemporaryDirectory(prefix="mobileconfig-test-") as tdir:
        workdir = Path(tdir)
        for eid in eval_ids:
            try:
                cases.append(TESTS[eid](workdir))
            except Exception as e:
                tc = TestCase(eid, f"crashed: {type(e).__name__}")
                tc.check(f"Test runner did not crash", False, str(e))
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
