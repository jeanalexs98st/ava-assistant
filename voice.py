import os
import io
import uuid
import time
import requests
from openai import OpenAI

AUDIO_DIR = "audio_files"
os.makedirs(AUDIO_DIR, exist_ok=True)

_client = None


def get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


LANG_CODES = {"en": "en", "pt": "pt", "es": "es"}

WHISPER_PROMPT = (
    "This is a voice message to a personal AI assistant called Ava. "
    "The user may mention money amounts, expenses, income, food, transport, bills, "
    "shopping, budgets, savings. They may speak casually, use slang, filler words "
    "like 'um', 'uh', 'like', 'então', 'tipo', 'pois', 'este', 'bueno', 'o sea'. "
    "Transcribe exactly what is said, including numbers and currency."
)


def transcribe_audio(media_url: str, account_sid: str, auth_token: str, lang: str = "pt") -> str:
    """Download a Twilio voice note and transcribe it with Whisper."""
    resp = requests.get(media_url, auth=(account_sid, auth_token), timeout=30)
    resp.raise_for_status()

    audio_bytes = io.BytesIO(resp.content)
    audio_bytes.name = "voice.ogg"

    transcript = get_client().audio.transcriptions.create(
        model="whisper-1",
        file=audio_bytes,
        language=LANG_CODES.get(lang, "pt"),
        prompt=WHISPER_PROMPT,
        temperature=0.0,        # Most deterministic = most accurate
    )
    return transcript.text.strip()


def clean_for_speech(text: str) -> str:
    """Remove emojis, markdown and symbols that sound weird when spoken."""
    import re
    # Remove emojis
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"
        u"\U0001F300-\U0001F5FF"
        u"\U0001F680-\U0001F6FF"
        u"\U0001F1E0-\U0001F1FF"
        u"\U00002500-\U00002BEF"
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        u"\U0001f926-\U0001f937"
        u"\U00010000-\U0010ffff"
        u"♀-♂"
        u"☀-⭕"
        u"‍"
        u"⏏"
        u"⏩"
        u"⌚"
        u"️"
        u"〰"
        "]+", re.UNICODE)
    text = emoji_pattern.sub('', text)
    # Remove markdown
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'_+', '', text)
    text = re.sub(r'`+', '', text)
    text = re.sub(r'\|+', ' ', text)
    # Clean extra spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def synthesize_speech(text: str, lang: str = "en") -> str:
    """
    Convert text to audio using OpenAI TTS (same engine as ChatGPT voice).
    Uses the 'onyx' voice — deep, natural, human-sounding male.
    Returns the audio filename.
    """
    # Clean up for speech — remove emojis, markdown, separators
    clean_text = clean_for_speech(text.replace("|||", " ... "))

    filename = f"{uuid.uuid4()}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)

    response = get_client().audio.speech.create(
        model="tts-1-hd",   # HD = highest quality, same as ChatGPT
        voice="fable",       # British accent, natural female — Ava's voice
        input=clean_text,
        speed=0.95,          # Slightly slower = more natural conversation feel
    )

    with open(filepath, "wb") as f:
        f.write(response.content)

    return filename


def cleanup_old_audio(max_age_seconds: int = 3600):
    """Delete audio files older than 1 hour."""
    now = time.time()
    for fname in os.listdir(AUDIO_DIR):
        fpath = os.path.join(AUDIO_DIR, fname)
        if os.path.isfile(fpath) and now - os.path.getmtime(fpath) > max_age_seconds:
            os.remove(fpath)
