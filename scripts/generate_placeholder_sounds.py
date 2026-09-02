"""Generates placeholder boot sound effects under assets/sounds/hardware/booting/.
Run this directly (`uv run python scripts/generate_placeholder_sounds.py`) to
regenerate them, e.g. after tweaking pitch/duration below. boot_tick.wav and
boot_complete.wav are still these synthesized beeps; logo_stinger.wav has since
been replaced by a real recording (ont5.wav, wired up separately in __init__.py)
and is no longer generated here.
"""

import struct
import wave
from pathlib import Path

import numpy as np

SOUNDS_DIR = Path(__file__).resolve().parents[1] / "assets" / "sounds" / "hardware" / "booting"
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


def _tone(freq: float, duration: float, amplitude: float = 0.4) -> np.ndarray:
    n = int(SAMPLE_RATE * duration)
    t = np.arange(n) / SAMPLE_RATE
    wave_data = np.sin(2 * np.pi * freq * t)
    wave_data *= _envelope(n, fade_samples=int(SAMPLE_RATE * 0.005))
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
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)

    # short blip for each boot-sequence line, classic BIOS POST tick
    _write_wav(SOUNDS_DIR / "boot_tick.wav", _tone(1200, 0.035, amplitude=0.25))

    # rising three-note chime once the boot sequence finishes
    complete = np.concatenate([
        _tone(660, 0.09),
        _tone(880, 0.09),
        _tone(1320, 0.16),
    ])
    _write_wav(SOUNDS_DIR / "boot_complete.wav", complete)


if __name__ == "__main__":
    main()
