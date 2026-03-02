
import logging
import requests
import json
import time
import sys
import os
import re

# Add the current directory to path so we can import backend services
sys.path.append(os.getcwd())

from backend.services.stt import WhisperSTT
from backend.services.tts import PiperTTS

# Set logging to ERROR to keep the console clean
logging.basicConfig(level=logging.ERROR)

_OLLAMA_URL = "http://localhost:11434/api/generate"
_MODEL = "qwen3.5-nothink:latest"

_SYSTEM_PROMPT = """\
You are jarvis — an AI assistant.
IMPORTANT: DO NOT include any thinking process or reasoning out loud.
Respond with ONLY a raw JSON object — no markdown, no preamble.
Respond with ONLY this JSON format:
{"speech": "your response here", "actions": []}"""

def test_loop():
    print(f"\n{'='*60}")
    print(f"   JARVIS PERFORMANCE & CHECKPOINT TEST")
    print(f"   Model: {_MODEL} (NO-THINK MODE)")
    print(f"{'='*60}")
    
    # --- CP 1: Initialization ---
    try:
        t_start = time.monotonic()
        print("\n[CP 1] Initializing STT & TTS services...")
        stt = WhisperSTT(model_size="tiny", device="auto")
        tts = PiperTTS()
        print(f"✅ SUCCESS: Services ready (Init took: {time.monotonic()-t_start:.2f}s)")
    except Exception as e:
        print(f"❌ FAILURE (CP 1): {e}")
        return

    while True:
        print(f"\n{'-'*40}")
        print("[CP 2] Waiting for voice input...")
        
        # --- CP 2: Voice Capture ---
        t_listen_start = time.monotonic()
        text = stt.listen()
        t_listen_end = time.monotonic()
        
        if not text:
            print(f"⚠️ WARNING (CP 2): No speech (Wait time: {t_listen_end-t_listen_start:.2f}s)")
            continue
            
        listen_dur = t_listen_end - t_listen_start
        print(f"✅ SUCCESS: Captured: '{text}' (Listen Duration: {listen_dur:.2f}s)")
            
        # --- CP 3: Ollama Communication ---
        print("[CP 3] Requesting response from Ollama...")
        payload = {
            "model": _MODEL,
            "prompt": _SYSTEM_PROMPT + f'\n\nUser: "{text}"',
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.1},
            "include_thinking": False
        }
        
        try:
            t_ollama_start = time.monotonic()
            resp = requests.post(_OLLAMA_URL, json=payload, timeout=30)
            resp.raise_for_status()
            full_data = resp.json()
            t_ollama_end = time.monotonic()
            ollama_dur = t_ollama_end - t_ollama_start
            
            # --- CP 4: Parsing Logic ---
            print(f"[CP 4] Processing Model Output (Inference: {ollama_dur:.2f}s)...")
            
            raw_content = full_data.get("response", "").strip()
            if not raw_content and "thinking" in full_data:
                print("💡 NOTE: Model ignored NO-THINK and used 'thinking' field.")
                raw_content = full_data.get("thinking", "").strip()
            
            if not raw_content:
                print("❌ FAILURE (CP 4): Model returned empty output.")
                continue

            raw_content = re.sub(r"```(?:json)?", "", raw_content).strip()
            match = re.search(r"\{.*\}", raw_content, re.DOTALL)
            if match:
                data = json.loads(match.group())
                speech = data.get("speech", "")
                print(f"✅ SUCCESS: Parsed speech: '{speech}'")
            else:
                raise ValueError(f"No JSON found in output")

            # --- CP 5: Speech Output ---
            if speech:
                print(f"[CP 5] Generating & Playing audio...")
                t_tts_start = time.monotonic()
                print(f"\n[jarvis] {speech}")
                tts.speak(speech, block=True)
                t_tts_end = time.monotonic()
                tts_dur = t_tts_end - t_tts_start
                
                total_dur = listen_dur + ollama_dur + tts_dur
                print(f"\n{'*'*40}")
                print(f"🏆 CYCLE COMPLETE")
                print(f"   STT/Listen: {listen_dur:.2f}s")
                print(f"   LLM/Ollama: {ollama_dur:.2f}s")
                print(f"   TTS/Audio:  {tts_dur:.2f}s")
                print(f"   TOTAL:      {total_dur:.2f}s")
                print(f"{'*'*40}")
            else:
                print("⚠️ WARNING (CP 5): Speech field empty.")

        except Exception as e:
            print(f"❌ FAILURE: {e}")
            if 'full_data' in locals():
                print(f"DEBUG DATA: {json.dumps(full_data, indent=2)}")

if __name__ == "__main__":
    try:
        test_loop()
    except KeyboardInterrupt:
        print("\n\n👋 Test stopped. Check your timing results above.")
