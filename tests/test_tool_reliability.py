"""
Phase 2: 50-Round Tool Calling Reliability Test.

Simulates OpenCode's behavior: full message history, 8 tools, English,
progressive context growth, mixed scenarios.

Task: "Fix a bug in a Python web app's authentication module"

Scenarios per round:
- Rounds 1-10: Exploration (glob, grep, read_file)
- Rounds 11-15: Planning (todowrite)
- Rounds 16-35: Implementation (edit_file, write_file, bash)
- Rounds 36-45: Testing (bash, read_file)
- Rounds 46-50: Cleanup & verification (bash, grep)

Metrics tracked:
- Success: correct XML tool call parsed
- Failure modes: search_hijack, malformed_xml, wrong_tool, no_tool_call, timeout
- Latency per round
- Context size growth

Usage:
    python3 tests/test_tool_reliability.py --base-url http://127.0.0.1:9090
"""
import argparse
import json
import time
import re
import httpx
import sys
from datetime import datetime
from typing import Optional

BASE_URL = "http://127.0.0.1:9090"
DELAY_BETWEEN_ROUNDS = 8  # seconds between requests to avoid rate limit

# ── Tool Definitions (English, matching OpenCode) ──
TOOLS = [
    {"type": "function", "function": {"name": "read_file", "description": "Read a file from the filesystem. Returns content with line numbers.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string", "description": "Absolute path to the file"}, "offset": {"type": "integer", "description": "Line to start from (1-indexed)"}, "limit": {"type": "integer", "description": "Max lines to read"}}, "required": ["file_path"]}}},
    {"type": "function", "function": {"name": "edit_file", "description": "Edit a file by replacing oldString with newString. The oldString must match exactly.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string", "description": "Absolute path to the file"}, "old_string": {"type": "string", "description": "Exact text to find"}, "new_string": {"type": "string", "description": "Replacement text"}}, "required": ["file_path", "old_string", "new_string"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Write content to a file. Creates or overwrites.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string", "description": "Absolute path"}, "content": {"type": "string", "description": "File content"}}, "required": ["file_path", "content"]}}},
    {"type": "function", "function": {"name": "grep", "description": "Search file contents using regex. Returns matching paths and line numbers.", "parameters": {"type": "object", "properties": {"pattern": {"type": "string", "description": "Regex pattern"}, "path": {"type": "string", "description": "Directory to search"}, "include": {"type": "string", "description": "File glob filter"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "glob", "description": "Find files matching a glob pattern.", "parameters": {"type": "object", "properties": {"pattern": {"type": "string", "description": "Glob pattern (e.g. '**/*.py')"}, "path": {"type": "string", "description": "Base directory"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "bash", "description": "Execute a shell command. Returns stdout and stderr.", "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "Shell command to run"}, "workdir": {"type": "string", "description": "Working directory"}, "timeout": {"type": "integer", "description": "Timeout in ms"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "todowrite", "description": "Create/update a structured task list for tracking progress.", "parameters": {"type": "object", "properties": {"todos": {"type": "array", "items": {"type": "object", "properties": {"content": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}, "priority": {"type": "string", "enum": ["high", "medium", "low"]}}}}}, "required": ["todos"]}}},
    {"type": "function", "function": {"name": "webfetch", "description": "Fetch content from a URL.", "parameters": {"type": "object", "properties": {"url": {"type": "string", "description": "URL to fetch"}, "format": {"type": "string", "enum": ["text", "markdown", "html"]}}, "required": ["url"]}}},
]

# ── Simulated project files (fake tool results) ──
FAKE_PROJECT_STRUCTURE = """src/
  auth/
    __init__.py
    middleware.py
    jwt_handler.py
    password.py
    oauth.py
  api/
    routes.py
    users.py
    admin.py
  models/
    user.py
    session.py
  tests/
    test_auth.py
    test_api.py
  config.py
  main.py
requirements.txt
README.md"""

FAKE_AUTH_MIDDLEWARE = '''"""Authentication middleware for FastAPI."""
import time
from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer
from .jwt_handler import decode_token, TokenExpiredError

security = HTTPBearer()

async def verify_token(request: Request):
    """Verify JWT token from Authorization header."""
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = auth.split(" ")[1]
    try:
        payload = decode_token(token)
        # BUG: not checking token expiry correctly
        if payload.get("exp") < time.time:  # should be time.time()
            raise HTTPException(status_code=401, detail="Token expired")
        request.state.user_id = payload["sub"]
    except TokenExpiredError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
'''

FAKE_JWT_HANDLER = '''"""JWT token handling."""
import jwt
import time
from datetime import datetime, timedelta

SECRET_KEY = "your-secret-key"
ALGORITHM = "HS256"

class TokenExpiredError(Exception):
    pass

def create_token(user_id: str, expires_delta: timedelta = None) -> str:
    """Create a new JWT token."""
    if expires_delta is None:
        expires_delta = timedelta(hours=24)
    expire = datetime.utcnow() + expires_delta
    payload = {"sub": user_id, "exp": expire.timestamp(), "iat": time.time()}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError("Token has expired")
    except jwt.InvalidTokenError as e:
        raise ValueError(f"Invalid token: {e}")
'''

FAKE_TEST_OUTPUT_FAIL = """FAILED tests/test_auth.py::test_token_expiry - TypeError: '<' not supported between instances of 'float' and 'builtin_function_or_method'
FAILED tests/test_auth.py::test_middleware_rejects_expired - AssertionError: Expected 401, got 500

2 failed, 5 passed in 1.23s"""

FAKE_TEST_OUTPUT_PASS = """tests/test_auth.py::test_token_creation PASSED
tests/test_auth.py::test_token_decode PASSED
tests/test_auth.py::test_token_expiry PASSED
tests/test_auth.py::test_middleware_valid_token PASSED
tests/test_auth.py::test_middleware_missing_token PASSED
tests/test_auth.py::test_middleware_rejects_expired PASSED
tests/test_auth.py::test_middleware_invalid_token PASSED

7 passed in 0.89s"""


# ── Scenario definitions: what to ask and expected tool ──
SCENARIOS = [
    # Phase 1: Exploration (rounds 1-10)
    {"user": "I need to fix a bug in the authentication module of this Python web app. The token expiry check is broken - users with expired tokens can still access protected endpoints. Let me start by looking at the project structure.", "expect_tool": "glob", "fake_result": FAKE_PROJECT_STRUCTURE},
    {"user": "Let me look at the auth middleware to understand how tokens are verified.", "expect_tool": "read_file", "fake_result": FAKE_AUTH_MIDDLEWARE},
    {"user": "I see the middleware imports from jwt_handler. Let me read that file too.", "expect_tool": "read_file", "fake_result": FAKE_JWT_HANDLER},
    {"user": "Let me search for where verify_token is used across the codebase.", "expect_tool": "grep", "fake_result": "src/api/routes.py:5: from src.auth.middleware import verify_token\nsrc/api/users.py:3: from src.auth.middleware import verify_token\nsrc/api/admin.py:4: from src.auth.middleware import verify_token"},
    {"user": "Let me check the existing tests for the auth module.", "expect_tool": "read_file", "fake_result": "import pytest\nfrom src.auth.jwt_handler import create_token, decode_token\nfrom src.auth.middleware import verify_token\n\ndef test_token_creation():\n    token = create_token('user123')\n    assert token is not None\n\ndef test_token_expiry():\n    # This test should catch the bug\n    import time\n    token = create_token('user123', timedelta(seconds=-1))\n    with pytest.raises(Exception):\n        decode_token(token)"},
    {"user": "Run the existing tests to see which ones fail.", "expect_tool": "bash", "fake_result": FAKE_TEST_OUTPUT_FAIL},
    {"user": "I can see the bug now. In middleware.py line 18, it compares `payload.get('exp') < time.time` but `time.time` is a function reference, not a call. Let me check if there are any other similar issues.", "expect_tool": "grep", "fake_result": "src/auth/middleware.py:18:        if payload.get(\"exp\") < time.time:  # should be time.time()"},
    {"user": "Let me also check the config to understand token expiry settings.", "expect_tool": "read_file", "fake_result": "# config.py\nTOKEN_EXPIRE_HOURS = 24\nREFRESH_TOKEN_DAYS = 7\nSECRET_KEY = 'your-secret-key'\nDATABASE_URL = 'postgresql://localhost/myapp'"},
    {"user": "Check if there's a requirements.txt to understand dependencies.", "expect_tool": "read_file", "fake_result": "fastapi==0.104.1\nuvicorn==0.24.0\npyjwt==2.8.0\npython-dotenv==1.0.0\nsqlalchemy==2.0.23\npytest==7.4.3"},
    {"user": "Let me look at how the routes use the middleware dependency.", "expect_tool": "read_file", "fake_result": "from fastapi import APIRouter, Depends\nfrom src.auth.middleware import verify_token\n\nrouter = APIRouter()\n\n@router.get('/users/me')\nasync def get_current_user(request: Request, _=Depends(verify_token)):\n    user_id = request.state.user_id\n    return {'user_id': user_id}"},
    # Phase 2: Planning (rounds 11-15)
    {"user": "Now I have a clear picture. Let me plan the fix.", "expect_tool": "todowrite", "fake_result": "Task list updated."},
    {"user": "Before fixing, let me understand: is the `decode_token` function in jwt_handler.py already checking expiry via PyJWT? Because PyJWT's `jwt.decode` raises `ExpiredSignatureError` automatically.", "expect_tool": None, "fake_result": None},
    {"user": "Good point. So the bug is that middleware.py has a redundant (and broken) expiry check on line 18. The `decode_token` function already handles expiry via PyJWT. The fix should remove the broken manual check and rely on the TokenExpiredError that's already caught. Let me also check if there are edge cases.", "expect_tool": "grep", "fake_result": "src/auth/middleware.py:18:        if payload.get(\"exp\") < time.time:\nsrc/auth/oauth.py:45:        if token_data['exp'] < time.time():"},
    {"user": "Found another instance in oauth.py but that one correctly uses `time.time()` with parentheses. Now let me check the password module for completeness.", "expect_tool": "read_file", "fake_result": "\"\"\"Password hashing utilities.\"\"\"\nimport bcrypt\n\ndef hash_password(password: str) -> str:\n    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()\n\ndef verify_password(password: str, hashed: str) -> bool:\n    return bcrypt.checkpw(password.encode(), hashed.encode())"},
    {"user": "Good, password module is fine. Let me update my task list and start the fix.", "expect_tool": "todowrite", "fake_result": "Task list updated."},
    # Phase 3: Implementation (rounds 16-35)
    {"user": "Fix the bug in middleware.py: remove the broken manual expiry check since decode_token already handles it via PyJWT's ExpiredSignatureError.", "expect_tool": "edit_file", "fake_result": "File edited successfully."},
    {"user": "Now let me improve the error handling in the middleware to be more specific about different failure modes.", "expect_tool": "edit_file", "fake_result": "File edited successfully."},
    {"user": "Let me also add proper logging to the middleware for debugging auth failures.", "expect_tool": "edit_file", "fake_result": "File edited successfully."},
    {"user": "Now update the test file to add a specific test for the expiry bug we just fixed.", "expect_tool": "edit_file", "fake_result": "File edited successfully."},
    {"user": "Add a test that verifies expired tokens are properly rejected by the middleware.", "expect_tool": "edit_file", "fake_result": "File edited successfully."},
    {"user": "Let me write a new integration test file for the full auth flow.", "expect_tool": "write_file", "fake_result": "File written successfully."},
    {"user": "Run the linter to make sure our changes don't have syntax errors.", "expect_tool": "bash", "fake_result": "All checks passed. No issues found."},
    {"user": "Run the type checker on the auth module.", "expect_tool": "bash", "fake_result": "Success: no issues found in 4 source files"},
    {"user": "Let me read the updated middleware to verify the fix looks correct.", "expect_tool": "read_file", "fake_result": "\"\"\"Authentication middleware for FastAPI.\"\"\"\nimport logging\nimport time\nfrom fastapi import Request, HTTPException\nfrom .jwt_handler import decode_token, TokenExpiredError\n\nlogger = logging.getLogger(__name__)\n\nasync def verify_token(request: Request):\n    auth = request.headers.get('Authorization')\n    if not auth or not auth.startswith('Bearer '):\n        raise HTTPException(status_code=401, detail='Missing token')\n    token = auth.split(' ')[1]\n    try:\n        payload = decode_token(token)\n        request.state.user_id = payload['sub']\n    except TokenExpiredError:\n        logger.info('Token expired for request %s', request.url.path)\n        raise HTTPException(status_code=401, detail='Token expired')\n    except Exception as e:\n        logger.warning('Invalid token: %s', e)\n        raise HTTPException(status_code=401, detail=f'Invalid token: {e}')"},
    {"user": "Good. Now let me add a refresh token endpoint since we're working on auth anyway.", "expect_tool": "edit_file", "fake_result": "File edited successfully."},
    {"user": "Update the jwt_handler to support refresh tokens.", "expect_tool": "edit_file", "fake_result": "File edited successfully."},
    {"user": "Add the refresh token route to the API router.", "expect_tool": "edit_file", "fake_result": "File edited successfully."},
    {"user": "Write tests for the refresh token functionality.", "expect_tool": "write_file", "fake_result": "File written successfully."},
    {"user": "Let me check if we need to update any imports in __init__.py.", "expect_tool": "read_file", "fake_result": "from .middleware import verify_token\nfrom .jwt_handler import create_token, decode_token\nfrom .password import hash_password, verify_password"},
    {"user": "Update __init__.py to export the new refresh_token function.", "expect_tool": "edit_file", "fake_result": "File edited successfully."},
    {"user": "Run a quick format check with black.", "expect_tool": "bash", "fake_result": "reformatted src/auth/middleware.py\nreformatted src/auth/jwt_handler.py\nAll done! 2 files reformatted, 3 files left unchanged."},
    {"user": "Let me verify the final state of jwt_handler.py after all changes.", "expect_tool": "read_file", "fake_result": FAKE_JWT_HANDLER + "\ndef create_refresh_token(user_id: str) -> str:\n    expire = datetime.utcnow() + timedelta(days=7)\n    payload = {'sub': user_id, 'exp': expire.timestamp(), 'type': 'refresh'}\n    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)\n\ndef verify_refresh_token(token: str) -> str:\n    payload = decode_token(token)\n    if payload.get('type') != 'refresh':\n        raise ValueError('Not a refresh token')\n    return payload['sub']"},
    # Phase 4: Testing (rounds 36-45)
    {"user": "Run all the auth tests now.", "expect_tool": "bash", "fake_result": FAKE_TEST_OUTPUT_PASS},
    {"user": "Run the full test suite to check for regressions.", "expect_tool": "bash", "fake_result": "tests/test_auth.py: 7 passed\ntests/test_api.py: 12 passed\ntests/test_refresh.py: 4 passed\n\n23 passed in 2.45s"},
    {"user": "Run tests with coverage to see if we missed anything.", "expect_tool": "bash", "fake_result": "Name                      Stmts   Miss  Cover\n-----------------------------------------------\nsrc/auth/__init__.py          4      0   100%\nsrc/auth/middleware.py       18      0   100%\nsrc/auth/jwt_handler.py      28      2    93%\nsrc/auth/password.py          6      0   100%\n-----------------------------------------------\nTOTAL                        56      2    96%"},
    {"user": "93% on jwt_handler - let me check what's not covered.", "expect_tool": "bash", "fake_result": "Lines not covered:\n  jwt_handler.py:42 - raise ValueError branch in verify_refresh_token\n  jwt_handler.py:38 - type check failure path"},
    {"user": "Let me add tests for those uncovered paths.", "expect_tool": "edit_file", "fake_result": "File edited successfully."},
    {"user": "Run coverage again to confirm 100%.", "expect_tool": "bash", "fake_result": "Name                      Stmts   Miss  Cover\n-----------------------------------------------\nsrc/auth/__init__.py          4      0   100%\nsrc/auth/middleware.py       18      0   100%\nsrc/auth/jwt_handler.py      28      0   100%\nsrc/auth/password.py          6      0   100%\n-----------------------------------------------\nTOTAL                        56      0   100%"},
    {"user": "Let me also run a quick security check with bandit.", "expect_tool": "bash", "fake_result": "Run started:2024-01-15\n\nTest results:\n  No issues identified.\n\nCode scanned:\n  Total lines of code: 156\n  Total lines skipped: 0"},
    {"user": "Check if there are any TODO comments we should address.", "expect_tool": "grep", "fake_result": "src/config.py:4:SECRET_KEY = 'your-secret-key'  # TODO: move to env var"},
    {"user": "Good catch. Let me fix that security issue - move SECRET_KEY to environment variable.", "expect_tool": "edit_file", "fake_result": "File edited successfully."},
    {"user": "Update the config to read from environment.", "expect_tool": "edit_file", "fake_result": "File edited successfully."},
    # Phase 5: Cleanup & verification (rounds 46-50)
    {"user": "Run the full test suite one final time to make sure everything passes.", "expect_tool": "bash", "fake_result": "23 passed in 2.31s"},
    {"user": "Let me do a final review - search for any remaining issues.", "expect_tool": "grep", "fake_result": "No matches found."},
    {"user": "Check git status to see all our changes.", "expect_tool": "bash", "fake_result": "modified:   src/auth/__init__.py\nmodified:   src/auth/middleware.py\nmodified:   src/auth/jwt_handler.py\nmodified:   src/config.py\nnew file:   tests/test_refresh.py\nmodified:   tests/test_auth.py"},
    {"user": "Everything looks good. Update the task list to mark everything complete.", "expect_tool": "todowrite", "fake_result": "Task list updated."},
    {"user": "Generate a summary of all changes we made. No tool needed, just summarize.", "expect_tool": None, "fake_result": None},
]


# ── Result classification ──
def classify_result(response: dict, expect_tool: Optional[str]) -> dict:
    """Classify whether a round succeeded or failed, and why."""
    choice = response["choices"][0]
    message = choice["message"]
    content = message.get("content") or ""
    tool_calls = message.get("tool_calls")
    finish_reason = choice.get("finish_reason", "")

    # Check for search hijack (search_results in non-streaming response isn't visible,
    # but if model answers directly when tool was expected, it's likely hijacked)
    if expect_tool is None:
        # Expected natural language response
        if tool_calls:
            return {"status": "fail", "mode": "unnecessary_tool_call", "detail": f"Called {tool_calls[0]['function']['name']} when no tool needed"}
        if content:
            return {"status": "ok", "mode": "natural_language"}
        return {"status": "fail", "mode": "empty_response"}

    # Expected a tool call
    if not tool_calls:
        if content:
            # Model answered in text instead of calling tool
            if any(kw in content.lower() for kw in ["search", "搜索", "查询结果"]):
                return {"status": "fail", "mode": "search_hijack", "detail": content[:100]}
            return {"status": "fail", "mode": "no_tool_call", "detail": f"Got text instead: {content[:100]}"}
        return {"status": "fail", "mode": "empty_response"}

    # Got tool calls - check if correct tool
    called_tool = tool_calls[0]["function"]["name"]
    args_str = tool_calls[0]["function"].get("arguments", "")

    # Validate arguments is valid JSON
    try:
        args = json.loads(args_str)
    except (json.JSONDecodeError, TypeError):
        return {"status": "fail", "mode": "malformed_args", "detail": f"Invalid JSON args: {args_str[:100]}"}

    if called_tool == expect_tool:
        return {"status": "ok", "mode": "correct_tool", "tool": called_tool, "args": args}
    else:
        # Wrong tool but still a valid tool call - partial success
        return {"status": "partial", "mode": "wrong_tool", "detail": f"Expected {expect_tool}, got {called_tool}", "tool": called_tool, "args": args}


# ── Main test runner ──
def run_reliability_test(base_url: str, max_rounds: int = 50, delay: int = DELAY_BETWEEN_ROUNDS):
    """Run the full 50-round reliability test."""
    print(f"\n{'='*70}")
    print(f"  TOOL CALLING RELIABILITY TEST - {max_rounds} ROUNDS")
    print(f"  Target: {base_url}")
    print(f"  Delay: {delay}s between rounds")
    print(f"  Started: {datetime.now().isoformat()}")
    print(f"{'='*70}\n")

    messages = []  # Full conversation history
    results = []
    tool_valid_names = {t["function"]["name"] for t in TOOLS}

    for i, scenario in enumerate(SCENARIOS[:max_rounds], 1):
        user_msg = scenario["user"]
        expect_tool = scenario["expect_tool"]
        fake_result = scenario["fake_result"]

        # Add user message
        messages.append({"role": "user", "content": user_msg})

        # Build request
        payload = {
            "model": "doubao",
            "stream": False,
            "messages": messages,
            "tools": TOOLS,
        }
        payload_size = len(json.dumps(payload))

        phase = "EXPLORE" if i <= 10 else "PLAN" if i <= 15 else "IMPL" if i <= 35 else "TEST" if i <= 45 else "CLEANUP"
        print(f"[{i:02d}/{max_rounds}] {phase} | expect={expect_tool or 'text'} | ctx={payload_size:,} chars")

        start = time.time()
        try:
            resp = httpx.post(f"{base_url}/v1/chat/completions", json=payload, timeout=120.0)
            elapsed = time.time() - start

            if resp.status_code != 200:
                error = resp.json().get("error", {}).get("message", resp.text[:100])
                print(f"  HTTP {resp.status_code} ({elapsed:.1f}s): {error}")
                result = {"round": i, "status": "fail", "mode": f"http_{resp.status_code}", "detail": error, "elapsed": elapsed, "ctx_size": payload_size}
                results.append(result)
                if "Not logged" in error or "710022004" in error:
                    print("\n  !!! SERVICE DOWN - STOPPING TEST !!!")
                    break
                # Don't add to messages on error
                messages.pop()  # Remove the user message we just added
                time.sleep(delay)
                continue

            data = resp.json()
            result_info = classify_result(data, expect_tool)
            result_info["round"] = i
            result_info["elapsed"] = elapsed
            result_info["ctx_size"] = payload_size

            status_icon = "OK" if result_info["status"] == "ok" else "PARTIAL" if result_info["status"] == "partial" else "FAIL"
            print(f"  {status_icon} ({elapsed:.1f}s) | {result_info['mode']}", end="")
            if "detail" in result_info:
                print(f" | {result_info['detail'][:60]}")
            else:
                print()

            results.append(result_info)

            # Add assistant response to history
            choice = data["choices"][0]["message"]
            if choice.get("tool_calls"):
                messages.append({
                    "role": "assistant", "content": None,
                    "tool_calls": choice["tool_calls"]
                })
                # Add fake tool result
                if fake_result:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": choice["tool_calls"][0]["id"],
                        "content": fake_result
                    })
            else:
                messages.append({"role": "assistant", "content": (choice.get("content") or "")[:500]})

        except httpx.TimeoutException:
            elapsed = time.time() - start
            print(f"  TIMEOUT ({elapsed:.1f}s)")
            results.append({"round": i, "status": "fail", "mode": "timeout", "elapsed": elapsed, "ctx_size": payload_size})
            messages.pop()  # Remove user message
        except Exception as e:
            elapsed = time.time() - start
            print(f"  ERROR ({elapsed:.1f}s): {e}")
            results.append({"round": i, "status": "fail", "mode": "exception", "detail": str(e), "elapsed": elapsed, "ctx_size": payload_size})
            messages.pop()

        # Rate limit protection
        if i < max_rounds:
            time.sleep(delay)

    # ── Print summary ──
    print(f"\n{'='*70}")
    print("  RESULTS SUMMARY")
    print(f"{'='*70}")

    total = len(results)
    ok = sum(1 for r in results if r["status"] == "ok")
    partial = sum(1 for r in results if r["status"] == "partial")
    fail = sum(1 for r in results if r["status"] == "fail")

    print(f"\n  Total rounds: {total}")
    print(f"  Success:      {ok} ({ok/total*100:.1f}%)")
    print(f"  Partial:      {partial} ({partial/total*100:.1f}%)")
    print(f"  Failed:       {fail} ({fail/total*100:.1f}%)")

    # Failure mode breakdown
    if fail > 0 or partial > 0:
        print(f"\n  Failure modes:")
        modes = {}
        for r in results:
            if r["status"] != "ok":
                mode = r.get("mode", "unknown")
                modes[mode] = modes.get(mode, 0) + 1
        for mode, count in sorted(modes.items(), key=lambda x: -x[1]):
            print(f"    {mode}: {count}")

    # Latency stats
    latencies = [r["elapsed"] for r in results if "elapsed" in r]
    if latencies:
        print(f"\n  Latency (seconds):")
        print(f"    Min:  {min(latencies):.1f}")
        print(f"    Max:  {max(latencies):.1f}")
        print(f"    Avg:  {sum(latencies)/len(latencies):.1f}")
        print(f"    P95:  {sorted(latencies)[int(len(latencies)*0.95)]:.1f}")

    # Context growth
    ctx_sizes = [r["ctx_size"] for r in results if "ctx_size" in r]
    if ctx_sizes:
        print(f"\n  Context growth:")
        print(f"    Start: {ctx_sizes[0]:,} chars")
        print(f"    End:   {ctx_sizes[-1]:,} chars")
        print(f"    Growth: {(ctx_sizes[-1]-ctx_sizes[0]):,} chars over {len(ctx_sizes)} rounds")

    print(f"\n  Finished: {datetime.now().isoformat()}")
    print(f"{'='*70}")

    # Save detailed results
    report = {
        "summary": {"total": total, "ok": ok, "partial": partial, "fail": fail, "success_rate": f"{ok/total*100:.1f}%"},
        "rounds": results,
    }
    report_path = "/tmp/tool_reliability_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  Full report saved to: {report_path}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tool calling reliability test")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--rounds", type=int, default=50)
    parser.add_argument("--delay", type=int, default=DELAY_BETWEEN_ROUNDS)
    args = parser.parse_args()

    run_reliability_test(args.base_url, max_rounds=args.rounds, delay=args.delay)
