import os
import requests
import pandas as pd
import numpy as np

# ดึงค่า Secrets ใหม่จาก GitHub Environment
LINE_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")
CRYPTOCOMPARE_API_KEY = os.getenv("CRYPTOCOMPARE_API_KEY")

COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "EIGEN", "SHIB", "FLOKI", "DOGE"]

def send_line_message(text_msg):
    """ฟังก์ชันส่งข้อความแบบ Push Message ผ่าน LINE Messaging API"""
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }
    payload = {
        "to": LINE_USER_ID,
        "messages": [
            {
                "type": "text",
                "text": text_msg
            }
        ]
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            print("Signal sent via Messaging API Successfully.")
        else:
            print(f"Failed to send LINE message: {response.text}")
    except Exception as e:
        print(f"Error sending LINE message: {e}")

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
        if response["Response"] == "Success":
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
    df['EMA_200'] = close.ewm(span=200, adjust=False).mean()
    
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

def scan_market():
    signals = []
    for coin in COINS:
        df = get_historical_data(coin)
        if df is None or len(df) < 200:
            continue
            
        df = calculate_indicators(df)
        current_row = df.iloc[-1]
        current_price = current_row['close']
        rsi = current_row['RSI']
        ema_200 = current_row['EMA_200']
        
        # เงื่อนไขระบบของคุณ: เหนือ EMA200 + RSI <= 32
        if current_price > ema_200 and rsi <= 32:
            entry_min = round(current_price * 0.97, 2)
            entry_max = round(current_price * 1.00, 2)
            target_profit = round(current_price * 1.10, 2)
            stop_loss = round(ema_200 * 0.98, 2)
            
            signals.append({
                "coin": coin, "price": current_price, "rsi": round(rsi, 2),
                "ema_200": round(ema_200, 2), "entry": f"${entry_min} - ${entry_max}",
                "tp": f"${target_profit}", "sl": f"${stop_loss}"
            })
    return signals

if __name__ == "__main__":
    print("Starting Screener via Messaging API...")
    opportunities = scan_market()
    
    if opportunities:
        # ปรับการจัดข้อความให้น่าอ่านเมื่อเด้งเข้าแชท LINE บอท
        message = "🎯 [Crypto Screener 4H]\nเงื่อนไข: ราคาเหนือ EMA200 + RSI <= 32"
        for opt in opportunities:
            message += f"\n\n🪙 เหรียญ: {opt['coin']}"
            message += f"\n💵 ราคาปัจจุบัน: ${opt['price']}"
            message += f"\n📉 RSI (4H): {opt['rsi']} (Oversold 🔥)"
            message += f"\n📈 เส้น EMA 200: ${opt['ema_200']}"
            message += f"\n🟢 ช่วงเข้าซื้อ: {opt['entry']}"
            message += f"\n🔴 เป้าหมายขาย (TP): {opt['tp']}"
            message += f"\n❌ จุดตัดขาดทุน (SL): {opt['sl']}"
        
        send_line_message(message)
    else:
        print("No signals found.")
