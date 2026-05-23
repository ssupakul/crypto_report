import os
import json
import requests
import pandas as pd
import numpy as np

LINE_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")
CRYPTOCOMPARE_API_KEY = os.getenv("CRYPTOCOMPARE_API_KEY")

COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "EIGEN", "FLOKI", "SHIB", "OP", "DOGE", "NEAR"]
STATE_FILE = "screener_state.json"

# ----------------------------------------------------
# 📂 การเก็บสถานะ (State Management)
# ----------------------------------------------------
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading state file: {e}")
    return {"last_signals": {}}

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=4)
    except Exception as e:
        print(f"Error saving state file: {e}")

def commit_state_to_repo():
    if os.getenv("GITHUB_ACTIONS") == "true":
        print("Configuring Git and committing state file...")
        os.system("git config --global user.name 'github-actions[bot]'")
        os.system("git config --global user.email 'github-actions[bot]@users.noreply.github.com'")
        os.system(f"git add {STATE_FILE}")
        status = os.system("git commit -m 'chore: update screener state with BB [skip ci]'")
        if status == 0:
            os.system("git push")
            print("Successfully committed and pushed state to repository.")
        else:
            print("No changes in state file to commit.")

# ----------------------------------------------------
# 📞 LINE Messaging API
# ----------------------------------------------------
def send_line_message(text_msg):
    url = "https://api.line.me/v2/bot/message/push"
    token = str(LINE_ACCESS_TOKEN).strip() if LINE_ACCESS_TOKEN else ""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    payload = {
        "to": str(LINE_USER_ID).strip(),
        "messages": [{"type": "text", "text": text_msg}]
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            print("Signal sent via Messaging API Successfully.")
        else:
            print(f"Failed to send LINE message: {response.text}")
    except Exception as e:
        print(f"Error sending LINE message: {e}")

# ----------------------------------------------------
# 📊 Data Fetching & Indicators (คำนวณ BB เพิ่มที่นี่)
# ----------------------------------------------------
def get_historical_data(coin):
    url = "https://min-api.cryptocompare.com/data/v2/histohour"
    params = {
        "fsym": coin,
        "tsym": "USD",
        "limit": 1000, 
        "api_key": CRYPTOCOMPARE_API_KEY
    }
    try:
        response = requests.get(url, params=params).json()
        if response.get("Response") == "Success":
            df = pd.DataFrame(response["Data"]["Data"])
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df.set_index('time', inplace=True)
            
            df_4h = df.resample('4h').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volumeto': 'sum'
            }).dropna()
            return df_4h
    except Exception as e:
        print(f"Error fetching data for {coin}: {e}")
    return None

def calculate_indicators(df):
    close = df['close']
    volume = df['volumeto']
    
    # 1. EMA 50 / 200
    df['EMA_50'] = close.ewm(span=50, adjust=False).mean()
    df['EMA_200'] = close.ewm(span=200, adjust=False).mean()
    
    # 2. RSI Standard (Wilder's)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = np.where(avg_loss == 0, np.nan, avg_gain / avg_loss)
    df['RSI'] = np.where(avg_loss == 0, 100, 100 - (100 / (1 + rs)))
    
    # 3. MACD (12, 26, 9)
    exp1 = close.ewm(span=12, adjust=False).mean()
    exp2 = close.ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # 4. Volume SMA 20
    df['Volume_SMA20'] = volume.rolling(window=20).mean()
    
    # 5. Bollinger Bands (20, 2) 🟢 [เพิ่มส่วนนี้]
    df['BB_Basis'] = close.rolling(window=20).mean()
    df['BB_Std'] = close.rolling(window=20).std()
    df['BB_Upper'] = df['BB_Basis'] + (df['BB_Std'] * 2)
    df['BB_Lower'] = df['BB_Basis'] - (df['BB_Std'] * 2)
    
    return df

def format_price(coin, price):
    if price < 0.001: return f"{price:.8f}"
    elif price < 1: return f"{price:.4f}"
    else: return f"{price:.2f}"

# ----------------------------------------------------
# 🔍 Market Scanner Engine (ปรับเงื่อนไข BB ร่วมสแกน)
# ----------------------------------------------------
def scan_market(state):
    buy_signals = []
    sell_signals = []
    last_signals = state.get("last_signals", {})
    
    for coin in COINS:
        df = get_historical_data(coin)
        if df is None or len(df) < 200:
            continue
            
        df = calculate_indicators(df)
        
        current_row = df.iloc[-1]
        prev_row = df.iloc[-2]
        current_time_str = str(df.index[-1])
        
        current_price = current_row['close']
        high_price = current_row['high']
        low_price = current_row['low']
        
        rsi = current_row['RSI']
        ema_50 = current_row['EMA_50']
        ema_200 = current_row['EMA_200']
        volume = current_row['volumeto']
        volume_sma20 = current_row['Volume_SMA20']
        
        bb_upper = current_row['BB_Upper']
        bb_lower = current_row['BB_Lower']
        
        # คอนเฟิร์ม Volume เสมอเมื่อเกิดสัญญาณเคลื่อนไหว
        is_volume_confirmed = volume > volume_sma20
        
        # สัญญาณพึ่งตัดกันของ MACD (Crossover)
        macd_bullish_cross = (prev_row['MACD'] <= prev_row['MACD_Signal']) and (current_row['MACD'] > current_row['MACD_Signal'])
        macd_bearish_cross = (prev_row['MACD'] >= prev_row['MACD_Signal']) and (current_row['MACD'] < current_row['MACD_Signal'])

        # 🟢 ฝั่งที่ 1: สัญญาณช้อนซื้อ (Buy Setup)
        # กรองเฉพาะแนวโน้มขาขึ้นภาพใหญ่ (Price > EMA 200) และ Volume เข้าสนับสนุน
        if current_price > ema_200 and is_volume_confirmed:
            signal_key = f"{coin}_BUY"
            if last_signals.get(signal_key) != current_time_str:
                
                signal_type = ""
                # เงื่อนไขร่วมใหม่: ราคาจิ้มหรือหลุดกรอบล่าง BB + MACD ตัดขึ้น + RSI โซนล่าง
                if low_price <= bb_lower and macd_bullish_cross and rsi <= 45:
                    signal_type = "BB Lower Touch + MACD Golden Cross 🚀"
                # เงื่อนไขสำรอง: หลุดกรอบล่าง BB + RSI Oversold จัดๆ ยืนยันการ Pullback แรงๆ
                elif low_price <= bb_lower and rsi <= 32:
                    signal_type = "BB Lower Touch + RSI Oversold 📉"
                
                if signal_type:
                    entry_min = format_price(coin, current_price * 0.97)
                    entry_max = format_price(coin, current_price * 1.00)
                    target_profit = format_price(coin, current_price * 1.12) 
                    stop_loss = format_price(coin, ema_200 * 0.98)           
                    
                    buy_signals.append({
                        "coin": coin, "price": format_price(coin, current_price), "rsi": round(rsi, 2),
                        "type": signal_type, "ema_50": format_price(coin, ema_50), "ema_200": format_price(coin, ema_200), 
                        "entry": f"${entry_min} - ${entry_max}", "tp": f"${target_profit}", "sl": f"${stop_loss}"
                    })
                    last_signals[signal_key] = current_time_str

        # 🔴 ฝั่งที่ 2: สัญญาณเตือนขาย (Sell Setup)
        if is_volume_confirmed:
            signal_key = f"{coin}_SELL"
            if last_signals.get(signal_key) != current_time_str:
                
                is_sell_triggered = False
                # เงื่อนไขร่วมใหม่: ราคาทะลุกรอบบน BB พร้อม RSI เข้าข่ายแพงมาก
                if high_price >= bb_upper and rsi >= 70:
                    is_sell_triggered = True
                # หรือเกิดแรงเทขายทำ Dead Cross ที่กรอบบน Bollinger Bands
                elif high_price >= bb_upper and macd_bearish_cross:
                    is_sell_triggered = True
                    
                if is_sell_triggered:
                    tp_range_min = format_price(coin, current_price * 1.00)
                    tp_range_max = format_price(coin, current_price * 1.05)
                    safety_exit_val = ema_50 if current_price > ema_50 else current_price * 0.95
                    safety_exit = format_price(coin, safety_exit_val)
                    
                    sell_signals.append({
                        "coin": coin, "price": format_price(coin, current_price), "rsi": round(rsi, 2),
                        "ema_50": format_price(coin, ema_50), "ema_200": format_price(coin, ema_200),
                        "tp_zone": f"${tp_range_min} - ${tp_range_max}", "exit": f"${safety_exit}"
                    })
                    last_signals[signal_key] = current_time_str
                    
    state["last_signals"] = last_signals
    return buy_signals, sell_signals, state

# ----------------------------------------------------
# 🚀 Execution
# ----------------------------------------------------
if __name__ == "__main__":
    print("Starting Screener with Bollinger Bands Integration...")
    
    current_state = load_state()
    buy_list, sell_list, updated_state = scan_market(current_state)
    save_state(updated_state)
    
    if buy_list:
        message_buy = "🎯 [Crypto Screener 4H - สัญญาณช้อนซื้อ (BB + MACD)]"
        for opt in buy_list:
            message_buy += f"\n\n🪙 เหรียญ: {opt['coin']}"
            message_buy += f"\n🚨 รูปแบบ: {opt['type']}"
            message_buy += f"\n💵 ราคาปัจจุบัน: ${opt['price']}"
            message_buy += f"\n📉 RSI (4H): {opt['rsi']}"
            message_buy += f"\n📈 เส้น EMA 50 / 200: ${opt['ema_50']} / ${opt['ema_200']}"
            message_buy += f"\n🟢 ช่วงเข้าซื้อ: {opt['entry']}"
            message_buy += f"\n🔴 เป้าหมายขาย (TP): {opt['tp']}"
            message_buy += f"\n❌ จุดตัดขาดทุน (SL): {opt['sl']}"
        send_line_message(message_buy)
        
    if sell_list:
        message_sell = "⚠️ [Crypto Screener 4H - เตือนโซนขาย (BB Upper Break)]"
        message_sell += "\nคำแนะนำ: ราคาชนหรือทะลุกรอบบน Bollinger Bands ควรแบ่งขายล๊อคกำไร"
        for opt in sell_list:
            message_sell += f"\n\n🪙 เหรียญ: {opt['coin']}"
            message_sell += f"\n💵 ราคาปัจจุบัน: ${opt['price']}"
            message_sell += f"\n📈 RSI (4H): {opt['rsi']}"
            message_sell += f"\n📈 เส้น EMA 50 / 200: ${opt['ema_50']} / ${opt['ema_200']}"
            message_sell += f"\n🔴 ช่วงราคาที่ควรทยอยขาย: {opt['tp_zone']}"
            message_sell += f"\n❌ จุดล็อกกำไรหลุดตรงนี้ต้องหนี (Exit): {opt['exit']}"
        send_line_message(message_sell)

    if not buy_list and not sell_list:
        print("No new Bollinger Bands crossover signals triggered in this session.")

    commit_state_to_repo()
