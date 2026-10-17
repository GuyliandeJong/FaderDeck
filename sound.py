"""Sounds through Windows' winmm: the mute chime, playing and recording,
and the sound check."""

import math
import array
import ctypes
import ctypes.wintypes
import re
import time
import threading

from core import log


# Mute sounds: two soft notes, falling when the microphone is muted and
# rising when it is unmuted. Each note is a chime: a warm overtone, a natural
# fade and a slight drop onto its pitch, rather than a flat beep. They are
# played through winmm's waveOut, which, unlike winsound, can play on a
# chosen device: the user's headphones rather than something the stream
# captures.
MUTE_SOUND_NOTES = {True: (784, 523), False: (523, 784)}  # Hz, by muted
MUTE_SOUND_SHAPE = {"step_ms": 85, "decay_ms": 110, "drop": 0.02, "overtone": 0.25}
SOUND_RATE = 44100
SOUND_CHECK_SECONDS = 5
_mute_sounds = {}


def chime_samples(
    notes, step_ms=70, decay_ms=60, drop=0.06, overtone=0.12,
    volume=0.35, rate=SOUND_RATE,
):
    """Mono 16-bit samples of the notes, each starting step_ms apart.

    decay_ms: how fast a note fades. drop: how far sharp a note starts
    (0.06 is 6 %). overtone: loudness of the octave above, for warmth.
    """
    step = rate * step_ms // 1000
    tail = rate * decay_ms * 6 // 1000  # until about -50 dB
    attack = max(1, rate * 3 // 1000)
    mix = [0.0] * (step * (len(notes) - 1) + tail)
    for index, frequency in enumerate(notes):
        start = index * step
        phase = 0.0
        for i in range(tail):
            seconds = i / rate
            pitch = frequency * (1 + drop * math.exp(-seconds / 0.015))
            phase += 2 * math.pi * pitch / rate
            envelope = min(1.0, i / attack) * math.exp(-seconds * 1000 / decay_ms)
            mix[start + i] += envelope * (
                math.sin(phase) + overtone * math.sin(2 * phase)
            )
    peak = max(abs(value) for value in mix) or 1.0
    return array.array(
        "h", (int(32767 * volume * value / peak) for value in mix)
    ).tobytes()


WAVE_MAPPER = 0xFFFFFFFF  # waveOut's id for the Windows default device
WHDR_DONE = 0x00000001


class _WaveFormat(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", ctypes.wintypes.WORD),
        ("nChannels", ctypes.wintypes.WORD),
        ("nSamplesPerSec", ctypes.wintypes.DWORD),
        ("nAvgBytesPerSec", ctypes.wintypes.DWORD),
        ("nBlockAlign", ctypes.wintypes.WORD),
        ("wBitsPerSample", ctypes.wintypes.WORD),
        ("cbSize", ctypes.wintypes.WORD),
    ]


class _WaveHeader(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_void_p),
        ("dwBufferLength", ctypes.wintypes.DWORD),
        ("dwBytesRecorded", ctypes.wintypes.DWORD),
        ("dwUser", ctypes.c_size_t),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("dwLoops", ctypes.wintypes.DWORD),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_size_t),
    ]


class _WaveOutCaps(ctypes.Structure):
    _fields_ = [
        ("wMid", ctypes.wintypes.WORD),
        ("wPid", ctypes.wintypes.WORD),
        ("vDriverVersion", ctypes.c_uint),
        ("szPname", ctypes.c_wchar * 32),
        ("dwFormats", ctypes.wintypes.DWORD),
        ("wChannels", ctypes.wintypes.WORD),
        ("wReserved1", ctypes.wintypes.WORD),
        ("dwSupport", ctypes.wintypes.DWORD),
    ]


class _WaveInCaps(ctypes.Structure):
    _fields_ = [
        ("wMid", ctypes.wintypes.WORD),
        ("wPid", ctypes.wintypes.WORD),
        ("vDriverVersion", ctypes.c_uint),
        ("szPname", ctypes.c_wchar * 32),
        ("dwFormats", ctypes.wintypes.DWORD),
        ("wChannels", ctypes.wintypes.WORD),
        ("wReserved1", ctypes.wintypes.WORD),
    ]


def _winmm():
    """winmm with the play (waveOut) and record (waveIn) calls declared."""
    winmm = ctypes.WinDLL("winmm")
    handle = ctypes.c_void_p
    for name, argtypes in (
        ("waveOutGetDevCapsW", (ctypes.c_size_t, ctypes.POINTER(_WaveOutCaps), ctypes.c_uint)),
        ("waveOutOpen", (ctypes.POINTER(handle), ctypes.c_uint, ctypes.POINTER(_WaveFormat),
                         ctypes.c_size_t, ctypes.c_size_t, ctypes.wintypes.DWORD)),
        ("waveOutPrepareHeader", (handle, ctypes.POINTER(_WaveHeader), ctypes.c_uint)),
        ("waveOutWrite", (handle, ctypes.POINTER(_WaveHeader), ctypes.c_uint)),
        ("waveOutUnprepareHeader", (handle, ctypes.POINTER(_WaveHeader), ctypes.c_uint)),
        ("waveOutClose", (handle,)),
        ("waveInGetDevCapsW", (ctypes.c_size_t, ctypes.POINTER(_WaveInCaps), ctypes.c_uint)),
        ("waveInOpen", (ctypes.POINTER(handle), ctypes.c_uint, ctypes.POINTER(_WaveFormat),
                        ctypes.c_size_t, ctypes.c_size_t, ctypes.wintypes.DWORD)),
        ("waveInPrepareHeader", (handle, ctypes.POINTER(_WaveHeader), ctypes.c_uint)),
        ("waveInAddBuffer", (handle, ctypes.POINTER(_WaveHeader), ctypes.c_uint)),
        ("waveInStart", (handle,)),
        ("waveInReset", (handle,)),
        ("waveInUnprepareHeader", (handle, ctypes.POINTER(_WaveHeader), ctypes.c_uint)),
        ("waveInClose", (handle,)),
    ):
        function = getattr(winmm, name)
        function.argtypes = argtypes
        function.restype = ctypes.c_uint
    winmm.waveOutGetNumDevs.restype = ctypes.c_uint
    winmm.waveInGetNumDevs.restype = ctypes.c_uint
    return winmm


def sound_devices():
    """Names of the devices Windows can play a sound on.

    waveOut keeps only the first 31 characters of a name.
    """
    winmm = _winmm()
    names = []
    for index in range(winmm.waveOutGetNumDevs()):
        caps = _WaveOutCaps()
        if winmm.waveOutGetDevCapsW(index, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
            names.append(caps.szPname)
    return names


def wave_header(data):
    """A buffer holding the samples, and a waveOut header pointing at it.

    Keep the buffer alive until the sound has played.
    """
    buffer = ctypes.create_string_buffer(data, len(data))
    # The raw address: a c_char_p here would point at a copy, and the
    # device would play that instead (silence).
    return buffer, _WaveHeader(ctypes.addressof(buffer), len(data))


def play_samples(data, device=""):
    """Play mono 16-bit samples on a device, by name, without waiting.

    An empty or unknown name plays on the Windows default device.
    """

    def run():
        winmm = _winmm()
        names = sound_devices()
        device_id = names.index(device) if device in names else WAVE_MAPPER
        sound_format = _WaveFormat(1, 1, SOUND_RATE, SOUND_RATE * 2, 2, 16, 0)
        handle = ctypes.c_void_p()
        if winmm.waveOutOpen(ctypes.byref(handle), device_id,
                             ctypes.byref(sound_format), 0, 0, 0):
            log.debug(f"Could not open {device or 'the default device'} for a sound")
            return
        buffer, header = wave_header(data)
        size = ctypes.sizeof(header)
        try:
            winmm.waveOutPrepareHeader(handle, ctypes.byref(header), size)
            winmm.waveOutWrite(handle, ctypes.byref(header), size)
            deadline = time.monotonic() + 5
            while not header.dwFlags & WHDR_DONE and time.monotonic() < deadline:
                time.sleep(0.02)
            winmm.waveOutUnprepareHeader(handle, ctypes.byref(header), size)
        finally:
            winmm.waveOutClose(handle)

    def guarded():
        try:
            run()
        except Exception as e:
            log.debug(f"Could not play a sound: {e}")

    threading.Thread(target=guarded, name="FaderDeckSound", daemon=True).start()


def recording_devices():
    """Names of the devices Windows can record from (cut at 31 characters)."""
    winmm = _winmm()
    names = []
    for index in range(winmm.waveInGetNumDevs()):
        caps = _WaveInCaps()
        if winmm.waveInGetDevCapsW(index, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
            names.append(caps.szPname)
    return names


def sound_check_device(names, output="B1"):
    """A recording device that carries the processed microphone.

    "VoiceMeeter Out B1" first. People rename these in Windows ("Stream
    Microphone"), so next any VoiceMeeter device that is not one of the
    hardware outputs A1-A5, preferring one that is called a microphone.
    The raw microphone itself would skip the processing.
    """
    wanted = f"out {output}".casefold()
    for name in names:
        if wanted in name.casefold():
            return name
    virtual = [
        name for name in names
        if "vb-audio" in name.casefold()
        and not re.search(r"out a\d", name.casefold())
    ]
    for name in virtual:
        if name.casefold().startswith("microphone"):
            return name
    return virtual[0] if virtual else ""


def record_samples(device, seconds):
    """Record mono 16-bit samples from a device, by name. Waits: call it
    off the GUI thread. Raises OSError when the device cannot be opened."""
    winmm = _winmm()
    names = recording_devices()
    if device not in names:
        raise OSError(f"{device or 'No device'} is not connected")
    sound_format = _WaveFormat(1, 1, SOUND_RATE, SOUND_RATE * 2, 2, 16, 0)
    handle = ctypes.c_void_p()
    if winmm.waveInOpen(ctypes.byref(handle), names.index(device),
                        ctypes.byref(sound_format), 0, 0, 0):
        raise OSError(f"{device} could not be opened for recording")
    buffer, header = wave_header(bytes(SOUND_RATE * 2 * seconds))
    size = ctypes.sizeof(header)
    try:
        winmm.waveInPrepareHeader(handle, ctypes.byref(header), size)
        winmm.waveInAddBuffer(handle, ctypes.byref(header), size)
        winmm.waveInStart(handle)
        deadline = time.monotonic() + seconds + 3
        while not header.dwFlags & WHDR_DONE and time.monotonic() < deadline:
            time.sleep(0.05)
        winmm.waveInReset(handle)
        winmm.waveInUnprepareHeader(handle, ctypes.byref(header), size)
        return ctypes.string_at(buffer, header.dwBytesRecorded)
    finally:
        winmm.waveInClose(handle)


def sound_check(device, seconds, play_on):
    """Record the processed microphone, then play it back. Returns a short
    report for the settings window."""
    samples = record_samples(device, seconds)
    if not samples:
        return "Nothing was recorded. Is the microphone routed to that output?"
    play_samples(samples, play_on)
    return "Playing back what voice chat and your stream hear."


def play_mute_sound(muted, device=""):
    if muted not in _mute_sounds:
        _mute_sounds[muted] = chime_samples(
            MUTE_SOUND_NOTES[muted], **MUTE_SOUND_SHAPE
        )
    play_samples(_mute_sounds[muted], device)
