# Changelog

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionsschema nach [Semantic Versioning](https://semver.org/lang/de/).

Die Version steht in der Datei `VERSION` im Repo-Root. Sie ist die einzige
Stelle, an der sie gepflegt wird: die CI prueft, dass hier ein Abschnitt mit
derselben Nummer existiert, und der Release-Workflow prueft, dass das Tag
`v<VERSION>` heisst.

## [Unreleased]

### Geaendert

- `load_spec` und `build_profile` melden ihre Abbruchgruende jetzt als
  Meldung mit Exit 2 statt als Traceback. Eine Spec mit kaputtem JSON, ohne
  `PayloadIdentifier` oder mit leerer `payloads`-Liste lief vorher in einen
  Stacktrace und Exit 1.
- `_SCHEMA_CACHE` merkt sich das Schema jetzt je Branch. Vorher lag dort ein
  einziges Dict ohne Branch-Schluessel, und der erste Lauf legte fest, was
  jeder weitere sah. Ueber die CLI fiel das nicht auf, ein Aufruf benutzt
  genau einen Branch. Als Bibliotheksaufruf schon: gemessen am Stand davor
  lieferte `load_all_schemas('seed_OS_27_0', offline=True)` nach einem
  vorherigen `release`-Aufruf dasselbe Objekt mit 121 PayloadTypes zurueck,
  ohne Hinweis. Jetzt meldet derselbe Aufruf, dass fuer diesen Branch kein
  Cache da ist.
- `build_profile` arbeitet auf einer Kopie der uebergebenen Payload-Dicts.
  Vorher schrieb es `PayloadUUID`, `PayloadIdentifier` und `PayloadVersion`
  in die Spec des Aufrufers zurueck, was fuer eine Bibliothek niemand
  erwartet. Am erzeugten Profil aendert sich nichts: dieselbe Spec ergibt
  Byte fuer Byte dieselbe Datei.
- `validate_mobileconfig.py` weist wie der Bau-Pfad aus, welche Payloads
  gegen ProfileManifests statt gegen Apples Schema geprueft wurden.

### Hinzugefuegt

- **Zertifikate aus einer JSON-Spec.** `{"__base64__": "..."}` und
  `{"__file__": "ca.der"}` werden vor der Validierung im ganzen Spec-Baum zu
  Bytes aufgeloest, in beliebiger Tiefe und auch in Listen. Ein relativer
  Pfad zaehlt vom Verzeichnis der Spec aus, damit dieselbe Spec aus jedem
  Arbeitsverzeichnis dasselbe Profil ergibt.

  Das schliesst eine Luecke, die jeden Zertifikats-Payload betraf: `<data>`
  will Bytes, JSON hat keine, und damit scheiterte
  `com.apple.security.root`, `.pkcs1` und `.pkcs12` aus einer JSON-Spec an
  genau dieser Stelle, waehrend README und Landingpage
  Multi-Payload-Profile mit Zertifikaten bewarben. Gemessen an einem frisch
  erzeugten Wurzelzertifikat: vorher Exit 2 mit `expected <data>, got dict`,
  jetzt ein Profil, dessen `<data>`-Feld dieselben 781 Bytes traegt wie die
  DER-Datei, ueber beide Marker.

  Aufgeloest wird unabhaengig davon, was das Schema an der Stelle erwartet.
  Anders ginge es nicht: die Aufloesung muesste sonst das Schema kennen,
  bevor die Spec steht. Ein Marker an der falschen Stelle faellt danach als
  `expected <string>, got bytes` auf.

  Ein nackter Base64-String bleibt eine Zeichenkette und faellt weiter als
  `expected <data>, got str` durch. Der Marker ersetzt sein ganzes
  Dictionary, daneben darf kein weiterer Key stehen, und beide Marker
  zusammen sind ein Abbruch statt einer Ratefrage.

  Nicht abgedeckt: die Marker kopieren Bytes und pruefen nicht, ob dahinter
  ein Zertifikat steckt. Eine PEM-Datei landet als PEM im Profil, Apple will
  an einem Zertifikats-Payload DER, umgewandelt wird nicht. `__file__` liest
  jeden Pfad, den der aufrufende Prozess lesen darf, ohne Groessengrenze und
  ohne Erlaubnisliste, `~` eingeschlossen, und die Bytes stehen danach im
  Klartext im Profil. Eine Spec ist damit so vertrauenswuerdig wie ihre
  Quelle. README, SKILL.md und `references/data-fields.md` sagen das an der
  Stelle, an der jemand den Marker nachschlaegt.
- Eval 10 `daten-marker-in-json-spec` und ein CI-Schritt, der sich ein
  Zertifikat mit `openssl` erzeugt, es ueber beide Marker in ein Profil baut
  und die Bytes im Profil gegen die DER-Datei haelt. Im Repo liegt weiterhin
  kein Zertifikat.

- **Validator fuer bereits vorhandene Profile.**
  `scripts/validate_mobileconfig.py` nimmt eine fertige `.mobileconfig`
  entgegen, egal wer sie gebaut hat, und prueft sie gegen dasselbe Schema,
  gegen das der Bau-Pfad prueft: die Profil-Ebene gegen `TopLevel.yaml`,
  jeden Eintrag aus `PayloadContent` gegen sein eigenes Schema. Bis hierher
  konnte das Werkzeug nur pruefen, was es selbst erzeugt hatte; ein Profil
  aus Jamf oder Intune liess sich nicht vorlegen.

  Drei Eingabeformen: XML-Plist, Binaer-Plist und signierter
  PKCS#7-Container, letzterer ueber `openssl smime -verify -noverify`
  ausgepackt. `-noverify` laesst die Zertifikatskette ungeprueft, die
  Signatur nicht: eine nachtraeglich veraenderte Datei faellt durch, ein
  gueltig signiertes Profil eines Ausstellers, dem niemand vertraut, geht
  durch. Wem ein Profil gehoert, sagt der Validator also nicht.

  Zwei Stufen mit einer Regel dahinter. **Fehler** heisst, das Schema wird
  verletzt: Pflichtkey fehlt, Typ passt nicht, Wert liegt ausserhalb von
  `rangelist` oder `range`. **Warnung** heisst, Apples Schema sagt dazu
  nichts oder es gibt keins: unbekannter Key, PayloadType ohne Schema,
  `format`-Regex, doppelt vergebene `PayloadUUID`. Exit 2 fuer Fehler, 1 fuer
  reine Warnungen, 0 fuer nichts. `--strict` macht aus jeder Warnung einen
  Fehler.

  Die Trennung ist der Grund, warum das Werkzeug auf fremden Dateien
  brauchbar bleibt: ein Profil aus einem realen MDM traegt regelmaessig Keys,
  die Apple nie beschrieben hat, und Payloads von Anbietern, fuer die Apple
  gar kein Schema hat. Gemessen an einem von Hand gebauten Jamf-Export mit
  `PayloadEnabled` auf oberster Ebene, einem `JamfInternalKey` im
  Restrictions-Payload und einem `com.google.Chrome`-Payload: drei Warnungen,
  kein Fehler, Exit 1. Als Fehler gewertet waere dieselbe Datei rot, ohne
  dass etwas an ihr falsch waere.

  Jeder Befund nennt seinen Pfad (`top-level`, `PayloadContent[0]`),
  `--format json` gibt dieselben Befunde maschinenlesbar aus, und mehrere
  Dateien in einem Aufruf sind erlaubt.

  Nicht abgedeckt: `supportedOS` wird nicht ausgewertet, ein iOS-only-Key in
  einem macOS-Profil laeuft durch. Verschluesselte Payloads bleiben zu,
  `EncryptedPayloadContent` ist `<data>` und wird nicht ausgepackt. Es gibt
  kein SARIF, also landen die Befunde nicht in GitHub Code Scanning, und es
  gibt keine fertige GitHub Action; der README-Abschnitt zeigt den direkten
  Aufruf.
- Eval 9 `validate-mobileconfig` und ein CI-Schritt, der den Validator von
  aussen faehrt: gebautes Profil Exit 0, erfundener Key Warnung mit Exit 1 und
  strikt Fehler mit Exit 2, `rangelist`-Verstoss Exit 2 auch ohne `--strict`,
  JSON-Ausgabe mit Stufe und Pfad, keine Plist Exit 2 ohne Traceback. Der
  Signier-Schritt reicht seine eigene signierte Ausgabe an den Validator
  weiter und danach dieselbe Datei mit einem geaenderten Byte, weil dort der
  einzige PKCS#7-Container dieser CI entsteht.

- **Signieren ueber den macOS-Schluesselbund.** `--sign-identity <Name oder
  SHA-1>` signiert mit `/usr/bin/security cms -S` statt mit `openssl`. Der
  private Schluessel verlaesst den Schluesselbund nicht, was der Regelfall
  ist, wenn das Signaturzertifikat per SCEP oder ADCS kommt und als nicht
  exportierbar markiert ist. `--keychain` schickt Suche und Signierung in
  einen bestimmten Schluesselbund statt in die Suchliste des Benutzers. Der
  Weg gibt es nur auf macOS; auf anderen Plattformen endet der Aufruf mit
  Exit 2 und dem Hinweis auf `--sign-cert`.
- Eval 7 `signing-error-paths`: prueft die Fehlerpfade beider Signier-Wege
  und laeuft auf jeder Plattform, weil der Erfolgsfall des
  Schluesselbund-Wegs eine Identitaet im Schluesselbund braucht.
- **Zweite Schema-Quelle fuer Drittanbieter-Domains.** `--manifests` schaltet
  ProfileManifests zu, damit `com.google.Chrome`, `com.microsoft.office`,
  `us.zoom.config` und der Rest nicht mehr als unbekannter PayloadType
  abgelehnt werden. `--manifests-ref` pinnt den Stand. Gilt fuer
  `build_mobileconfig.py` und `inspect_payload.py`.

  Apple gewinnt: die zweite Quelle wird nur gefragt, wenn Apple den
  PayloadType gar nicht kennt, zusammengefuehrt wird nichts. Fuer PPPC ist
  der Unterschied genau ein Key: Apples TCC-Schema kennt 24 Services,
  ProfileManifests 25, der Mehrwert heisst RemoteDesktop.

  ProfileManifests hat keine Lizenz, weder eine LICENSE-Datei noch ein
  Lizenzfeld ueber die GitHub-API. Deshalb liegt kein Manifest im Repo, keins
  im Release-Artefakt und keins als Test-Fixture. Geladen wird zur Laufzeit,
  in einen eigenen Cache unter
  `~/.cache/mobileconfig-builder/profilemanifests/<ref>/`. Jeder Lauf, der
  gegen die zweite Quelle geprueft hat, sagt das auf stderr.

  Uebersetzt wird nur, was der Validator auswertet. `pfm_conditionals`,
  `pfm_exclude`, `pfm_targets` und `pfm_app_min` bleiben liegen, das sind
  Regeln fuer eine Oberflaeche. Bedienelemente von ProfileCreator fallen
  raus: `PFC_SegmentedControl_0` steht in den Manifesten fuer Chrome, Office
  und Zoom als `pfm_require: always`, ist aber ein Reiter-Umschalter. Eins zu
  eins uebersetzt haette jedes Chrome-Payload einen Key gebraucht, den Chrome
  nie gesehen hat.
  Ein Dictionary mit beliebigen Schluesseln beschreibt ProfileManifests ueber
  das Platzhalter-Paar `{{key}}` und `{{value}}`, etwa `ExtensionSettings` bei
  Chrome. Daraus wird Apples `key: ANY`, sonst haette `--validate-strict`
  jede echte Erweiterungs-ID als unbekannten Key abgelehnt.

  Kein Netz und keine unbekannte Domain fuehren zu einem Traceback: beides
  endet mit einer Meldung, die sagt, welcher Cache-Ordner gemeint ist.
- Eval 8 `profilemanifests-normalisierung`: prueft die Uebersetzung gegen ein
  erfundenes Manifest, offline, ohne eine Datei aus dem fremden Repo.
- CI-Schritt, der ein Chrome-Profil gegen einen gepinnten Stand von
  ProfileManifests baut und danach prueft, dass kein Manifest im
  Arbeitsverzeichnis gelandet ist.

### Behoben

- **`--sign-identity` mit einem SHA-1 signierte mit dem falschen
  Zertifikat.** Der Fingerabdruck wurde auf den Namen zurueckuebersetzt und
  ungeprueft an `security cms -N` gereicht, das ausschliesslich nach Namen
  waehlt. Bei zwei Zertifikaten mit demselben Common Name unterschrieb
  irgendeines von beiden, der Lauf endete mit Exit 0 und nannte in der
  Erfolgszeile den angefragten Fingerabdruck. Gemessen an einem
  Wegwerf-Schluesselbund: angefragt `5CBEAAAA6A6C67A2EA514E2F28BF0516AE99819B`,
  signiert hat `C7AF8CB62D89BF49630564744B952BC7656841BB`. Der Fall wird
  jetzt auf beiden Wegen hinein abgelehnt, mit den betroffenen
  Fingerabdruecken in der Meldung. Ein Fingerabdruck ist fuer `cms -N` keine
  Auswahl, deshalb bietet die Meldung ihn nicht mehr als Ausweg an;
  `references/signing.md` sagt das jetzt ebenfalls so.
- **Kein unsigniertes Zwischenprodukt mehr auf der Platte.** Bisher schrieb
  der Build `<output>.unsigned.mobileconfig`, rief openssl und loeschte die
  Datei erst danach. Scheiterte der Aufruf, blieb sie mit Modus 0644 liegen,
  samt WLAN-Passwort im Klartext, daneben eine leere `<output>` und ein
  Traceback. Das Profil geht jetzt ueber stdin an das Signier-Werkzeug, eine
  Zwischendatei entsteht gar nicht. Scheitert das Signieren, endet der Lauf
  mit Exit 2 und einer Meldung, und am Ausgabepfad bleibt nichts liegen.
- **Der zweite Bau auf denselben Pfad vernichtete das alte Profil.**
  `openssl -out` und `security cms -o` kuerzen ihre Ausgabedatei schon beim
  Oeffnen auf null Bytes. Das Aufraeumen sprang nur an, wenn die Datei vorher
  nicht existierte, also gerade nicht im haeufigsten Fall: dem zweiten Bau
  nach einer Spec-Aenderung. Zurueck blieb eine leere .mobileconfig, die
  aussieht wie ein fertiges Profil, und das zuvor gueltige war weg. Gemessen:
  1378 Bytes vorher, 0 Bytes nachher. Signiert wird jetzt in eine
  Temporaerdatei im Zielverzeichnis, und die kommt erst nach allen Pruefungen
  per `os.replace` an den Zielpfad. Damit faellt auch die Frage weg, wann
  geloescht werden darf, und die beiden bisher widerspruechlichen Regeln
  (bedingtes Aufraeumen, bedingungsloses Loeschen nach `cms -D`) sind eine
  geworden. Eval 7 hat dafuer einen achten Check.
- **Der Exit-Code von `security cms` wird nicht mehr geglaubt.** Findet es
  die Identitaet nicht, meldet es den Fehler nur auf stderr, endet mit 0 und
  hinterlaesst eine Datei mit null Bytes. Unter Last endet es danach gar
  nicht mehr, sondern bleibt stehen. Der Build prueft deshalb vorher, ob der
  Schluesselbund die Identitaet ueberhaupt kennt, und bricht sonst ab, bevor
  `security cms` startet. Danach prueft er die fertige Datei: nicht leer,
  faengt mit einer ASN.1-SEQUENCE an, und `security cms -D` liefert Byte fuer
  Byte das gebaute Profil zurueck.
- **Der Signier-Aufruf hatte kein Timeout.** Die Identitaetssuche hatte eins
  (`IDENTITY_TIMEOUT=30`), das Signieren nicht. Erledigt war damit der
  Tippfehler im Identitaetsnamen, den die Vorabpruefung abfaengt. Ein
  gesperrter Schluesselbund oder ein Freigabe-Dialog ohne Fenstersitzung
  haengte den Bau weiterhin unbegrenzt und ohne Meldung. Beide Signier-Wege
  brechen jetzt nach fuenf Minuten mit Exit 2 ab und nennen die Ursachen samt
  Gegenmitteln: `security unlock-keychain`, `security set-keychain-settings`
  und die Zugriffsliste ueber `-T /usr/bin/security` plus
  `set-key-partition-list`, beim PEM-Weg die Passphrase-Abfrage von openssl.
  Fuenf Minuten sind bewusst grosszuegig, damit der Freigabe-Dialog beim
  ersten Aufruf nicht in einen abgebrochenen Bau laeuft.
- **`security cms` signierte mit SHA-1.** Ohne `-H SHA256` ist SHA-1 die
  Vorgabe, nachgewiesen mit `openssl cms -cmsout -print`. Der Schalter ist
  jetzt gesetzt.

- **DDM als Kapitel statt als Fussnote.** `references/ddm.md` beschreibt, was
  Declarative Device Management anders macht, wie eine Spec beide
  Ausgabeformate speisen koennte, woran die Abbildung haengt und in welcher
  Reihenfolge ein Export gebaut wuerde. Belegt statt behauptet: der
  `release`-Branch hat 121 PayloadTypes und 36 Configuration-Declarations,
  beim Passcode sind elf von dreizehn Keys reine Umbenennungen, einer dreht
  die Bedeutung um (`allowSimple: false` = `RequireComplexPasscode: true`),
  einer verschiebt den Bereich, und `com.apple.configuration.legacy` nimmt
  eine ProfileURL entgegen. Das README hat dafuer ein eigenes Kapitel statt
  des bisherigen Dreizeilers, SKILL.md sagt beim Abgrenzen jetzt auch, was
  der Unterschied praktisch bedeutet.

- **Die Herkunftsangabe „geprueft gegen ProfileManifests" stand auch da, wenn
  gar kein ProfileManifest gelesen wurde.** Der PayloadType wird zum
  Dateinamen im Manifest-Cache. Einer mit Pfadanteilen las damit eine
  beliebige `.plist` von der Platte, und der Lauf wies sie als
  ProfileManifests-Herkunft aus. Gemessen mit
  `../../../../../../<pfad>/fremd`: Exit 0 und die Herkunftszeile auf stderr.
  Ein PayloadType, der nicht wie eine Preference-Domain aussieht, gilt jetzt
  als unbekannt, und die Fehlermeldung sagt auch warum. Die Herkunftsangabe
  selbst kommt nicht mehr aus dem Umkehrschluss "Apple kennt es nicht",
  sondern aus dem `_origin`-Feld des Schemas, und nennt zusaetzlich den Stand.
  Sie traegt den Lizenzhinweis, also muss sie stimmen.
- **Der Secret-Scan haelt einen Wahrheitswert nicht mehr fuer ein Passwort.**
  Chrome hat den Policy-Key `PasswordManagerEnabled`, und ein Beispiel dafuer
  setzt ihn auf `false`. Bisher meldete der Scan das als undokumentierten
  Wert hinter einem Passwort-Key. Jetzt gehen `true`, `false`, `yes` und `no`
  durch, Zahlen weiterhin nicht: eine Ziffernfolge kann sehr wohl ein
  Passwort sein.
- **Ein symbolischer Link als Ausgabepfad wurde durch eine Datei ersetzt.**
  Das war der Preis der Temporaerdatei, und er ist erst danach aufgefallen.
  `openssl -out` schrieb durch den Link hindurch in die verlinkte Datei und
  liess den Link stehen; `os.replace` auf den Linknamen ersetzte den Link
  durch eine gewoehnliche Datei und liess die verlinkte Datei bei 0 Bytes
  zurueck. Gemessen gegen `origin/main`: dort blieb der Link stehen und die
  verlinkte Datei hatte 2468 Bytes gueltig signiert, mit der Temporaerdatei
  lag das Profil unter dem Linknamen und die verlinkte Datei war leer.
  Gearbeitet wird jetzt auf dem ueber `realpath` aufgeloesten Pfad, damit
  herauskommt, was vorher herauskam. Ein Link ins Leere legt weiter die
  Zieldatei an.
- **Ein langer Ausgabename ging nicht mehr durch.** Die Temporaerdatei heisst
  nach ihrem Ziel, und `mkstemp` haengt acht Zufallszeichen und `.teil` an,
  zusammen 27 Zeichen ueber den Namensstamm hinaus. Der alte Weg brauchte mit
  `.unsigned.mobileconfig` nur 22. In dem Fenster dazwischen signierte
  `origin/main` und dieser Zweig nicht mehr: gemessen bei einem Ausgabenamen
  aus 244 Zeichen Exit 0 und 2468 Bytes gueltig gegen
  `OSError: [Errno 63] File name too long`. Der Praefix wird jetzt auf
  `pathconf(PC_NAME_MAX)` abzueglich der 13 Zeichen von `mkstemp` gekuerzt.
  Damit signieren beide bei 244 Zeichen, und Namen bis 254 Zeichen, an denen
  `origin/main` scheiterte, gehen jetzt ebenfalls durch.
- **Fehler beim Anlegen und Verschieben der Temporaerdatei kamen als
  Traceback heraus.** `mkstemp` und `os.replace` lagen ausserhalb der
  `SchemaError`-Behandlung. Ein Ausgabeverzeichnis ohne Schreibrecht oder ein
  Verzeichnis als Ausgabepfad endeten damit mit Exit 1 und einem Absturz.
  Beide melden jetzt mit Exit 2 und sagen dazu, was am Zielpfad liegt: beim
  Verzeichnis ohne Schreibrecht, dass `os.replace` das Verzeichnis braucht
  und nicht nur die Zieldatei, und dass nicht signiert wurde. `origin/main`
  stuerzte in beiden Faellen ebenfalls ab, es gab dort gar keine
  `SchemaError`-Behandlung um das Signieren.
- CI-Schritt, der mit einem selbst erzeugten Zertifikat gegen den
  Ausgabepfad signiert: Normalfall, 254 Zeichen langer Name ohne
  liegengebliebene `.teil`-Datei, Symlink bleibt stehen und die verlinkte
  Datei ist signiert, Verzeichnis als Ausgabepfad endet mit Exit 2 ohne
  Traceback, und ein gescheiterter zweiter Bau laesst das vorhandene Profil
  Byte fuer Byte unveraendert. Gegen `origin/main` und gegen den Stand vor
  dieser Reparatur ist der Schritt rot.

### Geaendert

- Die Doku nennt fuer die Identitaetssuche `security find-identity -p smime`
  oder `-p basic` statt `-p codesigning`. Ein Profil-Signer traegt die EKU
  `emailProtection` oder gar keine einschraenkende EKU und faellt nicht unter
  die Code-Signing-Policy. Auf einem eingerichteten Firmen-Mac enthaelt keine
  der drei Listen die anderen.
- SECURITY.md: Angriffspfad 2 (liegengebliebener Klartext) ist als
  geschlossen dokumentiert, die Beschreibung der `.gitignore` in
  Angriffspfad 1 entspricht wieder der Datei.

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
