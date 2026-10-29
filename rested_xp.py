"""Read-only rested coverage, matching AzerothCore's internal half-coverage pool."""
from connection import env
import math
import os


def setting(name, default):
    value = float(env(name, default))
    if not math.isfinite(value) or value < 0:
        raise ValueError('Invalid rested XP configuration: ' + name)
    return value


def rested_view(character):
    max_level = setting('MAX_PLAYER_LEVEL', 80)
    if character['level'] >= max_level:
        return {'state': 'max_level'}
    required = character.get('next_level_xp')
    bonus = character.get('rest_bonus')
    if (not isinstance(required, (int, float)) or not math.isfinite(required) or required <= 0
            or not isinstance(bonus, (int, float)) or not math.isfinite(bonus) or bonus < 0):
        return {'state': 'unavailable'}
    multiplier = setting('REST_MAX_BONUS', 1.5)
    cap = required * multiplier / 2
    estimated = not bool(character['online'])
    if estimated:
        saved_at = character.get('logout_time')
        observed_at = character.get('rest_observed_at')
        if not saved_at or not observed_at:
            return {'state': 'unavailable'}
        tavern = bool(character.get('is_logout_resting'))
        rate = setting('REST_OFFLINE_IN_TAVERN_OR_CITY' if tavern else 'REST_OFFLINE_IN_WILDERNESS', 1)
        bubble = 0.125 if tavern else 0.031
        bonus += max(0, observed_at - saved_at) * required / 144000 * bubble * rate
    bonus = min(bonus, cap)
    return {'state': 'available', 'estimated': estimated,
            'bonus_xp': int(bonus), 'coverage_xp': int(bonus * 2),
            'level_percent': bonus * 200 / required, 'cap_percent': multiplier * 100,
            'cap_full_percent': bonus * 100 / cap if cap else 100,
            'remaining_percent': max(0, (cap - bonus) * 200 / required)}
