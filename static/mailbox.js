(()=>{
'use strict';
const $=id=>document.getElementById(id);
let page=1,listVersion=0,detailVersion=0,charactersVersion=0,receiver=new URLSearchParams(location.search).get('receiver')||'',selectedMail=0,roster=[];
function el(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
function coins(value){
 const n=el('span');n.className='money';let copper=Number(value)||0;
 const gold=Math.floor(copper/10000),silver=Math.floor(copper%10000/100);copper%=100;
 n.setAttribute('aria-label',gold+' gold, '+silver+' silver, '+copper+' copper');
 for(const [amount,type,show] of [[gold,'gold',gold>0],[silver,'silver',silver>0||gold>0],[copper,'copper',copper>0||(!gold&&!silver)]]){
  if(show){const icon=el('i');icon.className='coin '+type;icon.setAttribute('aria-hidden','true');n.append(document.createTextNode(amount),icon);}
 }return n;
}
async function request(path){const response=await fetch(path,{cache:'no-store'}),data=await response.json();if(!response.ok||!data.ok)throw new Error(data.error||'Mailbox unavailable');return data;}
function error(message){$('mail-error').textContent=message;$('mail-error').hidden=!message;}
function hideTooltip(){$('mail-tooltip').hidden=true;}
function slot(attachment){
 const n=el('span');n.className='mail-slot';
 if(attachment){
  const img=el('img');img.alt='';img.loading='lazy';img.src=attachment.icon?'/icons/'+encodeURIComponent(attachment.icon)+'.jpg':'/item-placeholder.svg';
  img.addEventListener('error',()=>{img.src='/item-placeholder.svg';},{once:true});n.append(img);
  if(attachment.quantity>1){const count=el('span',attachment.quantity);count.className='mail-count';n.append(count);}
 }else n.textContent='✉';
 return n;
}
function timeLeft(mail){
 const now=Date.now()/1000;
 if(mail.deliver_time>now)return 'Arrives in '+Math.ceil((mail.deliver_time-now)/60)+' min';
 const seconds=mail.expire_time-now;
 return seconds>86400?Math.ceil(seconds/86400)+' Days':Math.max(1,Math.ceil(seconds/3600))+' Hours';
}
function auctionKind(mail){
 if(mail.sender_type!==2)return null;
 return {0:'Outbid',1:'Auction won',2:'Auction successful',3:'Auction expired',4:'Auction cancelled',5:'Auction cancelled',6:'Sale pending'}[Number((mail.subject||'').split(':')[2])]||'Auction House';
}
function subject(mail){
 const kind=auctionKind(mail);
 return kind?kind+' · '+(mail.auction_item||'Item #'+(mail.subject||'').split(':')[0]):mail.subject||'(No subject)';
}
async function loadCharacters(){
 const token=++charactersVersion,params=new URLSearchParams({group:$('mail-group').value,q:$('mail-query').value});
 try{
  const data=await request('/api/mailbox/characters?'+params);
  if(token!==charactersVersion)return;
  roster=data.characters;
  $('mail-character').replaceChildren(new Option('Choose a character',''));
  for(const character of roster)$('mail-character').append(new Option(character.name+' ('+character.count+')',character.guid));
  if(roster.some(c=>String(c.guid)===receiver))$('mail-character').value=receiver;
  else $('mail-character').value=roster.length?String((roster.find(c=>c.count>0)||roster[0]).guid):'';
  receiver=$('mail-character').value;page=1;await load();
 }catch(e){if(token===charactersVersion)error(e.message);}
}
async function load(){
 const token=++listVersion;++detailVersion;selectedMail=0;hideTooltip();error('');
 $('mail-list').replaceChildren();$('mail-detail').replaceChildren(el('p','Select a message to read it.'));
 $('mail-previous').disabled=$('mail-next').disabled=true;
 $('mailbox-status').textContent='';$('mail-page').textContent='';
 const owner=roster.find(c=>String(c.guid)===receiver);
 $('mailbox-owner').textContent=owner?owner.name+' · Inbox':'Choose a character';
 if(!receiver){$('mail-list').append(el('p','No matching characters.'));return;}
 try{
  const data=(await request('/api/mailbox?'+new URLSearchParams({receiver,page}))).result;
  if(token!==listVersion)return;
  for(const mail of data.messages){
   const row=el('button');row.type='button';row.className='mail-row'+(!mail.read?' unread':'');row.setAttribute('aria-pressed','false');
   const info=el('span');info.className='mail-row-info';
   info.append(el('strong',mail.sender),el('span',subject(mail)));
   const time=el('span',timeLeft(mail));time.className='mail-time';
   row.append(slot(mail.attachments[0]),info,time);
   row.addEventListener('click',()=>{selectedMail=mail.id;for(const other of $('mail-list').children)other.setAttribute('aria-pressed',String(other===row));loadDetail(mail.id);});
   $('mail-list').append(row);
  }
  if(!data.messages.length){const empty=el('p','Your mailbox is empty.');empty.className='mail-empty';$('mail-list').append(empty);}
  const pages=Math.max(1,Math.ceil(data.totals.count/data.page_size));
  $('mail-page').textContent=page+' / '+pages;$('mail-previous').disabled=page<=1;$('mail-next').disabled=page>=pages;
  $('mailbox-status').textContent=data.totals.count+' messages · '+data.totals.unread+' recorded unread · Refreshed '+new Date().toLocaleTimeString();
  if(data.messages.length){
   selectedMail=data.messages[0].id;$('mail-list').firstChild.setAttribute('aria-pressed','true');
   loadDetail(selectedMail);
  }
 }catch(e){if(token===listVersion)error(e.message);}
}
async function loadDetail(id){
 const token=++detailVersion;hideTooltip();$('mail-detail').replaceChildren(el('p','Reading letter…'));
 try{
  const data=(await request('/api/mailbox?'+new URLSearchParams({receiver,id}))).result;
  if(token!==detailVersion||selectedMail!==id)return;
  const mail=data.messages[0];
  if(!mail){$('mail-detail').replaceChildren(el('p','This message is no longer available. Refresh the inbox.'));return;}
  const address=el('div');address.className='mail-address';
  for(const [label,text] of [['From',mail.sender],['Subject',subject(mail)]]){
   const p=el('p',label+' ');p.append(el('strong',text));address.append(p);
  }
  const body=el('div');body.className='mail-body';
  body.textContent=auctionKind(mail)?auctionKind(mail)+' correspondence for '+(mail.auction_item||'this item')+'.':mail.body?mail.body.split('|n').join(String.fromCharCode(10)):mail.template_id?'Template-generated letter #'+mail.template_id+'. Its text is not stored in the mail database.':'';
  if(mail.body_truncated)body.append(el('p','The stored message exceeds the viewer text limit.'));
  const attachments=el('div');attachments.className='mail-attachments';
  for(const item of mail.attachments){
   const link=wowheadLink('','item',item.id);link.className='mail-attachment';
   link.append(slot(item),el('span',item.name||'Item #'+item.id));
   function tooltip(event){const tip=$('mail-tooltip');ItemTooltip.render(tip,{id:item.id,name:item.name,icon:item.icon,quality:item.quality,count:item.quantity});tip.hidden=false;ItemTooltip.position(tip,link,event);}
   link.addEventListener('mouseenter',tooltip);link.addEventListener('focus',()=>tooltip());
   link.addEventListener('mousemove',event=>ItemTooltip.position($('mail-tooltip'),link,event));
   link.addEventListener('mouseleave',hideTooltip);link.addEventListener('blur',hideTooltip);attachments.append(link);
  }
  const finance=el('div');finance.className='mail-finance';
  if(auctionKind(mail)&&mail.body){
   const fields=mail.body.split(':');
   for(const [label,index] of [['Auction amount',1],['Deposit',3],['Auction cut',4]]){
    const value=Number(fields[index]);
    if(value>0){const p=el('p',label+' ');p.append(coins(value));finance.append(p);}
   }
  }
  if(mail.deliver_time>Date.now()/1000)finance.append(el('p','Delivery '+new Date(mail.deliver_time*1000).toLocaleString('en-GB')));
  if(mail.money){const p=el('p','Money attached ');p.append(coins(mail.money));finance.append(p);}
  if(mail.cod){const p=el('p','Cash on delivery ');p.append(coins(mail.cod));finance.append(p);}
  finance.append(el('p','Expires '+new Date(mail.expire_time*1000).toLocaleString('en-GB')));
  $('mail-detail').replaceChildren(address,body,attachments,finance);
 }catch(e){if(token===detailVersion)error(e.message);}
}
$('mail-group').addEventListener('change',loadCharacters);
$('mail-character').addEventListener('change',()=>{
 receiver=$('mail-character').value;page=1;
 const url=new URL(location.href);if(receiver)url.searchParams.set('receiver',receiver);else url.searchParams.delete('receiver');
 history.replaceState(null,'',url);load();
});
$('mail-search').addEventListener('submit',event=>{event.preventDefault();loadCharacters();});
$('mail-refresh').addEventListener('click',loadCharacters);
$('mail-previous').addEventListener('click',()=>{--page;load();});
$('mail-next').addEventListener('click',()=>{++page;load();});
window.addEventListener('resize',hideTooltip);
document.addEventListener('keydown',event=>{if(event.key==='Escape')hideTooltip();});
(async()=>{
 try{
  const session=await fetch('/api/session').then(r=>r.json());
  for(const group of session.groups.groups)$('mail-group').append(new Option(group.name,group.id));
  $('mail-group').value=session.groups.selected||'';await loadCharacters();
 }catch(e){error(e.message);}
})();
})();
