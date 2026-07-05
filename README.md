# AetherHome: Smart AI Home Assistant Hub

AetherHome is a smart home assistant dashboard and voice control hub running on Linux. It allows you to control ESP8266/ESP32 relay modules and smart switches via both real-time web interface toggles and offline/online voice commands.

## Features
- 🎙️ **Voice Command Processing**: Offline voice recognition (via Vosk/PocketSphinx) and online recognition.
- 🧠 **AI-Powered Intent Parsing**: Integrates with Google Gemini API (`gemini-2.5-flash`) to parse complex natural language queries (e.g., "It's getting stuffy here, can you start the fan?").
- 🔌 **ESP Client Firmware**: Standard Arduino template for ESP8266 and ESP32 web-switches.
- 💻 **Premium Web UI**: Responsive, glassmorphic dark-theme dashboard with WebSocket integration for real-time status updates and command logs.
- 🛠️ **Command Simulator**: Test intent actions directly by typing command phrases inside the dashboard.

---

## Project Structure
- [backend/main.py](file:///home/phablet/smart-home-assistant/backend/main.py): FastAPI Web Server, WebSockets, background microphone voice recognition thread, and device controls.
- [frontend/](file:///home/phablet/smart-home-assistant/frontend):
  - [index.html](file:///home/phablet/smart-home-assistant/frontend/index.html): HTML structure.
  - [style.css](file:///home/phablet/smart-home-assistant/frontend/style.css): Glassmorphic dark styling.
  - [app.js](file:///home/phablet/smart-home-assistant/frontend/app.js): WebSocket state manager and user action handler.
- [firmware/esp_client.ino](file:///home/phablet/smart-home-assistant/firmware/esp_client.ino): ESP8266/ESP32 client Arduino sketch.
- [requirements.txt](file:///home/phablet/smart-home-assistant/requirements.txt): List of python dependencies.

---

## Getting Started

### 1. Prerequisites (System Libraries)
For Linux, some packages require system-level development libraries to capture microphone input:

```bash
# Update and install build dependencies for PyAudio
sudo apt update
sudo apt install portaudio19-dev python3-dev build-essential
```

### 2. Python Environment Setup
Navigate to the project root and create a virtual environment:

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### 3. Setup Secrets (Optional)
If you want to use the **Google Gemini AI parser**, create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_gemini_api_key_here
```
If no key is present, the server automatically falls back to robust **rule-based matching** for your registered device names.

### 4. Running the Assistant Hub
Run the FastAPI development server:

```bash
# Make sure virtual environment is active
python3 backend/main.py
```
Open your browser and navigate to: **[http://localhost:8000](http://localhost:8000)**.

---

## ESP Module Configuration
1. Install [Arduino IDE](https://www.arduino.cc/en/software).
2. Install the **ArduinoJson** library in Arduino IDE (Sketch > Include Library > Manage Libraries).
3. Open [firmware/esp_client.ino](file:///home/phablet/smart-home-assistant/firmware/esp_client.ino).
4. Update the `ssid` and `password` variables with your local WiFi credentials.
5. Choose your board (ESP8266 or ESP32) and flash it.
6. Note the **IP address** displayed in the Arduino Serial Monitor once it connects.
7. Open the AetherHome dashboard, click **Add Device**, enter the IP address, and click save.
