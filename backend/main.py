import os
import sys
import asyncio
import json
import logging
import threading
import subprocess
import requests
import shutil
import time
from typing import Dict, List, Any, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
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

# Constants & Paths
BASE_DIR = "/home/phablet/smart-home-assistant"
BIN_DIR = os.path.join(BASE_DIR, "bin")
OLLAMA_PATH = os.path.join(BIN_DIR, "ollama")
OLLAMA_URL = "https://ollama.com/download/ollama-linux-arm64.tar.zst"

# Databases (In-Memory)
DEVICES: Dict[str, Dict[str, Any]] = {
    "esp-living-room": {
        "id": "esp-living-room",
        "name": "Living Room Light",
        "ip": "192.168.1.100",
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

connected_clients: List[WebSocket] = []
VOICE_LOGS: List[Dict[str, Any]] = []

# LLM State Variables
ACTIVE_LOCAL_MODEL: Optional[str] = None
OLLAMA_PROCESS: Optional[subprocess.Popen] = None

OLLAMA_INSTALL_STATUS = "Not Installed"
OLLAMA_INSTALL_PERCENT = 0
OLLAMA_INSTALL_SPEED = ""
OLLAMA_INSTALL_ETA = ""

CURRENT_PULLING_MODEL: Optional[str] = None
CURRENT_PULL_PERCENT = 0
CURRENT_PULL_SPEED = ""
CURRENT_PULL_ETA = ""

# Request Models
class DeviceUpdate(BaseModel):
    name: str
    ip: str
    type: str

class ModelPullRequest(BaseModel):
    model_name: str

class ModelSwitchRequest(BaseModel):
    model_name: str

class ChatMessage(BaseModel):
    role: str # "user" or "assistant"
    content: str

class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []

# ----------------- Helper: Speed & ETA Formatting -----------------

def format_speed(bytes_per_sec: float) -> str:
    if bytes_per_sec >= 1024 * 1024:
        return f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"
    elif bytes_per_sec >= 1024:
        return f"{bytes_per_sec / 1024:.0f} KB/s"
    else:
        return f"{bytes_per_sec:.0f} B/s"

def format_eta(seconds: float) -> str:
    if seconds <= 0:
        return "Calculating..."
    mins, secs = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours:d}h {mins:d}m"
    if mins > 0:
        return f"{mins:d}m {secs:d}s"
    return f"{secs:d}s"

# ----------------- Helper: Broadcast to WebSockets -----------------

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
    
    try:
        loop = asyncio.get_running_loop()
        asyncio.run_coroutine_threadsafe(broadcast_status("voice_log", log_item), loop)
    except RuntimeError:
        pass

# ----------------- ESP Module Controls -----------------

def send_esp_toggle(device_id: str, state: bool) -> bool:
    device = DEVICES.get(device_id)
    if not device:
        return False
    
    state_str = "1" if state else "0"
    url = f"http://{device['ip']}/toggle?state={state_str}"
    
    logger.info(f"Sending toggle {state_str} to device {device_id} at {url}")
    try:
        response = requests.get(url, timeout=2)
        if response.status_code == 200:
            device["state"] = "on" if state else "off"
            device["online"] = True
            
            try:
                loop = asyncio.get_running_loop()
                asyncio.run_coroutine_threadsafe(broadcast_status("devices", DEVICES), loop)
            except RuntimeError:
                pass
            return True
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to communicate with ESP {device_id}: {e}")
        # Toggle local simulation state for testing dashboard
        device["online"] = False
        device["state"] = "on" if state else "off"
        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(broadcast_status("devices", DEVICES), loop)
        except RuntimeError:
            pass
    return False

# ----------------- Ollama Background Management -----------------

def check_ollama_binary() -> bool:
    return os.path.exists(OLLAMA_PATH)

def is_ollama_running() -> bool:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=1)
        return r.status_code == 200
    except requests.RequestException:
        return False

def start_ollama_service():
    global OLLAMA_PROCESS, OLLAMA_INSTALL_STATUS
    if is_ollama_running():
        OLLAMA_INSTALL_STATUS = "Running"
        logger.info("Ollama is already running.")
        return True
    
    if not check_ollama_binary():
        OLLAMA_INSTALL_STATUS = "Not Installed"
        return False
        
    OLLAMA_INSTALL_STATUS = "Starting"
    logger.info("Launching Ollama service process...")
    try:
        env = os.environ.copy()
        env["OLLAMA_HOST"] = "0.0.0.0:11434"
        env["OLLAMA_MODELS"] = os.path.join(BASE_DIR, ".ollama", "models")
        os.makedirs(env["OLLAMA_MODELS"], exist_ok=True)
        
        OLLAMA_PROCESS = subprocess.Popen(
            [OLLAMA_PATH, "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        for _ in range(5):
            if is_ollama_running():
                OLLAMA_INSTALL_STATUS = "Running"
                logger.info("Ollama service successfully started.")
                return True
            threading.Event().wait(1)
            
        OLLAMA_INSTALL_STATUS = "Failed to Start"
        logger.error("Ollama service failed to bind to port 11434.")
    except Exception as e:
        OLLAMA_INSTALL_STATUS = "Failed to Start"
        logger.error(f"Failed to execute Ollama serve: {e}")
    return False

def bg_install_ollama(loop):
    global OLLAMA_INSTALL_STATUS, OLLAMA_INSTALL_PERCENT, OLLAMA_INSTALL_SPEED, OLLAMA_INSTALL_ETA
    OLLAMA_INSTALL_STATUS = "Downloading 0%"
    OLLAMA_INSTALL_PERCENT = 0
    OLLAMA_INSTALL_SPEED = ""
    OLLAMA_INSTALL_ETA = ""
    
    archive_path = "/tmp/ollama-linux-arm64.tar.zst"
    logger.info(f"Downloading Ollama binary from {OLLAMA_URL}...")
    
    try:
        start_time = time.time()
        with requests.get(OLLAMA_URL, stream=True) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            downloaded = 0
            
            with open(archive_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024): # 1MB chunks
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = int((downloaded / total_size) * 100)
                            percent = max(percent, OLLAMA_INSTALL_PERCENT)
                            OLLAMA_INSTALL_PERCENT = percent
                            OLLAMA_INSTALL_STATUS = f"Downloading {percent}%"
                            
                            elapsed = time.time() - start_time
                            if elapsed > 0:
                                speed_val = downloaded / elapsed
                                OLLAMA_INSTALL_SPEED = format_speed(speed_val)
                                remaining = total_size - downloaded
                                eta_val = remaining / speed_val if speed_val > 0 else 0
                                OLLAMA_INSTALL_ETA = format_eta(eta_val)
                            
                            asyncio.run_coroutine_threadsafe(
                                broadcast_status("ollama_install", {
                                    "status": OLLAMA_INSTALL_STATUS,
                                    "percent": OLLAMA_INSTALL_PERCENT,
                                    "speed": OLLAMA_INSTALL_SPEED,
                                    "eta": OLLAMA_INSTALL_ETA
                                }), loop
                            )
        
        logger.info("Download completed. Decompressing package...")
        OLLAMA_INSTALL_STATUS = "Extracting"
        OLLAMA_INSTALL_PERCENT = 100
        asyncio.run_coroutine_threadsafe(
            broadcast_status("ollama_install", {
                "status": OLLAMA_INSTALL_STATUS,
                "percent": OLLAMA_INSTALL_PERCENT
            }), loop
        )
        
        os.makedirs(BIN_DIR, exist_ok=True)
        cmd = f"tar --zstd -xf {archive_path} -C {BASE_DIR}"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if res.returncode != 0:
            raise Exception(f"Tar extraction failed: {res.stderr}")
            
        logger.info("Extraction completed. Starting service...")
        if os.path.exists(archive_path):
            os.remove(archive_path)
            
        success = start_ollama_service()
        if success:
            logger.info("Ollama is successfully set up and running!")
        
        asyncio.run_coroutine_threadsafe(
            broadcast_status("ollama_install", {
                "status": OLLAMA_INSTALL_STATUS,
                "percent": OLLAMA_INSTALL_PERCENT
            }), loop
        )
        
    except Exception as e:
        logger.error(f"Ollama installation failed: {e}")
        OLLAMA_INSTALL_STATUS = "Failed"
        asyncio.run_coroutine_threadsafe(
            broadcast_status("ollama_install", {
                "status": OLLAMA_INSTALL_STATUS,
                "error": str(e)
            }), loop
        )

# ----------------- Model Pull Manager -----------------

def bg_pull_model(model_name: str, loop):
    global CURRENT_PULLING_MODEL, CURRENT_PULL_PERCENT, CURRENT_PULL_SPEED, CURRENT_PULL_ETA
    CURRENT_PULLING_MODEL = model_name
    CURRENT_PULL_PERCENT = 0
    CURRENT_PULL_SPEED = ""
    CURRENT_PULL_ETA = ""
    
    logger.info(f"Starting pull for model: {model_name}")
    try:
        url = "http://localhost:11434/api/pull"
        r = requests.post(url, json={"name": model_name}, stream=True, timeout=1200)
        r.raise_for_status()
        
        pull_start_time = time.time()
        completed_by_digest = {}
        total_by_digest = {}
        
        for line in r.iter_lines():
            if line:
                data = json.loads(line)
                status = data.get("status", "")
                completed = data.get("completed", 0)
                total = data.get("total", 0)
                digest = data.get("digest", "")
                
                if digest and (status == "downloading" or completed == total):
                    completed_by_digest[digest] = completed
                    if total > 0:
                        total_by_digest[digest] = total
                
                total_completed = sum(completed_by_digest.values())
                total_expected = sum(total_by_digest.values())
                
                if total_expected > 0:
                    percent = int((total_completed / total_expected) * 100)
                    percent = max(percent, CURRENT_PULL_PERCENT)
                    if percent > 99:
                        percent = 99
                    CURRENT_PULL_PERCENT = percent
                    
                    elapsed = time.time() - pull_start_time
                    if elapsed > 0:
                        speed_val = total_completed / elapsed
                        CURRENT_PULL_SPEED = format_speed(speed_val)
                        remaining = total_expected - total_completed
                        eta_val = remaining / speed_val if speed_val > 0 else 0
                        CURRENT_PULL_ETA = format_eta(eta_val)
                        
                    asyncio.run_coroutine_threadsafe(
                        broadcast_status("model_pull", {
                            "model": model_name,
                            "status": "downloading",
                            "percent": CURRENT_PULL_PERCENT,
                            "speed": CURRENT_PULL_SPEED,
                            "eta": CURRENT_PULL_ETA
                        }), loop
                    )
                elif status == "success":
                    logger.info(f"Model {model_name} successfully downloaded.")
                    
        CURRENT_PULLING_MODEL = None
        CURRENT_PULL_PERCENT = 0
        CURRENT_PULL_SPEED = ""
        CURRENT_PULL_ETA = ""
        
        global ACTIVE_LOCAL_MODEL
        if not ACTIVE_LOCAL_MODEL:
            ACTIVE_LOCAL_MODEL = model_name
            
        asyncio.run_coroutine_threadsafe(
            broadcast_status("model_pull", {
                "model": model_name,
                "status": "success",
                "active_model": ACTIVE_LOCAL_MODEL
            }), loop
        )
    except Exception as e:
        logger.error(f"Failed to pull model {model_name}: {e}")
        CURRENT_PULLING_MODEL = None
        CURRENT_PULL_PERCENT = 0
        CURRENT_PULL_SPEED = ""
        CURRENT_PULL_ETA = ""
        asyncio.run_coroutine_threadsafe(
            broadcast_status("model_pull", {
                "model": model_name,
                "status": "failed",
                "error": str(e)
            }), loop
        )

# ----------------- Voice Command Parser (AI & Fallback) -----------------

def parse_intent_and_execute(text: str):
    text_lower = text.lower()
    logger.info(f"Processing command: '{text}'")
    
    # 1. Local LLM Intent Processing (Ollama)
    if ACTIVE_LOCAL_MODEL and is_ollama_running():
        try:
            logger.info(f"Using local LLM ({ACTIVE_LOCAL_MODEL}) to parse command...")
            prompt = (
                f"You are a smart home parser. Below is a list of registered smart home devices:\n"
                f"{json.dumps(DEVICES, indent=2)}\n\n"
                f"The user said: '{text}'\n\n"
                f"Instructions:\n"
                f"Match the user's intent to one of the registered devices and decide whether they want to turn it 'on' or 'off'.\n"
                f"If the request does not match any device, set target_device and action to null.\n"
                f"Respond ONLY with a raw JSON block containing exactly these keys:\n"
                f"{{\n"
                f"  \"target_device\": \"device_id or null\",\n"
                f"  \"action\": \"on or off or null\",\n"
                f"  \"explanation\": \"short explanation of why you performed this action\"\n"
                f"}}\n"
                f"Do not add any markdown formatting, code blocks, or preamble. Just raw JSON."
            )
            
            url = "http://localhost:11434/api/generate"
            payload = {
                "model": ACTIVE_LOCAL_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1
                }
            }
            r = requests.post(url, json=payload, timeout=10)
            
            if r.status_code == 200:
                raw_response = r.json().get("response", "").strip()
                logger.info(f"Ollama raw response: {raw_response}")
                
                if raw_response.startswith("```"):
                    start = raw_response.find("{")
                    end = raw_response.rfind("}")
                    if start != -1 and end != -1:
                        raw_response = raw_response[start:end+1]
                
                res_data = json.loads(raw_response)
                target = res_data.get("target_device")
                action = res_data.get("action")
                explanation = res_data.get("explanation", "")
                
                if target in DEVICES and action in ["on", "off"]:
                    state_bool = (action == "on")
                    send_esp_toggle(target, state_bool)
                    log_voice_command(text, f"LLM ({ACTIVE_LOCAL_MODEL}): {action.upper()} {target} - {explanation}", "Success")
                    return
                else:
                    logger.info(f"Ollama parsed command but found no valid match: {target} -> {action}")
            else:
                logger.warning(f"Ollama API returned non-200 code: {r.status_code}")
        except Exception as e:
            logger.error(f"Local LLM parsing failed: {e}")

    # 2. Cloud AI (Gemini) fallback
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
                    log_voice_command(text, f"Cloud AI: {action.upper()} {target}", "Success")
                    return
        except Exception as e:
            logger.error(f"Gemini intent parsing failed: {e}")

    # 3. Rule-based Intent Matching (Fallback or Default)
    matched = False
    is_on = any(x in text_lower for x in ["turn on", "switch on", "enable", "start", "open"])
    is_off = any(x in text_lower for x in ["turn off", "switch off", "disable", "stop", "close"])
    
    for device_id, device in DEVICES.items():
        name_lower = device["name"].lower()
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

VOICE_LISTENER_STATUS = "Stopped"

def start_voice_listener(loop):
    global VOICE_LISTENER_STATUS
    VOICE_LISTENER_STATUS = "Starting"
    logger.info("Initializing Voice Listener Thread...")
    
    try:
        import speech_recognition as sr
        recognizer = sr.Recognizer()
        
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

        while VOICE_LISTENER_STATUS == "Listening":
            try:
                with mic as source:
                    audio = recognizer.listen(source, timeout=5, phrase_time_limit=7)
                try:
                    command_text = recognizer.recognize_google(audio)
                    parse_intent_and_execute(command_text)
                except sr.UnknownValueError:
                    pass
                except sr.RequestError as e:
                    try:
                        command_text = recognizer.recognize_sphinx(audio)
                        parse_intent_and_execute(command_text)
                    except Exception as offline_err:
                        logger.error(f"Offline STT failed: {offline_err}")
            except sr.WaitTimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error in mic loop: {e}")
                threading.Event().wait(2)

    except ImportError:
        VOICE_LISTENER_STATUS = "Error: Missing Speech Libraries"
        logger.error("speech_recognition or pyaudio missing. Running in simulation mode.")
        run_voice_simulation_loop()

def run_voice_simulation_loop():
    global VOICE_LISTENER_STATUS
    if "Error:" not in VOICE_LISTENER_STATUS:
        VOICE_LISTENER_STATUS = "Simulation Mode"
    while "Error" not in VOICE_LISTENER_STATUS and VOICE_LISTENER_STATUS != "Stopped":
        threading.Event().wait(10)

# ----------------- FastAPI Routes: System and Devices -----------------

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
    success = await asyncio.to_thread(send_esp_toggle, device_id, state)
    return {"id": device_id, "state": DEVICES[device_id]["state"], "success": success}

@app.get("/api/voice-logs")
async def get_voice_logs():
    return VOICE_LOGS

@app.post("/api/simulate-voice")
async def simulate_voice(command: str):
    parse_intent_and_execute(command)
    return {"status": "processed", "command": command}

# ----------------- FastAPI Routes: Local LLM (Ollama) Management -----------------

@app.get("/api/llm/status")
async def get_llm_status():
    global OLLAMA_INSTALL_STATUS, ACTIVE_LOCAL_MODEL
    
    binary_present = check_ollama_binary()
    running = is_ollama_running()
    
    if running:
        OLLAMA_INSTALL_STATUS = "Running"
    elif binary_present:
        if OLLAMA_INSTALL_STATUS not in ["Starting", "Failed to Start"]:
            OLLAMA_INSTALL_STATUS = "Stopped"
    else:
        OLLAMA_INSTALL_STATUS = "Not Installed"
        
    return {
        "binary_installed": binary_present,
        "service_running": running,
        "status": OLLAMA_INSTALL_STATUS,
        "install_percent": OLLAMA_INSTALL_PERCENT,
        "install_speed": OLLAMA_INSTALL_SPEED,
        "install_eta": OLLAMA_INSTALL_ETA,
        "active_model": ACTIVE_LOCAL_MODEL,
        "pulling_model": CURRENT_PULLING_MODEL,
        "pull_percent": CURRENT_PULL_PERCENT,
        "pull_speed": CURRENT_PULL_SPEED,
        "pull_eta": CURRENT_PULL_ETA
    }

@app.post("/api/llm/install")
async def install_llm_service(background_tasks: BackgroundTasks):
    global OLLAMA_INSTALL_STATUS
    if OLLAMA_INSTALL_STATUS in ["Downloading", "Extracting"] or OLLAMA_INSTALL_STATUS.startswith("Downloading"):
        return {"status": "in_progress", "detail": OLLAMA_INSTALL_STATUS}
    
    if is_ollama_running():
        return {"status": "running", "detail": "Ollama is already running"}
        
    OLLAMA_INSTALL_STATUS = "Downloading 0%"
    loop = asyncio.get_event_loop()
    background_tasks.add_task(bg_install_ollama, loop)
    return {"status": "started", "detail": "Ollama installation triggered in background."}

@app.post("/api/llm/start")
async def start_llm_service_endpoint():
    success = start_ollama_service()
    if success:
        return {"status": "success", "detail": "Ollama service started."}
    else:
        raise HTTPException(status_code=500, detail="Failed to start Ollama service. Make sure it is installed.")

@app.get("/api/llm/models")
async def list_llm_models():
    if not is_ollama_running():
        return []
    
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=2)
        if r.status_code == 200:
            models_list = r.json().get("models", [])
            return models_list
    except Exception as e:
        logger.error(f"Failed to fetch local models: {e}")
        
    return []

@app.post("/api/llm/pull")
async def pull_llm_model(payload: ModelPullRequest, background_tasks: BackgroundTasks):
    if not is_ollama_running():
        raise HTTPException(status_code=503, detail="Ollama service is not running")
        
    global CURRENT_PULLING_MODEL
    if CURRENT_PULLING_MODEL:
        raise HTTPException(status_code=409, detail=f"Already pulling model: {CURRENT_PULLING_MODEL}")
        
    loop = asyncio.get_event_loop()
    background_tasks.add_task(bg_pull_model, payload.model_name, loop)
    return {"status": "started", "model": payload.model_name}

@app.delete("/api/llm/models/{model_name}")
async def delete_llm_model(model_name: str):
    if not is_ollama_running():
        raise HTTPException(status_code=503, detail="Ollama service is not running")
        
    try:
        url = "http://localhost:11434/api/delete"
        r = requests.delete(url, json={"name": model_name}, timeout=10)
        if r.status_code == 200:
            global ACTIVE_LOCAL_MODEL
            if ACTIVE_LOCAL_MODEL == model_name:
                ACTIVE_LOCAL_MODEL = None
                
            await broadcast_status("model_deleted", {"model": model_name})
            return {"status": "success", "deleted": model_name}
        else:
            raise HTTPException(status_code=r.status_code, detail="Ollama failed to delete model")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/llm/switch")
async def switch_active_model(payload: ModelSwitchRequest):
    global ACTIVE_LOCAL_MODEL
    
    if not is_ollama_running():
        raise HTTPException(status_code=503, detail="Ollama service is not running")
        
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=2)
        models = [m.get("name") for m in r.json().get("models", [])]
        
        matched_model = None
        for m in models:
            if m == payload.model_name or m.split(":")[0] == payload.model_name:
                matched_model = m
                break
                
        if not matched_model and payload.model_name != "":
            raise HTTPException(status_code=404, detail="Model is not installed. Please pull it first.")
            
        old_model = ACTIVE_LOCAL_MODEL
        ACTIVE_LOCAL_MODEL = matched_model
        await broadcast_status("model_switched", {"active_model": ACTIVE_LOCAL_MODEL})
        
        # Asynchronously preload the model in Ollama to make subsequent chat messages fast
        if ACTIVE_LOCAL_MODEL:
            def preload():
                try:
                    logger.info(f"Preloading model {ACTIVE_LOCAL_MODEL}...")
                    requests.post("http://localhost:11434/api/generate", json={"model": ACTIVE_LOCAL_MODEL}, timeout=90)
                    logger.info(f"Model {ACTIVE_LOCAL_MODEL} preloaded successfully.")
                except Exception as ex:
                    logger.warning(f"Failed to preload model {ACTIVE_LOCAL_MODEL}: {ex}")
            threading.Thread(target=preload, daemon=True).start()
        # If deactivating, tell Ollama to unload the model from memory to free up RAM!
        elif old_model:
            def unload():
                try:
                    logger.info(f"Unloading model {old_model} from Ollama RAM...")
                    # Loading with keep_alive=0 unloads it
                    requests.post("http://localhost:11434/api/generate", json={"model": old_model, "keep_alive": 0}, timeout=5)
                    logger.info(f"Model {old_model} successfully unloaded from RAM.")
                except Exception as ex:
                    logger.warning(f"Failed to unload model {old_model}: {ex}")
            threading.Thread(target=unload, daemon=True).start()
            
        return {"status": "success", "active_model": ACTIVE_LOCAL_MODEL}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ----------------- FastAPI Routes: Chat with AI -----------------

@app.post("/api/chat")
async def chat_with_ai(payload: ChatRequest):
    gemini_key = os.getenv("GEMINI_API_KEY")
    system_prompt = (
        "You are AetherHome, a smart home AI voice and chat assistant. "
        "Keep your responses extremely short, concise, and direct (maximum of 1 or 2 sentences). "
        "Avoid long explanations, greetings, preambles, or lists unless explicitly asked. "
        "Help the user configure their smart devices and chat politely."
    )
    
    # 1. Local LLM Chat (Ollama)
    if ACTIVE_LOCAL_MODEL and is_ollama_running():
        try:
            url = "http://localhost:11434/api/chat"
            messages = [{"role": "system", "content": system_prompt}]
            for msg in payload.history:
                messages.append({"role": msg.role, "content": msg.content})
            messages.append({"role": "user", "content": payload.message})
            
            # Increased timeout to 120 seconds to give Ollama enough time to generate responses on ARM64 CPU
            r = requests.post(url, json={
                "model": ACTIVE_LOCAL_MODEL,
                "messages": messages,
                "stream": False
            }, timeout=120)
            
            if r.status_code == 200:
                ai_response = r.json().get("message", {}).get("content", "")
                return {"response": ai_response, "source": f"local ({ACTIVE_LOCAL_MODEL})"}
            else:
                return {
                    "response": f"Ollama service error: Received HTTP {r.status_code} from local server.",
                    "source": "error"
                }
        except Exception as e:
            logger.error(f"Local Ollama chat failed: {e}")
            return {
                "response": f"Local Ollama inference failed: {str(e)}. (This can happen if the CPU is cold-loading the model. Please wait a moment and try sending your message again.)",
                "source": "error"
            }
            
    # 2. Cloud Gemini Chat
    if gemini_key:
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=gemini_key)
            
            contents = []
            for msg in payload.history:
                role_mapped = "user" if msg.role == "user" else "model"
                contents.append(types.Content(role=role_mapped, parts=[types.Part.from_text(text=msg.content)]))
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=payload.message)]))
            
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt
                )
            )
            return {"response": response.text, "source": "gemini-cloud"}
        except Exception as e:
            logger.error(f"Gemini chat failed: {e}")
            return {"response": f"Error communicating with Cloud AI: {e}", "source": "error"}
            
    # 3. Fallback
    return {
        "response": "Hello! I am AetherHome. Currently, the local LLM is not active and no cloud API key is configured. Please go to AI Settings in the top header to download a local model or set up a Gemini API Key.",
        "source": "fallback"
    }

# ----------------- WebSockets Connection Handler -----------------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    
    try:
        binary_present = check_ollama_binary()
        running = is_ollama_running()
        
        global OLLAMA_INSTALL_STATUS
        if running:
            OLLAMA_INSTALL_STATUS = "Running"
        elif binary_present:
            if OLLAMA_INSTALL_STATUS not in ["Starting", "Failed to Start"]:
                OLLAMA_INSTALL_STATUS = "Stopped"
        else:
            OLLAMA_INSTALL_STATUS = "Not Installed"

        await websocket.send_text(json.dumps({
            "type": "init",
            "data": {
                "devices": DEVICES,
                "voice_logs": VOICE_LOGS,
                "listener_status": VOICE_LISTENER_STATUS,
                "gemini_active": os.getenv("GEMINI_API_KEY") is not None,
                "llm": {
                    "binary_installed": binary_present,
                    "service_running": running,
                    "status": OLLAMA_INSTALL_STATUS,
                    "install_percent": OLLAMA_INSTALL_PERCENT,
                    "install_speed": OLLAMA_INSTALL_SPEED,
                    "install_eta": OLLAMA_INSTALL_ETA,
                    "active_model": ACTIVE_LOCAL_MODEL,
                    "pulling_model": CURRENT_PULLING_MODEL,
                    "pull_percent": CURRENT_PULL_PERCENT,
                    "pull_speed": CURRENT_PULL_SPEED,
                    "pull_eta": CURRENT_PULL_ETA
                }
            }
        }))
        
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if websocket in connected_clients:
            connected_clients.remove(websocket)

# ----------------- Serve Frontend Static Files -----------------

frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
else:
    logger.warning(f"Frontend directory not found at {frontend_dir}.")

@app.on_event("startup")
async def startup_event():
    loop = asyncio.get_event_loop()
    threading.Thread(target=start_voice_listener, args=(loop,), daemon=True).start()
    
    if check_ollama_binary():
        threading.Thread(target=start_ollama_service, daemon=True).start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
