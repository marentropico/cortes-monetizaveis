"""Dynamic word-by-word ASS subtitle generator for Shorts/Reels (1080x1920)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src import TEMP_DIR

CAPTION_PRESETS: dict[str, dict[str, Any]] = {
    "hormozi": {
        "label": "Hormozi Viral (Amarelo/Branco)",
        "font": "Arial Black",
        "fontsize": 74,
        "active_color": "#FFE600",
        "inactive_color": "#FFFFFF",
        "outline_color": "#000000",
        "hook_color": "#FFE600",
        "outline": 7,
        "shadow": 3,
        "uppercase": True,
    },
    "gamer_neon": {
        "label": "Gamer Neon (Ciano/Ácido)",
        "font": "Impact",
        "fontsize": 78,
        "active_color": "#00F3FF",
        "inactive_color": "#FFFFFF",
        "outline_color": "#05070F",
        "hook_color": "#CCFF00",
        "outline": 7,
        "shadow": 4,
        "uppercase": True,
    },
    "clean_white": {
        "label": "Clean Modern (Laranja/Branco)",
        "font": "Segoe UI",
        "fontsize": 68,
        "active_color": "#FFB117",
        "inactive_color": "#F8FAFC",
        "outline_color": "#111827",
        "hook_color": "#FFFFFF",
        "outline": 6,
        "shadow": 2,
        "uppercase": False,
    },
}


def to_ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp format H:MM:SS.cs."""
    cs = max(0, int(round(seconds * 100)))
    h = cs // 360000
    m = (cs // 6000) % 60
    s = (cs // 100) % 60
    c = cs % 100
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _esc_ass(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def _rgb_to_ass_aabbggrr(hex_rgb: str, alpha: str = "00") -> str:
    rgb = hex_rgb.lstrip("#")
    r, g, b = int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16)
    return f"&H{alpha}{b:02X}{g:02X}{r:02X}"


def _rgb_to_ass_bbggrr(hex_rgb: str) -> str:
    rgb = hex_rgb.lstrip("#")
    r, g, b = int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16)
    return f"{b:02X}{g:02X}{r:02X}"


def extract_words_in_range(
    transcript_data: dict[str, Any],
    cut_start: float,
    cut_end: float,
) -> list[dict[str, Any]]:
    """Extract and shift word timestamps into relative clip time [0, cut_end - cut_start]."""
    clip_dur = max(0.1, cut_end - cut_start)
    words_out: list[dict[str, Any]] = []

    for seg in transcript_data.get("segments", []):
        seg_words = seg.get("words") or []
        if seg_words:
            for w in seg_words:
                ws = float(w.get("start", 0.0))
                we = float(w.get("end", ws + 0.1))
                if we <= cut_start or ws >= cut_end:
                    continue
                rel_s = max(0.0, ws - cut_start)
                rel_e = min(clip_dur, we - cut_start)
                if rel_e <= rel_s:
                    rel_e = min(clip_dur, rel_s + 0.08)
                txt = str(w.get("word", "")).strip()
                if txt:
                    words_out.append({"word": txt, "start": rel_s, "end": rel_e})
        else:
            # Fallback if a segment lacks word-level list
            ss = float(seg.get("start", 0.0))
            se = float(seg.get("end", ss + 1.0))
            if se <= cut_start or ss >= cut_end:
                continue
            tokens = str(seg.get("text", "")).split()
            if not tokens:
                continue
            rel_s = max(0.0, ss - cut_start)
            rel_e = min(clip_dur, se - cut_start)
            step = max(0.08, (rel_e - rel_s) / len(tokens))
            for idx, tok in enumerate(tokens):
                ws = rel_s + idx * step
                we = min(clip_dur, ws + step)
                words_out.append({"word": tok, "start": ws, "end": we})

    return words_out


def _chunk_words(words: list[dict[str, Any]], max_words: int = 3) -> list[list[dict[str, Any]]]:
    """Group words into short caption blocks respecting punctuation and speech gaps."""
    blocks: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["start"] - w["end"]) if nxt else 99.0
        total_chars = sum(len(x["word"]) for x in cur)
        ends_punct = w["word"].endswith((".", "!", "?", ","))
        if (
            nxt is None
            or len(cur) >= max_words
            or total_chars >= 20
            or gap >= 0.45
            or (ends_punct and len(cur) >= 2)
        ):
            blocks.append(cur)
            cur = []
    return blocks


class ASSCaptionGenerator:
    """Generates dynamic word-highlighted .ass files for 1080x1920 vertical shorts."""

    def __init__(self, preset: str = "hormozi", words_per_line: int = 3) -> None:
        self.preset_name = preset if preset in CAPTION_PRESETS else "hormozi"
        self.cfg = CAPTION_PRESETS[self.preset_name]
        self.words_per_line = max(1, min(6, words_per_line))

    def generate_ass(
        self,
        transcript_data: dict[str, Any],
        cut_start: float,
        cut_end: float,
        output_ass_path: str | Path,
        hook_text: str = "",
        layout_mode: str = "split_screen",
    ) -> Path:
        """Write an .ass subtitle file for the given cut window."""
        clip_dur = max(0.5, cut_end - cut_start)
        words = extract_words_in_range(transcript_data, cut_start, cut_end)
        blocks = _chunk_words(words, max_words=self.words_per_line)

        cfg = self.cfg
        if layout_mode == "pip_split":
            # Positioned right below the y=608 split seam, to the left of the circular facecam (x=696..1036)
            cap_align = 8
            cap_margin_l = 45
            cap_margin_r = 415
            cap_margin_v = 632
            cap_fontsize = max(44, int(cfg["fontsize"]) - 10)
        else:
            cap_align = 2
            cap_margin_l = 60
            cap_margin_r = 60
            cap_margin_v = 320 if layout_mode == "split_screen" else 360
            cap_fontsize = int(cfg["fontsize"])
        primary_ass = _rgb_to_ass_aabbggrr(cfg["inactive_color"])
        outline_ass = _rgb_to_ass_aabbggrr(cfg["outline_color"])
        hook_ass = _rgb_to_ass_aabbggrr(cfg["hook_color"])
        active_bbggrr = _rgb_to_ass_bbggrr(cfg["active_color"])
        inactive_bbggrr = _rgb_to_ass_bbggrr(cfg["inactive_color"])

        lines = [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: TV.709",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            (
                f"Style: Cap,{cfg['font']},{cap_fontsize},{primary_ass},{primary_ass},"
                f"{outline_ass},&H80000000,-1,0,0,0,100,100,1,0,1,{cfg['outline']},{cfg['shadow']},{cap_align},{cap_margin_l},{cap_margin_r},{cap_margin_v},1"
            ),
            (
                f"Style: HookTitle,{cfg['font']},44,{hook_ass},{hook_ass},"
                f"&H00000000,&HB0000000,-1,0,0,0,100,100,1,0,1,6,3,8,90,90,85,1"
            ),
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]

        if hook_text and hook_text.strip():
            hook_end = min(3.5, clip_dur)
            # Wrap long hook text cleanly into at most 2 balanced lines
            hook_words = hook_text.strip().upper().split()
            if len(hook_words) > 4:
                mid = (len(hook_words) + 1) // 2
                line1 = _esc_ass(" ".join(hook_words[:mid]))
                line2 = _esc_ass(" ".join(hook_words[mid:]))
                clean_hook = f"{line1}\\N{line2}"
            else:
                clean_hook = _esc_ass(" ".join(hook_words))
            lines.append(
                f"Dialogue: 1,0:00:00.00,{to_ass_time(hook_end)},HookTitle,,0,0,0,,"
                f"{{\\q0\\fad(120,250)}}{clean_hook}"
            )

        for block in blocks:
            block_end = float(block[-1]["end"])
            for k, w in enumerate(block):
                ev_start = float(w["start"])
                if k < len(block) - 1:
                    ev_end = max(ev_start + 0.04, float(block[k + 1]["start"]))
                else:
                    ev_end = max(ev_start + 0.08, block_end + 0.08)
                ev_end = min(clip_dur, ev_end)
                if ev_end <= ev_start:
                    continue

                parts: list[str] = [r"{\q2}{\fsp1}"]
                for idx, item in enumerate(block):
                    word_txt = item["word"].upper() if cfg["uppercase"] else item["word"]
                    escaped = _esc_ass(word_txt)
                    if idx == k:
                        tag = (
                            f"{{\\rCap\\1c&H{active_bbggrr}&\\fscx100\\fscy100"
                            f"\\t(0,80,\\fscx118\\fscy118)\\t(80,180,\\fscx100\\fscy100)}}"
                        )
                        parts.append(f"{tag}{escaped}")
                    else:
                        parts.append(f"{{\\rCap\\1c&H{inactive_bbggrr}&\\fscx100\\fscy100}}{escaped}")
                    if idx != len(block) - 1:
                        parts.append(" ")

                lines.append(
                    f"Dialogue: 0,{to_ass_time(ev_start)},{to_ass_time(ev_end)},Cap,,0,0,0,,{''.join(parts)}"
                )

        out_path = Path(output_ass_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out_path


def load_transcript(transcript_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(transcript_path or (TEMP_DIR / "transcript.json"))
    return json.loads(path.read_text(encoding="utf-8"))
