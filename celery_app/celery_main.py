# This module contains the main Celery app

import datetime
from celery import Celery
from common.config.constants import DEFAULT_DATETIME_STR_QUERY
from common.helpers.datetimehelpers import datetime_to_str
from fetchers.rest.bitfinex import BitfinexOHLCVFetcher
from fetchers.rest.binance import BinanceOHLCVFetcher


app = Celery('Celery Coin App')
app.config_from_object('celery_app.celery_config')

bitfinex_fetcher = BitfinexOHLCVFetcher()
binance_fetcher = BinanceOHLCVFetcher()

# Periodic OHLCV update
app.conf.beat_schedule = {
    'bitfinex_ohlcv_1min': {
        'task': "celery_app.celery_tasks.bitfinex_fetch_ohlcvs_mutual_basequote_1min",
        'schedule': 100.0
    },
    'binance_ohlcv_1min': {
        'task': "celery_app.celery_tasks.binance_fetch_ohlcvs_mutual_basequote_1min",
        'schedule': 60.0
    }
}