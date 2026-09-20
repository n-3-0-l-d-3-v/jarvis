import pytest

from jarvis import voice


def test_sapi_script_escapes_quotes_and_can_target_wav():
    s = voice._sapi_script("it's ok", "C:/x.wav")
    assert "it''s ok" in s and "SetOutputToWaveFile('C:/x.wav')" in s


def test_sapi_script_plays_by_default():
    assert "SetOutputToWaveFile" not in voice._sapi_script("hi", None)


def test_transcribe_without_deps_raises_voice_error(monkeypatch):
    import builtins
    real = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", lambda n, *a, **k: (_ for _ in ()).throw(ImportError()) if n == "faster_whisper" else real(n, *a, **k))
    with pytest.raises(voice.VoiceError):
        voice.transcribe("x.wav")
