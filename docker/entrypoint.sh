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

if [ "${DOUBAO_ENABLE_VNC:-false}" = "true" ]; then
    echo "[entrypoint] VNC enabled: Xvfb :99 + x11vnc :5900 + noVNC :6080"
    Xvfb :99 -screen 0 1280x900x24 -nolisten tcp &
    export DISPLAY=:99
    i=0
    while [ "$i" -lt 20 ] && [ ! -e /tmp/.X11-unix/X99 ]; do
        i=$((i + 1))
        sleep 0.2
    done
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
    log_dir=/root/.cache/ms-playwright
    mkdir -p "$log_dir"
    exec python -m doubao2api
fi

exec xvfb-run -a -s "-screen 0 1280x900x24" python -m doubao2api
