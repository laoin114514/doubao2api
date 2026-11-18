#!/bin/sh
# doubao2api container entrypoint.
#
# Default: run the headed Chromium inside an xvfb virtual display (best
# anti-bot fingerprint, no VNC exposure).
# DOUBAO_ENABLE_VNC=true additionally starts:
#   - Xvfb on :99 (known display so x11vnc can attach)
#   - x11vnc on 127.0.0.1:5900 (password from DOUBAO_VNC_PASSWORD, optional)
#   - noVNC/websockify on 0.0.0.0:6080  -> http://<host>:6080/vnc.html
set -eu

start_vnc() {
    echo "[entrypoint] VNC enabled: Xvfb :99 + x11vnc :5900 + noVNC :6080"
    # A container *restart* (docker compose restart / crash restart) reuses the
    # filesystem, so the previous Xvfb leaves /tmp/.X99-lock behind. Xvfb then
    # refuses to start with "Server is already active for display 99" and the
    # headed browser dies with "Missing X server". Remove stale locks first.
    rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true

    Xvfb :99 -screen 0 1280x900x24 -nolisten tcp &
    XVFB_PID=$!
    export DISPLAY=:99
    i=0
    while [ "$i" -lt 50 ]; do
        if [ -S /tmp/.X11-unix/X99 ]; then
            break
        fi
        if ! kill -0 "$XVFB_PID" 2>/dev/null; then
            echo "[entrypoint] ERROR: Xvfb exited during startup" >&2
            exit 1
        fi
        i=$((i + 1))
        sleep 0.2
    done
    if [ ! -S /tmp/.X11-unix/X99 ]; then
        echo "[entrypoint] ERROR: Xvfb failed to create display :99" >&2
        exit 1
    fi

    if [ -n "${DOUBAO_VNC_PASSWORD:-}" ]; then
        echo "[entrypoint] noVNC/VNC password is enabled"
        x11vnc -display :99 -forever -shared -rfbport 5900 -localhost \
            -passwd "$DOUBAO_VNC_PASSWORD" &
    else
        echo "[entrypoint] WARNING: VNC is enabled WITHOUT a password;"
        echo "[entrypoint]          any client that can reach :6080 controls the browser."
        x11vnc -display :99 -forever -shared -rfbport 5900 -localhost -nopw &
    fi
    websockify --web=/usr/share/novnc 0.0.0.0:6080 localhost:5900 &

    exec python -m doubao2api
}

if [ "${DOUBAO_ENABLE_VNC:-false}" = "true" ]; then
    start_vnc
fi

exec xvfb-run -a -s "-screen 0 1280x900x24" python -m doubao2api
