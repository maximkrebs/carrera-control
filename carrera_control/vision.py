"""Detect the colored vehicle marker in a Carrera camera frame.

This module deliberately knows nothing about the track, throttle control, or
training. It converts one BGR image into either one :class:`Detection` or
``None``. Track recognition can build on that small, testable boundary later.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

import cv2
import numpy as np


MIN_COLOR_SATURATION = 70
MIN_COLOR_VALUE = 50


@dataclass(frozen=True)
class DetectionConfig:
    """Configuration for rejecting image noise and implausible candidates."""

    color: str = "green"
    min_area: float = 120.0
    max_area: float = 3500.0
    min_center_y: int = 0
    max_center_y: int | None = None
    min_width_to_height_ratio: float = 0.35
    morphology_open_kernel: int = 3
    morphology_close_kernel: int = 5

    def __post_init__(self) -> None:
        if self.color.lower() not in COLOR_RANGES:
            raise ValueError(f"Unsupported vehicle color: {self.color!r}.")
        if self.min_area < 0 or self.max_area < self.min_area:
            raise ValueError("Detection area limits are invalid.")
        if self.min_center_y < 0 or (self.max_center_y is not None and self.max_center_y < self.min_center_y):
            raise ValueError("Detection vertical limits are invalid.")
        if self.min_width_to_height_ratio < 0:
            raise ValueError("min_width_to_height_ratio must not be negative.")
        if self.morphology_open_kernel < 1 or self.morphology_close_kernel < 1:
            raise ValueError("Morphology kernel sizes must be positive.")


@dataclass(frozen=True)
class Detection:
    """Position and image bounds of a detected vehicle marker."""

    center: tuple[int, int]
    rect: tuple[int, int, int, int]
    area: float


# HSV hue uses the range 0..179 in OpenCV. Red wraps around that range and is
# therefore represented by two intervals.
COLOR_RANGES: dict[str, tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...]] = {
    "green": (((35, MIN_COLOR_SATURATION, MIN_COLOR_VALUE), (90, 255, 255)),),
    "cyan": (((80, MIN_COLOR_SATURATION, MIN_COLOR_VALUE), (105, 255, 255)),),
    "red": (
        ((0, MIN_COLOR_SATURATION, MIN_COLOR_VALUE), (10, 255, 255)),
        ((170, MIN_COLOR_SATURATION, MIN_COLOR_VALUE), (179, 255, 255)),
    ),
    "orange": (((5, MIN_COLOR_SATURATION, MIN_COLOR_VALUE), (24, 255, 255)),),
}


def color_mask(frame: np.ndarray, color: str) -> np.ndarray:
    """Return a binary mask for ``color`` in a BGR frame."""
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("frame must have shape (height, width, 3) and use BGR channels.")
    ranges = COLOR_RANGES.get(color.lower())
    if ranges is None:
        raise ValueError(f"Unsupported vehicle color: {color!r}.")

    hsv_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = np.zeros(hsv_frame.shape[:2], dtype=np.uint8)
    for lower, upper in ranges:
        mask |= cv2.inRange(hsv_frame, np.array(lower), np.array(upper))
    return mask


def find_vehicle(
    frame: np.ndarray,
    config: DetectionConfig | None = None,
    previous_center: tuple[int, int] | None = None,
) -> Detection | None:
    """Find the best colored vehicle marker in one camera frame.

    Candidates are filtered by contour area, vertical position, and shape. If
    ``previous_center`` is available, the candidate nearest to it is selected;
    otherwise the largest valid candidate is selected. This makes detection
    stable when another object has the same color.
    """
    active_config = config or DetectionConfig()
    mask = color_mask(frame, active_config.color)
    mask = _clean_mask(mask, active_config)
    height, _width = frame.shape[:2]
    maximum_center_y = active_config.max_center_y
    if maximum_center_y is None:
        maximum_center_y = height

    candidates: list[Detection] = []
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        candidate = _candidate_from_contour(contour, active_config, maximum_center_y)
        if candidate is not None:
            candidates.append(candidate)

    if not candidates:
        return None
    if previous_center is None:
        return max(candidates, key=lambda candidate: candidate.area)
    return min(candidates, key=lambda candidate: hypot(
        candidate.center[0] - previous_center[0],
        candidate.center[1] - previous_center[1],
    ))


def _clean_mask(mask: np.ndarray, config: DetectionConfig) -> np.ndarray:
    """Remove isolated pixels and close small gaps in a color mask."""
    open_kernel = np.ones((config.morphology_open_kernel, config.morphology_open_kernel), dtype=np.uint8)
    close_kernel = np.ones((config.morphology_close_kernel, config.morphology_close_kernel), dtype=np.uint8)
    cleaned = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_kernel)
    return cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, close_kernel)


def _candidate_from_contour(
    contour: np.ndarray,
    config: DetectionConfig,
    maximum_center_y: int,
) -> Detection | None:
    area = float(cv2.contourArea(contour))
    if not config.min_area <= area <= config.max_area:
        return None

    x, y, width, height = cv2.boundingRect(contour)
    center = (x + width // 2, y + height // 2)
    if not config.min_center_y <= center[1] <= maximum_center_y:
        return None
    if width / max(height, 1) < config.min_width_to_height_ratio:
        return None
    return Detection(center=center, rect=(x, y, width, height), area=area)