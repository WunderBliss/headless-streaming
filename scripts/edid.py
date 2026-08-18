#!/usr/bin/env python3
"""Minimal EDID 1.4 generation, validation, and mode normalization."""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


EDID_HEADER = bytes.fromhex("00 ff ff ff ff ff ff 00")
MANUFACTURER = "VDS"
PRODUCT_CODE = 0xD150
MONITOR_NAME = "HEADLESS-VDS"
SERIAL_TEXT = "HVD-00000001"
LEGACY_MONITOR_NAME = "VIRTUAL-POC"
LEGACY_SERIAL_TEXT = "VDS-POC-0001"
EDID_VERSION = (1, 4)
REFRESH_TOLERANCE_HZ = 0.5
FALLBACK_MAX_WIDTH = 3840
FALLBACK_MAX_HEIGHT = 2160
FALLBACK_MAX_HZ = 60.0
MAX_REQUEST_WIDTH = 16384
MAX_REQUEST_HEIGHT = 16384
MAX_REQUEST_HZ = 1000.0
MAX_FALLBACK_ASPECT_ERROR = 0.005
BASELINE_MODE = (1920, 1080, 60.0)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
EDID_DECODE = Path("/usr/bin/edid-decode")


class EdidError(ValueError):
    """Raised when generation or validation cannot produce a safe EDID."""


class DetailedTimingRangeError(EdidError):
    """Raised when a timing cannot fit in an EDID detailed timing descriptor."""


@dataclass(frozen=True)
class Timing:
    width: int
    height: int
    requested_hz: float
    pixel_clock_khz: int
    h_front: int
    h_sync: int
    h_back: int
    v_front: int
    v_sync: int
    v_back: int
    hsync_positive: bool
    vsync_positive: bool
    reduced_blanking: bool

    @property
    def h_blank(self) -> int:
        return self.h_front + self.h_sync + self.h_back

    @property
    def v_blank(self) -> int:
        return self.v_front + self.v_sync + self.v_back

    @property
    def h_total(self) -> int:
        return self.width + self.h_blank

    @property
    def v_total(self) -> int:
        return self.height + self.v_blank

    @property
    def actual_hz(self) -> float:
        return self.pixel_clock_khz * 1000 / (self.h_total * self.v_total)

    @property
    def horizontal_khz(self) -> float:
        return self.pixel_clock_khz / self.h_total


@dataclass(frozen=True)
class ValidationResult:
    manufacturer: str
    product_code: int
    blocks: int
    timing: Timing
    width_mm: int
    height_mm: int
    checksums: tuple[int, ...]

    def lines(self) -> list[str]:
        t = self.timing
        return [
            "EDID validation: PASS",
            f"  header: {EDID_HEADER.hex(' ')}",
            f"  length: {self.blocks * 128} bytes ({self.blocks} block)",
            "  checksums: "
            + ", ".join(
                f"block {index}=0x{checksum:02x} (sum modulo 256 = 0)"
                for index, checksum in enumerate(self.checksums)
            ),
            f"  version: {EDID_VERSION[0]}.{EDID_VERSION[1]}",
            f"  identity: {self.manufacturer} product 0x{self.product_code:04x}",
            "  preferred timing: "
            f"{t.width}x{t.height}@{t.actual_hz:.6f} Hz "
            f"(requested {t.requested_hz:g} Hz)",
            "  detailed timing: "
            f"{t.pixel_clock_khz / 1000:.3f} MHz, "
            f"H {t.width} {t.width + t.h_front} "
            f"{t.width + t.h_front + t.h_sync} {t.h_total}, "
            f"V {t.height} {t.height + t.v_front} "
            f"{t.height + t.v_front + t.v_sync} {t.v_total}, "
            f"{'+' if t.hsync_positive else '-'}HSync "
            f"{'+' if t.vsync_positive else '-'}VSync",
            "  timing standard: "
            + (
                "CVT reduced blanking v1"
                if t.reduced_blanking
                else "CVT normal blanking"
            ),
            f"  physical dimensions: {self.width_mm} mm x {self.height_mm} mm",
            "  extensions: none",
        ]


@dataclass(frozen=True)
class NormalizedMode:
    """A validated EDID and the exact/fallback decision that produced it."""

    requested_width: int
    requested_height: int
    requested_hz: float
    width: int
    height: int
    refresh_hz: float
    edid: bytes
    fallback: bool
    exact_rejection_reason: str | None
    aspect_error: float
    emergency: bool

    @property
    def requested(self) -> str:
        return _format_mode(
            self.requested_width, self.requested_height, self.requested_hz
        )

    @property
    def effective(self) -> str:
        return _format_mode(self.width, self.height, self.refresh_hz)


def _manufacturer_word(name: str) -> int:
    if len(name) != 3 or any(not ("A" <= char <= "Z") for char in name):
        raise EdidError("manufacturer must contain exactly three A-Z characters")
    return sum((ord(char) - 64) << shift for char, shift in zip(name, (10, 5, 0)))


def _decode_manufacturer(data: bytes) -> str:
    word = int.from_bytes(data, "big")
    return "".join(chr(((word >> shift) & 0x1F) + 64) for shift in (10, 5, 0))


def _vertical_sync_lines(width: int, height: int) -> int:
    # CVT 1.2 table 3-3. Exact integer aspect ratios get their prescribed VSync.
    if width * 3 == height * 4:
        return 4
    if width * 9 == height * 16:
        return 5
    if width * 10 == height * 16:
        return 6
    if width * 4 == height * 5:
        return 7
    if width * 9 == height * 15:
        return 7
    return 10


def cvt_timing(width: int, height: int, refresh_hz: float) -> Timing:
    """Calculate a progressive CVT 1.2 normal-blanking timing."""
    if not 320 <= width <= 4095:
        raise EdidError("width must be between 320 and 4095 pixels")
    if width % 8:
        raise EdidError("CVT width must be a multiple of 8 pixels")
    if not 200 <= height <= 4095:
        raise EdidError("height must be between 200 and 4095 pixels")
    if not math.isfinite(refresh_hz) or not 24 <= refresh_hz <= 240:
        raise EdidError("refresh rate must be between 24 and 240 Hz")

    cell_granularity = 8
    minimum_v_porch = 3
    minimum_vsync_back_porch_us = 550.0
    minimum_v_back_porch = 6
    hsync_percent = 8.0
    c_prime = 30.0
    m_prime = 300.0

    vsync = _vertical_sync_lines(width, height)
    h_period_est_us = (
        (1.0 / refresh_hz) - (minimum_vsync_back_porch_us / 1_000_000.0)
    ) / (height + minimum_v_porch) * 1_000_000.0
    if h_period_est_us <= 0:
        raise EdidError("requested mode leaves no time for CVT vertical blanking")

    vsync_back_porch = max(
        vsync + minimum_v_back_porch,
        round(minimum_vsync_back_porch_us / h_period_est_us),
    )
    v_back = vsync_back_porch - vsync
    ideal_duty_cycle = c_prime - (m_prime * h_period_est_us / 1000.0)
    if not 0 < ideal_duty_cycle < 100:
        raise EdidError("requested mode is outside the supported CVT duty-cycle range")

    h_blank = round(
        (width * ideal_duty_cycle / (100.0 - ideal_duty_cycle))
        / (2 * cell_granularity)
    ) * (2 * cell_granularity)
    h_total = width + h_blank
    h_sync = round((hsync_percent / 100.0 * h_total) / cell_granularity) * cell_granularity
    h_front = h_blank // 2 - h_sync
    h_back = h_blank - h_front - h_sync

    # CVT clocks are rounded down to the standard 250 kHz step.
    pixel_clock_mhz = math.floor((h_total / h_period_est_us) / 0.25) * 0.25
    pixel_clock_khz = round(pixel_clock_mhz * 1000)
    timing = Timing(
        width=width,
        height=height,
        requested_hz=refresh_hz,
        pixel_clock_khz=pixel_clock_khz,
        h_front=h_front,
        h_sync=h_sync,
        h_back=h_back,
        v_front=minimum_v_porch,
        v_sync=vsync,
        v_back=v_back,
        hsync_positive=False,
        vsync_positive=True,
        reduced_blanking=False,
    )
    _check_dtd_ranges(timing)
    return timing


def cvt_reduced_blanking_timing(
    width: int, height: int, refresh_hz: float
) -> Timing:
    """Calculate a progressive CVT 1.2 reduced-blanking-v1 timing."""
    if not 320 <= width <= 4095:
        raise EdidError("width must be between 320 and 4095 pixels")
    if width % 8:
        raise EdidError("CVT width must be a multiple of 8 pixels")
    if not 200 <= height <= 4095:
        raise EdidError("height must be between 200 and 4095 pixels")
    if not math.isfinite(refresh_hz) or not 24 <= refresh_hz <= 240:
        raise EdidError("refresh rate must be between 24 and 240 Hz")
    refresh_multiple = refresh_hz / 60.0
    if abs(refresh_multiple - round(refresh_multiple)) > 1e-6:
        raise EdidError(
            "CVT reduced blanking v1 requires a refresh-rate multiple of 60 Hz"
        )

    # CVT 1.2 reduced blanking v1 uses fixed horizontal blanking and at least
    # 460 us of vertical blanking.
    h_front = 48
    h_sync = 32
    h_back = 80
    v_front = 3
    v_sync = _vertical_sync_lines(width, height)
    minimum_v_blank_us = 460.0
    minimum_v_back_porch = 6

    h_period_est_us = (
        (1.0 / refresh_hz) - (minimum_v_blank_us / 1_000_000.0)
    ) / (height + v_front) * 1_000_000.0
    if h_period_est_us <= 0:
        raise EdidError(
            "requested mode leaves no time for CVT reduced vertical blanking"
        )

    v_blank = max(
        v_front + v_sync + minimum_v_back_porch,
        math.floor(minimum_v_blank_us / h_period_est_us) + 1,
    )
    v_back = v_blank - v_front - v_sync
    h_total = width + h_front + h_sync + h_back
    v_total = height + v_blank

    # CVT clocks are rounded down to the standard 250 kHz step.
    unrounded_pixel_clock_khz = h_total * v_total * refresh_hz / 1000.0
    pixel_clock_khz = math.floor(unrounded_pixel_clock_khz / 250.0) * 250
    timing = Timing(
        width=width,
        height=height,
        requested_hz=refresh_hz,
        pixel_clock_khz=pixel_clock_khz,
        h_front=h_front,
        h_sync=h_sync,
        h_back=h_back,
        v_front=v_front,
        v_sync=v_sync,
        v_back=v_back,
        hsync_positive=True,
        vsync_positive=False,
        reduced_blanking=True,
    )
    _check_dtd_ranges(timing)
    return timing


def _check_dtd_ranges(timing: Timing) -> None:
    fields = {
        "horizontal active": (timing.width, 0xFFF),
        "horizontal blanking": (timing.h_blank, 0xFFF),
        "vertical active": (timing.height, 0xFFF),
        "vertical blanking": (timing.v_blank, 0xFFF),
        "horizontal front porch": (timing.h_front, 0x3FF),
        "horizontal sync width": (timing.h_sync, 0x3FF),
        "vertical front porch": (timing.v_front, 0x3F),
        "vertical sync width": (timing.v_sync, 0x3F),
    }
    for name, (value, maximum) in fields.items():
        if not 0 <= value <= maximum:
            raise DetailedTimingRangeError(
                f"{name} {value} cannot be represented in an EDID DTD"
            )
    if not 10 <= timing.pixel_clock_khz <= 655_350:
        raise DetailedTimingRangeError(
            f"pixel clock {timing.pixel_clock_khz / 1000:.3f} MHz cannot be represented"
        )


def _physical_size_mm(width: int, height: int) -> tuple[int, int]:
    # A stable virtual density of 96 dpi avoids pathological compositor scaling.
    return round(width * 25.4 / 96), round(height * 25.4 / 96)


def _pack_dtd(timing: Timing, width_mm: int, height_mm: int) -> bytes:
    _check_dtd_ranges(timing)
    if not 1 <= width_mm <= 0xFFF or not 1 <= height_mm <= 0xFFF:
        raise EdidError("physical dimensions cannot be represented in an EDID DTD")

    data = bytearray(18)
    data[0:2] = (timing.pixel_clock_khz // 10).to_bytes(2, "little")
    data[2] = timing.width & 0xFF
    data[3] = timing.h_blank & 0xFF
    data[4] = ((timing.width >> 8) << 4) | (timing.h_blank >> 8)
    data[5] = timing.height & 0xFF
    data[6] = timing.v_blank & 0xFF
    data[7] = ((timing.height >> 8) << 4) | (timing.v_blank >> 8)
    data[8] = timing.h_front & 0xFF
    data[9] = timing.h_sync & 0xFF
    data[10] = ((timing.v_front & 0xF) << 4) | (timing.v_sync & 0xF)
    data[11] = (
        ((timing.h_front >> 8) & 0x3) << 6
        | ((timing.h_sync >> 8) & 0x3) << 4
        | ((timing.v_front >> 4) & 0x3) << 2
        | ((timing.v_sync >> 4) & 0x3)
    )
    data[12] = width_mm & 0xFF
    data[13] = height_mm & 0xFF
    data[14] = ((width_mm >> 8) << 4) | (height_mm >> 8)
    data[15] = 0
    data[16] = 0
    # Digital separate sync, progressive; polarity comes from the selected CVT timing.
    data[17] = 0x18 | (0x04 if timing.vsync_positive else 0) | (
        0x02 if timing.hsync_positive else 0
    )
    return bytes(data)


def _text_descriptor(tag: int, text: str) -> bytes:
    encoded = text.encode("ascii")
    if len(encoded) > 12:
        raise EdidError("descriptor text must be at most 12 ASCII characters")
    payload = (encoded + b"\n").ljust(13, b" ")
    return b"\x00\x00\x00" + bytes((tag, 0)) + payload


def generate_edid(width: int, height: int, refresh_hz: float) -> bytes:
    try:
        timing = cvt_timing(width, height, refresh_hz)
    except DetailedTimingRangeError:
        # Preserve normal blanking for existing modes, but fall back to CVT-RBv1
        # when normal blanking cannot fit in a base-block DTD. For example,
        # 2560x1600@120 exceeds the DTD's 655.35 MHz pixel-clock maximum without
        # reduced blanking.
        timing = cvt_reduced_blanking_timing(width, height, refresh_hz)
    width_mm, height_mm = _physical_size_mm(width, height)

    edid = bytearray(128)
    edid[0:8] = EDID_HEADER
    edid[8:10] = _manufacturer_word(MANUFACTURER).to_bytes(2, "big")
    edid[10:12] = PRODUCT_CODE.to_bytes(2, "little")
    edid[12:16] = bytes(4)
    edid[16] = 1
    edid[17] = 2026 - 1990
    edid[18:20] = bytes(EDID_VERSION)
    edid[20] = 0xA5  # Digital, 8 bits/component, DisplayPort interface.
    edid[21] = min(255, round(width_mm / 10))
    edid[22] = min(255, round(height_mm / 10))
    edid[23] = 120  # Gamma 2.20.
    edid[24] = 0x06  # sRGB is primary; first DTD is preferred.
    edid[25:35] = bytes.fromhex("ee 91 a3 54 4c 99 26 0f 50 54")
    edid[35:38] = bytes(3)  # No legacy established timings.
    edid[38:54] = b"\x01\x01" * 8  # No standard timings.
    edid[54:72] = _pack_dtd(timing, width_mm, height_mm)
    edid[72:90] = _text_descriptor(0xFC, MONITOR_NAME)
    edid[90:108] = _text_descriptor(0xFF, SERIAL_TEXT)
    edid[108:126] = bytes((0, 0, 0, 0x10, 0)) + bytes(13)  # Dummy descriptor.
    edid[126] = 0  # No extension blocks.
    edid[127] = (-sum(edid[:127])) & 0xFF

    result = bytes(edid)
    validate_edid(result, width, height, refresh_hz, require_managed_identity=True)
    return result


def _format_hz(refresh_hz: float) -> str:
    return f"{refresh_hz:.6f}".rstrip("0").rstrip(".")


def _format_mode(width: int, height: int, refresh_hz: float) -> str:
    return f"{width}x{height}@{_format_hz(refresh_hz)}"


def _exact_rejection_reason(
    width: int, height: int, refresh_hz: float, error: EdidError
) -> str:
    if width > 4095:
        return "width exceeds the base EDID 4095-pixel limit"
    if width < 320:
        return "width is below the generator's 320-pixel minimum"
    if width % 8:
        return "width is not divisible by the generator's 8-pixel granularity"
    if height > 4095:
        return "height exceeds the base EDID 4095-line limit"
    if height < 200:
        return "height is below the generator's 200-line minimum"
    if refresh_hz > 240:
        return "refresh exceeds the generator's 240 Hz limit"
    if refresh_hz < 24:
        return "refresh is below the generator's 24 Hz minimum"
    return str(error)


def _aspect_error(
    requested_width: int, requested_height: int, width: int, height: int
) -> float:
    requested_aspect = requested_width / requested_height
    return abs((width / height) - requested_aspect) / requested_aspect


def _fallback_dimension_candidates(
    requested_width: int, requested_height: int
) -> list[tuple[int, int, float]]:
    """Return large-to-small candidates within the request and fallback box."""
    maximum_width = min(requested_width, FALLBACK_MAX_WIDTH)
    maximum_height = min(requested_height, FALLBACK_MAX_HEIGHT)
    if maximum_width < 320 or maximum_height < 200:
        return []

    candidates: dict[tuple[int, int], tuple[float, float, int]] = {}
    for width in range((maximum_width // 8) * 8, 319, -8):
        ideal_height = width * requested_height / requested_width
        possible_heights = {
            math.floor(ideal_height),
            round(ideal_height),
            math.ceil(ideal_height),
            min(maximum_height, max(200, round(ideal_height))),
        }
        for height in possible_heights:
            if not 200 <= height <= maximum_height:
                continue
            error = _aspect_error(
                requested_width, requested_height, width, height
            )
            if error > MAX_FALLBACK_ASPECT_ERROR:
                continue
            # Both dimensions are bounded by the original request, so this scale
            # can never upscale merely to fill the fallback bounding box.
            scale = min(
                width / requested_width, height / requested_height
            )
            candidates[(width, height)] = (scale, error, width * height)

    ordered = sorted(
        candidates,
        key=lambda dimensions: (
            -candidates[dimensions][0],
            candidates[dimensions][1],
            -candidates[dimensions][2],
        ),
    )
    return [
        (width, height, candidates[(width, height)][1])
        for width, height in ordered
    ]


def normalize_mode(width: int, height: int, refresh_hz: float) -> NormalizedMode:
    """Generate an exact EDID or choose a safe, validated fallback mode."""
    if isinstance(width, bool) or not isinstance(width, int):
        raise EdidError("requested width must be an integer")
    if isinstance(height, bool) or not isinstance(height, int):
        raise EdidError("requested height must be an integer")
    if not 1 <= width <= MAX_REQUEST_WIDTH:
        raise EdidError(
            f"requested width must be between 1 and {MAX_REQUEST_WIDTH} pixels"
        )
    if not 1 <= height <= MAX_REQUEST_HEIGHT:
        raise EdidError(
            f"requested height must be between 1 and {MAX_REQUEST_HEIGHT} pixels"
        )
    if not isinstance(refresh_hz, (int, float)) or isinstance(refresh_hz, bool):
        raise EdidError("requested refresh must be numeric")
    refresh_hz = float(refresh_hz)
    if not math.isfinite(refresh_hz) or not 1 <= refresh_hz <= MAX_REQUEST_HZ:
        raise EdidError(
            f"requested refresh must be between 1 and {MAX_REQUEST_HZ:g} Hz"
        )

    try:
        exact_edid = generate_edid(width, height, refresh_hz)
    except EdidError as exact_error:
        reason = _exact_rejection_reason(width, height, refresh_hz, exact_error)
    else:
        return NormalizedMode(
            requested_width=width,
            requested_height=height,
            requested_hz=refresh_hz,
            width=width,
            height=height,
            refresh_hz=refresh_hz,
            edid=exact_edid,
            fallback=False,
            exact_rejection_reason=None,
            aspect_error=0.0,
            emergency=False,
        )

    fallback_hz = min(FALLBACK_MAX_HZ, max(24.0, refresh_hz))
    generation_errors: list[str] = []
    for candidate_width, candidate_height, aspect_error in (
        _fallback_dimension_candidates(width, height)
    ):
        try:
            fallback_edid = generate_edid(
                candidate_width, candidate_height, fallback_hz
            )
        except EdidError as fallback_error:
            if len(generation_errors) < 3:
                generation_errors.append(
                    f"{_format_mode(candidate_width, candidate_height, fallback_hz)}: "
                    f"{fallback_error}"
                )
            continue
        return NormalizedMode(
            requested_width=width,
            requested_height=height,
            requested_hz=refresh_hz,
            width=candidate_width,
            height=candidate_height,
            refresh_hz=fallback_hz,
            edid=fallback_edid,
            fallback=True,
            exact_rejection_reason=reason,
            aspect_error=aspect_error,
            emergency=False,
        )

    baseline_width, baseline_height, baseline_hz = BASELINE_MODE
    try:
        emergency_edid = generate_edid(
            baseline_width, baseline_height, baseline_hz
        )
    except EdidError as emergency_error:
        details = "; ".join(generation_errors) or "no aspect-preserving candidates"
        raise EdidError(
            f"exact mode was rejected ({reason}); fallback generation failed "
            f"({details}); emergency baseline also failed: {emergency_error}"
        ) from emergency_error
    return NormalizedMode(
        requested_width=width,
        requested_height=height,
        requested_hz=refresh_hz,
        width=baseline_width,
        height=baseline_height,
        refresh_hz=baseline_hz,
        edid=emergency_edid,
        fallback=True,
        exact_rejection_reason=reason,
        aspect_error=_aspect_error(
            width, height, baseline_width, baseline_height
        ),
        emergency=True,
    )


def _parse_dtd(data: bytes, requested_hz: float) -> tuple[Timing, int, int]:
    if len(data) != 18 or data[0:2] == b"\x00\x00":
        raise EdidError("first descriptor is not a detailed timing")
    pixel_clock_khz = int.from_bytes(data[0:2], "little") * 10
    width = data[2] | ((data[4] >> 4) << 8)
    h_blank = data[3] | ((data[4] & 0xF) << 8)
    height = data[5] | ((data[7] >> 4) << 8)
    v_blank = data[6] | ((data[7] & 0xF) << 8)
    h_front = data[8] | (((data[11] >> 6) & 0x3) << 8)
    h_sync = data[9] | (((data[11] >> 4) & 0x3) << 8)
    v_front = ((data[10] >> 4) & 0xF) | (((data[11] >> 2) & 0x3) << 4)
    v_sync = (data[10] & 0xF) | ((data[11] & 0x3) << 4)
    h_back = h_blank - h_front - h_sync
    v_back = v_blank - v_front - v_sync
    width_mm = data[12] | ((data[14] >> 4) << 8)
    height_mm = data[13] | ((data[14] & 0xF) << 8)
    if h_back < 0 or v_back < 0:
        raise EdidError("preferred timing has invalid blanking intervals")
    if data[17] & 0x80:
        raise EdidError("interlaced preferred timings are not supported")
    if data[17] & 0x18 != 0x18:
        raise EdidError("preferred timing does not use digital separate sync")
    timing = Timing(
        width=width,
        height=height,
        requested_hz=requested_hz,
        pixel_clock_khz=pixel_clock_khz,
        h_front=h_front,
        h_sync=h_sync,
        h_back=h_back,
        v_front=v_front,
        v_sync=v_sync,
        v_back=v_back,
        hsync_positive=bool(data[17] & 0x02),
        vsync_positive=bool(data[17] & 0x04),
        reduced_blanking=(
            h_blank == 160
            and h_front == 48
            and h_sync == 32
            and h_back == 80
            and bool(data[17] & 0x02)
            and not bool(data[17] & 0x04)
        ),
    )
    return timing, width_mm, height_mm


def validate_edid(
    data: bytes,
    expected_width: int | None = None,
    expected_height: int | None = None,
    expected_hz: float | None = None,
    *,
    require_managed_identity: bool = False,
    require_poc_identity: bool = False,
) -> ValidationResult:
    if len(data) < 128 or len(data) % 128:
        raise EdidError(f"EDID length {len(data)} is not a positive multiple of 128 bytes")
    if data[:8] != EDID_HEADER:
        raise EdidError("invalid EDID header")
    expected_blocks = data[126] + 1
    if len(data) != expected_blocks * 128:
        raise EdidError(
            f"extension count requires {expected_blocks * 128} bytes, got {len(data)}"
        )
    checksums = tuple(block[-1] for block in (data[i : i + 128] for i in range(0, len(data), 128)))
    for index in range(expected_blocks):
        if sum(data[index * 128 : (index + 1) * 128]) & 0xFF:
            raise EdidError(f"checksum failure in EDID block {index}")
    if tuple(data[18:20]) != EDID_VERSION:
        raise EdidError(f"expected EDID 1.4, got {data[18]}.{data[19]}")
    if not data[20] & 0x80:
        raise EdidError("EDID does not describe a digital display")
    if not data[24] & 0x02:
        raise EdidError("EDID does not mark the first detailed timing as preferred")

    manufacturer = _decode_manufacturer(data[8:10])
    product_code = int.from_bytes(data[10:12], "little")
    if require_managed_identity or require_poc_identity:
        common_identity = (
            (manufacturer, product_code) == (MANUFACTURER, PRODUCT_CODE)
            and data[12:16] == bytes(4)
            and data[108:126] == bytes((0, 0, 0, 0x10, 0)) + bytes(13)
            and data[126] == 0
        )
        current_identity = (
            data[72:90] == _text_descriptor(0xFC, MONITOR_NAME)
            and data[90:108] == _text_descriptor(0xFF, SERIAL_TEXT)
        )
        legacy_identity = (
            data[72:90] == _text_descriptor(0xFC, LEGACY_MONITOR_NAME)
            and data[90:108] == _text_descriptor(0xFF, LEGACY_SERIAL_TEXT)
        )
        if not common_identity or not (current_identity or legacy_identity):
            raise EdidError("EDID is not owned by headless-virtual-display")

    requested = expected_hz if expected_hz is not None else 0.0
    timing, width_mm, height_mm = _parse_dtd(data[54:72], requested)
    if expected_width is not None and timing.width != expected_width:
        raise EdidError(f"preferred width is {timing.width}, expected {expected_width}")
    if expected_height is not None and timing.height != expected_height:
        raise EdidError(f"preferred height is {timing.height}, expected {expected_height}")
    if expected_hz is not None and abs(timing.actual_hz - expected_hz) > REFRESH_TOLERANCE_HZ:
        raise EdidError(
            f"preferred refresh is {timing.actual_hz:.6f} Hz, expected {expected_hz:g} Hz "
            f"within {REFRESH_TOLERANCE_HZ:g} Hz"
        )
    if width_mm <= 0 or height_mm <= 0:
        raise EdidError("preferred timing has no physical dimensions")
    if abs(data[21] * 10 - width_mm) > 10 or abs(data[22] * 10 - height_mm) > 10:
        raise EdidError("base-block and preferred-timing physical dimensions disagree")

    return ValidationResult(
        manufacturer=manufacturer,
        product_code=product_code,
        blocks=expected_blocks,
        timing=timing,
        width_mm=width_mm,
        height_mm=height_mm,
        checksums=checksums,
    )


def is_managed_edid(data: bytes) -> bool:
    try:
        validate_edid(data, require_managed_identity=True)
    except EdidError:
        return False
    return True


is_poc_edid = is_managed_edid


def validate_with_edid_decode(data: bytes) -> str | None:
    """Run the installed standards checker without creating a temporary file."""
    if not EDID_DECODE.is_file():
        return None
    try:
        result = subprocess.run(
            [str(EDID_DECODE), "--check", "-"],
            input=data,
            capture_output=True,
            check=False,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise EdidError(f"edid-decode could not run: {error}") from error
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace").strip()
    if result.returncode != 0 or "EDID conformity: PASS" not in output:
        raise EdidError(
            "edid-decode rejected the generated EDID:\n" + (output or "(no output)")
        )
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate", help="generate and validate an EDID file")
    generate.add_argument("width", type=int)
    generate.add_argument("height", type=int)
    generate.add_argument("fps", type=float)
    generate.add_argument("output", type=Path)
    validate = subparsers.add_parser("validate", help="validate an existing EDID file")
    validate.add_argument("input", type=Path)
    validate.add_argument("width", type=int, nargs="?")
    validate.add_argument("height", type=int, nargs="?")
    validate.add_argument("fps", type=float, nargs="?")
    normalize = subparsers.add_parser(
        "normalize", help="show the exact/fallback decision without touching DRM"
    )
    normalize.add_argument("width", type=int)
    normalize.add_argument("height", type=int)
    normalize.add_argument("fps", type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "generate":
            data = generate_edid(args.width, args.height, args.fps)
            result = validate_edid(
                data,
                args.width,
                args.height,
                args.fps,
                require_managed_identity=True,
            )
            external_output = validate_with_edid_decode(data)
            output = args.output.resolve(strict=False)
            if not output.is_relative_to(PROJECT_ROOT):
                raise EdidError(
                    f"refusing to write outside the project directory {PROJECT_ROOT}: {output}"
                )
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
            print(f"Wrote {output} ({len(data)} bytes)")
        elif args.command == "validate":
            expected = (args.width, args.height, args.fps)
            if any(value is None for value in expected) and not all(
                value is None for value in expected
            ):
                raise EdidError("expected width, height, and fps must be supplied together")
            result = validate_edid(
                args.input.read_bytes(),
                args.width,
                args.height,
                args.fps,
                require_poc_identity=False,
            )
            external_output = validate_with_edid_decode(args.input.read_bytes())
        else:
            normalized = normalize_mode(args.width, args.height, args.fps)
            print(f"requested: {normalized.requested}")
            if normalized.fallback:
                print(
                    "exact mode unsupported: "
                    f"{normalized.exact_rejection_reason}"
                )
                print(f"effective: {normalized.effective} (fallback)")
                print(
                    f"aspect error: {normalized.aspect_error * 100:.6f}%"
                )
                if normalized.emergency:
                    print(
                        "warning: emergency baseline changes the requested "
                        "aspect ratio"
                    )
            else:
                print(f"effective: {normalized.effective} (exact)")
            result = validate_edid(
                normalized.edid,
                normalized.width,
                normalized.height,
                normalized.refresh_hz,
                require_managed_identity=True,
            )
            external_output = validate_with_edid_decode(normalized.edid)
        print("\n".join(result.lines()))
        if external_output is None:
            print("  edid-decode: not installed (internal validation only)")
        else:
            print("  edid-decode --check: PASS (EDID conformity: PASS)")
        return 0
    except (EdidError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
