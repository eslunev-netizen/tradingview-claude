import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "my-secret-123")


def ask_claude(symbol, timeframe, price, rsi, macd, signal_type, extra=""):
    prompt = f"""Ты — опытный технический аналитик. Дай краткий анализ точки входа.

Инструмент: {symbol}
Таймфрейм: {timeframe}
Текущая цена: {price}
RSI: {rsi}
MACD: {macd}
Сигнал от TradingView: {signal_type}
{f'Дополнительно: {extra}' if extra else ''}

Ответь строго по шаблону:
1. РЕШЕНИЕ: ВОЙТИ / НЕ ВХОДИТЬ / ЖДАТЬ
2. НАПРАВЛЕНИЕ: LONG / SHORT
3. ПРИЧИНА: почему
4. СТОП-ЛОСС: уровень
5. ЦЕЛЬ: тейк-профит"""

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    if response.status_code == 200:
        return response.json()["content"][0]["text"]
    return f"Ошибка Claude API: {response.status_code}"


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
        timeout=10,
    )


@app.route("/webhook", methods=["POST"])
def webhook():
    if request.args.get("secret", "") != WEBHOOK_SECRET:
        return jsonify({"error": "Неверный ключ"}), 403

    data = request.get_json(silent=True) or {}
    symbol    = data.get("symbol", "UNKNOWN")
    timeframe = data.get("timeframe", "?")
    price     = data.get("price", "?")
    rsi       = data.get("rsi", "?")
    macd      = data.get("macd", "?")
    signal    = data.get("signal", "нет сигнала")
    extra     = data.get("extra", "")

    analysis = ask_claude(symbol, timeframe, price, rsi, macd, signal, extra)

    send_telegram(
        f"📊 <b>{symbol} · {timeframe}</b>\n"
        f"💰 Цена: <b>{price}</b>\n"
        f"📈 RSI: {rsi} | MACD: {macd}\n"
        f"⚡ Сигнал: {signal}\n\n"
        f"🤖 <b>Claude:</b>\n{analysis}"
    )

    return jsonify({"status": "ok", "analysis": analysis})


@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "Сервер работает"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
