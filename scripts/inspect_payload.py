#!/usr/bin/env python3
"""
inspect_payload.py — Zeigt die Payload-Keys eines Profile-Types.

Nutzt das gecachte YAML-Schema von apple/device-management. Gibt eine
strukturierte Beschreibung aus, mit der ein User (oder Claude im
Interview-Flow) entscheiden kann, welche Werte gesetzt werden müssen.

Usage:
    python3 inspect_payload.py com.apple.wifi.managed
    python3 inspect_payload.py com.apple.wifi.managed --os macOS
    python3 inspect_payload.py com.apple.wifi.managed --required-only
    python3 inspect_payload.py com.apple.wifi.managed --json
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Reuse fetch_schema utilities
sys.path.insert(0, str(Path(__file__).parent))
from fetch_schema import (  # noqa: E402
    MANIFESTS_REF,
    index_payloads,
    load_manifest_schema,
    load_schema_map,
)


def find_schema(payloadtype: str, branch: str, refresh: bool = False,
                offline: bool = False, manifeste: dict | None = None):
    """Gibt (Quelldateien, Schema-Dokument) zurück.

    Nutzt dieselbe Auflösung wie build_mobileconfig.py: Dateien, die sich
    einen payloadtype teilen, werden vereint statt willkürlich ausgewählt,
    und Apple gewinnt vor ProfileManifests.
    """
    schemas = load_schema_map(branch, refresh=refresh, offline=offline)
    doc = schemas.get(payloadtype)
    if doc is None and manifeste is not None:
        doc = load_manifest_schema(payloadtype, refresh=refresh, **manifeste)
    if doc is None:
        return [], None
    return doc.get("_sources", []), doc


def fmt_type(key: dict) -> str:
    t = key.get("type", "<any>")
    vt = key.get("valuetype")
    sub = key.get("subtype")
    extras = []
    if vt:
        extras.append(f"valuetype={vt}")
    elif sub:
        extras.append(f"subtype={sub}")
    if "rangelist" in key:
        rl = key["rangelist"]
        rl_str = ", ".join(repr(x) for x in rl[:5])
        if len(rl) > 5:
            rl_str += ", …"
        extras.append(f"oneOf=[{rl_str}]")
    if "range" in key:
        r = key["range"]
        extras.append(f"range={r.get('min','?')}–{r.get('max','?')}")
    if "default" in key:
        extras.append(f"default={key['default']!r}")
    return t + (" (" + "; ".join(extras) + ")" if extras else "")


def supported_on_os(item: dict, os_name: str | None,
                    inherited: dict | None = None) -> bool:
    """Prüft ob ein key/payload auf der gewünschten OS unterstützt wird."""
    if not os_name:
        return True
    so = (item.get("supportedOS") or {})
    base = (inherited or {}).get(os_name)
    own = so.get(os_name)
    # If neither base nor own says anything → assume not supported
    if base is None and own is None:
        return False
    # If "removed" → skip
    if own and own.get("removed"):
        return False
    return True


def render_keys(keys: list[dict], indent: int = 0,
                os_name: str | None = None,
                inherited_os: dict | None = None,
                required_only: bool = False,
                lines: list[str] | None = None) -> list[str]:
    if lines is None:
        lines = []
    pad = "  " * indent
    for key in keys or []:
        if not isinstance(key, dict):
            continue
        if not supported_on_os(key, os_name, inherited_os):
            continue
        if required_only and key.get("presence") != "required":
            # Always descend into required containers; skip purely optional
            if not key.get("subkeys"):
                continue
        name = key.get("key", "?")
        if name == "ANY":
            lines.append(f"{pad}<ANY> — beliebige Sub-Keys erlaubt")
            continue
        marker = "*" if key.get("presence") == "required" else " "
        title = key.get("title", "")
        title_part = f" — {title}" if title else ""
        lines.append(f"{pad}{marker} {name}: {fmt_type(key)}{title_part}")
        content = key.get("content")
        if content and indent < 3:
            short = content.replace("\n", " ").strip()
            if len(short) > 140:
                short = short[:137] + "…"
            lines.append(f"{pad}    » {short}")
        if key.get("subkeys"):
            render_keys(key["subkeys"], indent + 1, os_name,
                        inherited_os, required_only, lines)
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("payloadtype", help="z.B. com.apple.wifi.managed")
    ap.add_argument("--branch", default="release")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--offline", action="store_true",
                    help="Nur Cache benutzen, kein Netz-Zugriff")
    ap.add_argument("--os", choices=["iOS", "macOS", "tvOS", "visionOS", "watchOS"],
                    help="Nur Keys ausgeben die auf dieser OS unterstützt werden")
    ap.add_argument("--required-only", action="store_true",
                    help="Nur required-Keys zeigen")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--manifests", action="store_true",
                    help="Zweite Schema-Quelle ProfileManifests zulassen, "
                         "fuer Domains, die Apple nicht beschreibt")
    ap.add_argument("--manifests-ref", default=MANIFESTS_REF,
                    help=f"Branch, Tag oder Commit von ProfileManifests "
                         f"(default: {MANIFESTS_REF})")
    args = ap.parse_args()

    manifeste = None
    if args.manifests:
        manifeste = {"ref": args.manifests_ref, "offline": args.offline}

    sources, doc = find_schema(args.payloadtype, args.branch,
                               refresh=args.refresh, offline=args.offline,
                               manifeste=manifeste)
    if doc is None:
        # fuzzy hint
        idx = index_payloads(args.branch, offline=args.offline)
        cands = [i for i in idx if args.payloadtype.lower() in i["payloadtype"].lower()]
        msg = f"Schema für PayloadType '{args.payloadtype}' nicht gefunden."
        if manifeste is None and not args.payloadtype.startswith("com.apple."):
            msg += ("\nApples Schema beschreibt nur Apple-Domains. Fuer "
                    "Drittanbieter --manifests versuchen.")
        if cands:
            msg += "\nMeintest du:\n  " + "\n  ".join(c["payloadtype"]
                                                       for c in cands[:10])
        raise SystemExit(msg)

    payload = doc.get("payload", {}) or {}
    inherited_os = payload.get("supportedOS") or {}

    if args.json:
        print(json.dumps({
            "filename": ", ".join(sources),
            "sources": sources,
            "payloadtype": payload.get("payloadtype"),
            "title": doc.get("title"),
            "description": doc.get("description"),
            "supportedOS": list(inherited_os.keys()),
            "supportedOS_detail": inherited_os,
            "origin": doc.get("_origin", "apple/device-management"),
            "payloadkeys": doc.get("payloadkeys", []),
        }, indent=2, ensure_ascii=False))
        return

    print(f"# {doc.get('title','')}  ({payload.get('payloadtype')})")
    label = "Sources" if len(sources) > 1 else "Source"
    print(f"# {label}: {', '.join(sources)}")
    if doc.get("_origin") == "ProfileManifests":
        print("# Herkunft: ProfileManifests, gepflegt von Mac-Admins, nicht "
              "von Apple, ohne Lizenzangabe.")
        print("# Nicht uebernommen werden pfm_conditionals, pfm_exclude, "
              "pfm_targets und pfm_app_min.")
    if len(sources) > 1:
        print(f"# {len(sources)} Schema-Dateien teilen sich diesen "
              f"PayloadType, die Keys sind hier vereint.")
    if doc.get("description"):
        print(f"# {doc['description']}")
    print(f"# Supported on: {', '.join(inherited_os.keys())}")
    if args.os:
        print(f"# Filter: {args.os}")
    if args.required_only:
        print("# Showing required keys only (with their containers)")
    print()
    print("Legende:  *=required  — keinMarker=optional")
    print()
    lines = render_keys(doc.get("payloadkeys", []),
                        os_name=args.os, inherited_os=inherited_os,
                        required_only=args.required_only)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
