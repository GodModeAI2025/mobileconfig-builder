#!/usr/bin/env python3
"""
fetch_schema.py — Lädt Apple device-management Profil-Schemas und cached sie lokal.

Quelle: https://github.com/apple/device-management (release branch).
Es existiert KEIN separater Beta-Branch öffentlich — Apple veröffentlicht
neue OS-Versionen direkt im release branch. Falls künftig ein Beta-Branch
erscheint, kann dieser über --branch beta angefordert werden.

Usage:
    python3 fetch_schema.py                 # alle Profile-Schemas (cached)
    python3 fetch_schema.py --refresh       # Cache neu laden
    python3 fetch_schema.py --branch release  # explizit Branch wählen
    python3 fetch_schema.py --list          # nur PayloadTypes auflisten
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

GITHUB_API = "https://api.github.com/repos/apple/device-management/contents/mdm/profiles"
RAW_BASE = "https://raw.githubusercontent.com/apple/device-management"
CACHE_DIR = Path.home() / ".cache" / "mobileconfig-builder"


def ensure_yaml():
    try:
        import yaml  # noqa: F401
        return
    except ImportError:
        print("Installing PyYAML…", file=sys.stderr)
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "--quiet", "--break-system-packages", "pyyaml"])


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "mobileconfig-builder"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def list_remote_profiles(branch: str) -> list[str]:
    """Liste aller .yaml Dateien im mdm/profiles/ Verzeichnis."""
    url = f"{GITHUB_API}?ref={branch}"
    try:
        data = json.loads(http_get(url))
    except urllib.error.HTTPError as e:
        if e.code == 404 and branch != "release":
            raise SystemExit(
                f"Branch '{branch}' existiert nicht. Bekannter Branch: 'release'."
            )
        raise
    return sorted(item["name"] for item in data
                  if item["name"].endswith(".yaml"))


def list_cached_profiles(branch: str) -> list[str]:
    cdir = CACHE_DIR / branch
    if not cdir.is_dir():
        return []
    return sorted(p.name for p in cdir.glob("*.yaml"))


def cache_path(branch: str, filename: str) -> Path:
    return CACHE_DIR / branch / filename


def fetch_profile(branch: str, filename: str, refresh: bool = False,
                  offline: bool = False) -> str:
    cp = cache_path(branch, filename)
    if cp.exists() and not refresh:
        return cp.read_text(encoding="utf-8")
    if offline:
        raise FileNotFoundError(
            f"{filename} not in cache and --offline is set"
        )
    url = f"{RAW_BASE}/{branch}/mdm/profiles/{filename}"
    body = http_get(url).decode("utf-8")
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(body, encoding="utf-8")
    return body


def fetch_all(branch: str, refresh: bool = False,
              offline: bool = False) -> dict[str, str]:
    """Lädt alle Profile-YAMLs, gibt {filename: content} zurück.

    Bei offline=True wird ausschließlich der lokale Cache benutzt.
    Wenn weder Netz noch Cache verfügbar sind, wird ein klarer Fehler geworfen.
    """
    if offline:
        files = list_cached_profiles(branch)
        if not files:
            raise SystemExit(
                f"Offline-Modus, aber kein Cache für branch '{branch}' "
                f"unter {CACHE_DIR / branch}. "
                "Erst einmal online laden oder --from-clone benutzen."
            )
    else:
        try:
            files = list_remote_profiles(branch)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            cached = list_cached_profiles(branch)
            if cached:
                print(f"Network unreachable ({e}); using cached schema.",
                      file=sys.stderr)
                files = cached
            else:
                raise
    out = {}
    for f in files:
        try:
            out[f] = fetch_profile(branch, f, refresh=refresh,
                                   offline=offline)
        except Exception as e:
            print(f"  WARN: {f}: {e}", file=sys.stderr)
    return out


def index_payloads(branch: str, refresh: bool = False,
                   offline: bool = False) -> list[dict]:
    """Erzeugt einen Index: payloadtype → filename + Metadaten."""
    ensure_yaml()
    import yaml
    files = fetch_all(branch, refresh=refresh, offline=offline)
    index = []
    for filename, body in files.items():
        try:
            doc = yaml.safe_load(body)
        except yaml.YAMLError:
            continue
        if not isinstance(doc, dict):
            continue
        payload = doc.get("payload", {}) or {}
        ptype = payload.get("payloadtype")
        if not ptype:
            # Skip helper files like TopLevel / CommonPayloadKeys
            if filename in ("TopLevel.yaml", "CommonPayloadKeys.yaml",
                            "GlobalPreferences.yaml"):
                index.append({
                    "filename": filename,
                    "payloadtype": filename.replace(".yaml", ""),
                    "title": doc.get("title", ""),
                    "description": doc.get("description", ""),
                    "supportedOS": list((payload.get("supportedOS") or {}).keys()),
                    "is_helper": True,
                })
            continue
        index.append({
            "filename": filename,
            "payloadtype": ptype,
            "title": doc.get("title", ""),
            "description": doc.get("description", ""),
            "supportedOS": list((payload.get("supportedOS") or {}).keys()),
            "is_helper": False,
        })
    return sorted(index, key=lambda x: x["payloadtype"])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--branch", default="release",
                    help="Git-Branch (default: release)")
    ap.add_argument("--refresh", action="store_true",
                    help="Cache neu laden")
    ap.add_argument("--offline", action="store_true",
                    help="Nur Cache benutzen, kein Netz-Zugriff")
    ap.add_argument("--from-clone", type=Path,
                    help="Cache aus einem lokalen Clone von "
                         "apple/device-management befüllen "
                         "(Pfad zum Repo-Root)")
    ap.add_argument("--list", action="store_true",
                    help="Nur Index der verfügbaren PayloadTypes ausgeben")
    ap.add_argument("--json", action="store_true",
                    help="Index als JSON statt Text")
    args = ap.parse_args()

    if args.from_clone:
        src = args.from_clone / "mdm" / "profiles"
        if not src.is_dir():
            raise SystemExit(f"Not a device-management clone: {args.from_clone}")
        dst = CACHE_DIR / args.branch
        dst.mkdir(parents=True, exist_ok=True)
        n = 0
        for f in src.glob("*.yaml"):
            (dst / f.name).write_bytes(f.read_bytes())
            n += 1
        print(f"Populated cache from {src} ({n} files)", file=sys.stderr)
        if not args.list:
            return

    if args.list:
        idx = index_payloads(args.branch, refresh=args.refresh,
                             offline=args.offline)
        if args.json:
            print(json.dumps(idx, indent=2, ensure_ascii=False))
        else:
            print(f"# Apple device-management — branch: {args.branch}")
            print(f"# {len(idx)} schema files\n")
            for item in idx:
                if item["is_helper"]:
                    continue
                oss = ",".join(item["supportedOS"]) or "—"
                print(f"  {item['payloadtype']:<55} [{oss}]  {item['title']}")
        return

    files = fetch_all(args.branch, refresh=args.refresh,
                      offline=args.offline)
    print(f"Cached {len(files)} schema files in {CACHE_DIR / args.branch}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
