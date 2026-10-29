"""Dashboard-only named groups; no game database writes."""
import json
import re
import uuid

def validate_group(name, members):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or any(ord(c) < 32 for c in name):
        raise ValueError('Choose a group name of 1–60 characters.')
    if not isinstance(members, list) or not 1 <= len(members) <= 6:
        raise ValueError('Choose between 1 and 6 characters.')
    normalized = []
    for member in members:
        if not isinstance(member, str) or not re.fullmatch(r'[A-Za-z]{2,12}', member.strip()):
            raise ValueError('Each character name must contain 2–12 letters.')
        member = member.strip().capitalize()
        if member in normalized:
            raise ValueError('Each character can appear only once in a group.')
        normalized.append(member)
    return {'name': name.strip(), 'members': normalized}


class Groups:
    # The owning snapshot cache serializes reads and writes with its lock.
    def __init__(self, path=None):
        self.path = path
        self.data = {'selected': None, 'groups': []}
        if path and path.exists():
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or not isinstance(data.get('groups'), list) or not 0 <= len(data['groups']) <= 32:
                raise ValueError('Invalid groups.json; restore a valid group configuration.')
            ids = set()
            for group in data['groups']:
                if not isinstance(group, dict) or not isinstance(group.get('id'), str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,40}', group['id']) or group['id'] in ids:
                    raise ValueError('Invalid group identifier in groups.json.')
                ids.add(group['id'])
                group.update(validate_group(group.get('name'), group.get('members')))
            if data.get('selected') not in ids and (data['groups'] or data.get('selected') is not None):
                raise ValueError('Invalid selected group in groups.json.')
            self.data = data

    def update(self, payload):
        data = json.loads(json.dumps(self.data))
        action = payload.get('action')
        group = next((g for g in data['groups'] if g['id'] == payload.get('id')), None)
        if action == 'create':
            if len(data['groups']) >= 32:
                raise ValueError('You can save up to 32 groups.')
            group = {'id': uuid.uuid4().hex, **validate_group(payload.get('name'), payload.get('members'))}
            data['groups'].append(group)
            data['selected'] = group['id']
        elif action in ('select', 'edit', 'delete'):
            if group is None:
                raise ValueError('That group no longer exists. Reload the dashboard.')
            if action == 'select':
                data['selected'] = group['id']
            elif action == 'edit':
                group.update(validate_group(payload.get('name'), payload.get('members')))
            else:
                if len(data['groups']) == 1:
                    raise ValueError('Keep at least one group.')
                data['groups'].remove(group)
                if data['selected'] == group['id']:
                    data['selected'] = data['groups'][0]['id']
        else:
            raise ValueError('Choose a supported group action.')
        if len({g['name'].casefold() for g in data['groups']}) != len(data['groups']):
            raise ValueError('Choose a unique group name.')
        if self.path:
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(data, ensure_ascii=False) + '\n')
            temporary.chmod(0o600)
            temporary.replace(self.path)
        self.data = data
        return data

    def selected(self):
        return next((g for g in self.data['groups'] if g['id'] == self.data['selected']), None)
