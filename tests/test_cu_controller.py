import pytest

from carrera_control import cu_controller
from carrera_control.cu_controller import CarreraCuController, PicoResponseError


class FakeSerial:
    def __init__(self, *args, **kwargs) -> None:
        self.commands: list[bytes] = []
        self.responses: list[bytes] = []
        self.closed = False

    def reset_input_buffer(self) -> None:
        pass

    def write(self, data: bytes) -> int:
        self.commands.append(data)
        self.responses.append(data)
        return len(data)

    def flush(self) -> None:
        pass

    def readline(self) -> bytes:
        return self.responses.pop(0) if self.responses else b""

    def close(self) -> None:
        self.closed = True


def test_context_manager_stops_and_clamps(monkeypatch) -> None:
    fake = FakeSerial()
    monkeypatch.setattr(cu_controller.serial, "Serial", lambda **kwargs: fake)

    with CarreraCuController() as controller:
        assert controller.set_stage(99) == 15

    assert fake.commands == [b"15\n", b"0\n"]
    assert fake.closed is True


def test_fast_path_rounds_and_does_not_read(monkeypatch) -> None:
    fake = FakeSerial()
    monkeypatch.setattr(cu_controller.serial, "Serial", lambda **kwargs: fake)

    with CarreraCuController() as controller:
        controller.set_stage_fast(4.9)
        fake.responses.clear()

    assert fake.commands == [b"5\n", b"0\n"]


def test_mismatched_pico_confirmation_raises(monkeypatch) -> None:
    fake = FakeSerial()
    fake.responses = [b"7\n", b"0\n"]
    monkeypatch.setattr(cu_controller.serial, "Serial", lambda **kwargs: fake)

    with CarreraCuController() as controller:
        with pytest.raises(PicoResponseError, match="expected 4"):
            controller.set_stage(4)