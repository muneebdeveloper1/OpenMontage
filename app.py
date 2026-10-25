import os
import sys
import time
import google.generativeai as genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from moviepy import TextClip, ColorClip, CompositeVideoClip

# Configure Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("[-] Error: GEMINI_API_KEY environment variable missing.")
    sys.exit(1)

genai.configure(api_key=GEMINI_API_KEY)

# List of models to try in order of preference
MODEL_FALLBACK_LIST = [
    'gemini-3.8-flash',
    'gemini-3.5-flash',
    'gemini-3.5-lite',
    'gemini-3.1-lite'
]

def generate_content_metadata(content_type, duration):
    """Tries multiple Gemini models with fallbacks and multiple attempts."""
    prompt = f"""
    Create YouTube metadata and script for a '{content_type}' style video.
    Target Video Length: {duration} seconds.
    Provide output in this exact format:
    TITLE: [Catchy Title]
    DESCRIPTION: [SEO Friendly Description]
    SCRIPT: [Short text script summarizing the main points to display in the video]
    """
    
    max_attempts_per_model = 4
    
    # Loop through each model in the fallback list
    for model_name in MODEL_FALLBACK_LIST:
        print(f"[*] Attempting to use Gemini model: {model_name}")
        
        for attempt in range(1, max_attempts_per_model + 1):
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                text = response.text
                
                # Parse output if successful
                title = "Generated Video"
                description = "Automated video content."
                script = "Hello world"
                
                for line in text.split('\n'):
                    if line.startswith("TITLE:"):
                        title = line.replace("TITLE:", "").strip()
                    elif line.startswith("DESCRIPTION:"):
                        description = line.replace("DESCRIPTION:", "").strip()
                    elif line.startswith("SCRIPT:"):
                        script = line.replace("SCRIPT:", "").strip()
                        
                print(f"[+] Successfully generated content using {model_name} on attempt {attempt}")
                return title, description, script
                
            except Exception as e:
                print(f"[-] Model {model_name} failed on attempt {attempt}/{max_attempts_per_model}: {e}")
                if attempt < max_attempts_per_model:
                    print(f"[*] Retrying {model_name} in 3 seconds...")
                    time.sleep(3)
                else:
                    print(f"[-] Exhausted all attempts for {model_name}. Switching to next fallback model...")
                    
    print("[-] Error: All fallback models and attempts failed.")
    sys.exit(1)

def create_video_file(script_text, duration=15, filename="output.mp4"):
    """Generates an MP4 video file locally using MoviePy."""
    print(f"[*] Rendering video file ({duration}s)...")
    try:
        bg = ColorClip(size=(1280, 720), color=(20, 20, 40), duration=duration)
        txt = TextClip(text=script_text, font_size=32, color='white', size=(1100, 600), method='caption')
        txt = txt.with_duration(duration).with_position('center')
        
        video = CompositeVideoClip([bg, txt])
        video.write_videofile(filename, fps=24, codec='libx264', audio=False, logger=None)
        print(f"[+] Video successfully created: {filename}")
        return filename
    except Exception as e:
        print(f"[-] Error generating video via MoviePy: {e}")
        with open(filename, "wb") as f:
            f.write(b'\x00\x00\x00\x20ftypisom') # Fallback dummy bytes
        return filename

def upload_to_youtube(video_file, title, description):
    """Uploads the video file to YouTube using token.json credentials."""
    print("[*] Authenticating with YouTube via token.json...")
    if not os.path.exists('token.json'):
        print("[-] Error: token.json file not found!")
        sys.exit(1)
        
    creds = Credentials.from_authorized_user_file('token.json', ['https://www.googleapis.com/auth/youtube.upload'])
    youtube = build('youtube', 'v3', credentials=creds)

    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': ['automated', 'ai', 'content'],
            'categoryId': '22'
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
    run_mode = os.getenv("RUN_MODE", "manual")
    
    if os.getenv("GITHUB_ACTIONS"):
        print(f"[*] Running in GitHub Actions. Mode: {run_mode}")
        content_type = os.getenv("CONTENT_TYPE", "Educational Explainer")
        try:
            duration = int(os.getenv("DURATION", "15"))
        except ValueError:
            duration = 15
            
        title, description, script = generate_content_metadata(content_type, duration)
        print(f"\n--- GENERATED PREVIEW INFO ---\nTitle: {title}\nDesc: {description}\nScript: {script}\n")
        
        video_path = create_video_file(script, duration=duration)
        upload_to_youtube(video_path, title, description)
    else:
        print("=== Local Mode ===")
        content_type = "Educational Explainer"
        duration = 15
        title, description, script = generate_content_metadata(content_type, duration)
        video_path = create_video_file(script, duration=duration)
        upload_to_youtube(video_path, title, description)

if __name__ == "__main__":
    main()
