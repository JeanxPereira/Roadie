"""Where the game lives. Override with BL_GAME_DIR."""
import os

DEFAULT_GAME_DIR = r"D:\ProgramLibrary\Steam\steamapps\common\BrutalLegend"


def game_dir() -> str:
    return os.environ.get("BL_GAME_DIR", DEFAULT_GAME_DIR)


def packs_dir() -> str:
    return os.path.join(game_dir(), "Win", "Packs")
