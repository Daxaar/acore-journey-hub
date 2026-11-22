"""Optional, explicitly configured administrator access to guild_tax.conf."""
import hmac
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from threading import Lock

LOCK = Lock()
RATES = re.compile(r'(?m)^[ \t]*GuildTax\.Rates[ \t]*=[ \t]*"([^"\r\n]*)"[ \t]*$')


def setting(name, field):
    value = os.environ.get(name)
    if value:
        return value
    private = Path(__file__).with_name('.guild-tax-admin.json')
    if private.is_file():
        return json.loads(private.read_text()).get(field)
    return None


def config_path():
    value = setting('JOURNEY_HUB_GUILD_TAX_CONFIG', 'config')
    return Path(value) if value else None


def parse(raw):
    matches = list(RATES.finditer(raw))
    if len(matches) != 1:
        raise ValueError('Expected one quoted GuildTax.Rates setting.')
    rates = {}
    for pair in matches[0][1].split(',') if matches[0][1].strip() else ():
        if not re.fullmatch(r'\s*[1-9][0-9]*\s*:\s*[0-9]{1,3}\s*', pair):
            raise ValueError('The saved guild rate list is invalid.')
        guild, rate = map(int, pair.split(':'))
        if guild > 4294967295 or rate > 100 or guild in rates:
            raise ValueError('The saved guild rate list is invalid.')
        rates[guild] = rate
    return rates


def saved_rates():
    path = config_path()
    return parse(path.read_text()) if path else None


def save_rates(payload, current_guilds):
    path = config_path()
    key_path = setting('JOURNEY_HUB_GUILD_TAX_ADMIN_KEY_FILE', 'key_file')
    if not path or not key_path:
        raise PermissionError('Guild tax editing is disabled.')
    key = Path(key_path).read_bytes().strip()
    entered = payload.get('key')
    if len(key) < 24 or not isinstance(entered, str) or not hmac.compare_digest(entered.encode(), key):
        raise PermissionError('Guild tax admin key was not accepted.')
    changes = payload.get('rates')
    if set(payload) != {'rates', 'key'} or not isinstance(changes, list) or not 1 <= len(changes) <= 1000:
        raise ValueError('Provide up to 1000 guild rates.')
    batch = {}
    for change in changes:
        if not isinstance(change, dict) or set(change) != {'guild', 'rate'}:
            raise ValueError('Provide a guild and a whole percentage.')
        guild, rate = change['guild'], change['rate']
        if type(guild) is not int or type(rate) is not int or not 0 < guild <= 4294967295 or not 0 <= rate <= 100 or guild in batch:
            raise ValueError('Each guild requires a unique rate from 0 to 100.')
        batch[guild] = rate
    if batch.keys() - current_guilds():
        raise ValueError('One or more guilds no longer exist.')
    with LOCK:
        raw = path.read_text()
        rates = parse(raw)
        for guild, rate in batch.items():
            if rate:
                rates[guild] = rate
            else:
                rates.pop(guild, None)
        value = ','.join(f'{gid}:{pct}' for gid, pct in sorted(rates.items()))
        updated = RATES.sub(lambda _: f'GuildTax.Rates = "{value}"', raw)
        if updated != raw:
            temp = None
            try:
                with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as output:
                    temp = Path(output.name)
                    output.write(updated)
                    output.flush()
                    os.fsync(output.fileno())
                temp.chmod(path.stat().st_mode & 0o777)
                temp.replace(path)
            finally:
                if temp is not None:
                    temp.unlink(missing_ok=True)
    return len(batch)
