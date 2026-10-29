"""Trusted, read-only MySQL snapshot transport."""
from connection import mysql_command, database_sql, database_environment

import json
import re
import os
import subprocess

from deployment_config import container

CONTAINER = container('db_container')


class DatabaseError(Exception):
    """A safe, credential-free error suitable for the local UI."""


def name_filter(alias, names):
    # Validated watch names are encoded as hex literals, never concatenated as raw SQL.
    if not names or any(not re.fullmatch(r'[A-Za-z]{2,12}', name) for name in names):
        raise ValueError('Watch names must contain 2–12 ASCII letters')
    literals = ','.join('0x' + name.encode().hex() for name in names)
    return f'{alias}.name IN ({literals}) AND {alias}.deleteDate IS NULL'


def snapshot_sql(names):
    selected = name_filter('c', names)
    fields = ["'kind', 'quest'", "'guid', s.guid", "'id', s.quest", "'status', s.status",
              "'explored', s.explored", "'timer', s.timer", "'playercount', s.playercount",
              "'template_found', q.ID IS NOT NULL", "'title', q.LogTitle", "'description', q.LogDescription",
              "'area', q.AreaDescription", "'level', q.QuestLevel", "'special_flags', COALESCE(a.SpecialFlags,0)",
              "'time_allowed', q.TimeAllowed", "'player_kills', q.RequiredPlayerKills",
              "'money_required', GREATEST(0,-q.RewardMoney)", "'money', c.money",
              "'faction', q.RequiredFactionId1", "'reputation_required', q.RequiredFactionValue1",
              "'has_area_trigger', EXISTS (SELECT 1 FROM acore_world.areatrigger_involvedrelation ar "
              "WHERE ar.quest=q.ID)"]
    fields += ["'category_id',q.QuestSortID", "'min_level',q.MinLevel", "'max_level',a.MaxLevel",
               "'race_mask',q.AllowableRaces", "'class_mask',a.AllowableClasses", "'prev_quest',a.PrevQuestID",
               "'exclusive_group',a.ExclusiveGroup", "'required_skill',a.RequiredSkillID", "'required_skill_points',a.RequiredSkillPoints",
               "'rep_min_faction',a.RequiredMinRepFaction", "'rep_max_faction',a.RequiredMaxRepFaction",
               "'flags',q.Flags" ]
    active_ids = f"SELECT s3.quest FROM acore_characters.character_queststatus s3 JOIN acore_characters.characters c3 ON c3.guid=s3.guid WHERE {name_filter('c3',names)} AND s3.status IN (1,3,5)"
    joins = []
    for i in range(1, 5):
        fields.extend([f"'mob{i}', s.mobcount{i}", f"'target{i}', q.RequiredNpcOrGo{i}",
                       f"'target_count{i}', q.RequiredNpcOrGoCount{i}", f"'objective_text{i}', q.ObjectiveText{i}",
                       f"'target_name{i}', IF(q.RequiredNpcOrGo{i}>0,ct{i}.name,go{i}.name)"])
        joins.extend([
            f'LEFT JOIN acore_world.creature_template ct{i} ON ct{i}.entry=q.RequiredNpcOrGo{i}',
            f'LEFT JOIN acore_world.gameobject_template go{i} ON go{i}.entry=-q.RequiredNpcOrGo{i}'])
    for i in range(1, 7):
        fields.extend([f"'item{i}', s.itemcount{i}", f"'item_id{i}', q.RequiredItemId{i}",
                       f"'item_count{i}', q.RequiredItemCount{i}", f"'item_name{i}', it{i}.name"])
        joins.append(f'LEFT JOIN acore_world.item_template it{i} ON it{i}.entry=q.RequiredItemId{i}')
    return f"""
SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
SET SESSION TRANSACTION READ ONLY;
SET SESSION MAX_EXECUTION_TIME=3000;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SELECT JSON_OBJECT('kind','meta','read_only',@@SESSION.transaction_read_only);
SELECT JSON_OBJECT('kind','character','guid',c.guid,'name',c.name,'race',c.race,'class',c.class,
 'level',c.level,'xp',c.xp,'online',c.online,'zone',c.zone,'logout_time',c.logout_time,
 'rest_bonus',c.rest_bonus,'is_logout_resting',c.is_logout_resting,
 'next_level_xp',px.Experience,'rest_observed_at',UNIX_TIMESTAMP(),
 'map',c.map,'x',c.position_x,'y',c.position_y,'reward_history_complete',1,'eligibility_data_complete',1)
FROM acore_characters.characters c
LEFT JOIN acore_world.player_xp_for_level px ON px.Level=c.level WHERE {selected};
SELECT JSON_OBJECT({','.join(fields)})
FROM acore_characters.characters c
JOIN acore_characters.character_queststatus s ON s.guid=c.guid AND s.status IN (1,3,5)
LEFT JOIN acore_world.quest_template q ON q.ID=s.quest
LEFT JOIN acore_world.quest_template_addon a ON a.ID=q.ID
{' '.join(joins)}
WHERE {selected};
SELECT JSON_OBJECT('kind','rewarded','guid',r.guid,'quest',r.quest,'active',r.active)
FROM acore_characters.characters c JOIN acore_characters.character_queststatus_rewarded r ON r.guid=c.guid
WHERE {selected} ORDER BY r.guid,r.quest LIMIT 20001;
SELECT JSON_OBJECT('kind','skill','guid',c.guid,'id',sk.skill,'value',sk.value)
FROM acore_characters.characters c JOIN acore_characters.character_skills sk ON sk.guid=c.guid
WHERE {selected} AND sk.skill IN (SELECT a.RequiredSkillID FROM acore_world.quest_template_addon a WHERE a.ID IN ({active_ids}));
SELECT JSON_OBJECT('kind','dependency','quest',a.ID,'id',p.ID,'signed_id',a.PrevQuestID,
 'title',p.LogTitle,'group',pa.ExclusiveGroup,'special_flags',pa.SpecialFlags,'flags',p.Flags,'category_id',p.QuestSortID)
FROM acore_world.quest_template_addon a JOIN acore_world.quest_template p ON p.ID=ABS(a.PrevQuestID)
LEFT JOIN acore_world.quest_template_addon pa ON pa.ID=p.ID WHERE a.ID IN ({active_ids});
SELECT JSON_OBJECT('kind','dependency','quest',a.NextQuestID,'id',a.ID,'signed_id',a.ID,
 'title',p.LogTitle,'group',a.ExclusiveGroup,'special_flags',a.SpecialFlags,'flags',p.Flags,'category_id',p.QuestSortID)
FROM acore_world.quest_template_addon a JOIN acore_world.quest_template p ON p.ID=a.ID
WHERE a.NextQuestID IN ({active_ids}) AND a.NextQuestID>0;
COMMIT;
"""


def read_database(names):
    # The credential is expanded only inside the existing container; never read .playerbots.env.
    command = mysql_command(xml=False)
    try:
        result = subprocess.run(command, env=database_environment(), input=database_sql(snapshot_sql(names)), text=True, encoding='utf-8',
                                capture_output=True, timeout=12, check=False)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        raise DatabaseError('Cannot reach Docker/MySQL. Check Docker and the Playerbots database container.') from exc
    if result.returncode:
        # Do not forward CLI output, connection details, or SQL errors to a browser or log.
        raise DatabaseError('Read-only database query failed. Check Docker access and the Playerbots container.')
    try:
        if len(result.stdout)>12000000: raise ValueError('Snapshot too large')
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        if not rows or rows[0] != {'kind': 'meta', 'read_only': 1}:
            raise ValueError('Read-only session was not confirmed')
        if sum(r.get('kind')=='rewarded' for r in rows)>=20001: raise ValueError('Reward history exceeds snapshot limit')
        return rows[1:]
    except (ValueError, TypeError) as exc:
        raise DatabaseError('The database returned an unexpected snapshot; check the installed schema.') from exc

