"""Synthetic 16:9 gameplay + facecam + TTS demo video generator for pipeline testing."""

from __future__ import annotations

import math
import subprocess
import wave
from pathlib import Path

import numpy as np

from src import INPUT_DIR, TEMP_DIR
from src.ffmpeg_utils import ensure_ffmpeg_in_path, get_ffmpeg_path

DEMO_SCRIPTS = {
    "pt": (
        "Olha isso mano, se liga no que acabou de acontecer nessa partida! "
        "Eu tava com pouca vida, sem munição quase nenhuma, e vieram três caras pra cima de mim. "
        "Caraca, não acredito que eu consegui fazer esse clutch impossível! "
        "Espera, olha o segundo lance agora, presta atenção no mapa. "
        "Meu Deus do céu, que jogada insana, isso vai direto pros shorts! "
        "Valeu galera, deixa o like se você curtiu essa reação absurda!"
    ),
    "en": (
        "Look at this bro, watch what just happened in this insane match! "
        "I had almost no health left, zero shield, and three enemies pushed my position at once. "
        "Oh my god, no way I actually pulled off that impossible clutch! "
        "Wait a second, check out the next play right here on the minimap. "
        "Seriously unbelievable play, this moment is going straight to vertical shorts! "
        "Hit subscribe if you enjoyed this crazy reaction!"
    ),
}


def _generate_tts_wav(text: str, out_wav: Path, lang: str = "pt") -> bool:
    """Synthesize spoken WAV using Windows SAPI SpeechSynthesizer."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    escaped = text.replace("'", "''")
    culture_prefix = "pt" if lang == "pt" else "en"
    ps_script = (
        "Add-Type -AssemblyName System.Speech; "
        "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$v = $synth.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -like '{culture_prefix}*' }} | Select-Object -First 1; "
        "if ($v) { $synth.SelectVoice($v.VoiceInfo.Name) }; "
        "$synth.Rate = 1; "
        f"$synth.SetOutputToWaveFile('{str(out_wav)}'); "
        f"$synth.Speak('{escaped}'); "
        "$synth.Dispose()"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return proc.returncode == 0 and out_wav.is_file() and out_wav.stat().st_size > 1000
    except Exception:
        return False


def _generate_fallback_wav(out_wav: Path, duration: float = 35.0) -> None:
    """Fallback synthetic audio track if Windows SAPI voices are unavailable."""
    sr = 16000
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    sig = 0.25 * np.sin(2 * math.pi * 220 * t) * (0.5 + 0.5 * np.sin(2 * math.pi * 1.5 * t))
    pcm = (np.clip(sig, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def generate_demo_gameplay(
    language: str = "pt",
    duration: float = 36.0,
    filename: str | None = None,
) -> Path:
    """Create a 1920x1080 demo gameplay video with simulated facecam & speech in input/."""
    ensure_ffmpeg_in_path()
    ffmpeg_bin = get_ffmpeg_path()
    lang = "pt" if language.lower().startswith("pt") else "en"

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    out_name = filename or f"demo_gameplay_{lang}.mp4"
    out_video = INPUT_DIR / out_name
    tts_wav = TEMP_DIR / f"demo_tts_{lang}.wav"

    script_text = DEMO_SCRIPTS[lang]
    ok_tts = _generate_tts_wav(script_text, tts_wav, lang=lang)
    if not ok_tts:
        _generate_fallback_wav(tts_wav, duration=duration)

    # Probe exact wav duration and pad/trim to requested minimum duration
    with wave.open(str(tts_wav), "rb") as wf:
        wav_dur = wf.getnframes() / float(wf.getframerate())
    final_dur = max(duration, round(wav_dur + 2.0, 2))

    # Build animated 1920x1080 gameplay canvas + simulated facecam box in top-left
    filter_complex = (
        f"testsrc2=size=1920x1080:rate=30:duration={final_dur}[game];"
        f"color=c=0x1e293b:size=480x280:rate=30:duration={final_dur},"
        "drawbox=x=0:y=0:w=480:h=280:color=0x00E6FF:t=6,"
        "drawtext=text='STREAMER CAM':fontcolor=white:fontsize=34:x=(w-text_w)/2:y=(h-text_h)/2[cam];"
        "[game][cam]overlay=x=32:y=32[v];"
        f"[1:a]apad=whole_dur={final_dur}[a]"
    )

    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"nullsrc=s=1920x1080:d={final_dur}",
        "-i",
        str(tts_wav),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "24",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-t",
        f"{final_dur:.2f}",
        str(out_video),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not out_video.is_file():
        raise RuntimeError(f"Falha ao criar vídeo demo: {proc.stderr.strip()}")
    return out_video
