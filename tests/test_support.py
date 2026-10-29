"""Explicit synthetic fixtures; production startup has no seeded characters or groups."""
from dashboard import SnapshotCache
from groups import Groups

PARTY=('Aster','Bran','Cora','Dena','Eryn','Fenn')


def seeded_groups(path=None):
    groups=Groups(path)
    if not groups.data['groups']:
        groups.data={'selected':'band','groups':[{'id':'band','name':'The Band','members':list(PARTY)}]}
    return groups


def fixture_cache(*args,**kwargs):
    kwargs.setdefault('bots',('Galen',))
    cache=SnapshotCache(*args,**kwargs)
    cache.groups=seeded_groups(kwargs.get('groups_file'))
    return cache
