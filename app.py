from flask import Flask, render_template, jsonify
import ccxt
import time
import datetime
import threading
import requests

app = Flask(__name__)

# === TƏNZİMLƏMƏLƏR ===
ARBITRAGE_PERCENT = 0.5       
MAX_ARBITRAGE_PERCENT = 100.0 
MIN_VOLUME_USDT = 500000      
MAX_FUNDING_RATE_PERCENT = 1.0   

TELEGRAM_BOT_TOKEN = "8701129404:AAFYMzGvlAnGZ_wNQiCWciS3W3Mp-KP7_K4"
TELEGRAM_CHAT_ID = "5490094790"

live_arbitrage_data = []

def send_startup_message():
    """Server işə düşəndə Telegram-a bir dəfə xəbər verir"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID, 
        "text": "🌐 <b>Vebsayt Skaneri Aktivdir!</b>\n\nSistem Render serverlərində uğurla işə düşdü. Canlı nəticələri vebsayt üzərindən izləyə bilərsiniz.", 
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, data=payload)
    except:
        pass

def get_exchange_url(exchange, token):
    base_coin = token.split('/')[0].split(':')[0] if '/' in token or ':' in token else token.replace('USDT', '')
    urls = {
        'OKX': f"https://www.okx.com/trade-swap/{base_coin}-USDT-SWAP",
        'Binance': f"https://www.binance.com/en/futures/{base_coin}USDT",
        'Bybit': f"https://www.bybit.com/trade/usdt/{base_coin}USDT",
        'MEXC': f"https://futures.mexc.com/exchange/{base_coin}_USDT",
        'KuCoin': f"https://www.kucoin.com/trade/ext/{base_coin}USDTM",
        'GateIO': f"https://www.gate.io/futures_trade/USDT/{base_coin}_USDT",
        'Bitget': f"https://www.bitget.com/futures/usdt/{base_coin}USDT",
        'HTX': f"https://www.htx.com/futures/linear_swap/exchange/#contract_code={base_coin}-USDT&contract_type=swap&type=cross"
    }
    return urls.get(exchange, "#")

def get_volume(ticker, price):
    vol = ticker.get('quoteVolume')
    if vol is not None: return float(vol)
    base_vol = ticker.get('baseVolume')
    if base_vol is not None and price is not None: return float(base_vol) * float(price)
    return 0.0

# === VEBSAYT SKANERİ ===
def run_scanner():
    global live_arbitrage_data
    
    exchanges = {
        'OKX': ccxt.okx({'options': {'defaultType': 'swap'}}),
        'Binance': ccxt.binance({'options': {'defaultType': 'future'}}),
        'Bybit': ccxt.bybit({'options': {'defaultType': 'linear'}}),
        'MEXC': ccxt.mexc({'options': {'defaultType': 'swap'}}),
        'KuCoin': ccxt.kucoin({'options': {'defaultType': 'swap'}}),
        'GateIO': ccxt.gateio({'options': {'defaultType': 'swap'}}),
        'Bitget': ccxt.bitget({'options': {'defaultType': 'swap'}}),
        'HTX': ccxt.htx({'options': {'defaultType': 'swap'}})
    }
    
    market_symbols = {}
    all_symbols = set()
    for name, exchange in exchanges.items():
        try:
            exchange.load_markets()
            symbols = set()
            for sym, market in exchange.markets.items():
                if market.get('contract') and market.get('settle') == 'USDT' and market.get('active') is not False:
                    symbols.add(sym)
            market_symbols[name] = symbols
            all_symbols.update(symbols)
        except: pass
            
    common_tokens = [sym for sym in all_symbols if sym in market_symbols.get('OKX', set())]
    pairs_to_check = [('OKX', ex) for ex in exchanges if ex != 'OKX']
    
    while True:
        try:
            all_tickers = {}
            for name, exchange in exchanges.items():
                try:
                    if exchange.has.get('fetchTickers'):
                        all_tickers[name] = exchange.fetch_tickers()
                    else:
                        all_tickers[name] = {}
                except:
                    all_tickers[name] = {}

            current_time = datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S')
            
            temp_web_data = []
            for token in common_tokens:
                best_net_diff = -1
                best_op = None

                for ex1, ex2 in pairs_to_check:
                    if token not in market_symbols.get(ex2, set()): continue

                    ticker1 = all_tickers.get(ex1, {}).get(token, {})
                    ticker2 = all_tickers.get(ex2, {}).get(token, {})
                    
                    p1, p2 = ticker1.get('last'), ticker2.get('last')
                    
                    if p1 and p2:
                        vol1, vol2 = get_volume(ticker1, p1), get_volume(ticker2, p2)
                        
                        if vol1 >= MIN_VOLUME_USDT and vol2 >= MIN_VOLUME_USDT:
                            buy_ex, buy_p, sell_ex, sell_p = (ex1, p1, ex2, p2) if p1 < p2 else (ex2, p2, ex1, p1)
                            raw_diff = ((sell_p - buy_p) / buy_p) * 100
                            
                            if ARBITRAGE_PERCENT <= raw_diff <= MAX_ARBITRAGE_PERCENT:
                                fr_buy = fr_sell = 0.0
                                try:
                                    if exchanges[buy_ex].has.get('fetchFundingRate'):
                                        fr_buy = float(exchanges[buy_ex].fetch_funding_rate(token).get('fundingRate', 0)) * 100
                                    if exchanges[sell_ex].has.get('fetchFundingRate'):
                                        fr_sell = float(exchanges[sell_ex].fetch_funding_rate(token).get('fundingRate', 0)) * 100
                                except:
                                    pass

                                if abs(fr_buy) > MAX_FUNDING_RATE_PERCENT or abs(fr_sell) > MAX_FUNDING_RATE_PERCENT:
                                    continue
                                
                                net_fr_cost = fr_buy - fr_sell
                                net_diff = raw_diff - net_fr_cost
                                
                                if net_diff >= ARBITRAGE_PERCENT and net_diff > best_net_diff:
                                    best_net_diff = net_diff
                                    best_op = {
                                        'token': token, 
                                        'buy_ex': buy_ex, 'buy_p': buy_p, 'buy_url': get_exchange_url(buy_ex, token), 'fr_buy': fr_buy,
                                        'sell_ex': sell_ex, 'sell_p': sell_p, 'sell_url': get_exchange_url(sell_ex, token), 'fr_sell': fr_sell,
                                        'raw_diff': raw_diff, 'net_diff': net_diff, 
                                        'tp_price': (buy_p + sell_p) / 2, 'time': current_time
                                    }
                
                if best_op:
                    temp_web_data.append(best_op)

            # Cədvəli ən yüksək xalis qazanca görə sıralayırıq
            temp_web_data.sort(key=lambda x: x['net_diff'], reverse=True)
            live_arbitrage_data = temp_web_data

        except: 
            pass
            
        time.sleep(5)

# === FLASK VEBSAYT YOLLARI ===
@app.route('/')
def index(): 
    return render_template('index.html')

@app.route('/api/data')
def get_data(): 
    return jsonify(live_arbitrage_data)

# Skaneri və Başlanğıc mesajını arxa planda işə salırıq
threading.Thread(target=send_startup_message, daemon=True).start()
threading.Thread(target=run_scanner, daemon=True).start()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)