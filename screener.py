import os
import requests
import pandas as pd
import numpy as np

LINE_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")
CRYPTOCOMPARE_API_KEY = os.getenv("CRYPTOCOMPARE_API_KEY")

COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "SHIB", "FLOKI", "NEAR", "DOGE", "OP", "EIGEN"]

def send_line_message(text_msg):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }
    payload = {
        "to": LINE_USER_ID,
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
    
    # คำนวณทั้ง EMA 50 (ระยะกลาง) และ EMA 200 (ระยะยาว)
    df['EMA_50'] = close.ewm(span=50, adjust=False).mean()
    df['EMA_200'] = close.ewm(span=200, adjust=False).mean()
    
    # คำนวณ RSI (14)
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
        ema_50 = current_row['EMA_50']
        ema_200 = current_row['EMA_200']
        
        # 🔥 เพิ่มเงื่อนไขพิจารณา EMA 50 ร่วมด้วย:
        # 1. ราคาต้องยืนเหนือ EMA 200 (เทรนด์ใหญ่ขาขึ้น)
        # 2. ราคาต้องอยู่เหนือ EMA 50 หรือเพิ่งย่อลงมาแตะแนวรับ EMA 50 (ไม่หลุดไปไกล)
        # 3. RSI เกิดภาวะ Oversold (<= 32) เพื่อเข้าซื้อจุดที่ได้เปรียบ
        if current_price > ema_200 and current_price > (ema_50 * 0.98) and rsi <= 32:
            
            # คำนวณโซนราคา
            entry_min = round(current_price * 0.97, 2)   # ตั้งรับลึก 3%
            entry_max = round(current_price * 1.00, 2)   # ซื้อราคาตลาดปัจจุบัน
            
            # ตั้งเป้าขายทำกำไร 10% จากราคาเข้าซื้อ
            target_profit = round(current_price * 1.10, 2) 
            
            # ใช้เส้น EMA 200 เป็นจุดหนีหลัก ถ้าหลุดใต้ EMA 200 ลงไป 2% ให้ Stop Loss ทันที
            stop_loss = round(ema_200 * 0.98, 2)           
            
            signals.append({
                "coin": coin, 
                "price": current_price, 
                "rsi": round(rsi, 2),
                "ema_50": round(ema_50, 2),
                "ema_200": round(ema_200, 2), 
                "entry": f"${entry_min} - ${entry_max}",
                "tp": f"${target_profit}", 
                "sl": f"${stop_loss}"
            })
    return signals

if __name__ == "__main__":
    print("Starting Advanced Screener (EMA50 + EMA200 + RSI)...")
    opportunities = scan_market()
    
    if opportunities:
        message = "🎯 [Crypto Screener 4H - อัปเดตเพิ่ม EMA 50]"
        message += "\nเงื่อนไข: ราคาเหนือ EMA200 & EMA50 + RSI <= 32"
        for opt in opportunities:
            message += f"\n\n🪙 เหรียญ: {opt['coin']}"
            message += f"\n💵 ราคาปัจจุบัน: ${opt['price']}"
            message += f"\n📉 RSI (4H): {opt['rsi']} (Oversold 🔥)"
            message += f"\n📈 เส้น EMA 50 (ระยะกลาง): ${opt['ema_50']}"
            message += f"\n📈 เส้น EMA 200 (ระยะยาว): ${opt['ema_200']}"
            message += f"\n🟢 ช่วงเข้าซื้อ: {opt['entry']}"
            message += f"\n🔴 เป้าหมายขาย (TP): {opt['tp']}"
            message += f"\n❌ จุดตัดขาดทุน (SL): {opt['sl']}"
        
        send_line_message(message)
    else:
        print("No signals matched the criteria in this interval.")
