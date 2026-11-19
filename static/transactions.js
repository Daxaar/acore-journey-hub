(()=>{
'use strict';
const $=id=>document.getElementById(id);
const labels={vendor_purchase:'Vendor purchase',vendor_sale_observed:'Vendor sale observed',loot:'Item loot',loot_money:'Money loot',listing_observed:'AH listing',sale_settlement_observed:'Sale settlement observed',expiration_observed:'Expiration observed',removal_observed:'Removal observed'};
let page=1,version=0,current=null,sessionToken="",monitoringVersion=0,characterRoster=[],rosterVersion=0,appliedFilters=null,exporting=false;
function el(tag,text){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;}
function money(value){const n=Number(value);return Math.floor(n/10000)+'g '+Math.floor(n%10000/100)+'s '+n%100+'c';}
function coinMoney(value){
 const span=el('span');span.className='money';
 let copper=Math.max(0,Math.round(Number(value)||0));
 const gold=Math.floor(copper/10000),silver=Math.floor(copper%10000/100);copper%=100;
 span.setAttribute('aria-label',gold+' gold, '+silver+' silver, '+copper+' copper');
 for(const [amount,type,show] of [[gold,'gold',gold>0],[silver,'silver',silver>0||gold>0],[copper,'copper',copper>0||(!gold&&!silver)]]){
  if(!show)continue;
  const icon=el('i');icon.className='coin '+type;icon.setAttribute('aria-hidden','true');
  span.append(document.createTextNode(amount.toLocaleString()),icon);
 }
 return span;
}
function priceLine(label,value,tag='div'){
 const line=el(tag);if(label)line.append(document.createTextNode(label+' '));
 line.append(coinMoney(value));return line;
}
function params(){
 const p=new URLSearchParams({page:String(page)});
 for(const key of ['group','character','kind','q','source','zone'])if($(key).value)p.set(key,$(key).value);
 for(const key of ['from','to'])if($(key).value)p.set(key,new Date($(key).value).toISOString().slice(0,19));
 return p;
}
async function load(){
 hideTooltip();const token=++version;$('error').hidden=true;$('export').disabled=true;
 $('previous').disabled=$('next').disabled=true;
 try{
  const requested=params();
  const response=await fetch('/api/transactions?'+requested,{cache:'no-store'}),data=await response.json();
  if(token!==version)return;
  if(!response.ok||!data.ok)throw new Error(data.error||'Transactions unavailable');
  appliedFilters=new URLSearchParams(requested);current=data.result;$('events').replaceChildren();
  for(const event of current.events){
   const row=el('tr'),actor=el('td',event.character||'Character #'+event.actor_guid);
   if(event.actor_ahbot)actor.append(el('small','AHBot'));
   if(event.counterparty_guid)actor.append(el('small',(event.counterparty||'Character #'+event.counterparty_guid)+(event.counterparty_ahbot?' · AHBot':'')));
   const item=el('td');
   if(event.item_id){
   const link=wowheadLink(event.item||'Item #'+event.item_id,'item',event.item_id);
   link.classList.add('transaction-item-link');
   const image=el('img');image.alt='';image.loading='lazy';image.width=22;image.height=22;
   image.src=event.icon?'/icons/'+encodeURIComponent(event.icon)+'.jpg':'/item-placeholder.svg';
   image.addEventListener('error',()=>{image.src='/item-placeholder.svg';},{once:true});
   link.prepend(image);item.append(link);
   link.addEventListener('mouseenter',e=>showTooltip(event,link,e));
   link.addEventListener('mousemove',e=>ItemTooltip.position($('transaction-tooltip'),link,e));
   link.addEventListener('mouseleave',hideTooltip);
   link.addEventListener('focus',()=>showTooltip(event,link));
   link.addEventListener('blur',hideTooltip);
   }else item.textContent=event.event_kind==='loot_money'?'Money':'—';
   const amount=el('td');amount.className='transaction-price';
   if(event.event_kind==='listing_observed'){
    amount.append(priceLine('Bid',event.start_bid),event.buyout?priceLine('Buyout',event.buyout):el('div','Buyout None'),priceLine('Deposit',event.deposit,'small'));
   }else if(event.event_kind==='sale_settlement_observed'){
    amount.append(priceLine('',event.proceeds),priceLine('Sale',event.gross,'small'),priceLine('Fee',event.fee,'small'),priceLine('Returned deposit',event.deposit,'small'));
    }else if(event.event_kind==='loot_money'){
    amount.append(priceLine('Looted',event.gross));
   }else if(event.event_kind==='vendor_purchase'){
    amount.append(priceLine('Paid',event.gross));
   }else if(event.event_kind==='vendor_sale_observed'){
    amount.append(priceLine('Received',event.proceeds));
   }else amount.textContent='—';
   row.append(el('td',new Date(event.recorded_at).toLocaleString('en-GB')),actor,el('td',labels[event.event_kind]||event.event_kind),sourceCell(event),item,el('td',event.event_kind==='loot_money'?'—':event.quantity),vendorPrice(event),amount,el('td',event.auction_id?'#'+event.auction_id:'—'));
   $('events').append(row);
  }
  $('summary').replaceChildren();
  for(const [label,value] of [['Events',current.totals.events],['Items looted',current.totals.loot_quantity],['Money looted',coinMoney(current.totals.loot_copper||0)],['Observed settlement proceeds',coinMoney(current.totals.settlement_proceeds)]]){
   const card=el('div'),amount=el('strong');amount.append(value instanceof Node?value:document.createTextNode(String(value)));card.append(amount,el('span',label));$('summary').append(card);
  }
  const vendorValue=el('div'),vendorAmount=el('strong');
  vendorAmount.append(coinMoney(current.totals.loot_vendor_value||0));
  vendorValue.append(vendorAmount,el('span','Loot vendor value'));
  vendorValue.title='Base vendor sell value of all looted items matching the applied filters, including every page.';
  $('summary').append(vendorValue);
  const pages=Math.max(1,Math.ceil(current.totals.events/current.page_size));
  $('page').textContent=page+' / '+pages;$('previous').disabled=page<=1;$('next').disabled=page>=pages;
  $('empty').hidden=!!current.events.length;$('export').disabled=exporting||!current.totals.events;
 }catch(error){if(token===version){$('error').textContent=error.message;$('error').hidden=false;}}
}
$('transaction-filters').addEventListener('submit',event=>{event.preventDefault();page=1;load();loadRoster().catch(error=>{$('history-status').textContent=error.message;});});
$('previous').addEventListener('click',()=>{--page;load();});
$('next').addEventListener('click',()=>{++page;load();});
$('export').addEventListener('click',async()=>{
 if(!appliedFilters||exporting)return;
 const filters=new URLSearchParams(appliedFilters);filters.delete('page');
 exporting=true;$('export').disabled=true;$('export').textContent='Exporting…';
 try{
  const response=await fetch('/api/transactions/export?'+filters,{cache:'no-store'});
  if(!response.ok){const data=await response.json();throw new Error(data.error||'Export failed');}
  const url=URL.createObjectURL(await response.blob());
  const link=el('a');link.href=url;link.download='transactions.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }catch(error){$('error').textContent=error.message;$('error').hidden=false;}
 finally{exporting=false;$('export').textContent='Export all results';$('export').disabled=!current?.totals.events;}
});
function sourceCell(event){
 const cell=el('td');
 if(!['loot','loot_money'].includes(event.event_kind)){cell.textContent='—';return cell;}
 if(event.source_name){
  if(event.source_type==='creature'&&event.source_entry)cell.append(wowheadLink(event.source_name,'npc',event.source_entry));
  else cell.append(el('span',event.source_name));
 }else cell.textContent='Unknown source';
 if(event.zone_name)cell.append(el('small',event.zone_name+(event.area_name&&event.area_name!==event.zone_name?' · '+event.area_name:'')));
 return cell;
}
function vendorPrice(event){
 const cell=el('td','—');
 if(event.event_kind==='loot'){
  cell.replaceChildren(el('div',money(event.vendor_sell_price||0)+' each'),el('small',money((event.vendor_sell_price||0)*event.quantity)+' stack'));
 }
 return cell;
}
function hideTooltip(){$('transaction-tooltip').hidden=true;}
function showTooltip(event,target,mouse){
 const tooltip=$('transaction-tooltip');
 ItemTooltip.render(tooltip,{id:event.item_id,name:event.item||'Item #'+event.item_id,count:event.quantity,sell_price:event.vendor_sell_price||0});
 tooltip.hidden=false;ItemTooltip.position(tooltip,target,mouse);
}
document.querySelector('.transaction-scroll').addEventListener('scroll',hideTooltip);
window.addEventListener('resize',hideTooltip);
document.addEventListener('keydown',event=>{if(event.key==='Escape')hideTooltip();});
function renderCharacterOptions(){
 const previous=$('character').value;
 $('character').replaceChildren(new Option('All recorded activity',''));
 for(const character of characterRoster){
  if(!character.monitored&&!$('include-historical').checked)continue;
  const option=el('option',character.name+(character.monitored?'':' (historical)'));
  option.value=character.guid;$('character').append(option);
 }
 $('character').value=previous;
 if(!$('character').value)$('character').value='';
 $('remove-history').disabled=!$('character').value;
 return previous!==$('character').value;
}
async function loadRoster(){
 const version=++rosterVersion;
 const response=await fetch('/api/transactions/characters',{cache:'no-store'}),data=await response.json();
 if(version!==rosterVersion)return;
 if(!response.ok||!data.ok)throw new Error(data.error||'Character history unavailable');
 characterRoster=data.characters;
 if(renderCharacterOptions()){page=1;load();}
 $('participant-list').replaceChildren();
 for(const character of characterRoster.filter(item=>!item.monitored&&item.has_history)){
  const row=el('div'),name=el('span',character.name);
  row.className='participant-row';row.setAttribute('role','listitem');
  name.className='monitoring-name class-'+character.class;
  row.append(name,el('small','Level '+character.level));$('participant-list').append(row);
 }
 if(!$('participant-list').children.length)$('participant-list').append(el('p','No other recorded participants.'));
}
$('include-historical').addEventListener('change',()=>{if(renderCharacterOptions()){page=1;load();}});
async function loadMonitoring(){
 const token=++monitoringVersion;
 try{
  const response=await fetch('/api/transactions/monitoring?'+new URLSearchParams({q:$('monitoring-query').value})),data=await response.json();
  if(token!==monitoringVersion)return;
  if(!response.ok||!data.ok)throw new Error(data.error||'Monitoring unavailable');
  $('monitoring-list').replaceChildren();
  for(const character of data.monitoring.characters){
   const label=el('label'),checkbox=el('input');checkbox.type='checkbox';checkbox.checked=character.monitored;
   const name=el('span',character.name),level=el('small','Level '+character.level);
   name.className='monitoring-name class-'+character.class;
   label.append(checkbox,name,level);$('monitoring-list').append(label);
   checkbox.addEventListener('change',async()=>{
    const wanted=checkbox.checked;checkbox.disabled=true;
    try{
     const response=await fetch('/api/transactions/monitoring',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':sessionToken},body:JSON.stringify({guid:character.guid,enabled:wanted})});
     const data=await response.json();
     if(!response.ok||!data.ok)throw new Error(data.error||'Could not save monitoring');
     $('monitoring-status').textContent=data.monitoring.enabled_count+' monitored. Change applies within five seconds.';
     await loadRoster().catch(error=>{$('monitoring-status').textContent='Monitoring saved. '+error.message;});
    }catch(error){checkbox.checked=!wanted;$('monitoring-status').textContent=error.message;}
    finally{checkbox.disabled=false;}
   });
  }
  $('monitoring-status').textContent=data.monitoring.enabled_count+' monitored · '+data.monitoring.characters.length+' shown'+(data.monitoring.characters.length===data.monitoring.limit?' · Refine the search to see more':'');
 }catch(error){$('monitoring-status').textContent=error.message;}
}
$('monitoring-search').addEventListener('submit',event=>{event.preventDefault();loadMonitoring();});
let removalTicket=null;
$('character').addEventListener('change',()=>{$('remove-history').disabled=!$('character').value;});
async function removalRequest(payload){
 const response=await fetch('/api/transactions/remove-history',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':sessionToken},body:JSON.stringify(payload)});
 const data=await response.json();
 if(!response.ok||!data.ok)throw new Error(data.error||'History removal failed');
 return data.removal;
}
$('remove-history').addEventListener('click',async()=>{
 $('remove-history').disabled=true;
 try{
  const snapshot=await removalRequest({action:'preview',guid:Number($('character').value)});
  removalTicket=snapshot.ticket;
  $('history-message').textContent='Remove '+snapshot.count+' recorded events involving '+snapshot.name+'?';
  $('history-dialog').returnValue='cancel';$('history-dialog').showModal();
 }catch(error){$('history-status').textContent=error.message;}
 finally{$('remove-history').disabled=!$('character').value;}
});
$('history-dialog').addEventListener('close',async()=>{
 if($('history-dialog').returnValue!=='confirm'||!removalTicket)return;
 const ticket=removalTicket;removalTicket=null;
 $('remove-history').disabled=true;
 try{
  let removal=await removalRequest({action:'confirm',ticket});
  $('history-status').textContent='History removal queued. Waiting for the realm recorder…';
  for(let attempt=0;attempt<30&&removal.state==='pending';++attempt){
   await new Promise(resolve=>setTimeout(resolve,1000));
   const response=await fetch('/api/transactions/remove-history?'+new URLSearchParams({ticket}));
   const data=await response.json();
   if(!response.ok||!data.ok)throw new Error(data.error||'Could not check removal');
   removal=data.removal;
  }
  if(removal.state==='failed')throw new Error('The recorder could not remove the history. Review its database log.');
  $('history-status').textContent=removal.state==='complete'?'History removed for '+removal.name+'.':'Removal remains queued. The realm recorder must be running to process it.';
  page=1;load();await loadRoster();
 }catch(error){$('history-status').textContent=error.message;}
 finally{$('remove-history').disabled=!$('character').value;}
});
async function setup(){
 try{
  const response=await fetch('/api/session'),session=await response.json();
  sessionToken=session.token;
  for(const group of session.groups.groups){const option=el('option',group.name);option.value=group.id;$('group').append(option);}
  $('group').value=session.groups.selected||'';
  await loadRoster();
 }catch(error){$('error').textContent='Group filters unavailable. '+error.message;$('error').hidden=false;}
 load();
 loadMonitoring();
}
setup();
})();
