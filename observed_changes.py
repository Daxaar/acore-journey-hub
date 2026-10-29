"""Compare observed data, without claiming to know a database save/event timestamp."""
import hashlib
import json


class ObservedChanges:
    def __init__(self):
        self.states = {}

    def observe(self, key, value, observed_at):
        fingerprint = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        previous = self.states.get(key)
        started = previous[1] if previous else observed_at
        changed = previous[2] if previous else None
        if previous and fingerprint != previous[0]:
            changed = observed_at
        if key not in self.states and len(self.states) >= 128:
            self.states.pop(next(iter(self.states)))
        self.states[key] = (fingerprint, started, changed)
        return {'monitoring_since': started, 'last_observed_change_at': changed}
