import os
import asyncio
import json
import logging
import threading
import requests
from typing import Dict, List, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SmartHomeBackend")

app = FastAPI(title="Smart AI Home Assistant Hub")

# CORS middleware to allow connection from UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simulated/Registered ESP devices database
# In a real app, this can be saved to a JSON file or SQLite
DEVICES: Dict[str, Dict[str, Any]] = {
    "esp-living-room": {
        "id": "esp-living-room",
        "name": "Living Room Light",
        "ip": "192.168.1.100", # Example IP, user can change it
        "state": "off",
        "type": "relay_switch",
        "online": False
    },
    "esp-kitchen-fan": {
        "id": "esp-kitchen-fan",
        "name": "Kitchen Fan",
        "ip": "192.168.1.101",
        "state": "off",
        "type": "relay_switch",
        "online": False
    }
}

# WebSocket connections storage
connected_clients: List[WebSocket] = []

# Voice command status log (to display on the web UI)
VOICE_LOGS: List[Dict[str, Any]] = []

class DeviceUpdate(BaseModel):
    name: str
    ip: str
    type: str

# ----------------- Helper Functions & Connection broadcast -----------------

async def broadcast_status(event_type: str, data: Any):
    """Broadcast real-time status updates to all connected web dashboards."""
    payload = json.dumps({"type": event_type, "data": data})
    disconnected = []
    for client in connected_clients:
        try:
            await client.send_text(payload)
        except Exception:
            disconnected.append(client)
    for client in disconnected:
        if client in connected_clients:
            connected_clients.remove(client)

def log_voice_command(phrase: str, intent: str, status: str):
    """Log a voice command and broadcast it to the frontend."""
    log_item = {
        "time": asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0,
        "phrase": phrase,
        "intent": intent,
        "status": status
    }
    VOICE_LOGS.append(log_item)
    if len(VOICE_LOGS) > 50:
        VOICE_LOGS.pop(0)
    
    # Run broadcast in thread-safe loop
    try:
        loop = asyncio.get_running_loop()
        asyncio.run_coroutine_threadsafe(broadcast_status("voice_log", log_item), loop)
    except RuntimeError:
        pass

# ----------------- Device Control Logic -----------------

def send_esp_toggle(device_id: str, state: bool) -> bool:
    """Send HTTP toggle command to the ESP module."""
    device = DEVICES.get(device_id)
    if not device:
        return False
    
    state_str = "1" if state else "0"
    url = f"http://{device['ip']}/toggle?state={state_str}"
    
    logger.info(f"Sending toggle {state_str} to device {device_id} at {url}")
    try:
        # 2-second timeout to avoid blocking backend
        response = requests.get(url, timeout=2)
        if response.status_code == 200:
            device["state"] = "on" if state else "off"
            device["online"] = True
            
            # Broadcast the updated device list
            try:
                loop = asyncio.get_running_loop()
                asyncio.run_coroutine_threadsafe(broadcast_status("devices", DEVICES), loop)
            except RuntimeError:
                pass
            return True
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to communicate with ESP {device_id}: {e}")
        # Mark as offline but toggle local simulation state just for UI testing
        device["online"] = False
        device["state"] = "on" if state else "off"
        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(broadcast_status("devices", DEVICES), loop)
        except RuntimeError:
            pass
    return False

# ----------------- Voice Command Processor -----------------

def parse_intent_and_execute(text: str):
    """Parse text from voice input and run matching commands."""
    text_lower = text.lower()
    logger.info(f"Processing command: '{text}'")
    
    # 1. Check for AI / Gemini override if API key is provided
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            from google import genai
            client = genai.Client(api_key=gemini_key)
            prompt = (
                f"You are a smart home parser. Below are the registered devices:\n"
                f"{json.dumps(DEVICES, indent=2)}\n\n"
                f"The user said: '{text}'\n"
                f"Respond with a JSON block containing:\n"
                f"- 'target_device': the device id, or null if no match.\n"
                f"- 'action': 'on', 'off', or null.\n"
                f"- 'explanation': what you did."
            )
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            # Simple extract JSON block
            raw_text = response.text
            start = raw_text.find("{")
            end = raw_text.rfind("}")
            if start != -1 and end != -1:
                res_data = json.loads(raw_text[start:end+1])
                target = res_data.get("target_device")
                action = res_data.get("action")
                if target in DEVICES and action in ["on", "off"]:
                    state_bool = (action == "on")
                    send_esp_toggle(target, state_bool)
                    log_voice_command(text, f"AI Action: {action.upper()} {target}", "Success")
                    return
        except Exception as e:
            logger.error(f"Gemini intent parsing failed, falling back to rule-based: {e}")

    # 2. Rule-based Intent Matching (Fallback or Default)
    matched = False
    
    # Match keywords for ON / OFF
    is_on = any(x in text_lower for x in ["turn on", "switch on", "enable", "start", "open"])
    is_off = any(x in text_lower for x in ["turn off", "switch off", "disable", "stop", "close"])
    
    for device_id, device in DEVICES.items():
        name_lower = device["name"].lower()
        # Check if user mentioned the device name
        if name_lower in text_lower or device_id.replace("esp-", "").replace("-", " ") in text_lower:
            if is_on:
                send_esp_toggle(device_id, True)
                log_voice_command(text, f"Turn ON {device['name']}", "Success")
                matched = True
                break
            elif is_off:
                send_esp_toggle(device_id, False)
                log_voice_command(text, f"Turn OFF {device['name']}", "Success")
                matched = True
                break
                
    if not matched:
        logger.info("No matching device/action found in voice command.")
        log_voice_command(text, "Unknown Intent", "No Device Match")

# ----------------- Voice Listener Thread -----------------
# We put this in a separate thread so it doesn't block the FastAPI web server.

VOICE_LISTENER_STATUS = "Stopped"

def start_voice_listener(loop):
    global VOICE_LISTENER_STATUS
    VOICE_LISTENER_STATUS = "Starting"
    logger.info("Initializing Voice Listener Thread...")
    
    try:
        import speech_recognition as sr
        recognizer = sr.Recognizer()
        
        # Try to open the default microphone
        try:
            mic = sr.Microphone()
            with mic as source:
                recognizer.adjust_for_ambient_noise(source, duration=1)
            VOICE_LISTENER_STATUS = "Listening"
            logger.info("Microphone initialized. Listening for commands...")
        except Exception as e:
            VOICE_LISTENER_STATUS = "Error: No Microphone Found"
            logger.error(f"Failed to bind microphone: {e}. Voice listener running in simulation mode.")
            run_voice_simulation_loop()
            return

        # Main active microphone listening loop
        while VOICE_LISTENER_STATUS == "Listening":
            try:
                with mic as source:
                    logger.info("Waiting for speech...")
                    # Timeout of 5 seconds, phrase limit of 7 seconds
                    audio = recognizer.listen(source, timeout=5, phrase_time_limit=7)
                
                logger.info("Speech detected, transcribing...")
                # We default to Sphinx (offline) or Google Speech recognition (free online)
                try:
                    # Use Google's free online API wrapper
                    command_text = recognizer.recognize_google(audio)
                    parse_intent_and_execute(command_text)
                except sr.UnknownValueError:
                    logger.debug("Speech recognition could not understand audio")
                except sr.RequestError as e:
                    logger.warning(f"Could not request results from Google Speech Recognition service; {e}")
                    # Try offline fallback using pocket sphinx if available
                    try:
                        command_text = recognizer.recognize_sphinx(audio)
                        parse_intent_and_execute(command_text)
                    except Exception as offline_err:
                        logger.error(f"Offline speech recognition fallback failed: {offline_err}")
            except sr.WaitTimeoutError:
                # Normal timeout when no speech is detected
                continue
            except Exception as e:
                logger.error(f"Error in microphone capture loop: {e}")
                await_sleep_seconds = 2
                threading.Event().wait(await_sleep_seconds)

    except ImportError:
        VOICE_LISTENER_STATUS = "Error: Missing Speech Libraries"
        logger.error("speech_recognition or pyaudio is not installed. Voice listener running in simulation mode.")
        run_voice_simulation_loop()

def run_voice_simulation_loop():
    """Helper to simulate voice command capability if mic is missing or imports fail."""
    global VOICE_LISTENER_STATUS
    if "Error:" not in VOICE_LISTENER_STATUS:
        VOICE_LISTENER_STATUS = "Simulation Mode"
    logger.info("Voice Simulation Loop active. You can type commands in the dashboard UI.")
    
    # Just run a simple keep-alive thread
    while "Error" not in VOICE_LISTENER_STATUS and VOICE_LISTENER_STATUS != "Stopped":
        threading.Event().wait(10)

# ----------------- FastAPI Routes -----------------

@app.get("/api/status")
async def get_system_status():
    return {
        "status": "online",
        "voice_listener": VOICE_LISTENER_STATUS,
        "device_count": len(DEVICES),
        "gemini_active": os.getenv("GEMINI_API_KEY") is not None
    }

@app.get("/api/devices")
async def get_devices():
    return DEVICES

@app.post("/api/devices")
async def add_device(device_id: str, payload: DeviceUpdate):
    if device_id in DEVICES:
        raise HTTPException(status_code=400, detail="Device ID already exists")
    DEVICES[device_id] = {
        "id": device_id,
        "name": payload.name,
        "ip": payload.ip,
        "state": "off",
        "type": payload.type,
        "online": False
    }
    await broadcast_status("devices", DEVICES)
    return DEVICES[device_id]

@app.delete("/api/devices/{device_id}")
async def delete_device(device_id: str):
    if device_id not in DEVICES:
        raise HTTPException(status_code=404, detail="Device not found")
    del DEVICES[device_id]
    await broadcast_status("devices", DEVICES)
    return {"status": "success"}

@app.post("/api/devices/{device_id}/toggle")
async def toggle_device(device_id: str, state: bool):
    if device_id not in DEVICES:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Run in a background executor to not block async loop
    success = await asyncio.to_thread(send_esp_toggle, device_id, state)
    return {"id": device_id, "state": DEVICES[device_id]["state"], "success": success}

@app.get("/api/voice-logs")
async def get_voice_logs():
    return VOICE_LOGS

@app.post("/api/simulate-voice")
async def simulate_voice(command: str):
    """Simulates a voice command input from the web dashboard."""
    parse_intent_and_execute(command)
    return {"status": "processed", "command": command}

# ----------------- WebSockets -----------------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    
    # Send initial state
    try:
        await websocket.send_text(json.dumps({
            "type": "init",
            "data": {
                "devices": DEVICES,
                "voice_logs": VOICE_LOGS,
                "listener_status": VOICE_LISTENER_STATUS,
                "gemini_active": os.getenv("GEMINI_API_KEY") is not None
            }
        }))
        
        while True:
            # Keep connection open and listen for messages
            data = await websocket.receive_text()
            # Handle client-sent messages if any
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if websocket in connected_clients:
            connected_clients.remove(websocket)

# ----------------- Serve Frontend -----------------

# Mount static files folder
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
else:
    logger.warning(f"Frontend directory not found at {frontend_dir}. APIs will work but dashboard won't be served.")

# Startup handler to launch voice listening thread
@app.on_event("startup")
async def startup_event():
    loop = asyncio.get_event_loop()
    threading.Thread(target=start_voice_listener, args=(loop,), daemon=True).start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
