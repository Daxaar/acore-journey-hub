"""Bounded, cached, read-only item-template details shared by every tooltip surface."""
import json
from pathlib import Path
import threading
import time
from armory import ITEM_TOOLTIP_FIELDS,read_inventory_sql
from mysql_access import DatabaseError
from spell_tooltips import enrich_item

ROOT=Path(__file__).resolve().parent
FIELDS={name:name for name in ITEM_TOOLTIP_FIELDS}
FIELDS.update({'id':'entry','name':'name','quality':'Quality','level':'ItemLevel','required_level':'RequiredLevel',
               'category':'class','subclass':'subclass','slot':'InventoryType','displayid':'displayid',
               'description':'description','sell_price':'SellPrice','required_skill':'RequiredSkill','skill_rank':'RequiredSkillRank',
               'max_stack':'stackable','max_count':'maxcount','Flags':'Flags','itemset':'itemset','socketBonus':'socketBonus',
               'gem_properties':'GemProperties','required_faction':'RequiredReputationFaction','required_rank':'RequiredReputationRank','required_spell':'requiredspell'})
FIELDS.update({name:name for name in ['holy_res','fire_res','nature_res','frost_res','shadow_res','arcane_res']})
FIELDS.update({name+'_'+str(i):name+'_'+str(i) for name in ['spellid','spelltrigger','socketColor'] for i in range(1,4)})
FIELDS.update({name+'_'+str(i):name+'_'+str(i) for name in ['spellid','spelltrigger'] for i in (4,5)})

FIELDS.update({name+'_'+str(i):name+'_'+str(i) for name in ['spellcooldown','spellcategorycooldown','spellcharges'] for i in range(1,6)})

def item_sql(entry):
    if type(entry) is not int or not 1<=entry<=4294967295:raise ValueError('Choose a valid item ID.')
    columns=','.join(f"'{key}',t.`{column}`" for key,column in FIELDS.items())
    return f'''SET SESSION TRANSACTION READ ONLY;
SET SESSION MAX_EXECUTION_TIME=3000;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SELECT JSON_OBJECT('kind','meta','read_only',@@SESSION.transaction_read_only);
SELECT JSON_OBJECT({columns}) FROM acore_world.item_template t WHERE t.entry={entry} LIMIT 1;
COMMIT;
'''


def load_metadata(root):
    try:
        value=json.loads((Path(root)/'assets/tooltip-metadata.json').read_text())
        return value if isinstance(value,dict) and value.get('format')==1 else {}
    except (OSError,ValueError):return {}


class ItemTooltipProvider:
    def __init__(self,root=ROOT,reader=read_inventory_sql):
        self.reader=reader;self.lock=threading.Lock();self.cached={};self.metadata=load_metadata(root)
        try:self.icons=json.loads((root/'assets/item-metadata.json').read_text()).get('icons',{})
        except (OSError,ValueError):self.icons={}
        try:self.skills=json.loads((root/'assets/profession-metadata.json').read_text()).get('skills',{})
        except (OSError,ValueError):self.skills={}

    def get(self,entry):
        sql=item_sql(entry)
        with self.lock:
            cached=self.cached.get(entry)
            if cached and time.monotonic()-cached[0]<60:return dict(cached[1])
            rows=self.reader(sql)
            if not rows:raise LookupError('No item template found for that ID.')
            if len(rows)!=1 or rows[0].get('id')!=entry:raise DatabaseError('Unexpected item template response.')
            item=enrich_item(rows[0],self.metadata)
            item['icon']=self.icons.get(str(item.get('displayid')))
            item['skill_name']=self.skills.get(str(item.get('required_skill')),{}).get('name')
            item['tooltip_complete']=True
            if len(self.cached)>=512:self.cached.pop(next(iter(self.cached)))
            self.cached[entry]=(time.monotonic(),item)
            return dict(item)
