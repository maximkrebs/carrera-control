import cv2
import numpy as np
import pytest

from carrera_control.vision import DetectionConfig, color_mask, find_vehicle


def test_find_vehicle_detects_a_green_marker() -> None:
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    cv2.rectangle(frame, (120, 90), (160, 130), (0, 255, 0), thickness=-1)

    detection = find_vehicle(frame, DetectionConfig(min_area=100))

    assert detection is not None
    assert detection.center == (140, 110)
    assert detection.rect == (120, 90, 41, 41)
    assert detection.area > 1000


def test_find_vehicle_uses_previous_center_to_choose_between_markers() -> None:
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    cv2.rectangle(frame, (30, 90), (70, 130), (0, 255, 0), thickness=-1)
    cv2.rectangle(frame, (220, 90), (260, 130), (0, 255, 0), thickness=-1)

    detection = find_vehicle(frame, previous_center=(245, 110))

    assert detection is not None
    assert detection.center == (240, 110)


def test_find_vehicle_returns_none_for_wrong_color_or_out_of_bounds_marker() -> None:
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    cv2.rectangle(frame, (120, 10), (160, 50), (0, 255, 0), thickness=-1)

    assert find_vehicle(frame, DetectionConfig(min_center_y=100)) is None
    assert find_vehicle(frame, DetectionConfig(color="red")) is None


def test_color_mask_rejects_invalid_frames_and_colors() -> None:
    with pytest.raises(ValueError, match="BGR"):
        color_mask(np.zeros((20, 20), dtype=np.uint8), "green")
    with pytest.raises(ValueError, match="Unsupported"):
        color_mask(np.zeros((20, 20, 3), dtype=np.uint8), "purple")