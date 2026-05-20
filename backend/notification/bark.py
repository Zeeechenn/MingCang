"""Bark iOS 推送通知（https://github.com/Finb/Bark）

BARK_KEY 未配置时静默跳过，不影响主流程。
"""
import json
import logging
import time
import urllib.error
import urllib.request

from backend.config import settings

logger = logging.getLogger(__name__)


def send_result(
    title: str,
    body: str,
    group: str = "StockSage",
    sound: str = "bark",
    retries: int = 1,
    backoff_seconds: float = 0.5,
    timeout: int = 10,
) -> dict:
    """
    发送 Bark 推送，返回结构化结果，便于调度器记录失败原因。
    retries 表示失败后的额外重试次数。
    """
    if not settings.bark_key:
        return {"ok": False, "skipped": True, "reason": "missing_bark_key", "attempts": 0}

    payload = json.dumps({
        "device_key": settings.bark_key,
        "title": title[:50],
        "body": body[:200],
        "group": group,
        "sound": sound,
        "icon": "https://cdn-icons-png.flaticon.com/512/2521/2521826.png",
    }, ensure_ascii=False).encode()

    url = f"{settings.bark_server.rstrip('/')}/push"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    last_error = None
    max_attempts = max(1, retries + 1)
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
            if result.get("code") == 200:
                logger.debug("Bark 推送成功: %s", title)
                return {"ok": True, "attempts": attempt, "response": result}
            last_error = f"non_200:{result}"
            logger.warning("Bark 返回非 200: %s", result)
        except urllib.error.URLError as e:
            last_error = str(e)
            logger.warning("Bark 推送失败（网络，第%d次）: %s", attempt, e)
        except Exception as e:
            last_error = str(e)
            logger.warning("Bark 推送失败（第%d次）: %s", attempt, e)
        if attempt < max_attempts and backoff_seconds > 0:
            time.sleep(backoff_seconds * attempt)
    return {"ok": False, "attempts": max_attempts, "reason": last_error or "unknown"}


def send(
    title: str,
    body: str,
    group: str = "StockSage",
    sound: str = "bark",
    retries: int = 1,
) -> bool:
    """发送 Bark 推送。返回 True 表示成功，False 表示跳过或失败。"""
    return bool(send_result(title, body, group=group, sound=sound, retries=retries).get("ok"))


def send_signal_alert(symbol: str, name: str, recommendation: str,
                      score: float, stop_loss: float, take_profit: float,
                      position_pct: float | None = None) -> bool:
    """盘后信号通知：标题和正文必须写明具体交易动作。"""
    if recommendation == "可关注":
        title = f"👀 观察：{name}({symbol}) 可关注"
        action = "动作：加入主动观察，不新开仓；等待分数突破小仓试错线或回调确认。"
    elif recommendation == "可小仓试错":
        title = f"📈 小仓试错：{name}({symbol})"
        pct = f"{position_pct * 100:.1f}%" if position_pct is not None else "小仓"
        action = f"动作：次日按规则买入 {pct}，并同步设置止盈止损。"
    elif recommendation in ("买入", "强买"):
        title = f"📈 旧框架买入：{name}({symbol})"
        action = "动作：旧框架入场信号，按测试规则买入并同步设置止盈止损。"
    else:
        title = f"📌 {name}({symbol}) {recommendation}"
        action = "动作：仅记录信号，不执行买入。"
    body = (
        f"{action}｜综合分 {score:+.0f}｜"
        f"止盈 {take_profit:.2f}｜止损 {stop_loss:.2f}"
    )
    return send(title, body)


def send_stoploss_alert(symbol: str, name: str, current_price: float,
                        stop_loss: float, signal_date: str) -> bool:
    """止损预警通知"""
    title = f"⚠️ 止损预警：{name}({symbol})"
    body = (
        f"当前价 {current_price:.2f} 触及止损 {stop_loss:.2f}"
        f"（信号日期 {signal_date}）"
    )
    return send(title, body, sound="alarm")
