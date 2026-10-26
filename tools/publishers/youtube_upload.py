"""YouTube Data API v3 uploader for finished OpenMontage renders.

One-time OAuth bootstrap (writes the refresh token into .env):

    pip install google-api-python-client google-auth-oauthlib
    python -m tools.publishers.youtube_upload --auth

Then:

    from tools.publishers.youtube_upload import upload
    upload("out/final.mp4", title="...", description="...")

Env vars: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_URI = "https://oauth2.googleapis.com/token"
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} is not set. Run 'python -m tools.publishers.youtube_upload --auth' "
            f"once, or add it to .env."
        )
    return value


def _credentials():
    from google.oauth2.credentials import Credentials

    return Credentials(
        token=None,
        refresh_token=_require("YT_REFRESH_TOKEN"),
        token_uri=TOKEN_URI,
        client_id=_require("YT_CLIENT_ID"),
        client_secret=_require("YT_CLIENT_SECRET"),
        scopes=SCOPES,
    )


def upload(
    video_path: str | Path,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    thumbnail_path: str | Path | None = None,
    privacy: str = "private",
    category_id: str = "22",
    made_for_kids: bool = False,
) -> dict:
    """Upload a video. Returns {"id": ..., "url": ...}."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    video = Path(video_path).expanduser().resolve()
    if not video.is_file():
        raise FileNotFoundError(f"Video not found: {video}")

    youtube = build("youtube", "v3", credentials=_credentials(), cache_discovery=False)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": (tags or [])[:500],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": bool(made_for_kids),
        },
    }

    media = MediaFileUpload(str(video), chunksize=-1, resumable=True)
    request = youtube.videos().insert(
        part="snippet,status", body=body, media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  uploaded {int(status.progress() * 100)}%", flush=True)

    video_id = response["id"]

    if thumbnail_path:
        thumb = Path(thumbnail_path).expanduser().resolve()
        if thumb.is_file():
            youtube.thumbnails().set(
                videoId=video_id, media_body=MediaFileUpload(str(thumb))
            ).execute()

    return {"id": video_id, "url": f"https://youtu.be/{video_id}"}


def _auth() -> int:
    """Installed-app OAuth flow; prints the refresh token to paste into .env."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_id = os.environ.get("YT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YT_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print("Set YT_CLIENT_ID and YT_CLIENT_SECRET in .env first.")
        return 1

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": TOKEN_URI,
                "redirect_uris": ["http://localhost"],
            }
        },
        scopes=SCOPES,
    )
    creds = flow.run_local_server(port=0, prompt="consent")

    print("\nAdd this line to .env:\n")
    print(f"YT_REFRESH_TOKEN={creds.refresh_token}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upload a render to YouTube.")
    parser.add_argument("--auth", action="store_true", help="Run OAuth and print refresh token.")
    parser.add_argument("video", nargs="?")
    parser.add_argument("--title", default=None)
    parser.add_argument("--description", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--thumbnail", default=None)
    parser.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    args = parser.parse_args(argv)

    if args.auth:
        return _auth()

    if not args.video:
        parser.error("provide a video path or use --auth")

    result = upload(
        args.video,
        title=args.title or Path(args.video).stem,
        description=args.description,
        tags=[t.strip() for t in args.tags.split(",") if t.strip()],
        thumbnail_path=args.thumbnail,
        privacy=args.privacy,
    )
    print(f"Uploaded: {result['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
