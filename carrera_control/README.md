# carrera_control

Das Paket `carrera_control` ist die Laptop-seitige Anwendung. Es enthaelt keine
MicroPython-Firmware. Die Firmware liegt separat unter [pico/](../../pico/).

## Module

### Hardware und Sicherheit

- [cu_controller.py](cu_controller.py): oeffnet COM4, sendet CU-Stufen und prueft Bestaetigungen
- `set_stage(...)`: bestaetigter, blockierender Befehl fuer Tests und Diagnose
- `set_stage_fast(...)`: nicht blockierender Befehl fuer den Regelkreis
- [stage_control.py](stage_control.py): Slow Start und Stufenbegrenzung

### Kamera und Strecke

- [vision.py](vision.py): HSV-Farberkennung des Fahrzeugmarkers
- [calibration_lap.py](calibration_lap.py): eine feste Recognition-Lap aufnehmen
- [track_graph.py](track_graph.py): Positionsspur glaetten, resampeln und als geschlossenen Graph speichern

Eine Recognition-Lap erzeugt:

```text
<run>/
├── path.csv
├── metadata.json
└── track_graph.json
```

### Training und Fahren

- [training.py](training.py): konservatives Segmentprofil, Kurvenausgaenge, AdaGrad-aehnliche Lernrate und Unfall-Peak-Suche
- [training_runtime.py](training_runtime.py): Live-Kamera-Loop, Rundenzeit, Lost/Off-track/Stall, Speicherung und WebUI-Status
- [autonomous_drive.py](autonomous_drive.py): automatisches Fahren mit dem schnellsten unfallfreien Profil
- [web_ui.py](web_ui.py): lokale Statusseite mit Kamerabild, Trackkarte, Gefahrenstellen, Rundenzeiten und Profilbalken
- [cli.py](cli.py): Kommandozeile fuer Recognition-Lap, Training und Drive

## Laufmodi

### Recognition-Lap

```powershell
python -m carrera_control.cli recognition-lap `
  --output-root data/recognition_laps `
  --stage 5 `
  --timeout-s 120 `
  --camera-index 1
```

Die feste Stufe wird nur fuer die Streckenaufzeichnung verwendet. Es findet
noch kein Training statt.

### Training

```powershell
python -m carrera_control.cli train `
  --track-graph data/recognition_laps/<run>/track_graph.json `
  --output-root data/training_runs `
  --duration-s 300 `
  --web-port 8090
```

Das Training startet konservativ, nutzt einen Slow Start und erhoeht nach
sauberen Runden einzelne Segmente. Bei `vehicle_lost`, `off_track` oder
`stalled` wird Stufe `0` gesendet und die Unfalllogik reduziert einen
vermuteten vorherigen Geschwindigkeits-Peak.

Ein Trainingslauf erzeugt:

```text
<run>/
├── profile.json
├── profile_snapshots/
├── lap_times.csv
├── events.jsonl
└── runtime_state.json
```

Die WebUI ist waehrend des Laufs unter `http://127.0.0.1:8090/` erreichbar.

### Automatisches Fahren

```powershell
python -m carrera_control.cli drive `
  --track-graph data/recognition_laps/<run>/track_graph.json `
  --training-root data/training_runs `
  --output-root data/drive_runs `
  --duration-s 300 `
  --web-port 8090
```

Ohne `--profile` sucht der Drive-Modus automatisch den schnellsten vorhandenen
Clean-Lap-Snapshot unter `data/training_runs/`. Im Drive-Modus wird das Profil
nicht weiter gelernt oder veraendert. Sicherheitsabschaltungen und der Pico-
Watchdog bleiben aktiv.

## WebUI

Die WebUI zeigt:

- Kamerabild und aktuellen Status
- aktuelle, letzte und beste Rundenzeit
- TrackGraph als Karte
- Gefahrenstellen als rote Marker mit Anzahl
- Segmentprofil mit aktuellen Stufen und Aenderungen
- Clean-Lap- und Unfallzaehler pro Segment

## Tests

Aus dem Projektordner:

```powershell
python -m pytest
```

Die Tests fuer dieses Paket liegen im Projektordner unter [tests/](../../tests/).
