"""一次性的验证码解除脚本。

背景：豆包服务端风控（710022004）要求真人完成一次人机验证才能解除。
用法：
    python captcha_fix.py
脚本用 doubao2api 的 profile 打开有头浏览器，自动发一条消息触发验证码，
弹窗弹出后，请手动完成验证码；完成后脚本检测到 AI 正常回复即打印提示，
并可保持窗口打开一段时间（方便账号“回暖”）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from playwright.async_api import async_playwright

PROFILE = Path(r"C:\Users\29084\Desktop\code\zcodeWorkspace\doubao-proxy\profile")
CHAT_URL = "https://www.doubao.com/chat/"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("captcha_fix")


async def main() -> None:
    pw = await async_playwright().start()
    ctx = await pw.chromium.launch_persistent_context(
        str(PROFILE), headless=False, channel="chrome",
        args=["--window-size=1280,900"])
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    await page.goto(CHAT_URL)
    await page.wait_for_selector("textarea.semi-input-textarea", timeout=30000)

    # 登录态确认
    n = await page.get_by_role("button", name="登录").count()
    log.info("登录按钮数量=%s（0 表示已登录）", n)
    if n > 0:
        log.warning("未登录！请先登录后再试。")

    # 自动发一条消息，触发可能的验证码
    ta = page.locator("textarea.semi-input-textarea")
    await ta.click()
    await ta.press_sequentially("你好，这是一条验证消息", delay=8)
    try:
        await page.wait_for_selector("#flow-end-msg-send", timeout=15000)
        await page.locator("#flow-end-msg-send").click()
        log.info("已发送测试消息，等待 AI 回复或验证码弹出……")
    except Exception:
        log.warning("发送按钮未出现，请手动在窗口里发一条消息。")

    # 轮询：直到出现 AI 回复（div.flex.justify-start 且有内容）说明验证通过
    start = time.monotonic()
    solved = False
    while time.monotonic() - start < 120:
        await asyncio.sleep(2)
        try:
            caps = await page.locator("#captcha_container").count()
            if caps > 0:
                log.info("检测到验证码弹窗 → 请立即在窗口里手动完成验证码！")
            loc = page.locator("div.flex.justify-start")
            cnt = await loc.count()
            ok = False
            if cnt > 0:
                txt = (await loc.nth(cnt - 1).inner_text()).strip()
                if txt and "验证消息" not in txt:
                    ok = True
            if ok:
                solved = True
                log.info("✅ AI 已正常回复，验证码已解除！")
                break
        except Exception:
            pass
    if not solved:
        log.warning("120 秒内未确认到回复。若你已手动通过验证码，可以继续等待；否则请重跑脚本。")

    log.info("保持窗口打开 60 秒（让账号回暖），之后自动关闭……")
    await asyncio.sleep(60)
    await ctx.close()
    await pw.stop()
    log.info("完成。")


if __name__ == "__main__":
    asyncio.run(main())
