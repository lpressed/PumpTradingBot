# binance_client.py
import os
import math
from typing import List, Dict, Optional, Tuple

from binance.client import Client
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv

load_dotenv()


class BinanceFuturesClient:
    def __init__(self, testnet: bool = False):
        api_key = os.getenv("BINANCE_API_KEY")
        api_secret = os.getenv("BINANCE_API_SECRET")

        if not api_key or not api_secret:
            raise ValueError("BINANCE_API_KEY or BINANCE_API_SECRET not set")

        self.client = Client(
            api_key=api_key,
            api_secret=api_secret,
            testnet=testnet,
            requests_params={"timeout": 15},
        )

        if not self.test_connection():
            raise ConnectionError("Failed to connect to Binance Futures API")

    def test_connection(self) -> bool:
        try:
            return self.client.futures_ping() == {}
        except Exception as e:
            print(f"[CONN ERROR] {e}")
            return False

    def get_balance_usdt(self) -> float:
        try:
            account = self.client.futures_account()
            for asset in account["assets"]:
                if asset["asset"] == "USDT":
                    return float(asset["walletBalance"])
            return 0.0
        except Exception as e:
            print(f"[ERROR] Balance: {e}")
            return 0.0

    def get_open_positions(self) -> List[Dict]:
        try:
            positions = self.client.futures_position_information()
            return [p for p in positions if float(p["positionAmt"]) != 0]
        except Exception as e:
            print(f"[ERROR] Positions: {e}")
            return []

    def get_position_by_symbol(self, symbol: str) -> Dict:
        try:
            pos = self.client.futures_position_information(symbol=symbol)
            return pos[0] if pos else {}
        except Exception:
            return {}

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            print(f"[OK] Leverage x{leverage} set for {symbol}")
            return True
        except Exception as e:
            print(f"[ERROR] Leverage {symbol}: {e}")
            return False

    def get_usdt_perpetual_symbols(self) -> List[str]:
        try:
            info = self.client.futures_exchange_info()
            return [
                s["symbol"] for s in info["symbols"]
                if s["contractType"] == "PERPETUAL"
                and s["quoteAsset"] == "USDT"
                and s["status"] == "TRADING"
            ]
        except Exception as e:
            print(f"[ERROR] Symbols: {e}")
            return []

    def get_klines(self, symbol: str, interval: str, limit: int = 3) -> List:
        try:
            return self.client.futures_klines(symbol=symbol, interval=interval, limit=limit)
        except Exception as e:
            print(f"[ERROR] Klines {symbol}: {e}")
            return []

    def get_current_price(self, symbol: str) -> float:
        try:
            return float(self.client.futures_symbol_ticker(symbol=symbol)["price"])
        except Exception as e:
            print(f"[ERROR] Price {symbol}: {e}")
            return 0.0

    def get_oi_growth(self, symbol: str, period: str = "5m", limit: int = 2) -> float:
        try:
            hist = self.client.futures_open_interest_hist(symbol=symbol, period=period, limit=limit)
            if len(hist) < 2:
                return 0.0
            prev = float(hist[-2]["sumOpenInterest"])
            curr = float(hist[-1]["sumOpenInterest"])
            return (curr - prev) / prev if prev > 0 else 0.0
        except Exception as e:
            print(f"[ERROR] OI {symbol}: {e}")
            return 0.0

    def get_qty_precision(self, symbol: str) -> int:
        try:
            info = self.client.futures_exchange_info()
            for s in info["symbols"]:
                if s["symbol"] == symbol:
                    for f in s["filters"]:
                        if f["filterType"] == "LOT_SIZE":
                            step = float(f["stepSize"])
                            return 0 if step >= 1 else int(-math.log10(step))
            return 3
        except Exception:
            return 3

    def get_price_precision(self, symbol: str) -> int:
        try:
            info = self.client.futures_exchange_info()
            for s in info["symbols"]:
                if s["symbol"] == symbol:
                    for f in s["filters"]:
                        if f["filterType"] == "PRICE_FILTER":
                            tick = float(f["tickSize"])
                            return 0 if tick >= 1 else int(-math.log10(tick))
            return 2
        except Exception:
            return 2

    def open_short_market(self, symbol: str, quantity: float) -> Optional[Dict]:
        try:
            qty = round(quantity, self.get_qty_precision(symbol))
            if qty <= 0:
                return None
            order = self.client.futures_create_order(
                symbol=symbol,
                side="SELL",
                type="MARKET",
                quantity=qty
            )
            print(f"[ENTRY OK] SHORT {symbol} qty={qty}")
            return order
        except Exception as e:
            print(f"[ENTRY ERROR] {symbol}: {e}")
            return None

    def place_take_profit_market(self, symbol: str, quantity: float, stop_price: float) -> Optional[Dict]:
        try:
            qty = round(quantity, self.get_qty_precision(symbol))
            stop_price = round(stop_price, self.get_price_precision(symbol))
            order = self.client.futures_create_order(
                symbol=symbol,
                side="BUY",
                type="TAKE_PROFIT_MARKET",
                stopPrice=stop_price,
                quantity=qty,
                reduceOnly=True,
                timeInForce="GTC"
            )
            print(f"[TP OK] {symbol} TP @ {stop_price}")
            return order
        except Exception as e:
            print(f"[TP ERROR] {symbol}: {e}")
            return None

    def cancel_all_open_orders(self, symbol: str) -> None:
        try:
            self.client.futures_cancel_all_open_orders(symbol=symbol)
            print(f"[OK] All open orders canceled for {symbol}")
        except Exception as e:
            print(f"[CANCEL ERROR] {symbol}: {e}")