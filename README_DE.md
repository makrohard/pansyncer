# PanSyncer

PanSyncer ist ein Linux-Kommandozeilenprogramm zur Synchronisation von Funkgeräten und SDR-Empfängern.
USB-Lautstärkeregler können als Eingabegeräte zum Ändern der Frequenz verwendet werden.

Funktionen:

- direkte Frequenzsynchronisation zwischen zwei Funkgeräten - z.B. für Antennensplitter-Setups
- Zwischenfrequenz Panadapter-Setups - z.B. mit einem klassischen Superhet-Transceiver und einem SDR als Panadapter
- Steuerung eines einzelnen Funkgeräts oder von GQRX
- Abstimmung per Tastatur, Maus oder USB-Lautstärkeknopf
- Bandwechsel über die Terminal-Oberfläche
- optionale Frequenzprotokollierung als Backup zu regulärer QSO-Logging-Software

PanSyncer steuert Funkgeräte über rigctld/Hamlib. Standardmäßig startet es rigctld so, dass FLRig als
Backend verwendet wird. GQRX wird über seine Fernsteuerungsschnittstelle gesteuert.

## Browser-Demo

[![Start in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/makrohard/pansyncer?quickstart=1)

Dann starten mit:
```bash
./testlab/start_codespaces_testlab.sh
```

## Schnellstart

Hier zunächst nur die wichtigsten Schritte, um PanSyncer zum Laufen zu bringen - detaillierte Anweisungen weiter unten.

### Voraussetzungen

PanSyncer ist ein Kommandozeilenprogramm für Linux. Es benötigt eine einigermaßen aktuelle Python-Version.

Die Standardkonfiguration setzt voraus, dass [FLRig](https://github.com/w1hkj/flrig) und
[GQRX](https://github.com/gqrx-sdr/gqrx) installiert sind. Die meisten Linux-Distributionen stellen dafür Pakete bereit.

Für die Funkgerätekommunikation wird `rigctld` verwendet. Dafür ist das Paket `hamlib` aus der jeweiligen Distribution
zu installieren. Unter Ubuntu heißt das Paket `libhamlib-utils`.

### Installation
  ```bash
  git clone https://github.com/makrohard/pansyncer.git
  cd pansyncer
  pipx install .
  ```
Zum Ausführen ohne Installation siehe: [Installation](#installation)

### Konfiguration
Die Konfiguration erfolgt in der **Konfigurationsdatei** `pansyncer.toml`.
Alternativ können Kommandozeilenparameter verwendet werden: `pansyncer --help`.

Die Standardkonfiguration läuft im Direct Mode. Für den iFreq-Modus wird die Zwischenfrequenz angegeben, zum Beispiel:
`pansyncer --ifreq 70.095`

### Im Terminal ausführen
  ```bash
  pansyncer
  ```
### Befehle
Nach dem Start lässt sich mit **?** die **Hilfe** zu den Befehlen anzeigen:
```text
Sync On / Off    :  1 / 0
Toggle devices   :  r = Rig,  g = GQRX, m = Mouse, k = VFO Knob
[...]
Quit             :  q 
```

### Funkgeräte verbinden
FLRig mit Xmlrpc und GQRX mit aktivierter Fernsteuerung starten. Die Verbindung wird automatisch hergestellt.
Falls nicht: Ports und rigctld-Befehl in der Konfigurationsdatei `pansyncer.toml` prüfen.

### USB-VFO-Knopf verbinden
Zum Einrichten eines unbekannten Knopfs siehe: [Einen USB-Lautstärkeknopf als VFO-Knopf verwenden](#einen-usb-lautstärkeknopf-als-vfo-knopf-verwenden)

## Inhaltsverzeichnis

* [Motivation](#motivation)
* [Architektur](#architektur)
* [Installation und Konfiguration](#installation-und-konfiguration)
  * [Umgebung](#umgebung)
  * [Installation](#installation)
  * [Konfigurationsdatei und Kommandozeilenargumente](#konfigurationsdatei-und-kommandozeilenargumente)
  * [Tests ausführen](#tests-ausführen)
  * [Hardware-Emulations-Testlab](#hardware-emulations-testlab)
* [Verwendung](#verwendung)
  * [Benutzeroberfläche](#benutzeroberfläche)
  * [Daemon-Modus](#daemon-modus)
  * [rigctld-Verwaltung](#rigctld-verwaltung)
  * [Frequenzprotokollierung](#frequenzprotokollierung)
  * [Synchronisationsmodi](#synchronisationsmodi)
    * [Direct Mode](#direct-mode)
    * [Standalone Mode](#standalone-mode)
    * [iFreq Mode](#ifreq-mode)
      * [Initiale Synchronisation für GQRX im iFreq-Modus](#initiale-synchronisation-für-gqrx-im-ifreq-modus)
* [Einen USB-Lautstärkeknopf als VFO-Knopf verwenden](#einen-usb-lautstärkeknopf-als-vfo-knopf-verwenden)
  * [Gerät identifizieren](#gerät-identifizieren)
  * [Event-Node finden](#event-node-finden)
  * [Events und Tastenzuordnungen prüfen](#events-und-tastenzuordnungen-prüfen)
  * [Benutzerberechtigung für das Knopfgerät vergeben](#benutzerberechtigung-für-das-knopfgerät-vergeben)
  * [PanSyncer für die Verwendung des Knopfgeräts konfigurieren](#pansyncer-für-die-verwendung-des-knopfgeräts-konfigurieren)

## Motivation

Ausgangspunkt war eine portable Amateurfunkstation mit QMX+-Transceiver und Airspy HF+ SDR, gekoppelt über einen
Antennensplitter. Zum Aufbau gehört ein Raspberry Pi als Steuerrechner. Trotz digitaler Steuerung sollte ein externer 
VFO-Knopf das Bediengefühl eines klassischen analogen Abstimmknopfs ermöglichen. Dafür sollte ein preisgünstiger
USB Lautstärkeregler verwendet werden. Zusätzlich wurde eine Lösung benötigt, um Funkgerät und SDR zu
synchronisieren. Das bewährte Skript [gqrx-panadapter](https://github.com/alexf91/gqrx-panadapter) deckte bereits
iFreq-Tap-Setups ab; PanSyncer ergänzt diesen Ansatz um weitere Funktionen, etwa automatisches Wiederverbinden im
Direct Mode nach Fehlern.


## Architektur

Ein typischer Aufbau könnte so aussehen:
```text
                                             +-------------------+
                        #############        | Input devices     |
          +-----------> # PanSyncer # <----- | Keyboard, Mouse,  |
          |             #############        | External VFO Knob | 
          |                   ^              +-------------------+
          |                   |
          v                   v 
    +-----------+       +-----------+        +-----------+        +-----------+            
    |   GQRX    |       |  rigctld  | <----> |   FLRig   | <----> | TRX (Rig) |
    +-----------+       +-----------+        +-----------+        +-----------+
                              ^                    ^
                              |                    |
                              v                    v
                        +-----------+        +-----------+                           
                        |  Logger   |        |  WSJT-X   |
                        +-----------+        +-----------+
```

Die Verwendung von FLRig, Logger oder Digi-Client (z. B. WSJT-X) ist optional. PanSyncer kann auch eine Verbindung zu 
zwei rigctld-Instanzen herstellen, die auf unterschiedlichen Ports laufen (angegeben als rig_port und gqrx_port). Diese
können dann mit zwei Amateurfunkgeräten oder beliebigen anderen Hamlib-Clients verbunden sein. Das funktioniert nur im
Direct Mode, und rigctld muss manuell gestartet werden.

[TOC](#inhaltsverzeichnis)
## Installation und Konfiguration

### Umgebung

* PanSyncer läuft unter *Linux*. Es verwendet systemspezifische Abhängigkeiten wie evdev und select. Es gibt keine Pläne, PanSyncer auf andere Betriebssysteme zu portieren.
* *Python* >= 3.11 – das in jeder aktuellen Linux-Distribution enthalten sein sollte. Die Abhängigkeiten werden wie unten beschrieben installiert.
* PanSyncer ist dafür gedacht, aus einem VT100-kompatiblen ANSI-Terminal heraus ausgeführt zu werden, sofern es nicht als Hintergrundprozess verwendet wird. Die meisten Linux-Terminals unterstützen dies.
* *[hamlib](https://hamlib.github.io/) rigctl* ist wesentlich – außer bei ausschließlicher Verwendung von GQRX, ohne TRX. Die meisten Linux-Distributionen haben ein Hamlib-Paket. Dieses Paket zu installieren ist in den meisten Fällen die beste Wahl. Unter Debian/Ubuntu lautet der Installationsbefehl:
`sudo apt-get install libhamlib-utils`
Unter anderen Distributionen heißt das Paket meist `hamlib`.

### Installation

* Installation:
  * `pipx` installieren, falls es noch nicht verfügbar ist
      ```bash
      # Debian, Ubuntu, Raspberry Pi OS:
      sudo apt install pipx
      ```
      ```bash
      # Fedora:
      sudo dnf install pipx
      ```
  * Den Befehlspfad von `pipx` in der Shell verfügbar machen
      ```bash
      pipx ensurepath
      ```
  * Repository klonen
  * In das Repository-Verzeichnis wechseln
  * PanSyncer mit `pipx` installieren
      ```bash
      git clone https://github.com/makrohard/pansyncer.git
      cd pansyncer
      pipx install .
      ```

  * **Ausführen**

      ```bash
      pansyncer --help
      ```

      Deinstallation:

      ```bash
      pipx uninstall pansyncer
      ```

* Alternativ kann das Skript ohne Installation ausgeführt werden:
  * Repository klonen
  * In das Repository-Verzeichnis wechseln
  * Virtuelle Python-Umgebung erstellen
  * Virtuelle Python-Umgebung aktivieren
  * Abhängigkeiten installieren
  * PanSyncer als Modul ausführen

      ```bash
      git clone https://github.com/makrohard/pansyncer.git
      cd pansyncer
      python -m venv .venv
      source .venv/bin/activate
      pip install -r requirements.txt
      python -m pansyncer.main --help
      ```

  * Vor dem Start von PanSyncer muss die virtuelle Umgebung in jeder neuen Shell aktiviert werden:

      ```bash
      source .venv/bin/activate
      python -m pansyncer.main --help
      ```


### Konfigurationsdatei und Kommandozeilenargumente

Standardmäßig verwendet PanSyncer den Direct Mode und verbindet rigctld mit FLRig. Für die Anpassung an die jeweilige
Umgebung gibt es zwei Möglichkeiten:

* Kommandozeilenargumente verwenden. `pansyncer --help` zeigt die verfügbaren Optionen an.
* Die Konfigurationsdatei verwenden: `pansyncer.toml`

Kommandozeilenargumente überschreiben die Konfigurationsdatei.
Wenn die Konfigurationsdatei fehlt, startet PanSyncer mit seinen eingebauten Standardwerten.
Wenn die Konfigurationsdatei vorhanden ist, aber ungültiges TOML enthält, bricht PanSyncer den Start mit einem
Konfigurationsfehler ab.

### Tests ausführen

Für Entwickler:
PanSyncer verwendet pytest für seine automatisierte Testsuite. Die Entwicklungsabhängigkeiten werden vom Repository-Root
aus installiert:
```bash
python -m pip install -e ".[dev]"
```

Tests ausführen:
```bash
python -m pytest
```
Die Tests verwenden Fake-Geräte und lokale Testserver. Sie benötigen keine Hardwaregeräte.

### Hardware-Emulations-Testlab

`testlab/` stellt Fake-Funkgeräte und Fake-Eingabegeräte für manuelle Tests ohne echte Hardware bereit.

Details siehe `testlab/README.md`.

[TOC](#inhaltsverzeichnis)
## Verwendung

### Benutzeroberfläche

PanSyncer stellt eine terminalbasierte Benutzeroberfläche bereit.

Oben rechts wird der aktive Modus angezeigt, der zur Laufzeit nicht geändert werden kann.
Die linke Spalte listet aktive Geräte auf; die nächste Spalte zeigt deren Verbindungsstatus. Aktive Geräte werden
überwacht und bei Trennung neu verbunden. Geräte können zur Laufzeit ein- und ausgeschaltet werden.
In der rechten Spalte wird bei Funkgeräten die aktuelle Frequenz angezeigt. Bei Eingabegeräten wird ein kurzer Hinweis
bei erfolgter Eingabe angezeigt. Logmeldungen werden unterhalb des letzten Geräts angezeigt. Logging-Parameter können in
`pansyncer.toml` angegeben werden.

Hinweis:
Die Tastatur kann nicht deaktiviert werden. Sie verwendet stdin und benötigt keine Verbindungslogik.
Rig hat zwei Verbindungsstatus: Grau bedeutet „rigctld socket antwortet“; Grün bedeutet „Das Rig liefert eine Frequenz“.

```text
 PanSyncer Control      iFreq
 Sync      ON   73.095.000 Hz
 Step                  100 Hz
 Rig       CON  14.200.000 Hz
 GQRX      CON  14.200.000 Hz
 Knob      CON
 Mouse     CON  UP
 Keyboard                20m
```

Das Drücken von **?** zeigt die Hilfe an:

```text
[INFO] Change Frequency :  + / -, arrow keys, mouse or external VFO Knob
[INFO] Sync On / Off    :  1 / 0
[INFO] Change Step      :  Spacebar, middle mouse button or knob click
[INFO] Toggle devices   :  r = Rig,  g = GQRX, m = Mouse, k = VFO Knob
[INFO] Change Band      :  w = Up,  s = Down
[INFO] Toggle display   :  d
[INFO] Quit             :  q 
```

Für kleine Bildschirme kann auf einen minimalistischen Anzeigemodus umgeschaltet werden:

```text
 Sync      ON          100 Hz
 Rig       CON  14.200.000 Hz
 GQRX      CON  14.200.000 Hz
```

### Daemon-Modus

PanSyncer kann mit dem Flag `-b` oder `--daemon` auch im Hintergrund ausgeführt werden. Dadurch werden Anzeige und
Tastatur deaktiviert. Beenden ist mit `Ctrl C` möglich. Einmal drücken und auf das ordnungsgemäße Beenden warten.

Um PanSyncer vollständig in den Hintergrund zu schicken, kann am Ende des Befehls ein `&` hinzugefügt werden.
Der folgende Befehl startet PanSyncer im Hintergrund und unterdrückt alle Ausgaben:

`pansyncer -b >/dev/null 2>&1 &`

Es sollte vermieden werden, mehrere Instanzen zu starten, da diese Ports blockieren und Geräte belegen können.

Laufende Instanzen auflisten:
```bash
ps ax | grep pansyncer  
24258 pts/0    Sl+    0:00 python -m pansyncer.main -b  
```
Prozess anhand seiner PID beenden:
`kill 24258`

### rigctld-Verwaltung

Standardmäßig startet PanSyncer rigctld als Subprozess. Es startet ihn nach Abstürzen neu und beendet ihn beim 
Herunterfahren.

Für einen manuellen Start von rigctld kann das Argument `--no-auto-rig` verwendet oder die entsprechende Option in der 
Konfigurationsdatei gesetzt werden.

Der rigctld-Befehl kann in der Konfigurationsdatei `pansyncer.toml` angepasst werden. Die Standardkonfiguration 
verwendet FLRig xmlrpc.

### Frequenzprotokollierung

Der Frequenzlogger schreibt immer dann eine Zeile mit Zeitstempel und Frequenz des Funkgeräts in eine Datei, wenn sich
die Frequenz ändert. Er wartet dabei kurz, um die Datei nicht zu fluten. Er kann als Backup für das reguläre
Logging-Programm dienen, falls dieses gelegentlich unbemerkt die CAT-Verbindung verliert. 
Der Frequenzlogger ist standardmäßig deaktiviert und kann durch Angabe eines Dateinamens aktiviert werden.

Nicht zu verwechseln mit den Programm-Loggern, die zu Debugging-Zwecken ebenfalls in eine Datei schreiben können.

### Synchronisationsmodi

#### Direct Mode

**Dieser Modus ist standardmäßig aktiviert, wenn das Flag `--ifreq` nicht gesetzt ist.**
Der Direct Mode synchronisiert zwei Funkgeräte auf dieselbe Frequenz. Das ist geeignet, wenn unabhängige Antennen
für die Funkgeräte vorhanden sind oder wenn das Antennensignal aufgeteilt und für beide Funkgeräte verwendet wird.
Dieser Modus synchronisiert die Frequenzen bidirektional, sodass beide Funkgeräte direkt abgestimmt werden können und
trotzdem synchron bleiben.


#### Standalone Mode
**Wenn nur ein Funkgerät aktiviert ist oder Sync deaktiviert wird, wird dieser Modus verwendet.**
Die Synchronisation kann abgeschaltet werden, ebenso eines der beiden Funkgeräte. Die Eingabegeräte funktionieren
weiterhin. So ist es möglich, PanSyncer zu verwenden, um einen externen VFO-Knopf mit einem Funkgerät zu koppeln 
– oder einfach Maus oder Tastatur zum Ändern der Frequenz zu verwenden. Eingabegeräte stimmen das erste verfügbare
verbundene Funkgerät ab. Wenn Rig verbunden ist, hat es Priorität. Andernfalls wird GQRX verwendet.



#### iFreq Mode

**Dieser Modus wird durch Setzen des ifreq-Flags aktiviert, z. B. `--ifreq 73.095`.**
Der Zwischenfrequenzmodus ist für die Verwendung mit dem IF-Out (oder gepufferten iFreq-Tap) eines klassischen 
Transceivers gedacht. Dieser Modus „verschiebt den Hintergrund“, indem LO_LNB (Hardware freq) von GQRX passend
zum hardwaregekoppelten Frequenzscrolling des Funkgeräts geändert wird.

Die Offset-Frequenz kann durch Klicken in den Wasserfall verwendet werden, um Nachbarsignale abzuhören.
Außerdem kann die Offset-Frequenz genutzt werden, um Signal und GQRX-Anzeige bei leichten Abweichungen abzugleichen.
Der Offset lässt sich jederzeit zurücksetzen, indem im Fenster `Receiver Options` mit der rechten Maustaste auf die
höchste Stelle geklickt wird.

Beim Ändern der GQRX-Hauptfrequenz geht die Synchronisation verloren. In diesem Fall muss die GQRX-Hauptfrequenz wieder 
auf die RIG-Frequenz gesetzt werden. Wenn alles synchron ist, passt „Hardware freq“ immer zur iFreq.

Im iFreq Mode folgt GQRX dem Rig, indem PanSyncer GQRXs LNB_LO / Hardwarefrequenz ändert.
Änderungen in GQRX werden nicht zurück zum Rig synchronisiert.

Wenn der iFreq-Modus nur mit GQRX verwendet wird, arbeitet PanSyncer als reiner LO-Controller.
Tastatur-, Maus- und VFO-Knopf-Eingaben ändern GQRXs `LNB_LO` / Hardwarefrequenz, nicht die normale GQRX-Frequenz.

##### Initiale Synchronisation für GQRX im iFreq-Modus

Für die initiale Synchronisation von GQRX im iFreq Mode muss die Local Oscillator Frequency (Hardware freq) so gesetzt
werden, dass sie zur Zwischenfrequenz des Transceivers passt. Vorgehen:

* `View -> Receiver Options`
* `Receiver Options` -> Offset auf 0 setzen (Rechtsklick auf die höchste Stelle)
* `File -> I/O Devices: I/Q input: LO_LNB` -> 0 eingeben und OK klicken
* `Frequency` -> auf 0 setzen
* Prüfen: Alle Frequenzen auf null gesetzt
* PanSyncer im iFreq Mode mit der Zwischenfrequenz des TRX starten, z. B. mit `--ifreq 73.095`. Dadurch wird die LO-Frequenz in GQRX entsprechend gesetzt.
* `Frequency` -> manuell auf RIG-Frequenz setzen
* `Receiver Options: Hardware freq` prüfen => Dies sollte nun zur GQRX- und RIG-Frequenz passen.
* Die Synchronisation ist damit hergestellt.

In zukünftigen Entwicklungen könnte es möglich werden, die iFreq automatisch zu synchronisieren und den iFreq Mode
bidirektional zu machen, wenn [IF tap sync support](https://github.com/gqrx-sdr/gqrx/pull/1422) zu GQRX hinzugefügt
wird. Derzeit müssen diese Schritte manuell durchgeführt werden.

[TOC](#inhaltsverzeichnis)
## Einen USB-Lautstärkeknopf als VFO-Knopf verwenden

Externe VFO-Knöpfe gibt es, aber sie sind oft für ein bestimmtes Funkgerät gebaut, sehr teuer oder erfordern Löten
und Programmierung auf Hardwareebene. Es gibt jedoch viele erschwingliche USB-Lautstärkeregeldrehknöpfe auf dem Markt,
die sehr gut als VFO-Knopf zu verwenden sind.

PanSyncer unterstützt bereits verschiedene Knöpfe, es kann also sein, dass es direkt funktioniert. Falls nicht, liegt
möglicherweise ein Berechtigungsproblem vor, oder der Knopf muss manuell konfiguriert werden. Vorgehen:

### Gerät identifizieren

Ausführen:
`sudo dmesg -w`
Dann den USB-Knopf einstecken. Suche nach Zeilen, die idVendor und idProduct zeigen.
In diesem Beispiel: idVendor=05ac, idProduct=0202

```text
[27531.159576] usb 1-2: new full-speed USB device number 17 using xhci_hcd
[27531.284796] usb 1-2: New USB device found, idVendor=05ac, idProduct=0202, bcdDevice= 1.04
[27531.284805] usb 1-2: New USB device strings: Mfr=0, Product=1, SerialNumber=0
[27531.284809] usb 1-2: Product: Wired KeyBoard
[27531.288949] input: Wired KeyBoard as /devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.0/0003:05AC:0202.000B/input/input24
[27531.365788] hid-generic 0003:05AC:0202.000B: input,hidraw0: USB HID v1.10 Keyboard [Wired KeyBoard] on usb-0000:00:14.0-2/input0
[27531.368348] input: Wired KeyBoard System Control as /devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.1/0003:05AC:0202.000C/input/input25
[27531.418945] input: Wired KeyBoard Consumer Control as /devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.1/0003:05AC:0202.000C/input/input26
[27531.419043] input: Wired KeyBoard Mouse as /devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.1/0003:05AC:0202.000C/input/input27
[27531.419210] hid-generic 0003:05AC:0202.000C: input,hidraw1: USB HID v1.10 Mouse [Wired KeyBoard] on usb-0000:00:14.0-2/input1
```

### Event-Node finden
Ein Knopf kann mehrere Geräte ausgeben (Tastatur, Maus, sonstiges Eingabegerät), die sogar alle denselben Namen
haben können. Daher muss ermittelt werden, welches der präsentierten Geräte die gewünschten Events liefert.

*Consumer Control* durch den Gerätenamen aus der vorherigen Ausgabe ersetzen und ausführen:
```bash
grep -B1 -A5 "Consumer Control" /proc/bus/input/devices
```
Beispielausgabe:

```bash
I: Bus=0003 Vendor=05ac Product=0202 Version=0110
N: Name="Wired KeyBoard Consumer Control"
P: Phys=usb-0000:00:14.0-2/input1
S: Sysfs=/devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.1/0003:05AC:0202.000C/input/input26
U: Uniq=
H: Handlers=kbd event5 
B: PROP=0
```
Die mit `H:` beginnende Zeile zeigt den Event-Node.

### Events und Tastenzuordnungen prüfen

Mit diesem Event-Node ausführen:

```bash
sudo evtest /dev/input/event5
```

Den Knopf drehen und klicken. Wenn keine Ausgabe erscheint, einen anderen Event-Node testen.
`sudo` wird verwendet, um den Befehl als root auszuführen. Wenn `evtest` auf dem richtigen Event-Node als normaler
Benutzer funktioniert, sind keine Berechtigungsänderungen erforderlich; diese werden weiter unten beschrieben.

Beispielausgabe:

```bash
Testing ... (interrupt to exit)
Event: time 1753651144.743483, type 4 (EV_MSC), code 4 (MSC_SCAN), value c00e9
Event: time 1753651144.743483, type 1 (EV_KEY), code 115 (KEY_VOLUMEUP), value 1
Event: time 1753651144.743483, -------------- SYN_REPORT ------------
Event: time 1753651144.745455, type 4 (EV_MSC), code 4 (MSC_SCAN), value c00e9
Event: time 1753651144.745455, type 1 (EV_KEY), code 115 (KEY_VOLUMEUP), value 0
Event: time 1753651144.745455, -------------- SYN_REPORT ------------
Event: time 1753651151.233693, type 4 (EV_MSC), code 4 (MSC_SCAN), value c00ea
Event: time 1753651151.233693, type 1 (EV_KEY), code 114 (KEY_VOLUMEDOWN), value 1
Event: time 1753651151.233693, -------------- SYN_REPORT ------------
Event: time 1753651151.235667, type 4 (EV_MSC), code 4 (MSC_SCAN), value c00ea
Event: time 1753651151.235667, type 1 (EV_KEY), code 114 (KEY_VOLUMEDOWN), value 0
Event: time 1753651151.235667, -------------- SYN_REPORT ------------
Event: time 1753651156.411861, type 4 (EV_MSC), code 4 (MSC_SCAN), value c00e2
Event: time 1753651156.411861, type 1 (EV_KEY), code 113 (KEY_MUTE), value 1
Event: time 1753651156.411861, -------------- SYN_REPORT ------------
Event: time 1753651156.414845, type 4 (EV_MSC), code 4 (MSC_SCAN), value c00e2
Event: time 1753651156.414845, type 1 (EV_KEY), code 113 (KEY_MUTE), value 0
Event: time 1753651156.414845, -------------- SYN_REPORT ------------
```

Wenn Events angezeigt werden, ist das richtige Gerät gefunden. Diese Ausgabe zeigt die Tastenzuordnungen, die später verwendet werden.

### Benutzerberechtigung für den USB-VFO Knopf vergeben

Standardmäßig können Benutzer oft nicht auf Eingabegeräte zugreifen. Der Benutzer wird der Gruppe `input` hinzugefügt:

```bash
sudo usermod -aG input $USER
```
Die Änderung wird erst nach dem Ab- und Anmelden wirksam.

Als Nächstes wird eine udev-Regel erstellt, um automatisch die richtigen Berechtigungen zu setzen.

Neue Datei erstellen:

`/etc/udev/rules.d/99-vfo-knob.rules`

Und dort die neue Regel einfügen. Das folgende Beispiel enthält alle Knöpfe, die PanSyncer derzeit kennt.
Gerätename, idVendor und idProduct müssen zum jeweiligen Gerät passen.

```bash
KERNEL=="event*", SUBSYSTEM=="input", ATTRS{name}=="Wired KeyBoard Consumer Control", ATTRS{idVendor}=="05ac", ATTRS{idProduct}=="0202", GROUP="input", MODE="0660"
KERNEL=="event*", SUBSYSTEM=="input", ATTRS{name}=="LCTECH LCKEY", ATTRS{idVendor}=="1189", ATTRS{idProduct}=="8890", GROUP="input", MODE="0660"
KERNEL=="event*", SUBSYSTEM=="input", ATTRS{name}=="413d:553a", ATTRS{idVendor}=="413d", ATTRS{idProduct}=="553a", GROUP="input", MODE="0660"
```
udev-Regeln neu laden, um die Änderungen anzuwenden:
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```
Der Knopf sollte nun als normaler Benutzer verwendbar sein.

### PanSyncer für die Verwendung des Knopfgeräts konfigurieren

Damit PanSyncer den Knopf kennt, wird der Konfigurationsdatei `pansyncer.toml` ein neuer Abschnitt `[[knobs]]` hinzugefügt. `target_vendor` und `target_product` müssen mit `0x` präfixiert werden; `target_name` ist exakt zu kopieren.

```text
[[knobs]]                                               ### Configure Knobs
target_name    = "Wired KeyBoard Consumer Control"      # Device Identification
target_vendor              = 0x05ac                     # Prefix 0x for hex value
target_product             = 0x0202
                                                        # Key mappings
key_up                     = 115                        # ecodes.KEY_VOLUMEUP
key_down                   = 114                        # ecodes.KEY_VOLUMEDOWN
key_step                   = 113                        # ecodes.KEY_MUTE
```

Damit sollte PanSyncer den Knopf nun finden und verbinden.

Wenn an diesem Punkt alles korrekt aussieht, der Knopf aber nicht wie erwartet funktioniert:
**Reboot tut gut.**
Dadurch werden Benutzerrechte und udev-Regel sicher angewendet.

Geschafft? Bitte die Daten per Github-Issue:
[GitHub](https://github.com/makrohard/pansyncer/issues) 
oder per E-Mail an [410733\@gmail.com](mailto:410733\@gmail.com) mit idVendor, idProduct und Name senden.
Gerne nehme ich funktionierende Konfigurationen in die Standardkonfiguration auf.