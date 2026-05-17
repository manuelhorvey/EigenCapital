#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.filterwarnings('ignore')

from paper_trading.engine import PaperTradingEngine
from paper_trading.serve import serve
import threading, time, json, pickle, signal as sigmod

REFRESH_INTERVAL = 1800  # 30 minutes
_shutdown = threading.Event()


def _signal_handler(signum, frame):
    _shutdown.set()


def main():
    sigmod.signal(sigmod.SIGTERM, _signal_handler)
    sigmod.signal(sigmod.SIGINT, _signal_handler)

    engine = PaperTradingEngine()

    # Load or train models
    any_new = False
    for name, asset in engine.assets.items():
        if _shutdown.is_set():
            return
        if os.path.exists(asset.model_path):
            with open(asset.model_path, 'rb') as f:
                asset.model = pickle.load(f)
                asset._trained = True
            print(f'  {name}: loaded cached model')
        else:
            print(f'  {name}: training new model...')
            asset.train(force=True)
            any_new = True

    print()
    if not _shutdown.is_set():
        print('Pulling live data from yfinance...')
        results = engine.run_once()
        engine.save_state()
        for name, r in results.items():
            if 'error' in r:
                print(f'  {name}: ERROR - {r["error"]}')
            else:
                print(f'  {name}: {r["signal"]}  conf={r["confidence"]}%  @ ${r["close_price"]}')
        p = engine.get_state()['portfolio']
        print(f'  Portfolio: ${p["total_value"]:,.2f}  ({p["total_return"]}%)')

    print()
    print('Starting dashboard server...')

    # Start HTTP server in background thread
    server_thread = threading.Thread(target=serve, args=(5000, _shutdown), daemon=True)
    server_thread.start()
    time.sleep(1)
    print(f'  State API: http://127.0.0.1:5000/state.json')
    print()
    print(f'Signals refresh every {REFRESH_INTERVAL//60} minutes from live yfinance data.')
    print('Press Ctrl+C to stop.')
    print()

    # Main loop: refresh signals until shutdown
    while not _shutdown.is_set():
        interrupted = _shutdown.wait(REFRESH_INTERVAL)
        if interrupted:
            break
        print(f'[{time.strftime("%H:%M")}] Refreshing signals...')
        try:
            engine.run_once()
            engine.save_state()
            print(f'  Done.')
        except Exception as e:
            print(f'  Error: {e}')

    # Wait for server to cleanly release port
    server_thread.join(timeout=3)
    print()
    print('Server stopped.')


if __name__ == '__main__':
    main()
