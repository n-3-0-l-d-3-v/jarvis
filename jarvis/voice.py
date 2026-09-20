"""Local voice I/O: microphone/file -> text (faster-whisper) and text -> speech (OS TTS).

Everything runs on this machine (private-tier safe). Heavy deps are imported
lazily so `jarvis` works without the `voice` extra installed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

DEFAULT_MODEL = os.environ.get("JARVIS_STT_MODEL", "base.en")


class VoiceError(Exception):
    pass


def transcribe(path: str | Path, model: str = DEFAULT_MODEL) -> str:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise VoiceError("install voice deps: pip install faster-whisper sounddevice") from exc
    segments, _ = WhisperModel(model, device="cpu", compute_type="int8").transcribe(str(path))
    return " ".join(s.text.strip() for s in segments).strip()


def record(seconds: float = 6.0, samplerate: int = 16000) -> Path:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise VoiceError("install voice deps: pip install faster-whisper sounddevice") from exc
    data = sd.rec(int(seconds * samplerate), samplerate=samplerate, channels=1, dtype="int16")
    sd.wait()
    out = Path(tempfile.mkstemp(suffix=".wav")[1])
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(samplerate)
        w.writeframes(data.tobytes())
    return out


def _sapi_script(text: str, wav_out: str | None) -> str:
    safe = text.replace("'", "''")
    target = f"$s.SetOutputToWaveFile('{wav_out}');" if wav_out else ""
    return f"Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; {target} $s.Speak('{safe}'); $s.Dispose()"


def speak(text: str, wav_out: str | None = None) -> None:
    """Speak via Windows SAPI (or espeak elsewhere). wav_out writes a file instead of playing."""
    if os.name == "nt":
        r = subprocess.run(["powershell", "-NoProfile", "-Command", _sapi_script(text, wav_out)], capture_output=True, text=True)
        if r.returncode != 0:
            raise VoiceError(r.stderr.strip() or "SAPI failed")
    elif shutil.which("espeak"):
        subprocess.run(["espeak", *(["-w", wav_out] if wav_out else []), text], check=True)
    else:
        raise VoiceError("no TTS engine found (install espeak)")
