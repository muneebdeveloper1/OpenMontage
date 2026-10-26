"""Avatar fallback — resolve a clip or still from `assets/avatar/` when no
stock source clears the acceptance threshold.

Guarantees a cut always has a real media `source`, so the Remotion composer
never degrades into a text-only card.

Usage (library):
    from tools.video.avatar_fallback import pick
    asset = pick("assets/avatar", target_seconds=4.5)

Usage (CLI):
    python -m tools.video.avatar_fallback --dir assets/avatar --seconds 4.5
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v", ".mkv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp"}

DEFAULT_DIR = "assets/avatar"
DEFAULT_SECONDS = 4.5
# Deterministic per-project seed so a re-run picks the same fallback.
DEFAULT_SEED = 42


def _scan(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in (VIDEO_EXTS | IMAGE_EXTS)
    )


def _seed_for(root: Path, explicit: int | None) -> int:
    if explicit is not None:
        return explicit
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def pool(avatar_dir: str | Path = DEFAULT_DIR) -> list[Path]:
    """All usable fallback files, sorted for determinism."""
    return _scan(Path(avatar_dir))


def is_available(avatar_dir: str | Path = DEFAULT_DIR) -> bool:
    return bool(pool(avatar_dir))


def pick(
    avatar_dir: str | Path = DEFAULT_DIR,
    target_seconds: float = DEFAULT_SECONDS,
    seed: int | None = None,
    exclude: set[str] | None = None,
) -> dict[str, Any] | None:
    """Return a fallback asset descriptor, or ``None`` if the folder is empty.

    Keys match what the compose layer expects on a cut:
        kind, path, duration, loop, animation, source, license
    """
    root = Path(avatar_dir)
    candidates = _scan(root)

    if exclude:
        banned = {str(Path(p).resolve()) for p in exclude}
        filtered = [p for p in candidates if str(p.resolve()) not in banned]
        candidates = filtered or candidates  # never return None just because of reuse

    if not candidates:
        return None

    rng = random.Random(_seed_for(root, seed))
    chosen = rng.choice(candidates)
    suffix = chosen.suffix.lower()
    is_video = suffix in VIDEO_EXTS

    return {
        "kind": "video" if is_video else "image",
        "path": str(chosen),
        "duration": round(float(target_seconds), 3),
        "loop": is_video,
        # Stills get motion so they do not read as a dead frame.
        "animation": "ken-burns-slow-zoom" if not is_video else "none",
        "source": "avatar_fallback",
        "license": "local-asset",
        "original_url": "",
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Pick an avatar fallback asset.")
    parser.add_argument("--dir", default=DEFAULT_DIR)
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    result = pick(args.dir, args.seconds, args.seed)
    if result is None:
        print(
            f"No fallback media found in '{args.dir}'. "
            "Create the folder and drop .mp4 / .jpg files into it."
        )
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
