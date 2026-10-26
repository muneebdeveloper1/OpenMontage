"""Finalize documentary-montage edit_decisions before composition.

Guarantees, for every cut:
  1. a resolvable `source` (asset id -> manifest path);
  2. duration between MIN_HOLD and MAX_HOLD seconds (default 4.0-5.0);
  3. no two adjacent cuts on the same source;
  4. avatar fallback when the source is missing / unresolvable.

Writes the repaired artifact back and prints a machine-readable report.

    python -m lib.finalize_documentary_edit projects/<id>
    python -m lib.finalize_documentary_edit projects/<id> --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

MIN_HOLD = 4.0
MAX_HOLD = 5.0
AVATAR_DIR = "assets/avatar"

VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v", ".mkv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp"}


# --------------------------------------------------------------------- helpers
def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[finalize] invalid JSON in {path}: {exc}", file=sys.stderr)
        return None


def _iter_artifact_files(project: Path, artifact: str) -> list[Path]:
    """Find every copy of an artifact under the project tree."""
    hits = [
        project / f"{artifact}.json",
        project / "artifacts" / f"{artifact}.json",
        project / "state" / f"{artifact}.json",
    ]
    hits.extend(sorted(project.rglob(f"{artifact}.json")))
    seen: set[Path] = set()
    unique: list[Path] = []
    for hit in hits:
        resolved = hit.resolve()
        if hit.is_file() and resolved not in seen:
            seen.add(resolved)
            unique.append(hit)
    return unique


def _asset_index(manifest: dict[str, Any]) -> dict[str, str]:
    """Map asset_id -> local file path from an asset_manifest."""
    index: dict[str, str] = {}
    assets = manifest.get("assets") or manifest.get("clips") or []
    if isinstance(assets, dict):
        assets = list(assets.values())
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        path = (
            asset.get("local_path")
            or asset.get("path")
            or asset.get("file")
            or asset.get("output_path")
            or ""
        )
        if not path:
            continue
        for key in ("asset_id", "id", "clip_id", "slot_id"):
            value = asset.get(key)
            if isinstance(value, str) and value:
                index[value] = path
    return index


def _exists_anywhere(project: Path, raw: str) -> str | None:
    """Resolve a source string to an existing file path, if possible."""
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute() and candidate.is_file():
        return str(candidate)
    for base in (project, project / "public", project.parent):
        probe = (base / raw).resolve()
        if probe.is_file():
            return str(probe)
    return None


def _is_media(path: str) -> bool:
    return Path(path).suffix.lower() in (VIDEO_EXTS | IMAGE_EXTS)


# ---------------------------------------------------------------------- repair
def finalize(
    project: Path,
    min_hold: float = MIN_HOLD,
    max_hold: float = MAX_HOLD,
    avatar_dir: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    from tools.video.avatar_fallback import pick as pick_fallback

    edits_path = _iter_artifact_files(project, "edit_decisions")
    if not edits_path:
        return {
            "success": False,
            "error": f"edit_decisions.json not found under {project}",
        }

    manifest_path = _iter_artifact_files(project, "asset_manifest")
    manifest = _load_json(manifest_path[0]) if manifest_path else {}
    index = _asset_index(manifest or {})

    fallback_dir = Path(avatar_dir) if avatar_dir else (project / AVATAR_DIR)

    report: dict[str, Any] = {
        "success": True,
        "files": [],
        "cuts_total": 0,
        "repaired_source": 0,
        "clamped_duration": 0,
        "avatar_filled": 0,
        "deduped_adjacent": 0,
        "unresolved": [],
    }

    for path in edits_path:
        data = _load_json(path)
        if data is None:
            continue

        cuts = data.get("cuts") or []
        previous_source: str | None = None

        for position, cut in enumerate(cuts):
            if not isinstance(cut, dict):
                continue
            report["cuts_total"] += 1

            # ---- 1. resolve source -------------------------------------
            raw = cut.get("source") or cut.get("asset_id") or ""
            resolved = _exists_anywhere(project, raw)

            if resolved is None and raw in index:
                resolved = _exists_anywhere(project, index[raw])

            if resolved is None and cut.get("asset_id") in index:
                resolved = _exists_anywhere(project, index[cut["asset_id"]])

            if resolved is None or not _is_media(resolved):
                fallback = pick_fallback(
                    fallback_dir,
                    target_seconds=float(cut.get("out_seconds", 0) or 0)
                    - float(cut.get("in_seconds", 0) or 0)
                    or 4.5,
                    exclude={previous_source} if previous_source else None,
                )
                if fallback:
                    resolved = fallback["path"]
                    cut["backgroundColor"] = cut.get("backgroundColor") or "#000000"
                    report["avatar_filled"] += 1
                else:
                    report["unresolved"].append(
                        {"cut_id": cut.get("id"), "raw_source": raw}
                    )
                    continue

            if resolved != raw:
                cut["source"] = resolved
                report["repaired_source"] += 1

            # ---- 2. clamp duration -------------------------------------
            try:
                in_s = float(cut.get("in_seconds", 0) or 0)
            except (TypeError, ValueError):
                in_s = 0.0
            try:
                out_s = float(cut.get("out_seconds", in_s) or in_s)
            except (TypeError, ValueError):
                out_s = in_s

            hold = out_s - in_s
            if hold < min_hold or hold > max_hold:
                new_hold = min(max(hold, min_hold), max_hold)
                cut["in_seconds"] = round(in_s, 3)
                cut["out_seconds"] = round(in_s + new_hold, 3)
                report["clamped_duration"] += 1

            # ---- 3. no two adjacent cuts on one source -----------------
            if cut.get("source") == previous_source:
                alternate = pick_fallback(
                    fallback_dir,
                    target_seconds=max_hold,
                    exclude={previous_source},
                )
                if alternate and alternate["path"] != previous_source:
                    cut["source"] = alternate["path"]
                    report["deduped_adjacent"] += 1

            previous_source = cut.get("source")

        data["cuts"] = cuts

        if not dry_run:
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        report["files"].append(str(path))

    if report["unresolved"]:
        report["success"] = False
        report["error"] = (
            f"{len(report['unresolved'])} cut(s) have no resolvable media and "
            f"'{fallback_dir}' is empty. Add files to {AVATAR_DIR}/."
        )

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Repair edit_decisions so every cut has real media."
    )
    parser.add_argument("project", help="Project directory, e.g. projects/my-video")
    parser.add_argument("--min-hold", type=float, default=MIN_HOLD)
    parser.add_argument("--max-hold", type=float, default=MAX_HOLD)
    parser.add_argument("--avatar-dir", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    result = finalize(
        Path(args.project).expanduser().resolve(),
        min_hold=args.min_hold,
        max_hold=args.max_hold,
        avatar_dir=args.avatar_dir,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
