### This module uses websocket to fetch binance 1-minute OHLCV data in real time


import sys
import random
import logging
import asyncio
import json
import redis
import websockets
from typing import Iterable
from common.config.constants import (
    REDIS_HOST, REDIS_PASSWORD, REDIS_DELIMITER
)
from fetchers.config.constants import (
    WS_SUB_REDIS_KEY, WS_SERVE_REDIS_KEY, WS_SUB_LIST_REDIS_KEY
)
from fetchers.rest.binance import BinanceOHLCVFetcher, EXCHANGE_NAME
from fetchers.utils.exceptions import UnsuccessfulConnection, ConnectionClosedOK


# Binance only allows up to 1024 subscriptions per ws connection
#   However, so far only a max value of 200 works...
URI = "wss://stream.binance.com:9443/ws"
MAX_SUB_PER_CONN = 200

class BinanceOHLCVWebsocket:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            username="default",
            password=REDIS_PASSWORD,
            decode_responses=True
        )
        self.ws_msg_ids = {
            "subscribe": 1
        }

        # Rest fetcher for convenience
        self.rest_fetcher = BinanceOHLCVFetcher()

        # Logging
        self.logger = logging.getLogger(f'{EXCHANGE_NAME}_websocket')
        self.logger.setLevel(logging.INFO)
        log_handler = logging.StreamHandler()
        log_handler.setLevel(logging.INFO)
        log_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        log_handler.setFormatter(log_formatter)
        self.logger.addHandler(log_handler)
    
    async def subscribe(self, symbols: Iterable, i: int = 0):
        '''
        Subscribes to Binance WS for `symbols`

        :params:
            `symbols`: list of symbols (not tsymbol)
                e.g., [ETHBTC]
        '''

        while True:
            try:
                # Delay before making a connection
                await asyncio.sleep(5 + random.random() * 5)
                async with websockets.connect(URI) as ws:
                    # Binance requires WS symbols to be lowercase
                    params = [
                        f'{symbol.lower()}@kline_1m'
                        for symbol in symbols
                    ]
                    await ws.send(json.dumps(
                        {
                            "method": "SUBSCRIBE",
                            "params": params,
                            "id": i
                        })
                    )
                    self.logger.info(f"Connection {i}: Successful")
                    while True:
                        resp = await ws.recv()
                        respj = json.loads(resp)
                        try:
                            if isinstance(respj, dict):
                                if 'result' in respj:
                                    if respj['result'] is not None:
                                        raise UnsuccessfulConnection
                                else:
                                    # self.logger.info(f"Response: {respj}")
                                    symbol = respj['s']
                                    timestamp = int(respj['k']['t'])
                                    open_ = respj['k']['o']
                                    high_ = respj['k']['h']
                                    low_ = respj['k']['l']
                                    close_ = respj['k']['c']
                                    volume_ = respj['k']['v']
                                    sub_val = f'{timestamp}{REDIS_DELIMITER}{open_}{REDIS_DELIMITER}{high_}{REDIS_DELIMITER}{low_}{REDIS_DELIMITER}{close_}{REDIS_DELIMITER}{volume_}'

                                    # Setting Redis data for updating ohlcv psql db
                                    #   and serving real-time chart
                                    # This Redis-update-ohlcv-psql-db-procedure
                                    #   may be changed with a pipeline from fastAPI...
                                    base_id = self.rest_fetcher.symbol_data[symbol]['base_id']
                                    quote_id = self.rest_fetcher.symbol_data[symbol]['quote_id']
                                    ws_sub_redis_key = WS_SUB_REDIS_KEY.format(
                                        exchange = EXCHANGE_NAME,
                                        delimiter = REDIS_DELIMITER,
                                        base_id = base_id,
                                        quote_id = quote_id
                                    )
                                    ws_serve_redis_key = WS_SERVE_REDIS_KEY.format(
                                        exchange = EXCHANGE_NAME,
                                        delimiter = REDIS_DELIMITER,
                                        base_id = base_id,
                                        quote_id = quote_id
                                    )

                                    # print(f'ws sub redis key: {ws_sub_redis_key}')
                                    # print(f'ws serve redis key: {ws_serve_redis_key}')

                                    # Add ws sub key to set of all ws sub keys
                                    # Set hash value for ws sub key
                                    self.redis_client.sadd(
                                        WS_SUB_LIST_REDIS_KEY, ws_sub_redis_key)
                                    self.redis_client.hset(
                                        ws_sub_redis_key, timestamp, sub_val)
                                    current_timestamp = self.redis_client.hget(
                                        ws_serve_redis_key, 'time')
                                    if current_timestamp is None or \
                                        timestamp >= int(current_timestamp):
                                        self.redis_client.hset(
                                            ws_serve_redis_key,
                                            mapping = {
                                                'time': timestamp,
                                                'open': open_,
                                                'high': high_,
                                                'low': low_,
                                                'close': close_,
                                                'volume': volume_
                                            }
                                        )
                        except Exception as exc:
                            self.logger.warning(f"EXCEPTION: {exc}")
                        await asyncio.sleep(0.01)
            except ConnectionClosedOK:
                pass
            except Exception as exc:
                raise Exception(exc)

    async def mutual_basequote(self):
        symbols_dict = self.rest_fetcher.get_mutual_basequote()
        self.rest_fetcher.close_connections()
        # symbols_dict = ["ETHBTC", "BTCEUR"]
        await asyncio.gather(self.subscribe(symbols_dict.keys()))

    async def all(self):
        '''
        Subscribes to WS channels of all symbols
        '''

        self.rest_fetcher.fetch_symbol_data()
        symbols =  tuple(self.rest_fetcher.symbol_data.keys())

        # Subscribe to `MAX_SUB_PER_CONN` per connection (e.g., 1024)
        await asyncio.gather(
            *(self.subscribe(symbols[i:i+MAX_SUB_PER_CONN], i)
                for i in range(0, len(symbols), MAX_SUB_PER_CONN)))
    
    def run_mutual_basequote(self):
        asyncio.run(self.mutual_basequote())

    def run_all(self):
        asyncio.run(self.all())


if __name__ == "__main__":
    run_cmd = sys.argv[1]
    ws_binance = BinanceOHLCVWebsocket()
    if getattr(ws_binance, run_cmd):
        getattr(ws_binance, run_cmd)()
