"""
Ava Voice Call Handler
When someone calls Ava's Twilio number:
1. Ava greets them in her British voice
2. User speaks — Whisper transcribes it
3. Claude generates Ava's response
4. OpenAI TTS speaks it back in British accent
"""
import os
import io
import requests
from flask import request
from twilio.twiml.voice_response import VoiceResponse, Gather
from openai import OpenAI
import advisor
import database as db

BASE_URL = os.getenv("RAILWAY_STATIC_URL", os.getenv("BASE_URL", ""))

VOICE_SETTINGS = {
    "voice": "Polly.Amy",      # Amazon Polly British female voice (built into Twilio)
    "language": "en-GB",
}


def get_openai():
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def twiml_greet():
    """Initial greeting when someone calls Ava."""
    resp = VoiceResponse()
    gather = Gather(
        input="speech",
        action="/call/respond",
        method="POST",
        language="en-GB",
        speech_timeout="auto",
        timeout=5,
    )
    gather.say(
        "Hey! You've reached Ava. What can I help you with?",
        voice=VOICE_SETTINGS["voice"],
        language=VOICE_SETTINGS["language"],
    )
    resp.append(gather)
    resp.say("I didn't catch that. Give me a call back!", voice=VOICE_SETTINGS["voice"])
    return str(resp)


def twiml_respond():
    """Handle user's spoken input and respond as Ava."""
    speech_result = request.form.get("SpeechResult", "")
    caller = request.form.get("From", "unknown")
    lang = "en"

    resp = VoiceResponse()

    if not speech_result:
        resp.say("Sorry, I didn't catch that!", voice=VOICE_SETTINGS["voice"])
        resp.redirect("/call/voice")
        return str(resp)

    # Get Ava's response using the AI
    try:
        phone = f"call:{caller}"
        reply = advisor.ask_advisor(phone, speech_result, "£", lang, is_chat=True)
        # Clean up ||| separators for spoken response
        spoken = reply.replace("|||", " ... ").replace("*", "").replace("_", "")
    except Exception as e:
        spoken = "Sorry, something went wrong on my end. Try again?"

    # Gather next input after responding
    gather = Gather(
        input="speech",
        action="/call/respond",
        method="POST",
        language="en-GB",
        speech_timeout="auto",
        timeout=8,
    )
    gather.say(spoken, voice=VOICE_SETTINGS["voice"], language=VOICE_SETTINGS["language"])
    resp.append(gather)
    resp.say("Alright, talk soon!", voice=VOICE_SETTINGS["voice"])
    return str(resp)
