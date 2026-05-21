#!/usr/bin/env python3
import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.filterwarnings('ignore')

from quantforge import setup_logging
from paper_trading.engine import PaperTradingEngine, LOG_PATH
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logger = setup_logging(logging.INFO, log_file=LOG_PATH)
from paper_trading.serve import serve
import threading, time, json, pickle, signal as sigmod

REFRESH_INTERVAL = 1800
_shutdown = threading.Event()


def _signal_handler(signum, frame):
    _shutdown.set()


def main():
    sigmod.signal(sigmod.SIGTERM, _signal_handler)
    sigmod.signal(sigmod.SIGINT, _signal_handler)

    engine = PaperTradingEngine()

    any_new = False
    for name, asset in engine.assets.items():
        if _shutdown.is_set():
            return
        if os.path.exists(asset.model_path):
            with open(asset.model_path, 'rb') as f:
                asset.model = pickle.load(f)
                asset._trained = True
            logger.info('%s: loaded cached model', name)
        else:
            logger.info('%s: training new model...', name)
            asset.train(force=True)
            any_new = True

    if not _shutdown.is_set():
        logger.info('Pulling live data from yfinance...')
        results = engine.run_once()
        engine.save_state()
        for name, r in results.items():
            if name == 'satellite':
                continue
            if 'error' in r:
                logger.error('%s: ERROR - %s', name, r['error'])
            else:
                logger.info('%s: %s  conf=%s%%  @ $%s', name, r['signal'], r['confidence'], r['close_price'])
        p = engine.get_state()['portfolio']
        logger.info('Portfolio: $%.2f (%s%%)', p['total_value'], p['total_return'])

    logger.info('Starting dashboard server...')

    server_thread = threading.Thread(target=serve, args=(5000, _shutdown), daemon=True)
    server_thread.start()
    time.sleep(1)
    logger.info('State API: http://127.0.0.1:5000/state.json')
    logger.info('Signals refresh every %d minutes from live yfinance data.', REFRESH_INTERVAL // 60)
    logger.info('Press Ctrl+C to stop.')

    while not _shutdown.is_set():
        interrupted = _shutdown.wait(REFRESH_INTERVAL)
        if interrupted:
            break
        logger.info('Refreshing signals...')
        try:
            engine.run_once()
            engine.save_state()
            logger.info('Done.')
        except Exception as e:
            logger.error('Error: %s', e)

    try:
        engine.save_state()
        logger.info('State saved on shutdown.')
    except Exception as e:
        logger.error('Failed to save state on shutdown: %s', e)
    server_thread.join(timeout=3)
    logger.info('Server stopped.')


if __name__ == '__main__':
    main()
