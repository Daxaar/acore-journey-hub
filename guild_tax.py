"""Read-only contribution and transfer diagnostics for Guild Tax Burden."""

from armory import read_inventory_sql
from guild_tax_config import saved_rates

PERIODS = {
    'today': 'UTC_DATE()',
    '7d': 'UTC_TIMESTAMP() - INTERVAL 7 DAY',
    '30d': 'UTC_TIMESTAMP() - INTERVAL 30 DAY',
    'all': None,
}
ATTEMPTS = 'acore_characters.guild_tax_attempt'
DEPOSITS = 'acore_characters.guild_tax_deposit'
MATCH = 'd.wallet_debit = a.tax AND d.bank_credit = a.tax'


def current_guilds():
    return {row["id"] for row in read_inventory_sql(
        'SET SESSION TRANSACTION READ ONLY; '
        "SELECT JSON_OBJECT('kind','meta','read_only',@@SESSION.transaction_read_only); "
        "SELECT JSON_OBJECT('id',guildid) FROM acore_characters.guild;"
    )}


def get_guild_tax(params, reader=read_inventory_sql):
    if set(params) - {'guild', 'period', 'character'} or any(len(values) != 1 for values in params.values()):
        raise ValueError('Provide one value per filter.')
    guild = int(params.get('guild', ['0'])[0])
    character = int(params.get('character', ['0'])[0])
    period = params.get('period', ['7d'])[0]
    if not 0 <= guild <= 4294967295 or not 0 <= character <= 4294967295 or period not in PERIODS:
        raise ValueError('Invalid guild, character or period.')
    def query(sql):
        return reader(
            'SET SESSION time_zone = "+00:00"; '
            'SET SESSION TRANSACTION READ ONLY; '
            'SET SESSION MAX_EXECUTION_TIME=3000; '
            'START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY; '
            "SELECT JSON_OBJECT('kind','meta','read_only',@@SESSION.transaction_read_only); "
            + sql + '; COMMIT;'
        )

    rates = saved_rates()
    guilds = query(f"""SELECT JSON_OBJECT('id',g.guildid,'name',g.name,
        'has_attempt',EXISTS (SELECT 1 FROM {ATTEMPTS} a WHERE a.guild_id=g.guildid),
        'faction',CASE WHEN leader.race IN (1,3,4,7,11) THEN 'Alliance'
                       WHEN leader.race IN (2,5,6,8,10) THEN 'Horde' ELSE 'Unknown' END,
        'members',(SELECT COUNT(*) FROM acore_characters.guild_member m WHERE m.guildid=g.guildid))
        FROM acore_characters.guild g
        LEFT JOIN acore_characters.characters leader ON leader.guid=g.leaderguid
        ORDER BY g.name""")
    if rates is not None:
        for entry in guilds:
            entry['rate'] = rates.get(entry['id'], 0)
    join = f'FROM {ATTEMPTS} a LEFT JOIN {DEPOSITS} d USING(event_id)'
    period_filter = f' AND a.created_at >= {PERIODS[period]}' if PERIODS[period] else ''
    if not guild:
        totals = query(f"""SELECT JSON_OBJECT('id',a.guild_id,'paid',SUM(a.tax))
            {join} WHERE {MATCH}{period_filter} GROUP BY a.guild_id""")
        paid_by_guild = {row['id']: int(row['paid']) for row in totals}
        summary = [dict(entry, paid=paid_by_guild.get(entry['id'], 0)) for entry in guilds]
        summary.sort(key=lambda entry: -entry['paid'])
        return {'guilds': guilds, 'guild': 0, 'summary': summary, 'ranks': [],
                'history': [], 'health': {}, 'can_edit_rates': rates is not None}

    condition = f'a.guild_id={guild}{period_filter}'
    ranks = query(f"""SELECT JSON_OBJECT('guid',a.character_guid,'name',COALESCE(MAX(c.name),MAX(a.character_name)),
        'class',MAX(c.class),'level',MAX(c.level),'paid',SUM(a.tax))
        {join} LEFT JOIN acore_characters.characters c ON c.guid=a.character_guid
        WHERE {condition} AND {MATCH}
        GROUP BY a.character_guid ORDER BY SUM(a.tax) DESC,a.character_guid""")
    health = query(f"""SELECT JSON_OBJECT('attempts',COUNT(*),
        'matched',COALESCE(SUM(IF({MATCH},1,0)),0),
        'mismatches',COALESCE(SUM(IF(d.event_id IS NOT NULL AND NOT ({MATCH}),1,0)),0),
        'failed',COALESCE(SUM(IF(d.event_id IS NULL AND a.reported_failure,1,0)),0),
        'unverifiable',COALESCE(SUM(IF(d.event_id IS NULL AND NOT a.reported_failure,1,0)),0),
        'copper_delta',COALESCE(SUM(CAST(d.bank_credit AS SIGNED)-CAST(d.wallet_debit AS SIGNED)),0))
        {join} WHERE a.guild_id={guild}
          AND a.created_at BETWEEN UTC_TIMESTAMP()-INTERVAL 24 HOUR AND UTC_TIMESTAMP()-INTERVAL 5 MINUTE""")[0]
    health = {key: int(value) for key, value in health.items()}
    errors = health['mismatches'] + health['failed']
    checked = health['matched'] + errors
    health['checked'] = checked
    health['rate'] = errors / checked if checked else 0
    health['alert'] = checked >= 20 and errors * 20 > checked
    history = query(f"""SELECT JSON_OBJECT('id',a.event_id,'time',a.created_at,
        'gross',a.gross,'tax',a.tax,'net',a.net,'rate',a.rate,'source',a.source_entry,
        'state',CASE WHEN {MATCH} THEN 'Recorded'
                    WHEN d.event_id IS NOT NULL THEN 'Mismatch'
                    WHEN a.reported_failure THEN 'Failed' ELSE 'Unverified' END)
        {join} WHERE {condition} AND a.character_guid={character}
        ORDER BY a.created_at DESC,a.event_id DESC LIMIT 100""") if character else []
    return {'guilds': guilds, 'guild': guild, 'ranks': ranks, 'history': history, 'health': health, 'can_edit_rates': rates is not None}
