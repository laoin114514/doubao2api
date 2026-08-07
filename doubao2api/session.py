"""
Cookie management for Doubao Chat API.

Supports loading cookies from:
1. DOUBAO_COOKIE environment variable (Cookie header format)
2. .doubao_session.json file (written by QR login or /v1/session/update)
"""
import json
import os
from pathlib import Path
from typing import Any, Dict


def _parse_cookie_header(cookie_header: str) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    for item in cookie_header.split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        cookies[name.strip()] = value.strip()
    return cookies


def load_cookies(session_file: str = ".doubao_session.json") -> Dict[str, str]:
    """
    Load cookies from env var or session JSON file.

    Tries in order:
    1. DOUBAO_COOKIE env var
    2. session_file JSON
    """
    cookie_header = os.environ.get("DOUBAO_COOKIE", "").strip()
    if cookie_header:
        parsed = _parse_cookie_header(cookie_header)
        if parsed:
            return parsed

    path = Path(session_file)
    if not path.exists():
        raise FileNotFoundError(
            f"session file not found: {session_file}. "
            "Set DOUBAO_COOKIE env var, prepare .doubao_session.json, "
            "or use QR login (POST /v1/session/qr-login)."
        )

    data = json.loads(path.read_text(encoding="utf-8"))
    cookies = data.get("cookies", {})
    if not isinstance(cookies, dict) or not cookies:
        raise ValueError(f"invalid cookies in {session_file}")
    return {str(k): str(v) for k, v in cookies.items()}


def load_session(session_file: str = ".doubao_session.json") -> Dict[str, Any]:
    """
    Load the full session including cookies and device params.

    Returns a dict with keys:
    - ``cookies``: name→value mapping
    - ``params``: device_id, web_id, fp, fp_verified (may be empty if not saved yet)
    """
    path = Path(session_file)
    if not path.exists():
        return {"cookies": {}, "params": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"cookies": {}, "params": {}}
    cookies = data.get("cookies", {})
    params = data.get("params", {})
    return {
        "cookies": {str(k): str(v) for k, v in cookies.items()} if isinstance(cookies, dict) else {},
        "params": params if isinstance(params, dict) else {},
    }


def save_params(
    params: Dict[str, str],
    session_file: str = ".doubao_session.json",
    fp_verified: bool = False,
) -> None:
    """
    Update the ``params`` section of the session file in-place.

    Creates the file if it does not exist (cookies will be empty).
    """
    path = Path(session_file)
    data: Dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    data["params"] = {
        "device_id": params.get("device_id", ""),
        "web_id": params.get("web_id", ""),
        "fp": params.get("fp", ""),
        "fp_verified": fp_verified,
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
