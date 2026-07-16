#!/usr/bin/env bash
# connect-mobile.sh — one-shot JARVIS mobile bring-up
#
# Brings up phone camera → /dev/video2 via scrcpy + v4l2loopback, then
# (optionally) launches the JARVIS backend.
#
# Usage:
#   ./scripts/connect-mobile.sh                  # USB ADB, no backend
#   ./scripts/connect-mobile.sh --backend        # USB ADB, then start backend
#   ./scripts/connect-mobile.sh --wifi 1.2.3.4   # Wi-Fi ADB, no backend
#   ./scripts/connect-mobile.sh --wifi 1.2.3.4 --backend
#   ./scripts/connect-mobile.sh --laptop-dev     # backend in laptop dev mode

set -euo pipefail

# ───────────────────────────── config ─────────────────────────────
VIDEO_NR=2
VIDEO_DEV="/dev/video${VIDEO_NR}"
CARD_LABEL="phonecam"
SCRCPY_FPS=30
SCRCPY_SIZE=1080
ADB_PORT=5555
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ──────────────────────────── colors ──────────────────────────────
RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; BLU=$'\033[34m'; RST=$'\033[0m'
ok()   { echo "${GRN}[OK]${RST}   $*"; }
info() { echo "${BLU}[..]${RST}   $*"; }
warn() { echo "${YLW}[!!]${RST}   $*"; }
die()  { echo "${RED}[XX]${RST}   $*" >&2; exit 1; }

# ────────────────────────── arg parse ─────────────────────────────
WIFI_IP=""
START_BACKEND=0
LAPTOP_DEV=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --wifi)        WIFI_IP="${2:?--wifi needs IP}"; shift 2 ;;
    --backend)     START_BACKEND=1; shift ;;
    --laptop-dev)  START_BACKEND=1; LAPTOP_DEV=1; shift ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) die "Unknown arg: $1 (try --help)" ;;
  esac
done

# ────────────────────────── deps check ────────────────────────────
need_pkg=()
command -v scrcpy >/dev/null || need_pkg+=("scrcpy")
command -v adb    >/dev/null || need_pkg+=("android-tools")
modinfo v4l2loopback >/dev/null 2>&1 || need_pkg+=("v4l2loopback-dkms")

if (( ${#need_pkg[@]} )); then
  warn "Missing packages: ${need_pkg[*]}"
  if command -v pacman >/dev/null; then
    info "Installing via pacman (sudo required)…"
    sudo pacman -S --needed --noconfirm "${need_pkg[@]}" || die "pacman install failed"
  elif command -v apt >/dev/null; then
    info "Installing via apt (sudo required)…"
    sudo apt update && sudo apt install -y "${need_pkg[@]}" || die "apt install failed"
  else
    die "Install manually: ${need_pkg[*]}"
  fi
fi
ok "scrcpy, adb, v4l2loopback present"

# ───────────────────────── v4l2loopback ───────────────────────────
if [[ ! -e "$VIDEO_DEV" ]]; then
  info "Loading v4l2loopback (creates ${VIDEO_DEV})…"
  if lsmod | grep -q '^v4l2loopback'; then
    sudo modprobe -r v4l2loopback || die "Could not unload existing v4l2loopback"
  fi
  sudo modprobe v4l2loopback video_nr="$VIDEO_NR" card_label="$CARD_LABEL" exclusive_caps=1 \
    || die "modprobe v4l2loopback failed"
fi
[[ -e "$VIDEO_DEV" ]] || die "${VIDEO_DEV} still missing after modprobe"
ok "${VIDEO_DEV} ready (label: ${CARD_LABEL})"

# ───────────────────────── adb connect ────────────────────────────
adb start-server >/dev/null

if [[ -n "$WIFI_IP" ]]; then
  info "Connecting ADB over Wi-Fi: ${WIFI_IP}:${ADB_PORT}"
  adb connect "${WIFI_IP}:${ADB_PORT}" || die "adb connect failed (run 'adb tcpip ${ADB_PORT}' over USB first)"
fi

info "Waiting for ADB device (timeout 30s)…"
for i in {1..30}; do
  if adb devices | awk 'NR>1 && $2=="device" {found=1} END{exit !found}'; then
    break
  fi
  sleep 1
done
adb devices | awk 'NR>1 && $2=="device" {found=1} END{exit !found}' \
  || die "No ADB device. USB: enable USB-debugging + 'Always allow'. Wi-Fi: pass --wifi <ip>."
DEV_ID="$(adb devices | awk 'NR>1 && $2=="device" {print $1; exit}')"
ok "ADB device: ${DEV_ID}"

# ────────────────────────── scrcpy run ────────────────────────────
if pgrep -af "scrcpy.*v4l2-sink=${VIDEO_DEV}" >/dev/null; then
  info "Killing previous scrcpy on ${VIDEO_DEV}"
  pkill -f "scrcpy.*v4l2-sink=${VIDEO_DEV}" || true
  sleep 1
fi

info "Starting scrcpy → ${VIDEO_DEV} (camera, back-facing, no audio)"
scrcpy \
  --video-source=camera \
  --camera-facing=back \
  --v4l2-sink="${VIDEO_DEV}" \
  --no-audio \
  --no-video-playback \
  --no-window \
  --max-fps "${SCRCPY_FPS}" \
  --max-size "${SCRCPY_SIZE}" \
  >/tmp/scrcpy-jarvis.log 2>&1 &
SCRCPY_PID=$!
echo "$SCRCPY_PID" >/tmp/scrcpy-jarvis.pid
sleep 2

if ! kill -0 "$SCRCPY_PID" 2>/dev/null; then
  warn "scrcpy died early. Tail of log:"
  tail -20 /tmp/scrcpy-jarvis.log >&2
  die "scrcpy failed to start (see /tmp/scrcpy-jarvis.log)"
fi
ok "scrcpy running (PID ${SCRCPY_PID}, log: /tmp/scrcpy-jarvis.log)"

info "Waiting for ${VIDEO_DEV} to produce frames…"
for i in {1..15}; do
  if v4l2-ctl --device="${VIDEO_DEV}" --get-fmt-video 2>/dev/null | grep -q 'Width/Height'; then
    ok "${VIDEO_DEV} is producing frames"
    break
  fi
  sleep 1
done

# ──────────────────────── backend launch ──────────────────────────
if (( START_BACKEND )); then
  cd "$PROJECT_DIR"
  if [[ -f /home/ladliju/Developer/Machine-learning/.venv/bin/activate ]]; then
    source /home/ladliju/Developer/Machine-learning/.venv/bin/activate
  else
    warn "ml venv not found at expected path — backend may fail on imports"
  fi

  if (( LAPTOP_DEV )); then
    info "Launching backend (laptop dev mode, no wake word)"
    exec python3 -m backend.main --laptop --no-wake-word
  else
    info "Launching backend (full system, ${VIDEO_DEV})"
    exec python3 -m backend.main --device "${VIDEO_DEV}"
  fi
else
  ok "Mobile connected. Start backend manually:"
  echo "    cd \"${PROJECT_DIR}\" && ml && python3 -m backend.main --device ${VIDEO_DEV}"
  echo
  echo "Stop scrcpy: kill \$(cat /tmp/scrcpy-jarvis.pid)"
fi
