# Changelog

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionsschema nach [Semantic Versioning](https://semver.org/lang/de/).

Die Version steht in der Datei `VERSION` im Repo-Root. Sie ist die einzige
Stelle, an der sie gepflegt wird: die CI prueft, dass hier ein Abschnitt mit
derselben Nummer existiert, und der Release-Workflow prueft, dass das Tag
`v<VERSION>` heisst.

## [0.1.0] - 2026-09-04

Erstes Release. Das Repo gab es vorher schon, veroeffentlicht war davon
nichts. Dieser Eintrag fasst zusammen, was seit dem ersten Stand repariert
wurde und was jetzt im Artefakt liegt.

### Behoben

- **Beide Skripte pruefen gegen dasselbe Schema.** 127 YAML-Dateien ergeben
  121 PayloadTypes, `com.apple.MCX` kommt in sechs Dateien vor,
  `com.apple.extensiblesso` in zwei. `inspect_payload.py` nahm den ersten
  Treffer, `build_mobileconfig.py` den letzten. Dasselbe Profil wurde also je
  nach Skript gegen ein anderes Schema geprueft: inspect empfahl
  `EnableGuestAccount`, der Build lehnte den Key unter `--validate-strict` ab.
  `fetch_schema.load_schema_map` vereint die Varianten jetzt, beide Skripte
  holen ihr Schema aus dieser einen Funktion. Wo Varianten sich
  widersprechen, gewinnt die weitere Fassung.
- **Erfundene Top-Level-Keys fallen unter `--validate-strict` durch.**
  Validiert wurde bisher nur `spec['payloads']`. Keys auf der Profil-Ebene
  liefen folgenlos durch, obwohl das Projekt zusagt, gegen Apples offizielles
  Schema zu validieren. `validate_top_level` prueft die fertige
  Profil-Struktur gegen `TopLevel.yaml` und meldet Befunde mit dem Praefix
  `top-level:`. Exit-Code 2, keine Ausgabedatei.
- **Der PyYAML-Auto-Install kommt auch mit altem pip zurecht.**
  `ensure_yaml` rief `pip install --quiet --break-system-packages
  pyyaml`. Die Option gibt es erst ab pip 23.0.1, das mit macOS
  ausgelieferte Python 3.9 bringt 21.2.4 mit: dort endete der erste
  inspect- oder build-Aufruf mit `no such option` und einem Traceback,
  statt PyYAML zu installieren. Jetzt laeuft erst der Aufruf ohne die
  Option, danach der mit ihr. Scheitern beide, steht die Ausgabe beider
  Anlaeufe da, nicht nur die des letzten, dazu der pip-Befehl von Hand,
  und der Aufruf endet mit Exit-Code 2.
- **Der Negativtest haengt an der Fehlermeldung.** Eval 4 akzeptierte jeden
  Exit-Code ungleich 0, ein Absturz vor der Validierung bestand den Test also
  genauso wie die Ablehnung, die er nachweisen soll. Verlangt sind jetzt
  Exit-Code 2, eine Meldung ab `Validation issues:` auf stderr und kein
  Python-Traceback.
- **Die Zahl der Payloads ist nachgezaehlt statt behauptet.**
  `fetch_schema.py --list` zeigt einen Eintrag pro PayloadType und nennt in
  der Kopfzeile die berechnete Typenzahl neben der Dateizahl. SKILL.md und
  die Landingpage verweisen auf diese Ausgabe.
- **`evals.json` und `run_tests.py` laufen nicht mehr auseinander.**
  `evals.json` deklarierte 50 Erwartungen, der Runner prueft 46. Die vier
  fehlenden sind umgesetzt, und der Runner vergleicht nach jedem gruenen Eval
  die Zahl der geprueften Checks mit der Zahl der deklarierten Erwartungen.
- **Der Titel eines vereinten Schemas nennt alle Varianten.** Fuer
  `com.apple.MCX` stand vorher nur der Titel der Basisdatei im Kopf, obwohl
  die Keys aus sechs Dateien stammen.
- **LICENSE nennt einen Rechteinhaber.** Der Apache-Platzhalter
  `Copyright [yyyy] [name of copyright owner]` ist ausgefuellt, README sagt
  nicht mehr MIT, wo die Lizenzdatei Apache-2.0 sagt. `NOTICE` haelt die
  Herkunft der Apple-Schemas fest.

### Hinzugekommen

- **CI** (`.github/workflows/ci.yml`): Eval-Suite mit sechs Faellen, ein Build
  mit erfundenem Top-Level-Key ueber die Kommandozeile, die Schema-Inspektion
  des Wi-Fi-Payloads und ein Secret-Scan. Der Schema-Stand von
  `apple/device-management` ist auf eine Commit-SHA gepinnt, damit eine
  Aenderung bei Apple die CI nicht ohne eigenes Zutun rot faerbt.
- **`tools/scan_secrets.py`**: sucht in den versionierten Dateien nach
  eingecheckten Profilen, Schluesseldateien, PEM-Bloecken und Werten hinter
  Passwort-Keys. Die erfundenen Passwoerter der Beispiel-Specs stehen in
  einer Allowlist, jeder andere Wert faellt auf.
- **`.gitignore`** deckt `*.mobileconfig`, Signier-Material und
  `__pycache__` ab. Der Quickstart schreibt die Ausgabedatei ins Repo-Root,
  und die enthaelt das WLAN-Passwort im Klartext.
- **`scripts/package_release.py`** baut das Release-Artefakt aus den
  versionierten Dateien, ohne Netz, zweimal hintereinander mit demselben
  Ergebnis.
- **Release-Workflow** (`.github/workflows/release.yml`): reagiert auf ein
  Tag `v*`, prueft Tag gegen `VERSION`, ruft das Packaging-Skript auf und
  haengt das Ergebnis an das Release.
