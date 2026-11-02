# TMC2209 Steuerung mit Flask

Dieses Projekt startet ein kleines Flask-Webinterface für einen TMC2209-Schrittmotor. Die Lösung kombiniert:

- Step/Dir-GPIO-Steuerung für den Motor
- UART-Konfiguration für TMC2209-Register
- Ablaufsteuerung mit Beschleunigungsrampe / trapezförmigem Profil

## Hardware-Anschluss

Für den Standard-Mode mit Step/Dir-Mode und Hardware-UART des Raspberry Pi werden diese Pins verwendet:

- STEP -> GPIO17
- DIR -> GPIO27
- ENABLE -> GPIO22
- Raspberry Pi TXD (GPIO14 / Pin 8) -> TMC2209 PDN_UART **über 1kOhm**
- Raspberry Pi RXD (GPIO15 / Pin 10) -> TMC2209 PDN_UART **direkt**
- GND -> gemeinsame Masse mit dem Raspberry Pi
- VM + -> Motorversorgung (z. B. 12V/24V)
- Motor-A/B -> entsprechend an den Motor anschließen

Wichtig: Das TMC2209-Modul braucht eine passende Motorversorgung und eine gemeinsame GND-Verbindung mit dem Raspberry Pi.

Bei gemeinsamem UART-Bus mit mehreren Treibern wird die TMC2209-Adresse über MS1/MS2 festgelegt:

- MS1=0, MS2=0 -> Adresse 0
- MS1=1, MS2=0 -> Adresse 1
- MS1=0, MS2=1 -> Adresse 2
- MS1=1, MS2=1 -> Adresse 3

Die App nutzt standardmäßig Adresse `0` und kann über `TMC2209_UART_ADDRESS` angepasst werden.
Als UART-Device wird standardmäßig `/dev/serial0` verwendet (`TMC2209_UART_DEVICE`).

## Python-Umgebung

Auf einem echten Raspberry Pi installierst du `lgpio`:

```bash
sudo apt update
sudo apt install python3-lgpio gpiod
```

Dann im Projekt:

```bash
cd /home/rainer/Projects/TMC2209
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Optional für UART-Konfiguration:

```bash
export TMC2209_UART_DEVICE=/dev/serial0
export TMC2209_UART_BAUD=115200
export TMC2209_UART_ADDRESS=0
```

## Starten

Danach:

```bash
. .venv/bin/activate
python app.py
```

Für `lgpio` ist kein zusätzlicher Daemon nötig.

Damit `/dev/serial0` für TMC2209 nutzbar ist, im Raspberry Pi Setup:

- `sudo raspi-config`
- **Interface Options -> Serial Port**
- Login shell über serial: **No**
- Hardware serial port: **Yes**

Danach geöffnetes Webinterface:

```text
http://raspberrypi.local:5000
```

oder lokal auf dem Pi:

```text
http://127.0.0.1:5000
```

## Weboberfläche

- Schritte eingeben
- Richtung wählen
- Maximalgeschwindigkeit und Beschleunigung konfigurieren
- UART-Konfiguration für Microsteps und Strom anpassen
- UART-Setup im laufenden Betrieb umschalten (Device, Adresse, Baudrate)
- UART-Diagnosepanel mit letztem Testresultat, Samples und Fehlerdetails
- UART Self-Check für Device/Permissions/Port-Open vor Registertests
- Register-Map-Panel zum Lesen/Schreiben von TMC2209-Registern
- Motor starten, stoppen und aktivieren/deaktivieren

## Hardware-UART-Konfiguration

Die Klasse `HardwareUARTTMC2209` nutzt den Linux-UART (`/dev/serial0`) mit pyserial und sendet TMC2209-Datagramme mit CRC-8/ATM.

Die App stellt in der Oberfläche alle relevanten Werte für:

- Microsteps
- Strom in mA
- UART-Device (`/dev/serial0` etc.)
- UART-Adresse (MS1/MS2)
- UART-Baudrate

bereit.

Zusätzlich gibt es ein Register-Map-Panel mit den wichtigen TMC2209-Registern
(z. B. GCONF, GSTAT, IOIN, CHOPCONF, DRV_STATUS, PWMCONF). Dort kannst du
Register direkt lesen und für beschreibbare Register auch schreiben.

Der UART-Test im Webinterface ist absichtlich streng:

- 3 Leseversuche
- mindestens 2 gültige Antworten erforderlich
- instabile Werte zwischen den Versuchen => Fehler
- konstante Werte `0x00000000` oder `0xFFFFFFFF` werden als verdächtig gewertet

Der UART Self-Check prüft separat:

- existiert das UART-Device (z. B. `/dev/serial0`)
- hat der Prozess Lese-/Schreibrechte
- lässt sich der Port öffnen und initialisieren

## Hinweis

Wenn das Programm auf einem Rechner ohne Raspberry Pi läuft, arbeitet es automatisch im Demo-Modus und simuliert die Bewegung. So kann die Oberfläche lokal getestet werden, ohne angeschlossenen Motor.
