"""Gameplay-Shorts-Pipeline core modules."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "input"
OUTPUT_DIR = PROJECT_ROOT / "output"
TEMP_DIR = PROJECT_ROOT / "temp"
PROJECTS_TEMP_DIR = TEMP_DIR / "projects"
MODELS_TEMP_DIR = TEMP_DIR / "models"
REPOS_DIR = PROJECT_ROOT / "repos"
REMOTION_DIR = PROJECT_ROOT / "remotion"

__all__ = [
    "PROJECT_ROOT",
    "INPUT_DIR",
    "OUTPUT_DIR",
    "TEMP_DIR",
    "PROJECTS_TEMP_DIR",
    "MODELS_TEMP_DIR",
    "REPOS_DIR",
    "REMOTION_DIR",
]
