#!/usr/bin/env python3
"""
fetch_schema.py — Lädt Apple device-management Profil-Schemas und cached sie lokal.

Quelle: https://github.com/apple/device-management (Branch release).
Neben release veröffentlicht Apple einen Seed-Branch für die kommende
OS-Generation, derzeit seed_OS_27_0. Default bleibt release; der Seed-Stand
kommt über --branch seed_OS_27_0 und landet in einem eigenen Cache-Ordner.
Welche Branches es gerade gibt, zeigt
  git ls-remote --heads https://github.com/apple/device-management.git

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
    """Sorgt dafür, dass PyYAML importierbar ist, sonst Abbruch mit Exit 2.

    Zwei Anläufe, weil kein einzelner Aufruf überall durchkommt: pip kennt
    --break-system-packages erst ab 23.0.1, das mit macOS ausgelieferte
    Python 3.9 bringt 21.2.4 mit und bricht an der unbekannten Option ab.
    Ein von der Distribution verwaltetes Python wiederum weist die
    Installation ohne diese Option zurück. Also erst ohne, dann mit. Wenn
    beides scheitert, kommt eine Meldung statt eines Tracebacks.
    """
    try:
        import yaml  # noqa: F401
        return
    except ImportError:
        pass

    print("Installing PyYAML…", file=sys.stderr)
    import importlib
    import subprocess
    basis = [sys.executable, "-m", "pip", "install", "--quiet", "pyyaml"]
    fehlschlaege = []
    for befehl in (basis, basis + ["--break-system-packages"]):
        try:
            subprocess.run(befehl, check=True, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as exc:
            fehlschlaege.append((befehl, exc.stderr))
            continue
        importlib.invalidate_caches()
        return

    # Beide Anlaeufe, nicht nur der letzte: auf altem pip scheitert der zweite
    # immer an der unbekannten Option, und diese Meldung wuerde den
    # eigentlichen Grund des ersten Anlaufs verdecken.
    for befehl, ausgabe in fehlschlaege:
        print("Fehlgeschlagen: %s" % " ".join(befehl), file=sys.stderr)
        if ausgabe:
            sys.stderr.write(ausgabe.decode("utf-8", "replace"))
    print("PyYAML fehlt und liess sich nicht automatisch installieren. "
          "Bitte von Hand nachziehen:\n"
          f"  {sys.executable} -m pip install pyyaml", file=sys.stderr)
    raise SystemExit(2)


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
                f"Branch '{branch}' existiert nicht. Bekannt sind 'release' "
                f"und der jeweilige Seed-Branch, z.B. 'seed_OS_27_0'. "
                f"Aktuelle Liste: git ls-remote --heads "
                f"https://github.com/apple/device-management.git"
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


def parse_all(branch: str, refresh: bool = False,
              offline: bool = False) -> dict[str, dict]:
    """Lädt alle Profil-YAMLs und gibt {filename: geparstes Dokument} zurück."""
    ensure_yaml()
    import yaml
    out: dict[str, dict] = {}
    for filename, body in fetch_all(branch, refresh=refresh,
                                    offline=offline).items():
        try:
            doc = yaml.safe_load(body)
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict):
            out[filename] = doc
    return out


def _merge_keydef(variants: list[dict], variant_count: int) -> dict:
    """Fasst die Definitionen desselben Keys aus mehreren Varianten zusammen.

    Die erste Definition (aus der Basisdatei) gibt die Struktur vor.
    Wo Varianten sich widersprechen, gewinnt immer die weitere Fassung,
    damit die Vereinigung kein Profil ablehnt, das gegen eine einzelne
    Variante gültig wäre.
    """
    merged = dict(variants[0])

    # required nur, wenn jede beteiligte Datei den Key kennt und verlangt
    if len(variants) < variant_count or \
            any(v.get("presence") != "required" for v in variants):
        if merged.get("presence") == "required":
            merged["presence"] = "optional"

    # rangelist: Vereinigung, aber nur wenn jede Variante eine Liste vorgibt
    if all("rangelist" in v for v in variants):
        values: list = []
        for v in variants:
            for item in v["rangelist"]:
                if item not in values:
                    values.append(item)
        merged["rangelist"] = values
    else:
        merged.pop("rangelist", None)

    # range: weitester gemeinsamer Bereich
    if all("range" in v for v in variants):
        mins = [(v["range"] or {}).get("min") for v in variants]
        maxs = [(v["range"] or {}).get("max") for v in variants]
        widened: dict = {}
        if all(m is not None for m in mins):
            widened["min"] = min(mins)
        if all(m is not None for m in maxs):
            widened["max"] = max(maxs)
        if widened:
            merged["range"] = widened
        else:
            merged.pop("range", None)
    else:
        merged.pop("range", None)

    # format: nur behalten, wenn alle Varianten dieselbe Regex vorgeben
    formats = {v.get("format") for v in variants}
    if len(formats) != 1 or None in formats:
        merged.pop("format", None)

    return merged


def merge_schema_variants(payloadtype: str,
                          docs_by_file: dict[str, dict]) -> dict:
    """Vereint mehrere YAML-Dateien mit demselben payloadtype zu einem Schema.

    Apple vergibt denselben payloadtype an mehrere Dateien: com.apple.MCX
    kommt in sechs Varianten vor (Accounts, EnergySaver, FileVault2,
    Mobility, TimeServer, WiFi), com.apple.extensiblesso in zwei (generisch
    und Kerberos). Ein Payload dieses Typs darf Keys aus jeder Variante
    tragen. Wer eine einzelne Datei auswählt, weist gültige Profile zurück,
    deshalb ist die Vereinigung die einzige Auflösung, die keine falschen
    Fehler erzeugt. Das Ergebnis trägt die Herkunft in `_sources`.
    """
    filenames = sorted(docs_by_file)
    base_name = f"{payloadtype}.yaml"
    if base_name in docs_by_file:
        filenames.remove(base_name)
        filenames.insert(0, base_name)

    merged = dict(docs_by_file[filenames[0]])
    merged["_sources"] = filenames
    if len(filenames) == 1:
        return merged

    order: list[str] = []
    variants: dict[str, list[dict]] = {}
    for filename in filenames:
        for kdef in docs_by_file[filename].get("payloadkeys") or []:
            if not isinstance(kdef, dict) or not kdef.get("key"):
                continue
            name = kdef["key"]
            if name not in variants:
                variants[name] = []
                order.append(name)
            variants[name].append(kdef)

    merged["payloadkeys"] = [
        _merge_keydef(variants[name], len(filenames)) for name in order
    ]

    # Titel und Beschreibung der Basisdatei beschreiben nur eine Variante und
    # wären für die Vereinigung schlicht falsch.
    titles = [docs_by_file[f].get("title", "") for f in filenames]
    merged["title"] = " + ".join(t for t in titles if t)
    descriptions = {docs_by_file[f].get("description", "") for f in filenames}
    if len(descriptions) > 1:
        merged["description"] = ""
    return merged


def load_schema_map(branch: str, refresh: bool = False,
                    offline: bool = False) -> dict[str, dict]:
    """payloadtype → Schema-Dokument, kollidierende Dateien vereint.

    Gemeinsame Grundlage für inspect_payload.py und build_mobileconfig.py:
    beide sehen damit für jeden PayloadType dasselbe Schema.
    """
    docs = parse_all(branch, refresh=refresh, offline=offline)
    by_type: dict[str, dict[str, dict]] = {}
    for filename, doc in docs.items():
        ptype = (doc.get("payload") or {}).get("payloadtype")
        if not ptype:
            continue
        by_type.setdefault(ptype, {})[filename] = doc
    return {ptype: merge_schema_variants(ptype, group)
            for ptype, group in by_type.items()}


def index_payloads(branch: str, refresh: bool = False,
                   offline: bool = False) -> list[dict]:
    """Erzeugt einen Index: payloadtype → Quelldateien + Metadaten.

    Ein Eintrag pro PayloadType, nicht pro Datei. Alle Dateien unter
    mdm/profiles/ tragen einen payloadtype, auch TopLevel und
    CommonPayloadKeys, deshalb bleibt is_helper hier False.
    """
    index = []
    for ptype, doc in load_schema_map(branch, refresh=refresh,
                                      offline=offline).items():
        payload = doc.get("payload", {}) or {}
        sources = doc.get("_sources", [])
        index.append({
            "filename": ", ".join(sources),
            "sources": sources,
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
            n_files = sum(len(item["sources"]) for item in idx)
            print(f"# Apple device-management — branch: {args.branch}")
            print(f"# {len(idx)} payload types from {n_files} schema files\n")
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
