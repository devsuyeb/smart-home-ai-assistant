# AetherHome: Smart AI Home Assistant Hub

AetherHome is a smart home assistant dashboard and voice control hub running on Linux. It allows you to control ESP8266/ESP32 relay modules and smart switches via both real-time web interface toggles and offline/online voice commands.

## Features
- 🎙️ **Voice Command Processing**: Offline voice recognition (via Vosk) and online recognition.
- 🧠 **AI-Powered Intent Parsing**: Integrates with local LLM models (Gemma 3 1B, Qwen 2.5 1.5B, TinyLlama 1.1B) running locally via **Ollama**, or cloud Google Gemini API.
- ⚙️ **On-Demand AI Management**: Download, install, delete, and switch local LLM models directly from the web interface.
- 💻 **Premium Web UI**: Responsive, glassmorphic dark-theme dashboard with WebSocket integration for real-time status updates and command logs.
- 🛠️ **Command Simulator**: Test intent actions directly by typing command phrases inside the dashboard.

---

## Project Structure
- [backend/main.py](file:///home/phablet/smart-home-assistant/backend/main.py): FastAPI Web Server, WebSockets, background microphone voice recognition thread, and local/cloud LLM manager APIs.
- [frontend/](file:///home/phablet/smart-home-assistant/frontend):
  - [index.html](file:///home/phablet/smart-home-assistant/frontend/index.html): HTML structure.
  - [style.css](file:///home/phablet/smart-home-assistant/frontend/style.css): Glassmorphic dark styling for dashboard and LLM manager.
  - [app.js](file:///home/phablet/smart-home-assistant/frontend/app.js): WebSocket state manager, API caller, and dynamic UI renderer.
- [firmware/esp_client.ino](file:///home/phablet/smart-home-assistant/firmware/esp_client.ino): ESP8266/ESP32 client Arduino sketch.
- [aetherhome.sh](file:///home/phablet/smart-home-assistant/aetherhome.sh): One-click startup script for Linux.
- [requirements.txt](file:///home/phablet/smart-home-assistant/requirements.txt): List of python dependencies.

---

## Quick Start (Core App Ready)

The application core is fully set up and ready to run.

### 1. Launch the Application
Run the startup script from the root of the project:

```bash
cd /home/phablet/smart-home-assistant
./aetherhome.sh
```

Alternatively, you can open your Linux application launcher/desktop menu and click on **AetherHome**.

This script will start the FastAPI web server. Open your browser and navigate to: **[http://localhost:8000](http://localhost:8000)**.

### 2. Set Up local AI from the Dashboard
Once the web UI loads:
1. Click the **AI Settings** gear icon in the top-right header.
2. If Ollama is not installed on your system, click the **Install Ollama** button. The server will download (~1.5GB) and set up the local inference engine in the background automatically.
3. Once running, you will see a list of pre-configured models:
   - **Gemma 3 1B**
   - **Qwen 2.5 1.5B**
   - **TinyLlama 1.1B**
4. Click **Pull** next to the model you want to download.
5. Click **Activate** on your downloaded model to run intent parsing fully locally!
