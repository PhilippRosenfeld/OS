"""Generated placeholder shell sound effects under assets/sounds/shell/ --
kept for reference/history. Both the synthesized encrypt.wav and decrypt.wav
this used to produce have since been replaced by a single real recording
(crypt.mp3, shared by both encrypt and decrypt, wired up in __init__.py), so
running this script no longer does anything.
"""

import wave
import struct
from pathlib import Path

import numpy as np

SOUNDS_DIR = Path(__file__).resolve().parents[1] / "assets" / "sounds" / "shell"
SAMPLE_RATE = 44100


def _envelope(n: int, fade_samples: int) -> np.ndarray:
    """Linear fade-in/out so tones start/stop without an audible click."""
    fade_samples = min(fade_samples, n // 2)
    env = np.ones(n)
    if fade_samples > 0:
        ramp = np.linspace(0.0, 1.0, fade_samples)
        env[:fade_samples] *= ramp
        env[-fade_samples:] *= ramp[::-1]
    return env


def _tone(freq: float, duration: float, amplitude: float = 0.35) -> np.ndarray:
    n = int(SAMPLE_RATE * duration)
    t = np.arange(n) / SAMPLE_RATE
    wave_data = np.sin(2 * np.pi * freq * t)
    wave_data *= _envelope(n, fade_samples=int(SAMPLE_RATE * 0.004))
    return wave_data * amplitude


def _write_wav(path: Path, samples: np.ndarray) -> None:
    samples = np.clip(samples, -1.0, 1.0)
    pcm = (samples * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(struct.pack(f"<{len(pcm)}h", *pcm))
    print(f"wrote {path} ({len(samples) / SAMPLE_RATE:.2f}s)")


def main() -> None:
    print("Nothing to generate -- both placeholders were replaced by a real recording (crypt.mp3).")


if __name__ == "__main__":
    main()
