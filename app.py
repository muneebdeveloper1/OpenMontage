import os
import sys
import time
import json
import asyncio
import requests
import google.generativeai as genai
import edge_tts
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# MoviePy 2.0 imports
from moviepy import VideoFileClip, AudioFileClip, ColorClip, CompositeVideoClip, concatenate_videoclips

# --- CONFIGURATION ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")

if not GEMINI_API_KEY:
    print("[-] Error: GEMINI_API_KEY missing.")
    sys.exit(1)
if not PEXELS_API_KEY:
    print("[-] Error: PEXELS_API_KEY missing.")
    sys.exit(1)

genai.configure(api_key=GEMINI_API_KEY)

# Using valid, real Gemini models
MODEL_FALLBACK_LIST = ['gemini-1.5-flash', 'gemini-1.5-pro']

def generate_script_json(topic):
    prompt = f"""
    You are a professional documentary writer. Write a 60-second script about {topic}.
    You MUST respond in valid JSON format only.
    Structure:
    {{
        "title": "Catchy YouTube title",
        "description": "SEO description with hashtags",
        "sentences": ["Sentence 1.", "Sentence 2.", "Sentence 3."]
    }}
    Make sure "sentences" contains an array of 10 to 15 short sentences. Each sentence will be displayed for 4-5 seconds.
    """
    
    for model_name in MODEL_FALLBACK_LIST:
        try:
            print(f"[*] Generating script with {model_name}...")
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            data = json.loads(response.text)
            return data["title"], data["description"], data["sentences"]
        except Exception as e:
            print(f"[-] {model_name} failed: {e}")
            time.sleep(2)
            
    print("[-] All Gemini models failed.")
    sys.exit(1)

async def generate_edge_tts(text, output_file):
    """Generates audio using Microsoft Edge TTS (Christopher voice)."""
    print("[*] Generating voiceover with Edge TTS...")
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+0%")
    await communicate.save(output_file)

def download_pexels_video(keyword, output_path):
    """Searches Pexels for a video and downloads the best quality match."""
    print(f"    [*] Fetching footage for: '{keyword}'")
    url = f"https://api.pexels.com/videos/search?query={keyword}&per_page=1&orientation=landscape&size=large"
    headers = {"Authorization": PEXELS_API_KEY}
    
    try:
        res = requests.get(url, headers=headers).json()
        if res.get("videos") and len(res["videos"]) > 0:
            # Get the highest resolution file
            video_files = res["videos"][0]["video_files"]
            video_files.sort(key=lambda x: x.get("width", 0), reverse=True)
            video_url = video_files[0]["link"]
            
            # Download video
            with requests.get(video_url, stream=True) as r:
                r.raise_for_status()
                with open(output_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            return True
    except Exception as e:
        print(f"    [-] Pexels download failed: {e}")
    return False

def create_video_file(sentences, audio_file, duration, filename="output.mp4"):
    """Assembles the stock footage and audio into a final video."""
    print(f"[*] Rendering video ({duration}s)...")
    
    clips = []
    temp_files = []
    clip_duration = duration / len(sentences)
    
    for i, sentence in enumerate(sentences):
        # Use the first few words as the search keyword
        keyword = " ".join(sentence.split()[:4])
        video_path = f"temp_clip_{i}.mp4"
        
        success = download_pexels_video(keyword, video_path)
        
        if success and os.path.exists(video_path):
            temp_files.append(video_path)
            try:
                # Load video, resize to 720p, and trim to match 4-5s duration
                clip = VideoFileClip(video_path).resized(height=720)
                if clip.duration < clip_duration:
                    # Loop if too short
                    clip = clip.with_effects([vfx.Loop(duration=clip_duration)])
                else:
                    clip = clip.subclipped(0, clip_duration)
                clips.append(clip)
            except Exception as e:
                print(f"    [-] Error loading clip: {e}")
                success = False
                
        if not success:
            # Fallback to a black screen if download fails
            bg = ColorClip(size=(1280, 720), color=(20, 20, 20), duration=clip_duration)
            clips.append(bg)
            
    print("[*] Stitching clips together...")
    final_video = concatenate_videoclips(clips, method="compose")
    
    # Add Audio
    audio = AudioFileClip(audio_file)
    # Trim or loop audio to match video duration
    if audio.duration < duration:
        audio = audio.with_effects([afx.AudioLoop(duration=duration)])
    else:
        audio = audio.subclipped(0, duration)
        
    final_video = final_video.with_audio(audio)
    
    # Export
    final_video.write_videofile(
        filename, 
        fps=24, 
        codec='libx264', 
        audio_codec='aac',
        logger=None
    )
    
    # Cleanup
    final_video.close()
    for f in temp_files:
        if os.path.exists(f):
            os.remove(f)
            
    print(f"[+] Video successfully created: {filename}")
    return filename

def upload_to_youtube(video_file, title, description):
    print("[*] Authenticating with YouTube via token.json...")
    if not os.path.exists('token.json'):
        print("[-] Error: token.json not found!")
        sys.exit(1)
        
    creds = Credentials.from_authorized_user_file('token.json', ['https://www.googleapis.com/auth/youtube.upload'])
    youtube = build('youtube', 'v3', credentials=creds)

    body = {
        'snippet': {
            'title': title[:100],
            'description': description[:5000],
            'tags': ['documentary', 'history', 'ai'],
            'categoryId': '27' # Education
        },
        'status': {
            'privacyStatus': 'private'
        }
    }

    media = MediaFileUpload(video_file, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
    
    print("[*] Uploading video to YouTube...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[*] Uploaded {int(status.progress() * 100)}%")
            
    print(f"[+] Upload Complete! Video ID: {response.get('id')}")

def main():
    topic = os.getenv("TOPIC", "The Bronze Age Collapse")
    duration = int(os.getenv("DURATION", "60"))
    
    print(f"[*] Starting pipeline for: {topic}")
    
    # 1. Generate Script
    title, description, sentences = generate_script_json(topic)
    print(f"\n--- GENERATED INFO ---\nTitle: {title}\nSentences: {len(sentences)}\n----------------------\n")
    
    full_script = " ".join(sentences)
    
    # 2. Generate Audio (Edge TTS)
    audio_path = "voiceover.mp3"
    asyncio.run(generate_edge_tts(full_script, audio_path))
    
    # 3. Create Video (Stock Footage + Audio)
    video_path = create_video_file(sentences, audio_path, duration)
    
    # 4. Upload to YouTube
    upload_to_youtube(video_path, title, description)

if __name__ == "__main__":
    main()
