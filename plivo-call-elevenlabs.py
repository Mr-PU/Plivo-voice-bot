from flask import Flask, request, render_template, Response
from dotenv import load_dotenv
import plivo
from plivo.xml import ResponseElement, GetInputElement, PlayElement
import os
import asyncio
from openai import AsyncOpenAI
from elevenlabs import ElevenLabs
from functools import lru_cache
import uuid
import aiohttp

app = Flask(__name__)

# Load environment variables
load_dotenv()

AUTH_ID = os.getenv("AUTH_ID")
AUTH_TOKEN = os.getenv("AUTH_TOKEN")
PLIVO_NUMBER = os.getenv("PLIVO_NUMBER")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "Rachel")  # Default to Rachel
BASE_URL = "https://818a-49-36-144-42.ngrok-free.app"  # Replace with production URL
AUDIO_DIR = "static/audio"  # Directory to store temporary audio files

# Ensure audio directory exists
os.makedirs(AUDIO_DIR, exist_ok=True)

# Initialize clients
plivo_client = plivo.RestClient(AUTH_ID, AUTH_TOKEN)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# Short audio file for faster playback
BEEP_URL = "https://actions.google.com/sounds/v1/cartoon/short_beep.ogg"

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        phone_number = request.form["phone_number"]
        make_call(phone_number)
        return f"Calling {phone_number}..."
    return render_template("index.html")

@app.route("/answer", methods=["GET", "POST"])
def answer_call():
    response = ResponseElement()
    
    # Short initial greeting using ElevenLabs
    greeting_audio = generate_audio_file("Hi! I'm your AI assistant. How can I help?")
    response.add(PlayElement(f"{BASE_URL}/static/audio/{greeting_audio}"))
    
    # Immediate input detection
    get_input = GetInputElement(
        action=f"{BASE_URL}/process_speech",
        method="POST",
        input_type="speech",
        finish_on_key="#"
    )
    get_input.add(PlayElement(BEEP_URL))
    
    response.add(get_input)
    return Response(response.to_string(), mimetype="text/xml")

@app.route("/process_speech", methods=["POST"])
async def process_speech():
    speech_text = request.form.get("Speech", "")
    call_uuid = request.form.get("CallUUID", "")
    
    response = ResponseElement()
    
    if not speech_text.strip():
        retry_audio = generate_audio_file("I didn't hear you. Try again.")
        response.add(PlayElement(f"{BASE_URL}/static/audio/{retry_audio}"))
        get_input = GetInputElement(
            action=f"{BASE_URL}/process_speech",
            method="POST",
            input_type="speech",
            finish_on_key="#"
        )
        get_input.add(PlayElement(BEEP_URL))
        response.add(get_input)
    else:
        # Get OpenAI response asynchronously
        openai_response = await get_openai_response(speech_text)
        
        # Generate audio with ElevenLabs
        response_audio = generate_audio_file(openai_response[:500])  # Limit to 500 chars
        response.add(PlayElement(f"{BASE_URL}/static/audio/{response_audio}"))
        
        # Continue input detection
        get_input = GetInputElement(
            action=f"{BASE_URL}/process_speech",
            method="POST",
            input_type="speech",
            finish_on_key="#"
        )
        get_input.add(PlayElement(BEEP_URL))
        response.add(get_input)
    
    return Response(response.to_string(), mimetype="text/xml")

@lru_cache(maxsize=100)
def generate_audio_file(text):
    """Generate audio file with ElevenLabs and return filename."""
    try:
        audio = elevenlabs_client.generate(
            text=text,
            voice=VOICE_ID,
            model="eleven_monolingual_v1",
            output_format="mp3_44100"
        )
        # Save audio to file
        filename = f"{uuid.uuid4()}.mp3"
        filepath = os.path.join(AUDIO_DIR, filename)
        with open(filepath, "wb") as f:
            for chunk in audio:
                f.write(chunk)
        return filename
    except Exception as e:
        print(f"ElevenLabs Error: {e}")
        return generate_audio_file("Sorry, I had an error.")  # Fallback

@lru_cache(maxsize=100)
async def get_openai_response(user_input):
    """Async function to get response from OpenAI API"""
    try:
        completion = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": """You are Mirai, a friendly voice AI for Iffort, an AI-first tech company. Share concise details about Iffort’s services (AI/ML solutions, mobile/performance marketing, conversational AI) and success stories. Use simple language, focus on results, and keep responses under 7 seconds. End with a question like "Want more details?" Avoid jargon or hypotheticals. If outside Iffort’s data, politely decline."""},
                {"role": "user", "content": user_input}
            ],
            max_tokens=30,
            temperature=0.9,
            timeout=2
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"OpenAI Error: {e}")
        return "Sorry, I had an error."

def make_call(to_number):
    try:
        response = plivo_client.calls.create(
            from_=PLIVO_NUMBER,
            to_=to_number,
            answer_url=f"{BASE_URL}/answer",
            answer_method="GET"
        )
        print(f"Call initiated to {to_number}. UUID: {response.request_uuid}")
    except Exception as e:
        print(f"Call Error: {e}")

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    app.run(host="0.0.0.0", port=8765, debug=False, threaded=True)