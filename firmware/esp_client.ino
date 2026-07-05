/**
 * Smart Home Assistant - ESP Module Client Firmware
 * Supports both ESP8266 and ESP32.
 * 
 * This firmware connects to WiFi and starts a local web server.
 * The Linux central server can control it by sending HTTP requests:
 * - GET /toggle?state=1  (Turns relay/LED ON)
 * - GET /toggle?state=0  (Turns relay/LED OFF)
 * - GET /status          (Returns JSON status of the device & sensors)
 */

#if defined(ESP8266)
#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
using WebServerClass = ESP8266WebServer;
#elif defined(ESP32)
#include <WiFi.h>
#include <WebServer.h>
using WebServerClass = WebServer;
#else
#error "Please select ESP8266 or ESP32 board in Arduino IDE"
#endif

#include <ArduinoJson.h> // Make sure to install ArduinoJson via Library Manager

// WiFi Credentials
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";

// Hardware configuration
const int RELAY_PIN = 2; // GPIO2 (On-board LED on most ESPs, active LOW on ESP8266)
bool deviceState = false;

WebServerClass server(80);

void handleRoot() {
  server.send(200, "text/plain", "ESP Smart Home Client Active. Use /toggle or /status");
}

void handleStatus() {
  StaticJsonDocument<200> doc;
  doc["device_id"] = WiFi.macAddress();
  doc["device_type"] = "relay_switch";
  doc["state"] = deviceState ? "on" : "off";
  doc["rssi"] = WiFi.RSSI();
  doc["uptime_s"] = millis() / 1000;
  
  // Optional sensor reading simulation
  doc["temperature"] = 24.5; 
  
  String response;
  serializeJson(doc, response);
  server.send(200, "application/json", response);
}

void handleToggle() {
  if (server.hasArg("state")) {
    String stateArg = server.arg("state");
    if (stateArg == "1" || stateArg == "on") {
      deviceState = true;
      digitalWrite(RELAY_PIN, HIGH); // Adjust to LOW if your relay triggers on LOW
    } else if (stateArg == "0" || stateArg == "off") {
      deviceState = false;
      digitalWrite(RELAY_PIN, LOW);
    }
    
    // Respond with new status
    handleStatus();
  } else {
    server.send(400, "text/plain", "Missing 'state' parameter (1 or 0)");
  }
}

void handleNotFound() {
  server.send(404, "text/plain", "Not Found");
}

void setup() {
  Serial.begin(115200);
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW); // Initially OFF

  // Connect to WiFi
  Serial.println();
  Serial.print("Connecting to ");
  Serial.println(ssid);
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("");
  Serial.println("WiFi connected");
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());

  // Setup HTTP server paths
  server.on("/", handleRoot);
  server.on("/status", handleStatus);
  server.on("/toggle", handleToggle);
  server.onNotFound(handleNotFound);
  
  server.begin();
  Serial.println("HTTP server started");
}

void loop() {
  server.handleClient();
  delay(1);
}
