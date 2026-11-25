"""Hourly market collection and opt-in local price publishing."""
import argparse
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sqlite3
import time

from anniversary_market import collect_anniversary
from market_analytics import sample_analytics
from market_history import DEFAULT_ITEMS, collect, data_root
from market_local_history import sample
from market_policy import generate
from mysql_access import DatabaseError


def cycle(config, root, log):
    try:
        stamp, count = collect(root)
        log.info('Snapshot %s with %s new observations', stamp, count)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        log.warning('Collection failed: %s', error)
    try:
        collect_anniversary(root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        log.warning('Anniversary archive failed: %s', error)
    try:
        sample()
    except (OSError, ValueError, DatabaseError, sqlite3.Error) as error:
        log.warning('Local sample failed: %s', error)
    try:
        policy = json.loads(config.read_text())
        mode = policy['mode']
        if mode == 'disabled':
            return
        if mode not in ('live','historical') or type(policy['freshness_hours']) is not int or not 1 <= policy['freshness_hours'] <= 24:
            raise ValueError('Invalid publishing policy.')
        output = Path(policy['output']).expanduser()
        allowed = DEFAULT_ITEMS if policy.get('pilot', True) else None
        result = generate(mode, output, policy['freshness_hours'], allowed_items=allowed)
        log.info('Publisher status: %s', {key:value for key,value in result.items() if key!='anniversary_ids'})
        try:
            snapshot = sample_analytics(output, policy.get('bot_ids', []))
            if snapshot:
                log.info('Auction coverage sample: %s', snapshot)
        except (OSError, ValueError, KeyError, DatabaseError, sqlite3.Error) as error:
            log.warning('Auction coverage sampling failed: %s', error)
    except (OSError, ValueError, KeyError, TypeError, DatabaseError, sqlite3.Error) as error:
        log.warning('Publishing failed; previous price file retained: %s', error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', required=True, type=Path)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    root = data_root().resolve()
    root.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('market-worker')
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(root/'collector.log', maxBytes=262144, backupCount=2)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
    with (root/'collector.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, 'Another collector is running.\n')
        while True:
            cycle(args.policy, root, logger)
            if args.once:
                return
            time.sleep(3600)


if __name__ == '__main__':
    main()
