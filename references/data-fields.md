# Data-Felder (`<data>`) in der Spec

Schema-Type `<data>` heißt: an dieser Stelle erwartet die Plist Bytes (z.B. ein DER-encoded Zertifikat).

In JSON gibt es keinen nativen Bytes-Typ. Drei Lösungen:

## Option 1: Base64-Marker in der Spec

```json
{
  "PayloadContent": {"__base64__": "MIIDXTCCAkWgAwIBAgIJAL..."}
}
```

Vor dem Aufruf von `build_mobileconfig.py` mit einem kleinen Pre-Processor lösen:

```python
import json, base64, sys

def resolve(o):
    if isinstance(o, dict):
        if list(o.keys()) == ["__base64__"]:
            return base64.b64decode(o["__base64__"])
        return {k: resolve(v) for k, v in o.items()}
    if isinstance(o, list):
        return [resolve(x) for x in o]
    return o

spec = json.load(open(sys.argv[1]))
spec = resolve(spec)
# spec is now ready, but JSON can't hold bytes — pass as plist or pickle
```

## Option 2: YAML mit `!!binary`

YAML hat einen Binary-Tag:

```yaml
PayloadContent: !!binary |
  MIIDXTCCAkWgAwIBAgIJAL...
```

`PyYAML` lädt das als `bytes`. `build_mobileconfig.py` kann YAML direkt verarbeiten — dann ist das die einfachste Variante.

## Option 3: Datei-Referenz

```json
{ "PayloadContent": {"__file__": "ca.cer"} }
```

Dafür braucht's einen Pre-Processor, der die Datei einliest und in Bytes konvertiert. Diese Variante ist im aktuellen `build_mobileconfig.py` nicht implementiert — eine sinnvolle Erweiterung.

## Aktueller Status im Skill

`build_mobileconfig.py` validiert `<data>`-Felder typgerecht (akzeptiert `bytes`/`bytearray`), aber implementiert noch keinen automatischen Base64-Resolver. Wenn ein User Zertifikat-Inhalt unterbringen muss:
1. Entweder Spec als YAML schreiben mit `!!binary`-Tag.
2. Oder Claude erzeugt vor dem Build mit einem kurzen Helper-Skript einen aufgelösten JSON-Spec.
