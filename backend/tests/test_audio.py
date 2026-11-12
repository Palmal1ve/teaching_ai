import wave

from faster_whisper import decode_audio


def test_faster_whisper_can_decode_audio_with_the_pinned_pyav(tmp_path):
    path = tmp_path / "silence.wav"
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(16000)
        file.writeframes(b"\0\0" * 16000)
    assert decode_audio(str(path)).shape == (16000,)
