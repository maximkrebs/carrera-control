"""Laptop-side control for a Pico emulating a Carrera Control Unit throttle."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import TextIO

import serial


MIN_STAGE = 0
MAX_STAGE = 15
DEFAULT_PORT = "COM4"
DEFAULT_BAUDRATE = 115200
DEFAULT_TIMEOUT_S = 1.0
DEFAULT_WRITE_TIMEOUT_S = 0.2


class PicoResponseError(RuntimeError):
    """Raised when the Pico response is missing or does not confirm the command."""


class CarreraCuController:
    """Control the Pico using one throttle stage per newline-terminated command."""

    def __init__(
        self,
        port: str = DEFAULT_PORT,
        baudrate: int = DEFAULT_BAUDRATE,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        write_timeout_s: float = DEFAULT_WRITE_TIMEOUT_S,
        dry_run: bool = False,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be greater than zero.")
        if write_timeout_s <= 0:
            raise ValueError("write_timeout_s must be greater than zero.")
        self.port = port
        self.baudrate = baudrate
        self.timeout_s = timeout_s
        self.write_timeout_s = write_timeout_s
        self.dry_run = dry_run
        self._serial: serial.Serial | None = None

    def __enter__(self) -> "CarreraCuController":
        self.open()
        return self

    def __exit__(self, exception_type, exception, traceback) -> bool:
        try:
            if self._serial is not None:
                try:
                    self.stop()
                except Exception:
                    if exception_type is None:
                        raise
        finally:
            self.close()
        return False

    def open(self) -> None:
        """Open the serial connection and discard startup data from the Pico."""
        if self._serial is not None:
            return
        if self.dry_run:
            return
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout_s,
            write_timeout=self.write_timeout_s,
        )
        self._serial.reset_input_buffer()

    def close(self) -> None:
        """Close the serial connection without sending another command."""
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def set_stage(self, stage: int) -> int:
        """Set and confirm a throttle stage, clamped to the Pico range 0..15."""
        bounded_stage = self._clamp_stage(stage)
        if self.dry_run:
            return bounded_stage
        return self._send_stage(bounded_stage)

    def set_stage_fast(self, stage: int) -> None:
        """Send a stage without waiting for confirmation, for control loops."""
        if self._serial is None:
            if self.dry_run:
                return
            raise RuntimeError("The Carrera CU serial connection is not open.")
        bounded_stage = self._clamp_stage(stage)
        self._serial.write(f"{bounded_stage}\n".encode("ascii"))

    def stop(self) -> int:
        """Set the throttle to stage zero and confirm the response."""
        return self._send_stage(MIN_STAGE)

    @staticmethod
    def _clamp_stage(stage: int) -> int:
        return max(MIN_STAGE, min(MAX_STAGE, round(float(stage))))

    def _send_stage(self, stage: int) -> int:
        if self._serial is None:
            raise RuntimeError("The Carrera CU serial connection is not open.")
        self._serial.write(f"{stage}\n".encode("ascii"))
        self._serial.flush()
        response = self._serial.readline()
        if not response:
            raise PicoResponseError(f"Timed out waiting for Pico confirmation of stage {stage}.")
        try:
            confirmed_stage = int(response.decode("ascii").strip())
        except (UnicodeDecodeError, ValueError) as error:
            raise PicoResponseError(f"Invalid Pico response: {response!r}.") from error
        if confirmed_stage != stage:
            raise PicoResponseError(f"Pico confirmed stage {confirmed_stage}, expected {stage}.")
        return confirmed_stage


def record_throttle_schedule(
    csv_path: str | Path,
    hold_seconds: float = 7.0,
    port: str = DEFAULT_PORT,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> None:
    """Log commanded stages and timestamps; this does not measure vehicle motion."""
    if hold_seconds < 0:
        raise ValueError("hold_seconds must not be negative.")

    output_path = Path(csv_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        _write_schedule(handle, hold_seconds, port, baudrate, timeout_s)


def _write_schedule(
    handle: TextIO,
    hold_seconds: float,
    port: str,
    baudrate: int,
    timeout_s: float,
) -> None:
    writer = csv.writer(handle)
    writer.writerow(("timestamp_utc", "stage"))
    with CarreraCuController(port, baudrate, timeout_s) as controller:
        for stage in range(4, MAX_STAGE + 1):
            controller.set_stage(stage)
            writer.writerow((datetime.now(timezone.utc).isoformat(), stage))
            handle.flush()
            time.sleep(hold_seconds)


def measure_throttle_levels(
    csv_path: str | Path,
    hold_seconds: float = 7.0,
    port: str = DEFAULT_PORT,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> None:
    """Backward-compatible alias for :func:`record_throttle_schedule`."""
    record_throttle_schedule(csv_path, hold_seconds, port, baudrate, timeout_s)