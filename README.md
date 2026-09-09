# Carrera Control

Kameragestützte Steuerung für ein Carrera Digital 132 Slotcar.

Der Laptop erkennt das Fahrzeug, verarbeitet eine aufgezeichnete Recognition-Lap,
erzeugt daraus einen geschlossenen TrackGraph und steuert die CU-Gasstufe über
einen Raspberry Pi Pico.

## Architektur

```text
Kamera
  -> carrera_control/vision.py
  -> Recognition-Lap und TrackGraph
  -> Training oder automatisches Fahren
  -> carrera_control/cu_controller.py
  -> USB-Serial
  -> pico/main.py
  -> PWM an der Carrera Control Unit
```

## Dokumentation

- [Pico-Firmware](pico/README.md)
  - Hardwareanschluss
  - PWM-Protokoll
  - Watchdog
  - Firmware auf den Pico kopieren
- [Laptop-Paket carrera_control](carrera_control/README.md)
  - Module und Verantwortlichkeiten
  - Recognition-Lap
  - TrackGraph
  - Training
  - automatisches Fahren
  - WebUI
  - CLI und Ausgabedateien

## Schnellstart
Zuerst einen Carrera-Handregler an die Bahn anschließen und das Fahrzeug diesem Regler zuordnen. Prüfen, dass sich das Fahrzeug mit diesem Regler fahren lässt. Anschließend den „Connect +/2.0“-Dongle aus der Buchse der Control Unit (CU) entfernen und den RJ12-Stecker des Pico-Aufbaus in dieselbe Buchse stecken.

Aus dem Ordner `carrera_project` in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
```

Danach zuerst eine Recognition-Lap aufnehmen:

```powershell
python -m carrera_control.cli recognition-lap `
  --output-root data/recognition_laps `
  --stage 5 `
  --timeout-s 120 `
  --camera-index 1
```

Mit dem erzeugten TrackGraph kann ein kurzer Trainingslauf gestartet werden:

```powershell
python -m carrera_control.cli train `
  --track-graph data/recognition_laps/<run>/track_graph.json `
  --output-root data/training_runs `
  --duration-s 60 `
  --web-port 8090
```

Die WebUI ist während des Laufs unter `http://127.0.0.1:8090/` erreichbar.

## Projektstruktur

```text
carrera_project/
├── config/                  # lokale Konfiguration, falls benötigt
├── data/                    # generierte Recognition-, Trainings- und Fahrdaten
├── pico/                    # Firmware für den Raspberry Pi Pico
├── carrera_control/         # Laptop-Anwendung
├── tests/                   # automatisierte Tests
├── pyproject.toml           # Paket- und Abhängigkeitsdefinition
└── README.md                # diese Projektübersicht
```

## Sicherheit

- Gültige CU-Stufen liegen zwischen `0` und `15`.
- Stufen unter `4` starten das Fahrzeug normalerweise nicht.
- Der Pico setzt die PWM nach 500 ms ohne neuen Befehl auf Stufe `0`.
- Bei verlorener Erkennung, Off-track oder Stillstand wird ebenfalls Stufe `0` gesendet.
- Live-Tests zuerst kurz und mit niedriger Stufe ausführen.
