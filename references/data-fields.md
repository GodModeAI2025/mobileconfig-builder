# Daten-Felder (`<data>`) in der Spec

Schema-Type `<data>` heißt: an dieser Stelle erwartet die Plist Bytes, etwa
ein DER-kodiertes Zertifikat. Betroffen sind
`com.apple.security.root`, `.pkcs1`, `.pkcs12` und alles andere, was ein
Zertifikat oder einen Token trägt.

JSON kennt keinen Bytes-Typ. Deshalb gibt es zwei Marker, die
`build_mobileconfig.py` vor der Validierung auflöst, und für YAML zusätzlich
den eingebauten Binary-Tag.

## `__base64__`: die Bytes stehen in der Spec

```json
{
  "PayloadType": "com.apple.security.root",
  "PayloadCertificateFileName": "ca.cer",
  "PayloadContent": {"__base64__": "MIIDXTCCAkWgAwIBAgIJAL..."}
}
```

Zeilenumbrüche und Leerzeichen sind erlaubt und fliegen vor dem Dekodieren
raus. Das ist genau das Format, das zwischen den BEGIN- und END-Zeilen einer
PEM-Datei steht, und auch das, was `base64 < ca.der` ausgibt.

## `__file__`: die Bytes stehen in einer Datei

```json
{
  "PayloadType": "com.apple.security.root",
  "PayloadCertificateFileName": "ca.cer",
  "PayloadContent": {"__file__": "ca.der"}
}
```

Ein relativer Pfad zählt vom Verzeichnis der Spec aus, nicht vom
Arbeitsverzeichnis. Dieselbe Spec ergibt damit aus jedem Verzeichnis heraus
dasselbe Profil. `~` wird aufgelöst, ein absoluter Pfad bleibt, wie er ist.

## YAML: `!!binary`

```yaml
payloads:
  - PayloadType: com.apple.security.pkcs12
    PayloadContent: !!binary |
      MIIDXTCC...
```

PyYAML macht daraus Bytes, bevor der Builder die Spec überhaupt sieht. Die
beiden Marker funktionieren in einer YAML-Spec trotzdem.

## Regeln, die für beide Marker gelten

Aufgelöst wird im ganzen Spec-Baum, in beliebiger Tiefe, in Dictionaries und
in Listen, und zwar bevor validiert wird. Die Auflösung fragt nicht, was das
Schema an der Stelle erwartet: sie müsste dafür das Schema kennen, bevor die
Spec steht. Wer einen Marker an eine Stelle setzt, an der Bytes nichts
verloren haben, bekommt das von der Validierung gesagt, als
`expected <string>, got bytes`.

Der Marker ersetzt sein ganzes Dictionary. Neben ihm darf kein weiterer Key
stehen, und beide Marker zusammen sind ebenfalls ein Abbruch, weil sonst
geraten werden müsste, welcher gilt.

Ein nackter Base64-String ohne Marker bleibt eine Zeichenkette. Das ist
Absicht: eine Zeichenkette, die zufällig wie Base64 aussieht, ist nicht
zwangsläufig als Bytes gemeint. Sie fällt weiter als
`expected <data>, got str` durch.

Fehler enden mit Exit-Code 2, mit einer Meldung, die die Stelle in der Spec
nennt, und ohne dass eine Datei entsteht:

```
FEHLER: payloads[0].PayloadContent: der Wert hinter __base64__ ist kein
gueltiges Base64 (Non-base64 digit found).
```

## Was die Marker nicht prüfen

Sie kopieren Bytes. Ob dahinter ein Zertifikat steckt, prüft niemand: eine
PEM-Datei landet als PEM-Bytes im Profil, und Apple erwartet an einem
Zertifikats-Payload DER. Vorher umwandeln:

```bash
openssl x509 -in ca.pem -outform der -out ca.der
```

`__file__` liest, was im Pfad steht, ohne Größengrenze. Die Bytes stehen
danach im Profil, im Klartext, wie jedes andere Feld auch. Für Passwörter
und private Schlüssel gilt derselbe Satz wie überall in diesem Repo: ein
unverschlüsseltes Profil ist kein Ort für Geheimnisse, die niemand sehen
soll.

Gelesen wird jeder Pfad, den der aufrufende Prozess lesen darf. `~` wird
aufgelöst, ein absoluter Pfad bleibt stehen, und eine Erlaubnisliste gibt es
nicht. Eine Spec ist damit so vertrauenswürdig wie ihre Quelle: eine Spec,
die jemand anders geschrieben hat, gehört vor dem Build auf `__file__`
durchgesehen, sonst holt sie mit `{"__file__": "~/.ssh/id_rsa"}` eine Datei
ins Profil, die dort nichts verloren hat.

## Prüfen, was herausgekommen ist

```bash
python3 scripts/validate_mobileconfig.py profil.mobileconfig --strict
python3 -c "import plistlib; \
  print(len(plistlib.load(open('profil.mobileconfig','rb'))\
['PayloadContent'][0]['PayloadContent']), 'Bytes')"
```
