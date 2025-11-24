/*
  esp32_controller.ino  –  AI Bot Motor Controller
  ───────────────────────────────────────────────────
  The ESP32 is a "dumb client": it connects to the laptop's TCP server,
  receives a single ASCII byte, and drives the motor pins accordingly.
  It does NO thinking – all decisions live on the laptop.

  Hardware wiring (L298N dual H-bridge):
  ┌──────────┬──────────────┐
  │ L298N    │ ESP32 GPIO   │
  ├──────────┼──────────────┤
  │ ENA      │ 25  (PWM)    │  Left motor speed
  │ IN1      │ 26           │  Left motor direction
  │ IN2      │ 27           │  Left motor direction
  │ ENB      │ 13  (PWM)    │  Right motor speed
  │ IN3      │ 14           │  Right motor direction
  │ IN4      │ 12           │  Right motor direction
  └──────────┴──────────────┘

  Commands received (single byte):
    'F'  – Forward
    'B'  – Backward (reverse)
    'L'  – Turn Left  (left motor backward, right forward)
    'R'  – Turn Right (left motor forward, right backward)
    'S'  – Stop

  Setup:
    1. Install Arduino-ESP32 core in Arduino IDE.
    2. Edit WIFI_SSID, WIFI_PASS, SERVER_IP to match your network.
    3. Flash to ESP32, open Serial Monitor at 115200 baud to see status.

  The bot ALWAYS stops if the TCP connection drops.  The laptop must
  re-send the desired command after reconnection.
*/

#include <WiFi.h>

// ─── WiFi / server config ─────────────────────────────────────────────────────
const char* WIFI_SSID  = "YOUR_WIFI_SSID";          // ← edit
const char* WIFI_PASS  = "YOUR_WIFI_PASSWORD";       // ← edit
const char* SERVER_IP  = "192.168.1.100";            // ← laptop's IP on LAN
const uint16_t SERVER_PORT = 9999;

// ─── Motor pin definitions (L298N) ───────────────────────────────────────────
// Left motor
#define PIN_ENA  25   // PWM speed
#define PIN_IN1  26
#define PIN_IN2  27
// Right motor
#define PIN_ENB  13   // PWM speed
#define PIN_IN3  14
#define PIN_IN4  12

// PWM (ledc) settings
#define PWM_FREQ   1000   // Hz
#define PWM_RES    8      // bits  (0-255)
#define PWM_CH_L   0      // ledc channel for left motor
#define PWM_CH_R   1      // ledc channel for right motor

// Default drive speed (0–255). Reduce if bot is too fast.
#define SPEED_NORMAL  200
#define SPEED_TURN    180   // slightly slower for turns

// ─── Globals ──────────────────────────────────────────────────────────────────
WiFiClient client;
char lastCmd = 'S';

// ─── Forward declarations ─────────────────────────────────────────────────────
void connectWiFi();
void connectServer();
void executeCommand(char cmd);
void motorForward();
void motorBackward();
void motorTurnLeft();
void motorTurnRight();
void motorStop();
void setMotors(int leftSpeed, bool leftFwd, int rightSpeed, bool rightFwd);


// ─── Setup ────────────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n[ESP32] AI Bot Motor Controller – booting…");

  // Motor output pins
  pinMode(PIN_IN1, OUTPUT);
  pinMode(PIN_IN2, OUTPUT);
  pinMode(PIN_IN3, OUTPUT);
  pinMode(PIN_IN4, OUTPUT);

  // PWM channels (ESP32 Arduino core v3 uses ledcAttach)
  ledcAttach(PIN_ENA, PWM_FREQ, PWM_RES);
  ledcAttach(PIN_ENB, PWM_FREQ, PWM_RES);

  motorStop();   // safe default

  connectWiFi();
  connectServer();

  Serial.println("[ESP32] Ready – waiting for commands.");
}


// ─── Main loop ────────────────────────────────────────────────────────────────

void loop() {
  // Reconnect if the TCP connection was lost
  if (!client.connected()) {
    Serial.println("[ESP32] Connection lost – stopping motors and reconnecting…");
    motorStop();
    delay(1000);
    connectServer();
    return;
  }

  // Read one byte from the laptop brain
  if (client.available()) {
    char cmd = (char)client.read();

    // Ignore whitespace/newlines the laptop might accidentally send
    if (cmd == '\n' || cmd == '\r' || cmd == ' ') return;

    Serial.print("[ESP32] CMD: ");
    Serial.println(cmd);

    lastCmd = cmd;
    executeCommand(cmd);
  }

  // No explicit delay here; loop() runs fast and client.available() is cheap.
  // The 50 ms sleep on the Python side limits the command rate naturally.
}


// ─── Command dispatcher ───────────────────────────────────────────────────────

void executeCommand(char cmd) {
  switch (cmd) {
    case 'F': motorForward();   break;
    case 'B': motorBackward();  break;
    case 'L': motorTurnLeft();  break;
    case 'R': motorTurnRight(); break;
    case 'S': motorStop();      break;
    default:
      Serial.print("[ESP32] Unknown command: ");
      Serial.println(cmd);
      motorStop();   // unknown → safe stop
      break;
  }
}


// ─── Motor primitives ─────────────────────────────────────────────────────────

/*
  setMotors() is the single place that touches the H-bridge pins.
  leftSpeed / rightSpeed : 0–255 PWM duty
  leftFwd  / rightFwd    : true = forward, false = backward
*/
void setMotors(int leftSpeed, bool leftFwd, int rightSpeed, bool rightFwd) {
  // Left motor
  ledcWrite(PIN_ENA, leftSpeed);
  digitalWrite(PIN_IN1, leftFwd  ? HIGH : LOW);
  digitalWrite(PIN_IN2, leftFwd  ? LOW  : HIGH);

  // Right motor
  ledcWrite(PIN_ENB, rightSpeed);
  digitalWrite(PIN_IN3, rightFwd ? HIGH : LOW);
  digitalWrite(PIN_IN4, rightFwd ? LOW  : HIGH);
}

void motorForward() {
  setMotors(SPEED_NORMAL, true,  SPEED_NORMAL, true);
}

void motorBackward() {
  setMotors(SPEED_NORMAL, false, SPEED_NORMAL, false);
}

/*
  Pivot turn: one side forward, other side backward.
  Fast in-place rotation – good for searching or realignment.
*/
void motorTurnLeft() {
  setMotors(SPEED_TURN, false, SPEED_TURN, true);
}

void motorTurnRight() {
  setMotors(SPEED_TURN, true,  SPEED_TURN, false);
}

void motorStop() {
  ledcWrite(PIN_ENA, 0);
  ledcWrite(PIN_ENB, 0);
  digitalWrite(PIN_IN1, LOW);
  digitalWrite(PIN_IN2, LOW);
  digitalWrite(PIN_IN3, LOW);
  digitalWrite(PIN_IN4, LOW);
}


// ─── Network helpers ──────────────────────────────────────────────────────────

void connectWiFi() {
  Serial.print("[ESP32] Connecting to WiFi: ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    if (millis() - t0 > 20000) {
      Serial.println("\n[ESP32] WiFi timeout – restarting…");
      ESP.restart();
    }
  }
  Serial.println();
  Serial.print("[ESP32] WiFi OK  IP: ");
  Serial.println(WiFi.localIP());
}

void connectServer() {
  Serial.print("[ESP32] Connecting to laptop ");
  Serial.print(SERVER_IP);
  Serial.print(":");
  Serial.println(SERVER_PORT);

  while (!client.connect(SERVER_IP, SERVER_PORT)) {
    Serial.print(".");
    delay(1000);
  }
  Serial.println("\n[ESP32] Connected to brain!");
  // Enable TCP keep-alive to detect stale connections quickly
  client.setNoDelay(true);
}
