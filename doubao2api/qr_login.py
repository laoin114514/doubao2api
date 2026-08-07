"""
QR code login for Doubao (豆包).

Ported from LiveSub's QRLogin.cpp. Runs the full QR login flow
in a background thread and notifies callers via callbacks.

Flow:
  1. GET doubao.com → collect ttwid + base cookies
  2. GET /passport/safe/csrf_token → passport_csrf_token
  3. GET /passport/web/get_qrcode → QR token + base64 PNG
  4. Poll /passport/web/check_qrconnect every 1.5s
     new → scanned → confirmed (with redirect_url)
  5. Follow redirect_url → extract sessionid + full cookies
"""

import base64
import json
import logging
import random
import ssl
import string
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

BASE_URL = "https://www.doubao.com"
AID = 497858

# Current Chrome version — keep in sync with client.py UA
CHROME_VERSION = "148.0.0.0"
CHROMIUM_BUILD = "148.0.7816.0"  # used by client.py _security_params

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{CHROME_VERSION} Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.doubao.com/chat/login",
    "Origin": "https://www.doubao.com",
}


def generate_device_params() -> Dict[str, str]:
    """Generate fresh device fingerprint parameters.

    Each QR login creates a new "device identity" to avoid
    inheriting risk scores from previous sessions.
    """
    chars = string.ascii_letters + string.digits
    fp_parts = [
        "".join(random.choices(chars, k=8)),
        "".join(random.choices(chars, k=4)),
        "".join(random.choices(chars, k=4)),
        "".join(random.choices(chars, k=4)),
        "".join(random.choices(chars, k=12)),
    ]
    fp = "verify_" + "_".join(fp_parts)
    device_id = str(random.randint(7000000000000000, 7999999999999999))
    web_id = str(random.randint(7600000000000000000, 7699999999999999999))
    return {"fp": fp, "device_id": device_id, "web_id": web_id}


class QRStatus(Enum):
    """States of the QR login state machine."""

    IDLE = "idle"
    FETCHING_QR = "fetching_qr"
    WAITING_SCAN = "waiting_scan"
    SCANNED = "scanned"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    ERROR = "error"


@dataclass
class QRResult:
    """Outcome of a QR login attempt."""

    status: QRStatus = QRStatus.IDLE
    qrcode_data: bytes = b""
    cookies: Dict[str, str] = field(default_factory=dict)
    sessionid: str = ""
    device_params: Dict[str, str] = field(default_factory=dict)
    error: str = ""


StatusCallback = Callable[[QRStatus, str], None]
DoneCallback = Callable[[QRResult], None]


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only, no requests dependency)
# ---------------------------------------------------------------------------

def _serialize_cookies(cookies: Dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def _parse_set_cookies(headers) -> Dict[str, str]:
    """Extract name=value pairs from all Set-Cookie headers."""
    cookies: Dict[str, str] = {}
    raw_list = headers.get_all("Set-Cookie") or []
    for raw in raw_list:
        part = raw.split(";", 1)[0].strip()
        if "=" in part:
            name, value = part.split("=", 1)
            cookies[name.strip()] = value.strip()
    return cookies


_ssl_ctx = ssl.create_default_context()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Handler that suppresses automatic redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_get(
    url: str,
    headers: Dict[str, str],
    cookies: Dict[str, str],
    follow_redirects: bool = False,
    timeout: int = 10,
) -> Tuple[int, str, Dict[str, str]]:
    """
    Synchronous GET.  Returns ``(status_code, body, new_cookies)``.

    When *follow_redirects* is True, 3xx responses are followed manually
    so that ``Set-Cookie`` headers from **every** hop are collected.
    """
    all_new_cookies: Dict[str, str] = {}
    current_url = url
    max_hops = 10

    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=_ssl_ctx),
        _NoRedirect,
    )

    for _ in range(max_hops):
        req = urllib.request.Request(current_url, method="GET")
        for k, v in headers.items():
            req.add_header(k, v)
        merged = dict(cookies)
        merged.update(all_new_cookies)
        if merged:
            req.add_header("Cookie", _serialize_cookies(merged))

        try:
            resp = opener.open(req, timeout=timeout)
            body = resp.read().decode("utf-8", errors="replace")
            all_new_cookies.update(_parse_set_cookies(resp.headers))
            return resp.status, body, all_new_cookies
        except urllib.error.HTTPError as e:
            if e.headers:
                all_new_cookies.update(_parse_set_cookies(e.headers))

            if follow_redirects and e.code in (301, 302, 303, 307, 308):
                location = e.headers.get("Location", "") if e.headers else ""
                if location:
                    if not location.startswith("http"):
                        location = urljoin(current_url, location)
                    current_url = location
                    continue

            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            return e.code, body, all_new_cookies

    return 0, "", all_new_cookies


# ---------------------------------------------------------------------------
# QRLogin
# ---------------------------------------------------------------------------

class QRLogin:
    """
    Doubao QR code login, ported from LiveSub ``QRLogin.cpp``.

    Usage::

        qr = QRLogin()
        qr.start(on_status=my_status_cb, on_done=my_done_cb)
    """

    POLL_INTERVAL = 1.5
    TIMEOUT_SEC = 120

    def __init__(self) -> None:
        self._running = False
        self._cancel = False
        self._thread: Optional[threading.Thread] = None
        self.result: Optional[QRResult] = None
        self.qrcode_data: bytes = b""

    # -- public API ----------------------------------------------------------

    def start(
        self,
        on_status: Optional[StatusCallback] = None,
        on_done: Optional[DoneCallback] = None,
    ) -> None:
        """Start the login flow in a background thread."""
        if self._running:
            return
        self._cancel = False
        self._running = True
        self.result = None
        self.qrcode_data = b""
        self._thread = threading.Thread(
            target=self._run, args=(on_status, on_done), daemon=True
        )
        self._thread.start()

    def cancel(self) -> None:
        """Signal the polling loop to stop."""
        self._cancel = True

    @property
    def is_running(self) -> bool:
        return self._running

    # -- internals -----------------------------------------------------------

    def _run(
        self,
        on_status: Optional[StatusCallback],
        on_done: Optional[DoneCallback],
    ) -> None:
        result = QRResult()
        try:
            if on_status:
                on_status(QRStatus.FETCHING_QR, "正在获取二维码...")

            session_cookies: Dict[str, str] = {}

            csrf_token = self._get_csrf_token(session_cookies)
            logger.debug(
                "CSRF token: %s",
                csrf_token[:20] + "..." if csrf_token else "(empty)",
            )

            token, qr_bytes = self._get_qr_code(csrf_token, session_cookies)
            result.qrcode_data = qr_bytes
            self.qrcode_data = qr_bytes

            # "qr_ready" signals the GUI to display the image immediately
            if on_status:
                on_status(QRStatus.FETCHING_QR, "qr_ready")

            result = self._poll_qr_connect(
                token, csrf_token, session_cookies, on_status
            )
            result.qrcode_data = qr_bytes

        except Exception as e:
            logger.exception("QR login error")
            result.status = QRStatus.ERROR
            result.error = str(e)
            if on_status:
                on_status(QRStatus.ERROR, str(e))

        self.result = result
        self._running = False
        if on_done:
            on_done(result)

    def _get_csrf_token(self, session_cookies: Dict[str, str]) -> str:
        """Visit homepage + csrf_token endpoint to obtain passport_csrf_token."""
        _, _, new_ck = _http_get(BASE_URL + "/", BASE_HEADERS, {})
        session_cookies.update(new_ck)

        for name in ("passport_csrf_token", "passport_csrf_token_default"):
            if session_cookies.get(name):
                return session_cookies[name]

        url = f"{BASE_URL}/passport/safe/csrf_token/?aid={AID}"
        _, body, new_ck = _http_get(url, BASE_HEADERS, session_cookies)
        session_cookies.update(new_ck)

        try:
            data = json.loads(body)
            if data.get("error_code") == 0:
                token = data.get("data", {}).get("passport_csrf_token", "")
                if token:
                    return token
        except (json.JSONDecodeError, KeyError):
            pass

        return session_cookies.get("passport_csrf_token", "")

    def _get_qr_code(
        self, csrf_token: str, session_cookies: Dict[str, str]
    ) -> Tuple[str, bytes]:
        """Fetch a QR code.  Returns ``(token, png_bytes)``."""
        next_url = urllib.parse.quote("https://www.doubao.com", safe="")
        url = f"{BASE_URL}/passport/web/get_qrcode/?next={next_url}&aid={AID}"

        headers = dict(BASE_HEADERS)
        headers["x-tt-passport-csrf-token"] = csrf_token

        _, body, new_ck = _http_get(url, headers, session_cookies)
        session_cookies.update(new_ck)

        data = json.loads(body)
        qr_data = data.get("data", {})
        error_code = qr_data.get("error_code", data.get("error_code", -1))

        if error_code != 0 or data.get("message") != "success":
            raise RuntimeError(f"获取二维码失败: error_code={error_code}")

        token = qr_data.get("token", "")
        if not token:
            raise RuntimeError("二维码响应中无 token")

        # The ``qrcode`` field is a **raw** base64 string (PNG), NOT a data URI.
        qrcode_raw = qr_data.get("qrcode", "") or qr_data.get("qrcode_url", "")
        qr_bytes = b""
        if qrcode_raw:
            if qrcode_raw.startswith("data:"):
                _, _, b64_part = qrcode_raw.partition(",")
                qr_bytes = base64.b64decode(b64_part)
            elif qrcode_raw.startswith("http"):
                with urllib.request.urlopen(qrcode_raw, timeout=10) as resp:
                    qr_bytes = resp.read()
            else:
                qr_bytes = base64.b64decode(qrcode_raw)

        return token, qr_bytes

    def _poll_qr_connect(
        self,
        token: str,
        csrf_token: str,
        session_cookies: Dict[str, str],
        on_status: Optional[StatusCallback],
    ) -> QRResult:
        """Poll ``check_qrconnect`` until confirmed, expired, or timeout."""
        result = QRResult()
        last_status = ""
        start = time.monotonic()

        while not self._cancel:
            if time.monotonic() - start >= self.TIMEOUT_SEC:
                result.status = QRStatus.EXPIRED
                result.error = "二维码已过期 (超时)"
                return result

            next_url = urllib.parse.quote("https://www.doubao.com", safe="")
            url = (
                f"{BASE_URL}/passport/web/check_qrconnect/"
                f"?next={next_url}&token={token}&aid={AID}"
            )

            headers = dict(BASE_HEADERS)
            headers["x-tt-passport-csrf-token"] = csrf_token

            try:
                _, body, new_ck = _http_get(url, headers, session_cookies)
                session_cookies.update(new_ck)
            except Exception:
                time.sleep(2.0)
                continue

            try:
                data = json.loads(body)
                qr_data = data.get("data", {})
                error_code = qr_data.get(
                    "error_code", data.get("error_code", -1)
                )

                if error_code != 0 or data.get("message") != "success":
                    desc = qr_data.get("description", "").lower()
                    if "expired" in desc or "过期" in desc:
                        result.status = QRStatus.EXPIRED
                        result.error = "二维码已过期"
                        return result
                    time.sleep(2.0)
                    continue

                qr_status = qr_data.get("status", "")
                redirect_url = qr_data.get("redirect_url", "")

                if qr_status != last_status:
                    last_status = qr_status

                    if qr_status == "new":
                        result.status = QRStatus.WAITING_SCAN
                        if on_status:
                            on_status(QRStatus.WAITING_SCAN, "等待扫码")

                    elif qr_status == "scanned":
                        result.status = QRStatus.SCANNED
                        if on_status:
                            on_status(QRStatus.SCANNED, "已扫码，请在手机上确认")

                    elif qr_status == "confirmed":
                        result.status = QRStatus.CONFIRMED
                        result.cookies = dict(session_cookies)
                        result.device_params = generate_device_params()
                        if on_status:
                            on_status(QRStatus.CONFIRMED, "登录成功")

                        if redirect_url:
                            final = self._extract_session_from_redirect(
                                redirect_url, session_cookies
                            )
                            result.cookies = final

                        result.sessionid = result.cookies.get("sessionid", "")
                        return result

                    elif qr_status == "expired":
                        result.status = QRStatus.EXPIRED
                        result.error = "二维码已过期"
                        return result

            except (json.JSONDecodeError, KeyError):
                pass

            time.sleep(self.POLL_INTERVAL)

        result.status = QRStatus.ERROR
        result.error = "已取消"
        return result

    def _extract_session_from_redirect(
        self, redirect_url: str, session_cookies: Dict[str, str]
    ) -> Dict[str, str]:
        """Follow the post-login redirect chain to collect session cookies."""
        headers = dict(BASE_HEADERS)
        _, _, new_ck = _http_get(
            redirect_url,
            headers,
            session_cookies,
            follow_redirects=True,
            timeout=15,
        )
        session_cookies.update(new_ck)
        return dict(session_cookies)
