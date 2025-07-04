import os
import time
import threading
from datetime import datetime, time as dt_time
from flask import Flask, request, jsonify
from alpaca_trade_api.rest import REST, TimeFrame

# === CONFIG ===
API_KEY = os.getenv("APCA_API_KEY_ID")
API_SECRET = os.getenv("APCA_API_SECRET_KEY")
BASE_URL = "https://broker-api.sandbox.alpaca.markets"

api = REST(API_KEY, API_SECRET, BASE_URL)
app = Flask(__name__)

SYMBOLS = ["AAPL", "TSLA", "AMD"]
POSITION_SIZE = 1
STOP_LOSS_PERCENT = 0.02
TAKE_PROFIT_PERCENT = 0.04
breakout_levels = {}
bot_running = False
log_history = []

# === CORE FUNCTIONS ===
def log(msg):
    print(msg)
    log_history.append(f"{datetime.now().strftime('%H:%M:%S')} - {msg}")
    if len(log_history) > 100:
        log_history.pop(0)

def get_930_945_candle(symbol):
    try:
        now = datetime.now()
        today = now.date()
        start = datetime.combine(today, dt_time(9, 30))
        end = datetime.combine(today, dt_time(9, 45))
        bars = api.get_bars(symbol, TimeFrame.Minute, start=start.isoformat(), end=end.isoformat()).df
        if bars.empty:
            log(f"No 9:30-9:45 data for {symbol}")
            return None
        high = bars['high'].max()
        low = bars['low'].min()
        return high, low
    except Exception as e:
        log(f"Error getting candle for {symbol}: {e}")
        return None

def get_current_price(symbol):
    try:
        return api.get_last_trade(symbol).price
    except Exception as e:
        log(f"Error fetching price for {symbol}: {e}")
        return None

def place_order(symbol, qty, side):
    try:
        api.submit_order(symbol=symbol, qty=qty, side=side, type='market', time_in_force='day')
        log(f"{side.upper()} order placed for {symbol}")
    except Exception as e:
        log(f"Order error for {symbol}: {e}")

def get_position(symbol):
    try:
        return int(api.get_position(symbol).qty)
    except:
        return 0

def calculate_exit_prices(entry_price):
    sl = entry_price * (1 - STOP_LOSS_PERCENT)
    tp = entry_price * (1 + TAKE_PROFIT_PERCENT)
    return sl, tp

def monitor_positions():
    positions = api.list_positions()
    for position in positions:
        symbol = position.symbol
        qty = int(position.qty)
        entry_price = float(position.avg_entry_price)
        current_price = get_current_price(symbol)
        if current_price is None:
            continue
        sl, tp = calculate_exit_prices(entry_price)
        if current_price <= sl:
            log(f"Stop loss for {symbol} hit at {current_price}")
            place_order(symbol, qty, 'sell')
        elif current_price >= tp:
            log(f"Take profit for {symbol} hit at {current_price}")
            place_order(symbol, qty, 'sell')

def trade_logic():
    global breakout_levels
    now = datetime.now()
    market_open = datetime.combine(now.date(), dt_time(9, 30))
    market_close = datetime.combine(now.date(), dt_time(16, 0))
    if not (market_open <= now <= market_close):
        log("Market closed. Skipping.")
        return

    for symbol in SYMBOLS:
        if symbol not in breakout_levels or breakout_levels[symbol]['date'] != now.date():
            candle = get_930_945_candle(symbol)
            if candle is None:
                continue
            high, low = candle
            breakout_levels[symbol] = {'high': high, 'low': low, 'date': now.date()}
            log(f"{symbol} breakout: High={high}, Low={low}")

        current_price = get_current_price(symbol)
        if current_price is None:
            continue

        pos_qty = get_position(symbol)
        if current_price > breakout_levels[symbol]['high'] and pos_qty == 0:
            log(f"Buy signal for {symbol} at {current_price}")
            place_order(symbol, POSITION_SIZE, 'buy')

def bot_loop():
    global bot_running
    log("✅ Bot started.")
    while bot_running:
        trade_logic()
        monitor_positions()
        time.sleep(60)
    log("⛔ Bot stopped.")

# === FLASK ENDPOINTS ===
@app.route("/")
def home():
    return "✅ Trading Bot API is Live"

@app.route("/start", methods=["GET"])
def start_bot():
    global bot_running
    if not bot_running:
        bot_running = True
        threading.Thread(target=bot_loop).start()
        return jsonify({"status": "Bot started"})
    return jsonify({"status": "Bot already running"})

@app.route("/stop", methods=["GET"])
def stop_bot():
    global bot_running
    bot_running = False
    return jsonify({"status": "Bot stopping..."})

@app.route("/status", methods=["GET"])
def status():
    return jsonify({"running": bot_running})

@app.route("/set-symbols", methods=["POST"])
def set_symbols():
    global SYMBOLS
    data = request.json
    SYMBOLS = data.get("symbols", SYMBOLS)
    return jsonify({"symbols": SYMBOLS})

@app.route("/set-stop-loss", methods=["POST"])
def set_stop_loss():
    global STOP_LOSS_PERCENT
    data = request.json
    STOP_LOSS_PERCENT = float(data.get("stop_loss", STOP_LOSS_PERCENT))
    return jsonify({"stop_loss": STOP_LOSS_PERCENT})

@app.route("/set-take-profit", methods=["POST"])
def set_take_profit():
    global TAKE_PROFIT_PERCENT
    data = request.json
    TAKE_PROFIT_PERCENT = float(data.get("take_profit", TAKE_PROFIT_PERCENT))
    return jsonify({"take_profit": TAKE_PROFIT_PERCENT})

@app.route("/logs", methods=["GET"])
def get_logs():
    return jsonify({"logs": log_history[-50:]})

@app.route("/balance", methods=["GET"])
def get_balance():
    try:
        account = api.get_account()
        return jsonify({
            "cash": account.cash,
            "portfolio_value": account.portfolio_value
        })
    except Exception as e:
        return jsonify({"error": str(e)})

# === LAUNCH APP ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)