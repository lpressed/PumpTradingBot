# paper_trade.py
# Симулятор paper trade для SHORT_ONLY с усреднением и TP/liquidation
# Использует реальные данные с Binance для цен/klines/OI, но трейды — виртуальные (в памяти)
# Логгирует входы, усреднения, закрытия по TP, liquidation

import time
import math
from typing import Dict, List

from binance.client import Client
from dotenv import load_dotenv
import os

load_dotenv()

# Конфиг (аналогично config.py, но встроенный)
TRADE_MODE = "SHORT_ONLY"
INITIAL_BALANCE = 10.0  # USDT для симуляции
LEVERAGE = 10
POSITION_SIZE = 0.05      # 5% от баланса на каждую сделку
MAX_OPEN_TRADES = 3

USE_AVERAGING = True
AVG_LEVELS = 2
AVG_DROP_PERCENT = 5.0
AVG_MULTIPLIER = 1.0

TP_PERCENT = 3.0

PUMP_PERCENT = 8
TIMEFRAMES = ["1m", "3m", "5m", "15m"]
MIN_OI_GROWTH = 0.05

CHECK_INTERVAL = 30  # секунд

# Симулированный аккаунт
class PaperAccount:
    def __init__(self):
        self.balance = INITIAL_BALANCE
        self.positions: Dict[str, Dict] = {}  # symbol -> {entry_price, total_qty, level, avg_price}
        self.log = []  # список логов

    def open_short(self, symbol: str, qty: float, entry_price: float):
        if symbol in self.positions:
            return  # уже есть

        self.positions[symbol] = {
            "entry_price": entry_price,
            "avg_price": entry_price,
            "total_qty": qty,
            "level": 1
        }
        self.log.append(f"[ENTRY] SHORT {symbol} qty={qty:.4f} @ {entry_price:.2f}")

    def average_short(self, symbol: str, new_qty: float, current_price: float):
        pos = self.positions.get(symbol)
        if not pos or pos["level"] >= AVG_LEVELS:
            return

        new_total_qty = pos["total_qty"] + new_qty
        new_avg_price = ((pos["avg_price"] * pos["total_qty"]) + (current_price * new_qty)) / new_total_qty

        pos["avg_price"] = new_avg_price
        pos["total_qty"] = new_total_qty
        pos["level"] += 1

        self.log.append(f"[AVG] {symbol} level={pos['level']} new_qty={new_qty:.4f} @ {current_price:.2f} new_avg={new_avg_price:.2f}")

    def check_tp_liquidation(self, symbol: str, current_price: float):
        pos = self.positions.get(symbol)
        if not pos:
            return

        # TP: цена упала ниже avg_price - TP%
        tp_price = pos["avg_price"] * (1 - TP_PERCENT / 100)
        if current_price <= tp_price:
            pnl = pos["total_qty"] * (pos["avg_price"] - current_price)
            self.balance += pnl
            self.log.append(f"[TP CLOSE] {symbol} @ {current_price:.2f} PNL={pnl:.2f} new_balance={self.balance:.2f}")
            del self.positions[symbol]
            return

        # Liquidation: для шорта, если цена выросла на (1 / leverage) * 100% от avg_price (упрощённо, без fees)
        liq_margin = 1 / LEVERAGE
        liq_price = pos["avg_price"] * (1 + liq_margin)
        if current_price >= liq_price:
            pnl = -pos["total_qty"] * pos["avg_price"] * liq_margin  # полная потеря маржи
            self.balance += pnl
            self.log.append(f"[LIQUIDATION] {symbol} @ {current_price:.2f} PNL={pnl:.2f} (loss) new_balance={self.balance:.2f}")
            del self.positions[symbol]

# Binance клиент для данных (без трейдов)
class DataClient:
    def __init__(self):
        self.client = Client(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_API_SECRET"))

    def get_symbols(self) -> List[str]:
        info = self.client.futures_exchange_info()
        return [s["symbol"] for s in info["symbols"] if s["contractType"] == "PERPETUAL" and s["quoteAsset"] == "USDT" and s["status"] == "TRADING"]

    def get_klines(self, symbol: str, interval: str, limit: int = 3) -> List:
        return self.client.futures_klines(symbol=symbol, interval=interval, limit=limit)

    def get_current_price(self, symbol: str) -> float:
        return float(self.client.futures_symbol_ticker(symbol=symbol)["price"])

    def get_oi_growth(self, symbol: str, period: str = "5m", limit: int = 2) -> float:
        hist = self.client.futures_open_interest_hist(symbol=symbol, period=period, limit=limit)
        if len(hist) < 2:
            return 0.0
        prev = float(hist[-2]["sumOpenInterest"])
        curr = float(hist[-1]["sumOpenInterest"])
        return (curr - prev) / prev if prev > 0 else 0.0

    def get_qty_precision(self, symbol: str) -> int:
        info = self.client.futures_exchange_info()
        for s in info["symbols"]:
            if s["symbol"] == symbol:
                for f in s["filters"]:
                    if f["filterType"] == "LOT_SIZE":
                        step = float(f["stepSize"])
                        return 0 if step >= 1 else int(-math.log10(step))
        return 3

def main():
    print("=== PAPER TRADE SIMULATOR (SHORT with AVG) ===")
    print(f"Initial Balance: {INITIAL_BALANCE:.2f} USDT")

    data_client = DataClient()
    account = PaperAccount()

    symbols = data_client.get_symbols()
    print(f"Loaded {len(symbols)} symbols")

    while True:
        print(f"\n--- Cycle {time.strftime('%H:%M:%S')} ---")
        print(f"Balance: {account.balance:.2f} | Open pos: {len(account.positions)}")

        if len(account.positions) >= MAX_OPEN_TRADES:
            print("Max positions → skip new entries")
        else:
            # Сканирование новых сигналов
            for symbol in symbols:
                if symbol in account.positions:
                    continue

                pump_found = False
                for tf in TIMEFRAMES:
                    kl = data_client.get_klines(symbol, tf, limit=3)
                    if len(kl) < 3:
                        continue
                    close_old = float(kl[0][4])
                    close_now = float(kl[2][4])
                    growth = (close_now - close_old) / close_old if close_old > 0 else 0
                    if growth >= PUMP_PERCENT / 100:
                        print(f"[SIGNAL] {symbol} @{tf} +{growth*100:.2f}%")
                        pump_found = True
                        break

                if not pump_found:
                    continue

                oi_growth = data_client.get_oi_growth(symbol)
                print(f"[OI] {symbol}: {oi_growth*100:.2f}%")

                if oi_growth < MIN_OI_GROWTH:
                    continue

                price = data_client.get_current_price(symbol)
                if price <= 0:
                    continue

                qty = (account.balance * POSITION_SIZE) / price
                qty = round(qty, data_client.get_qty_precision(symbol))

                account.open_short(symbol, qty, price)

                # Начальный TP/liquidation будет проверяться в мониторинге

        # Мониторинг открытых позиций: усреднение, TP, liquidation
        for symbol in list(account.positions.keys()):
            price = data_client.get_current_price(symbol)
            if price <= 0:
                continue

            pos = account.positions[symbol]
            drop_pct = (price - pos["avg_price"]) / pos["avg_price"] * 100  # + для роста цены (против шорта)

            if USE_AVERAGING and pos["level"] < AVG_LEVELS and drop_pct >= AVG_DROP_PERCENT:
                new_qty = (account.balance * POSITION_SIZE * AVG_MULTIPLIER) / price
                new_qty = round(new_qty, data_client.get_qty_precision(symbol))
                account.average_short(symbol, new_qty, price)

            # Проверка TP / Liq
            account.check_tp_liquidation(symbol, price)

        # Вывод свежих логов
        for log in account.log[-5:]:  # последние 5
            print(log)

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()