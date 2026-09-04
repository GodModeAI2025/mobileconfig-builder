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
  2. Validiert jede Payload gegen das Apple-Schema (required keys, types, ranges).
  3. Ergänzt fehlende Pflichtfelder (PayloadIdentifier, PayloadUUID, PayloadVersion)
     deterministisch.
  4. Schreibt eine binäre+lesbare XML-Plist mit Endung .mobileconfig.
  5. (Optional) Signiert mit OpenSSL, wenn cert/key übergeben werden.

Usage:
    python3 build_mobileconfig.py spec.json -o profile.mobileconfig
    python3 build_mobileconfig.py spec.yaml -o profile.mobileconfig --validate-strict
    python3 build_mobileconfig.py spec.json -o p.mobileconfig --sign-cert cert.pem --sign-key key.pem
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
from fetch_schema import ensure_yaml, load_schema_map  # noqa: E402

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


def get_schema(payloadtype: str, branch: str) -> dict | None:
    return load_all_schemas(branch).get(payloadtype)


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
                     strict: bool = False) -> list[str]:
    """Returns list of error strings; empty means valid."""
    errors: list[str] = []
    ptype = payload.get("PayloadType")
    if not ptype:
        return ["payload: missing PayloadType"]
    schema = get_schema(ptype, branch)
    if schema is None:
        return [
            f"payload: unknown PayloadType '{ptype}' "
            f"(no schema in branch '{branch}')"
        ]
    # Combine payload-specific keys with the CommonPayloadKeys
    # so PayloadType/UUID/Identifier/etc. are not flagged as "unknown".
    keydefs = list(schema.get("payloadkeys", []) or [])
    keydefs += get_common_keys(branch)
    _check_keys(payload, keydefs, ptype, errors, strict)
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
                  offline: bool = False) -> tuple[dict, list[str]]:
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
            errs = validate_payload(p, branch, strict=strict)
            for e in errs:
                all_errors.append(f"payloads[{i}] {e}")
        final_payloads.append(p)

    profile = dict(meta)
    profile["PayloadContent"] = final_payloads
    return profile, all_errors


# ─────────────────────────────────────────────────────────────────────────────
# Optional signing
# ─────────────────────────────────────────────────────────────────────────────
def sign_profile(unsigned_path: Path, signed_path: Path,
                 cert: Path, key: Path,
                 ca_chain: Path | None = None) -> None:
    """Use openssl smime to sign the profile (CMS / PKCS#7 detached → embedded)."""
    cmd = [
        "openssl", "smime", "-sign", "-signer", str(cert),
        "-inkey", str(key), "-nodetach", "-outform", "der",
        "-in", str(unsigned_path), "-out", str(signed_path),
    ]
    if ca_chain:
        cmd += ["-certfile", str(ca_chain)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SchemaError(f"openssl signing failed: {proc.stderr}")


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
    ap.add_argument("--sign-cert", type=Path,
                    help="X.509-Zertifikat (PEM) zum Signieren")
    ap.add_argument("--sign-key", type=Path,
                    help="Privater Schlüssel (PEM) zum Signieren")
    ap.add_argument("--sign-ca", type=Path,
                    help="CA-Chain (PEM, optional)")
    args = ap.parse_args()

    spec = load_spec(args.spec)
    profile, errors = build_profile(
        spec, branch=args.branch,
        strict=args.validate_strict,
        validate=not args.no_validate,
        offline=args.offline,
    )

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

    if args.sign_cert and args.sign_key:
        # Write unsigned to a tmp file, then sign.
        tmp = args.output.with_suffix(".unsigned.mobileconfig")
        with tmp.open("wb") as f:
            plistlib.dump(profile, f, fmt=plistlib.FMT_XML)
        sign_profile(tmp, args.output, args.sign_cert, args.sign_key,
                     args.sign_ca)
        tmp.unlink()
        print(f"✓ Signed profile written to {args.output}")
    elif args.sign_cert or args.sign_key:
        sys.exit("--sign-cert and --sign-key must be used together")
    else:
        with args.output.open("wb") as f:
            plistlib.dump(profile, f, fmt=plistlib.FMT_XML)
        print(f"✓ Unsigned profile written to {args.output}")
        print("  (Apple-Geräte zeigen 'Nicht signiert' beim Install — "
              "für produktiven Einsatz mit --sign-cert/--sign-key signieren.)")


if __name__ == "__main__":
    main()
