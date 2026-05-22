import os
import requests
import pandas as pd
import numpy as np

# แก้ไขคำขึ้นต้นเป็นตัวพิมพ์เล็กให้ถูกต้องตามหลัก Python
LINE_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")
CRYPTOCOMPARE_API_KEY = os.getenv("CRYPTOCOMPARE_API_KEY")

COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "FLOKI", "SHIB", "OP", "DOGE", "NEAR"]

def send_line_message(text_msg):
    url = "https://api.line.me/v2/bot/message/push"
    
    # เพิ่มความชัวร์ด้วยการล้างช่องว่าง (Strip) เผื่อมี Space ติดมาจาก GitHub Secrets
    token = str(LINE_ACCESS_TOKEN).strip() if LINE_ACCESS_TOKEN else ""
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"  # ตรวจสอบให้มั่นใจว่าสะกดคำว่า Bearer เว้นวรรค 1 ที ถูกต้อง
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
            # พิมพ์ตรวจสอบ Headers ออกมาดูหากพังอีกครั้งเพื่อความง่ายในการเช็ค
            print(f"Failed to send LINE message: {response.text}")
            print(f"Debug Info - Token Length: {len(token)}, UserID Length: {len(payload['to'])}")
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
    df['EMA_50'] = close.ewm(span=50, adjust=False).mean()
    df['EMA_200'] = close.ewm(span=200, adjust=False).mean()
    
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

def check_bullish_divergence(df, lookback=15):
    if len(df) < lookback + 2:
        return False
    curr_price = df['low'].iloc[-1]
    curr_rsi = df['RSI'].iloc[-1]
    for i in range(3, lookback):
        prev_price = df['low'].iloc[-i]
        prev_rsi = df['RSI'].iloc[-i]
        if curr_price < prev_price and curr_rsi > prev_rsi:
            if prev_rsi < 35 or curr_rsi < 35:
                return True
    return False

def scan_market():
    buy_signals = []
    sell_signals = []
    
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
        
        is_divergence = check_bullish_divergence(df)
        
        # ----------------------------------------------------
        # 🟢 ฝั่งที่ 1: ตรวจจับสัญญาณน่าช้อนซื้อ (Buy/Long Setup)
        # ----------------------------------------------------
        if current_price > ema_200:
            signal_type = ""
            if current_price > (ema_50 * 0.98) and rsi <= 32:
                signal_type = "RSI Oversold + Pullback 📉"
            elif is_divergence:
                signal_type = "Bullish Divergence 📈"
                
            if signal_type:
                entry_min = round(current_price * 0.97, 2)
                entry_max = round(current_price * 1.00, 2)
                target_profit = round(current_price * 1.12, 2) 
                stop_loss = round(ema_200 * 0.98, 2)           
                
                buy_signals.append({
                    "coin": coin, "price": current_price, "rsi": round(rsi, 2),
                    "type": signal_type, "ema_50": round(ema_50, 2), "ema_200": round(ema_200, 2), 
                    "entry": f"${entry_min} - ${entry_max}", "tp": f"${target_profit}", "sl": f"${stop_loss}"
                })
        
        # ----------------------------------------------------
        # 🔴 ฝั่งที่ 2: เพิ่มเงื่อนไขตรวจสอบ RSI Overbought (Sell/Take Profit Setup)
        # ----------------------------------------------------
        if rsi >= 70:
            # แนะนำให้ทยอยแบ่งขายทำกำไรเมื่อราคาขึ้นมาแรงเกินไป
            tp_range_min = round(current_price * 1.00, 2) # ราคาปัจจุบันเป็นจุดเริ่มแบ่งขายไม้แรก
            tp_range_max = round(current_price * 1.05, 2) # คาดการณ์ว่าอาจจะกาวต่อได้อีกขยับไป 5%
            
            # จุดล็อกกำไร (Trailing Stop) หากราคาร่วงย้อนกลับลงมาหลุดเส้น EMA 50 ให้ล้างพอร์ตสิทธิ์กำไร
            safety_exit = round(ema_50, 2) if current_price > ema_50 else round(current_price * 0.95, 2)
            
            sell_signals.append({
                "coin": coin, "price": current_price, "rsi": round(rsi, 2),
                "ema_50": round(ema_50, 2), "ema_200": round(ema_200, 2),
                "tp_zone": f"${tp_range_min} - ${tp_range_max}", "exit": f"${safety_exit}"
            })
            
    return buy_signals, sell_signals

if __name__ == "__main__":
    print("Starting Comprehensive Screener (Buy Setup + Overbought Warning)...")
    buy_list, sell_list = scan_market()
    
    # 1. ส่งแจ้งเตือนถ้าเจอสัญญาณช้อนซื้อ
    if buy_list:
        message_buy = "🎯 [Crypto Screener 4H - สัญญาณช้อนซื้อ]"
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
        
    # 2. ส่งแจ้งเตือนถ้าเจอเหรียญที่เข้าโซนต้องระวังขายทำกำไร (Overbought)
    if sell_list:
        message_sell = "⚠️ [Crypto Screener 4H - เตือนโซน Overbought]"
        message_sell += "\nคำแนะนำ: ราคาวิ่งแรงเกินไป ควรพิจารณาแบ่งขายทำกำไร"
        for opt in sell_list:
            message_sell += f"\n\n🪙 เหรียญ: {opt['coin']}"
            message_sell += f"\n🔥 สถานะ: RSI Overbought (ซื้อมากเกินไป)"
            message_sell += f"\n💵 ราคาปัจจุบัน: ${opt['price']}"
            message_sell += f"\n📈 RSI (4H): {opt['rsi']} 🚨"
            message_sell += f"\n📈 เส้น EMA 50 / 200: ${opt['ema_50']} / ${opt['ema_200']}"
            message_sell += f"\n🔴 ช่วงราคาที่ควรทยอยขาย: {opt['tp_zone']}"
            message_sell += f"\n❌ จุดล็อกกำไรหลุดตรงนี้ต้องหนี (Exit): {opt['exit']}"
        send_line_message(message_sell)

    if not buy_list and not sell_list:
        print("No buy or sell signals triggered in this session.")
