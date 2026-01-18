# main.py
import time
from binance_client import BinanceFuturesClient
from config import *
from typing import Dict
# Глобальное состояние для отслеживания усреднений (symbol -> {entry_price, total_qty, level})
averaging_state: Dict[str, Dict] = {}

def main():
    print("=== SHORT BOT with AVERAGING (no SL) ===")
    print(f"Real: {REAL_ACCOUNT} | Lev: x{LEVERAGE} | Pos: {POSITION_SIZE*100}%")
    print(f"Avg: {USE_AVERAGING} ({AVG_LEVELS} levels, drop {AVG_DROP_PERCENT}%) | TP: {TP_PERCENT}%")

    try:
        client = BinanceFuturesClient(testnet=False)
    except Exception as e:
        print(f"[FATAL] Init failed: {e}")
        return

    balance = client.get_balance_usdt()
    print(f"[INFO] USDT Balance: {balance:.2f}")

    if balance <= 0:
        print("[ERROR] Zero balance")
        return

    symbols = client.get_usdt_perpetual_symbols()
    print(f"[INFO] {len(symbols)} symbols loaded")

    while True:
        print(f"\n--- Scan {time.strftime('%H:%M:%S')} ---")

        balance = client.get_balance_usdt()
        open_pos = client.get_open_positions()

        if len(open_pos) >= MAX_OPEN_TRADES:
            print("Max positions → skip")
            time.sleep(CHECK_INTERVAL)
            continue

        # 1. Проверяем существующие позиции на усреднение
        for pos in open_pos:
            symbol = pos["symbol"]
            if float(pos["positionAmt"]) >= 0:  # только шорты
                continue

            state = averaging_state.get(symbol, {})
            if not state:
                # Если состояния нет — это новая позиция (возможно, открытая вручную)
                entry_price = float(pos["entryPrice"])
                total_qty = abs(float(pos["positionAmt"]))
                averaging_state[symbol] = {
                    "entry_price": entry_price,
                    "total_qty": total_qty,
                    "level": 1
                }
                print(f"[STATE] Restored {symbol} entry={entry_price}, qty={total_qty}")
                continue

            current_price = client.get_current_price(symbol)
            if current_price <= 0:
                continue

            drop_pct = (current_price - state["entry_price"]) / state["entry_price"] * 100

            if state["level"] < AVG_LEVELS and drop_pct >= AVG_DROP_PERCENT:
                print(f"[AVG] {symbol} +{drop_pct:.2f}% → level {state['level']+1}")

                new_qty = (balance * POSITION_SIZE * AVG_MULTIPLIER) / current_price
                new_qty = round(new_qty, client.get_qty_precision(symbol))

                if REAL_ACCOUNT:
                    client.open_short_market(symbol, new_qty)
                    # Обновляем состояние
                    new_total_qty = state["total_qty"] + new_qty
                    new_avg_price = ((state["entry_price"] * state["total_qty"]) + (current_price * new_qty)) / new_total_qty
                    state["entry_price"] = new_avg_price
                    state["total_qty"] = new_total_qty
                    state["level"] += 1

                    # Переставляем TP
                    client.cancel_all_open_orders(symbol)
                    tp_price = new_avg_price * (1 - TP_PERCENT / 100)
                    client.place_take_profit_market(symbol, new_total_qty, tp_price)
                else:
                    print(f"[TEST] Would avg {symbol} qty={new_qty} @ {current_price:.2f}")

        # 2. Открытие новых позиций
        for symbol in symbols:
            if any(p["symbol"] == symbol and float(p["positionAmt"]) < 0 for p in open_pos):
                continue  # уже в позиции

            pump_found = False
            for tf in TIMEFRAMES:
                kl = client.get_klines(symbol, tf, limit=3)
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

            oi_growth = client.get_oi_growth(symbol)
            print(f"[OI] {symbol}: {oi_growth*100:.2f}%")

            if oi_growth < MIN_OI_GROWTH:
                continue

            print(f"[TRADE] {symbol} → SHORT")

            if not client.set_leverage(symbol, LEVERAGE):
                continue

            price = client.get_current_price(symbol)
            if price <= 0:
                continue

            qty = (balance * POSITION_SIZE) / price
            qty = round(qty, client.get_qty_precision(symbol))

            if REAL_ACCOUNT:
                client.open_short_market(symbol, qty)

                # Сохраняем начальное состояние
                averaging_state[symbol] = {
                    "entry_price": price,
                    "total_qty": qty,
                    "level": 1
                }

                # Ставим начальный TP
                tp_price = price * (1 - TP_PERCENT / 100)
                client.place_take_profit_market(symbol, qty, tp_price)
            else:
                tp_price = price * (1 - TP_PERCENT / 100)
                print(f"[TEST] SHORT {symbol} qty={qty} @ {price:.2f}")
                print(f"      TP @ {tp_price:.4f}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()