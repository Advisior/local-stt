"""System default input device lookup (#44).

macOS only, via CoreAudio through ctypes. Everywhere else, and on any
error, the lookup returns None and callers skip the check.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from typing import Optional

_logger = logging.getLogger(__name__)

_COREAUDIO_PATH = "/System/Library/Frameworks/CoreAudio.framework/CoreAudio"
_SYSTEM_OBJECT = 1  # kAudioObjectSystemObject
_ELEMENT_MAIN = 0  # kAudioObjectPropertyElementMain


def _fourcc(code: bytes) -> int:
    return int.from_bytes(code, "big")


_DEFAULT_INPUT_DEVICE = _fourcc(b"dIn ")  # kAudioHardwarePropertyDefaultInputDevice
_SCOPE_GLOBAL = _fourcc(b"glob")  # kAudioObjectPropertyScopeGlobal


class _PropertyAddress(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


_get_property_data = None


def _load_get_property_data():
    global _get_property_data
    if _get_property_data is None:
        fn = ctypes.cdll.LoadLibrary(_COREAUDIO_PATH).AudioObjectGetPropertyData
        fn.argtypes = [
            ctypes.c_uint32,
            ctypes.POINTER(_PropertyAddress),
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_void_p,
        ]
        fn.restype = ctypes.c_int32
        _get_property_data = fn
    return _get_property_data


def default_input_device_id() -> Optional[int]:
    """CoreAudio id of the system default input device, or None."""
    if sys.platform != "darwin":
        return None
    try:
        get_property_data = _load_get_property_data()
        address = _PropertyAddress(_DEFAULT_INPUT_DEVICE, _SCOPE_GLOBAL, _ELEMENT_MAIN)
        device_id = ctypes.c_uint32(0)
        size = ctypes.c_uint32(ctypes.sizeof(device_id))
        status = get_property_data(
            _SYSTEM_OBJECT, ctypes.byref(address), 0, None,
            ctypes.byref(size), ctypes.byref(device_id),
        )
    except Exception:
        _logger.debug("Default input lookup unavailable", exc_info=True)
        return None
    if status != 0:
        _logger.debug("Default input lookup failed (OSStatus %d)", status)
        return None
    return int(device_id.value)
