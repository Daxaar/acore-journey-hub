"use strict";
// WotLK item class/subclass/InventoryType values, rather than retail-only categories.
(() => {
 const leaf=(name,subclass,slot='')=>({name,subclass:String(subclass),slot:String(slot)});
 const slots=()=>[[1,'Head'],[3,'Shoulders'],['5,20','Chest'],[9,'Wrists'],[10,'Hands'],[6,'Waist'],[7,'Legs'],[8,'Feet']].map(([slot,name])=>({name,slot:String(slot)}));
 const group=(name,subclass,children)=>({name,subclass,children});
 window.AuctionCategories=[
  {name:'All items',category:''},
  {name:'Weapons',category:2,children:[
   group('One-Handed','0,4,7,13,15',[leaf('One-Handed Axes',0),leaf('One-Handed Maces',4),leaf('One-Handed Swords',7),leaf('Daggers',15),leaf('Fist Weapons',13)]),
   group('Two-Handed','1,5,6,8,10',[leaf('Two-Handed Axes',1),leaf('Two-Handed Maces',5),leaf('Two-Handed Swords',8),leaf('Polearms',6),leaf('Staves',10)]),
   group('Ranged','2,3,16,18,19',[leaf('Bows',2),leaf('Guns',3),leaf('Crossbows',18),leaf('Thrown',16),leaf('Wands',19)]),
   group('Miscellaneous','14,20',[leaf('Miscellaneous',14),leaf('Fishing Poles',20)])]},
  {name:'Armor',category:4,children:[group('Cloth','1',slots()),group('Leather','2',slots()),group('Mail','3',slots()),group('Plate','4',slots()),
   leaf('Shields',6),leaf('Cloaks','0,1','16'),leaf('Necklaces',0,2),leaf('Rings',0,11),leaf('Trinkets',0,12),leaf('Held In Off-hand',0,23),
   group('Relics','7,8,9,10',[leaf('Librams',7),leaf('Idols',8),leaf('Totems',9),leaf('Sigils',10)]),leaf('Miscellaneous',0)]},
  {name:'Containers',category:1,children:[[0,'Bags'],[1,'Soul Bags'],[2,'Herb Bags'],[3,'Enchanting Bags'],[4,'Engineering Bags'],[5,'Gem Bags'],[6,'Mining Bags'],[7,'Leatherworking Bags'],[8,'Inscription Bags']].map(([id,name])=>leaf(name,id))},
  {name:'Gems',category:3,children:[[0,'Red'],[1,'Blue'],[2,'Yellow'],[3,'Purple'],[4,'Green'],[5,'Orange'],[6,'Meta'],[7,'Simple'],[8,'Prismatic']].map(([id,name])=>leaf(name,id))},
  {name:'Consumables',category:0,children:[[1,'Potions'],[2,'Elixirs'],[3,'Flasks'],[4,'Scrolls'],[5,'Food & Drink'],[6,'Item Enhancements'],[7,'Bandages'],[8,'Other'],[0,'Consumables']].map(([id,name])=>leaf(name,id))},
  {name:'Glyphs',category:16,children:[[1,'Warrior'],[2,'Paladin'],[3,'Hunter'],[4,'Rogue'],[5,'Priest'],[6,'Death Knight'],[7,'Shaman'],[8,'Mage'],[9,'Warlock'],[11,'Druid']].map(([id,name])=>leaf(name,id))},
  {name:'Trade goods',category:7,children:[[5,'Cloth'],[6,'Leather'],[7,'Metal & Stone'],[8,'Meat'],[9,'Herbs'],[10,'Elemental'],[12,'Enchanting'],[1,'Parts'],[2,'Explosives'],[3,'Devices'],[4,'Jewelcrafting'],[13,'Materials'],[14,'Armor Enchantments'],[15,'Weapon Enchantments'],[11,'Other'],[0,'Trade Goods']].map(([id,name])=>leaf(name,id))},
  {name:'Reagents',category:5},
  {name:'Recipes',category:9,children:[[1,'Leatherworking'],[2,'Tailoring'],[3,'Engineering'],[4,'Blacksmithing'],[5,'Cooking'],[6,'Alchemy'],[7,'First Aid'],[8,'Enchanting'],[9,'Fishing'],[10,'Jewelcrafting'],[11,'Inscription'],[0,'Books']].map(([id,name])=>leaf(name,id))},
  {name:'Projectiles',category:6,children:[leaf('Arrows',2),leaf('Bullets',3)]},
  {name:'Quivers',category:11,children:[leaf('Quivers',2),leaf('Ammo Pouches',3)]},
  {name:'Quest items',category:12},{name:'Keys',category:13},
  {name:'Miscellaneous',category:15,children:[[0,'Junk'],[1,'Reagents'],[2,'Companion Pets'],[3,'Holiday'],[4,'Other'],[5,'Mounts']].map(([id,name])=>leaf(name,id))}
 ];
})();
