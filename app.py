import os
import re
import sys
import time
import json
import asyncio

import requests
import edge_tts

# New SDK (google-generativeai is dead)
from google import genai
from google.genai import types

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# MoviePy 2.x
from moviepy import (
    VideoFileClip,
    AudioFileClip,
    ColorClip,
    concatenate_videoclips,
    vfx,
    afx,
)

# --- CONFIGURATION ---
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
PEXELS_API_KEY = (os.getenv("PEXELS_API_KEY") or "").strip()

if not GEMINI_API_KEY:
    print("[-] Error: GEMINI_API_KEY missing.")
    sys.exit(1)
if not PEXELS_API_KEY:
    print("[-] Error: PEXELS_API_KEY missing.")
    sys.exit(1)

client = genai.Client(api_key=GEMINI_API_KEY)

# Best model first, cheapest last.
MODEL_FALLBACK_LIST = [
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]

JSON_CONFIG = types.GenerateContentConfig(
    response_mime_type="application/json",
    temperature=0.7,
)


def _parse_json(text: str) -> dict:
    """Gemini sometimes wraps JSON in markdown fences even with mime type set."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text.strip())


def generate_script_json(topic: str):
    prompt = f"""
    You are a professional documentary writer. Write a 60-second script about {topic}.
    You MUST respond in valid JSON format only.
    Structure:
    {{
        "title": "Catchy YouTube title",
        "description": "SEO description with hashtags",
        "sentences": ["Sentence 1.", "Sentence 2.", "Sentence 3."]
    }}
    Make sure "sentences" contains an array of 10 to 15 short sentences.
    Each sentence will be displayed for 4-5 seconds.
    """

    for model_name in MODEL_FALLBACK_LIST:
        try:
            print(f"[*] Generating script with {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=JSON_CONFIG,
            )
            text = response.text
            if not text:
                raise RuntimeError("empty response (possibly blocked by safety filters)")

            data = _parse_json(text)
            sentences = data["sentences"]
            if not isinstance(sentences, list) or not sentences:
                raise ValueError("'sentences' is not a non-empty list")

            print(f"[+] Success with {model_name}")
            return data["title"], data["description"], sentences
        except Exception as e:
            print(f"[-] {model_name} failed: {type(e).__name__}: {e}")
            time.sleep(2)

    print("[-] All Gemini models failed.")
    sys.exit(1)


async def generate_edge_tts(text: str, output_file: str):
    """Generates audio using Microsoft Edge TTS (Christopher voice)."""
    print("[*] Generating voiceover with Edge TTS...")
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+0%")
    await communicate.save(output_file)


def download_pexels_video(keyword: str, output_path: str) -> bool:
    """Searches Pexels for a video and downloads the best landscape MP4 match."""
    print(f"    [*] Fetching footage for: '{keyword}'")
    try:
        res = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={
                "query": keyword,
                "per_page": 1,
                "orientation": "landscape",
                "size": "large",
            },
            timeout=30,
        )
        res.raise_for_status()
        payload = res.json()

        videos = payload.get("videos") or []
        if not videos:
            return False

        files = [
            f for f in videos[0].get("video_files", [])
            if f.get("file_type") == "video/mp4" and f.get("link")
        ]
        if not files:
            return False

        files.sort(key=lambda x: x.get("width", 0), reverse=True)
        video_url = files[0]["link"]

        with requests.get(video_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return True

    except Exception as e:
        print(f"    [-] Pexels download failed: {e}")
        return False


def fit_720p(clip):
    """Resize to 720p height, then center-crop/pad width to exactly 1280."""
    clip = clip.resized(height=720)
    if clip.w < 1280:
        clip = clip.resized(width=1280)
    if clip.w > 1280:
        clip = clip.cropped(x_center=clip.w / 2, width=1280)
    return clip


def create_video_file(sentences, audio_file, duration, filename="output.mp4"):
    """Assembles stock footage and audio into a final 720p video."""
    print(f"[*] Rendering video (target {duration}s)...")

    audio = AudioFileClip(audio_file)
    if audio.duration and audio.duration < duration:
        print(f"[!] Voiceover is only {audio.duration:.1f}s — shortening video to match.")
        duration = audio.duration

    clip_duration = duration / len(sentences)
    clips = []
    temp_files = []

    try:
        for i, sentence in enumerate(sentences):
            keyword = " ".join(sentence.split()[:4])
            video_path = f"temp_clip_{i}.mp4"
            clip = None

            if download_pexels_video(keyword, video_path):
                temp_files.append(video_path)
                try:
                    clip = VideoFileClip(video_path)
                    if clip.duration is None or clip.duration <= 0:
                        raise ValueError("zero-duration clip")
                    clip = fit_720p(clip)
                    clip = clip.without_audio()
                    if clip.duration < clip_duration:
                        clip = clip.with_effects([vfx.Loop(duration=clip_duration)])
                    else:
                        clip = clip.subclipped(0, clip_duration)
                except Exception as e:
                    print(f"    [-] Error preparing clip: {e}")
                    clip = None

            if clip is None:
                clip = ColorClip(size=(1280, 720), color=(20, 20, 20), duration=clip_duration)

            clips.append(clip)

        print("[*] Stitching clips together...")
        final_video = concatenate_videoclips(clips, method="compose")

        if final_video.duration > duration:
            final_video = final_video.subclipped(0, duration)

        audio = audio.subclipped(0, min(audio.duration, duration))
        final_video = final_video.with_audio(audio)

        final_video.write_videofile(
            filename,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            logger=None,
        )

        final_video.close()
        audio.close()
        print(f"[+] Video successfully created: {filename}")
        return filename

    finally:
        for c in clips:
            try:
                c.close()
            except Exception:
                pass
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)


def upload_to_youtube(video_file, title, description):
    print("[*] Authenticating with YouTube via token.json...")
    if not os.path.exists("token.json"):
        print("[-] Error: token.json not found!")
        sys.exit(1)

    creds = Credentials.from_authorized_user_file(
        "token.json", ["https://www.googleapis.com/auth/youtube.upload"]
    )
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": ["documentary", "history", "ai"],
            "categoryId": "27",  # Education
        },
        "status": {"privacyStatus": "private"},
    }

    media = MediaFileUpload(video_file, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    print("[*] Uploading video to YouTube...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[*] Uploaded {int(status.progress() * 100)}%")

    video_id = response.get("id")
    print(f"[+] Upload Complete! Video ID: {video_id}")
    return video_id


def main():
    topic = os.getenv("TOPIC", "The Bronze Age Collapse")
    duration = int(os.getenv("DURATION", "60"))

    print(f"[*] Starting pipeline for: {topic}")

    title, description, sentences = generate_script_json(topic)
    print(f"\n--- GENERATED INFO ---\nTitle: {title}\nSentences: {len(sentences)}\n----------------------\n")

    full_script = " ".join(sentences)

    audio_path = "voiceover.mp3"
    asyncio.run(generate_edge_tts(full_script, audio_path))

    video_path = create_video_file(sentences, audio_path, duration)
    upload_to_youtube(video_path, title, description)


if __name__ == "__main__":
    main()
