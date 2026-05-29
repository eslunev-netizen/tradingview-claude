import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
WEBHOOK_SECRET     = os.environ.get("WEBHOOK_SECRET", "my-secret-123")


def ask_claude(symbol, timeframe, price, signal_type, extra=""):
    """
    Просим Claude дать краткий разбор сигнала по тем данным, что у нас реально есть.
    Никаких RSI/MACD не требуем — стратегия другая: уровни сессий, фибо-пивоты, ретесты, объём.
    """
    prompt = (
        "Ты опытный технический аналитик и трейдер внутри дня. "
        "Тебе пришёл сигнал от индикатора, построенного на: уровнях азиатской сессии (POC/VAH/VAL/High/Low), "
        "фибо-пивотах (P/S1-S3/R1-R3), ретесте уровней, ложных пробоях и повышенном объёме. "
        "RSI/MACD не используются — стратегия не про осцилляторы, а про реакцию цены на уровни.\n\n"
        "Данные сигнала:\n"
        "- Инструмент: " + str(symbol) + "\n"
        "- Таймфрейм: " + str(timeframe) + "\n"
        "- Цена: " + str(price) + "\n"
        "- Тип сигнала: " + str(signal_type) + "\n"
        "- Детали: " + str(extra) + "\n\n"
        "Дай короткий разбор по шаблону (без воды, максимум 6-8 строк):\n"
        "1. РЕШЕНИЕ: ВОЙТИ / ПРОПУСТИТЬ / ОСТОРОЖНО\n"
        "2. НАПРАВЛЕНИЕ: LONG / SHORT (из типа сигнала)\n"
        "3. ОСНОВАНИЕ: 1-2 фразы, почему сигнал заслуживает внимания\n"
        "4. РИСКИ: 1 фраза, что может пойти не так\n"
        "5. СТОП-ЛОСС: ориентир (например, 'за ближайший уровень' или конкретная логика)\n"
        "6. ЦЕЛЬ: ориентир (например, 'следующий уровень фибо/пивота')\n\n"
        "Если данных явно недостаточно для решения — так и скажи в пункте 1: 'ПРОПУСТИТЬ — данные неполные'. "
        "Не выдумывай уровни и цифры, которых нет."
    )
    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        if response.status_code == 200:
            return response.json()["content"][0]["text"]
        return "Ошибка Claude API: " + str(response.status_code) + " — " + response.text[:200]
    except Exception as e:
        return "Сбой запроса к Claude: " + str(e)


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        # не валим запрос из-за телеги
        pass


def parse_payload(raw_body, raw_text):
    """
    Терпимый парсер. Принимает:
    - JSON ({"symbol":"...","price":"..."})
    - простой текст из TradingView (тогда часть полей берём из текста, остальное "?")
    """
    # 1) пробуем JSON
    if raw_body:
        if isinstance(raw_body, dict):
            return raw_body
    if raw_text:
        try:
            return json.loads(raw_text)
        except Exception:
            pass

    # 2) текстовый fallback: всё, что прислали, идёт в "signal"
    text = (raw_text or "").strip()
    return {
        "symbol":    "?",
        "timeframe": "?",
        "price":     "?",
        "signal":    text if text else "нет сигнала",
        "extra":     "",
    }


@app.route("/webhook", methods=["POST"])
def webhook():
    if request.args.get("secret", "") != WEBHOOK_SECRET:
        return jsonify({"error": "Неверный ключ"}), 403

    raw_body = request.get_json(silent=True)
    raw_text = request.get_data(as_text=True) or ""

    data = parse_payload(raw_body, raw_text)

    symbol    = str(data.get("symbol",    "?"))
    timeframe = str(data.get("timeframe", "?"))
    price     = str(data.get("price",     "?"))
    signal    = str(data.get("signal",    "нет сигнала"))
    extra     = str(data.get("extra",     ""))

    # эмодзи по направлению
    sig_lower = signal.lower()
    if "вверх" in sig_lower or "long" in sig_lower or "buy" in sig_lower or "↑" in signal:
        head_emoji = "🟢"
    elif "вниз" in sig_lower or "short" in sig_lower or "sell" in sig_lower or "↓" in signal:
        head_emoji = "🔴"
    else:
        head_emoji = "⚡"

    # формат таймфрейма: если число — добавим 'м'/'ч' для понятности
    tf_display = timeframe
    if timeframe.isdigit():
        n = int(timeframe)
        tf_display = (str(n // 60) + "ч") if n >= 60 and n % 60 == 0 else (timeframe + "м")
    elif timeframe.upper() in ("D", "1D"):
        tf_display = "День"
    elif timeframe.upper() in ("W", "1W"):
        tf_display = "Неделя"

    # запрос к Claude (можно отключить, если хочется просто чистый сигнал — см. ниже)
    analysis = ask_claude(symbol, tf_display, price, signal, extra)

    msg = (
        head_emoji + " <b>" + signal + "</b>\n"
        "📊 " + symbol + " · " + tf_display + "\n"
        "💰 Цена: <b>" + price + "</b>\n"
    )
    if extra:
        msg += "📝 " + extra + "\n"
    msg += "\n🤖 <b>Claude:</b>\n" + analysis

    send_telegram(msg)
    return jsonify({"status": "ok", "parsed": data, "analysis": analysis})


@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "Server is running"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
