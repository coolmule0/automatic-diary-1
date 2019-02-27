import io
import itertools
import logging
import os
import subprocess
import sys
from functools import partial
from pathlib import Path
from typing import Iterable, Iterator, List

import caldav

from automatic_journal.common import Item, chain
from automatic_journal.providers.icalendar.main import parse_calendar

logger = logging.getLogger(__name__)


def lookup_secret(key: str, val: str) -> str:
    completed_process = subprocess.run(
        ['secret-tool', 'lookup', key, val],
        stdout=subprocess.PIPE,
        check=True,
        universal_newlines=True,  # Don't use arg 'text' for Python 3.6 compat.
    )
    return completed_process.stdout


def load_config(config_json: dict) -> dict:
    try:
        url = config_json['caldav']['url']
        username = config_json['caldav']['username']
        password_key = config_json['caldav']['password_key']
        password_val = config_json['caldav']['password_val']
        cache_dir = config_json['caldav']['cache_dir']
    except (KeyError, TypeError):
        logger.error('Invalid config')
        sys.exit(1)
    password = lookup_secret(password_key, password_val)
    return {
        'url': url,
        'username': username,
        'password': password,
        'cache_dir': cache_dir,
    }


def read_events_data_from_cache(
    cache_dir: Path, no_cache: bool
) -> Iterator[str]:
    if no_cache:
        return
    if cache_dir.is_dir():
        logger.info(f'Reading cache {cache_dir}')
        for cache_file in os.scandir(cache_dir):
            if cache_file.is_file():
                yield Path(cache_file.path).read_text()


def write_events_to_cache(events: Iterator[caldav.Event], cache_dir: Path):
    logger.info(f'Writing cache {cache_dir}')
    cache_dir.mkdir(parents=True, exist_ok=True)
    for event in events:
        _, event_id = event.url.rsplit('/', maxsplit=1)
        cache_file = cache_dir / event_id
        if cache_file.exists():
            raise Exception(f'Cache file {cache_file} already exists')
        cache_file.write_text(event.data)


def download_events(config: dict, no_cache: bool) -> List[str]:
    url = config['url']
    username = config['username']
    password = config['password']
    cache_dir = Path(config['cache_dir'])
    events_data = list(read_events_data_from_cache(cache_dir, no_cache))
    if events_data:
        return events_data
    logger.info('Connecting to %s', url)
    client = caldav.DAVClient(url, username=username, password=password)
    logger.info('Reading principal')
    principal = client.principal()
    events = itertools.chain(
        calendar.events() for calendar in principal.calendars()
    )
    write_events_to_cache(events, cache_dir)
    return [event.data for event in events]


def parse_events(
    events_data: Iterable[str], subprovider: str
) -> Iterator[Item]:
    for event_data in events_data:
        lines = io.StringIO(event_data)
        for event in parse_calendar(lines):
            yield Item(
                dt=event.one_date, text=event.name, subprovider=subprovider
            )


def main(config_json: dict, no_cache: bool, *args, **kwargs) -> Iterator[Item]:
    config = load_config(config_json)
    return chain(
        partial(download_events, no_cache=no_cache),
        partial(parse_events, subprovider=config['url']),
    )(config)
