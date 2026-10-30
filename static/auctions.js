"use strict";
(() => {
 const $=id=>document.getElementById(id);
 const categories=window.AuctionCategories;

 let page=1,category='',subclass='',slot='',selected=null,listingPage=1;
 let searchController,detailController,searchVersion=0,detailVersion=0;
 let activeParams=new URLSearchParams(),selectedPath='0';
 const treeNodes=[],expanded=new Set();
 function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
 function money(value){
  const n=el('span',undefined,'money');
  if(value===null||value===undefined){n.textContent='Bid only';return n;}
  let copper=Math.ceil(Number(value));const gold=Math.floor(copper/10000),silver=Math.floor(copper%10000/100);copper%=100;
  n.setAttribute('aria-label',`${gold} gold, ${silver} silver, ${copper} copper`);
  for(const [amount,denomination,show] of [[gold,'gold',gold>0],[silver,'silver',silver>0||gold>0],[copper,'copper',copper>0||(!gold&&!silver)]]){
   if(show)n.append(document.createTextNode(amount.toLocaleString()),el('i',undefined,'coin '+denomination));
  }
  return n;
 }
 function itemTitle(item){const h=el('h3',undefined,'quality-'+item.quality);h.append(wowheadLink(item.name,'item',item.id));return h;}
 function icon(item){const img=el('img',undefined,'item-icon');img.alt='';img.loading='lazy';img.src=item.icon?'/icons/'+encodeURIComponent(item.icon)+'.jpg':'/item-placeholder.svg';img.addEventListener('error',()=>{if(!img.src.endsWith('/item-placeholder.svg'))img.src='/item-placeholder.svg';});return img;}
 function params(){return new URLSearchParams({house:$('house').value,q:$('search').value,category,subclass,slot,quality:$('quality').value,min:$('min-level').value,max:$('max-level').value,sort:$('sort').value,page:String(page)});}
 function error(message){$('market-error').textContent=message;$('market-error').hidden=!message;}
 async function request(url,signal){const r=await fetch(url,{cache:'no-store',signal});const data=await r.json();if(!r.ok||!data.ok)throw new Error(data.error||'The market is unavailable. Try refreshing.');return data.result;}
 function categoryLabel(){const node=treeNodes.find(n=>n.key===selectedPath);return node?node.names.join(' › '):'All items';}
 function renderTree(){
  for(const node of treeNodes){
   const isSelected=node.key===selectedPath;
   node.button.setAttribute('aria-pressed',String(isSelected));
   node.button.classList.toggle('ancestor',selectedPath.startsWith(node.key+'/'));
   if(node.children){node.children.hidden=!expanded.has(node.key);node.button.setAttribute('aria-expanded',String(expanded.has(node.key)));}
  }
  $('category-selection').textContent=categoryLabel();
 }
 function selectNode(node,announce=true){
  selectedPath=node.key;category=String(node.values.category??'');subclass=String(node.values.subclass??'');slot=String(node.values.slot??'');
  renderTree();
  if(announce)$('category-status').textContent=categoryLabel()+' · press Search';
 }
 function buildTree(nodes,parent,keyPrefix='',names=[]){
  const ul=el('ul');
  nodes.forEach((node,index)=>{
   const key=keyPrefix?keyPrefix+'/'+index:String(index),values={...parent,...node};
   const li=el('li'),button=el('button',node.name,node.children?'category-branch':'category-leaf');
   button.type='button';button.dataset.key=key;
   if(!keyPrefix)button.className='category-root';
   const record={key,values,button,names:[...names,node.name]};treeNodes.push(record);li.append(button);
   if(node.children){record.children=buildTree(node.children,values,key,record.names);record.children.id='category-'+key.replaceAll('/','-');record.children.hidden=true;button.setAttribute('aria-controls',record.children.id);li.append(record.children);}
   button.addEventListener('click',()=>{
    if(record.children){if(expanded.has(key)&&selectedPath===key)expanded.delete(key);else expanded.add(key);}
    selectNode(record);
   });
   ul.append(li);
  });
  return ul;
 }
 $('categories').append(buildTree(categories,{}));
 let tooltipAnchor=null;
 function hideTooltip(){tooltipAnchor?.removeAttribute('aria-describedby');tooltipAnchor=null;$('item-tooltip').hidden=true;}
 function positionTooltip(target,event){
  const tooltip=$('item-tooltip');if(tooltip.hidden)return;
  ItemTooltip.position(tooltip,target,event);
 }
 function showTooltip(item,target,event){
  hideTooltip();tooltipAnchor=target;
  const tooltip=$('item-tooltip');ItemTooltip.render(tooltip,item);tooltip.hidden=false;
  positionTooltip(target,event);
  target.setAttribute('aria-describedby','item-tooltip');
 }
 function closeDetail(){hideTooltip();$('detail').hidden=true;$('exchange').classList.remove('has-detail');selected=null;for(const row of $('items').children)row.classList.remove('selected');}
 function closeButton(){const button=el('button','‹ Back to results','metal-button detail-close');button.type='button';button.addEventListener('click',()=>{closeDetail();document.querySelector('#items .item-link')?.focus();});return button;}
 function placeholder(text){hideTooltip();$('detail').hidden=false;$('exchange').classList.add('has-detail');$('detail').replaceChildren(closeButton(),el('div',text,'detail-placeholder'));}
 const pairs={price:['price','price_desc'],name:['name','name_desc'],quantity:['quantity','quantity_asc'],level:['level','level_asc'],skill:['skill','skill_asc']};
 function syncSort(){
  const recipe=activeParams.get('category')==='9',levelHeader=document.querySelector('.market-table th:nth-child(3)'),levelButton=levelHeader.querySelector('button');
  levelHeader.dataset.sort=levelButton.dataset.sort=recipe?'skill':'level';
  const sort=$('sort').value;
  for(const th of document.querySelectorAll('.market-table thead th')){
   const key=th.dataset.sort,button=th.querySelector('button'),label={price:'Price',name:'Name',level:'iLvl',skill:'Skill',quantity:'Available'}[key];
   button.replaceChildren(document.createTextNode(label));th.removeAttribute('aria-sort');
   if(pairs[key].includes(sort)){const descending=['price_desc','name_desc','quantity','level','skill'].includes(sort);th.setAttribute('aria-sort',descending?'descending':'ascending');button.append(el('span',descending?' ↓':' ↑'));}
  }
 }
 function renderItems(result){
  $('items').replaceChildren();syncSort();
  if(result.items.length){const tr=el('tr',undefined,'result-hint'),td=el('td');td.colSpan=4;td.append(el('span','⌁','hint-icon'),document.createTextNode('Click an entry for more information.'),el('span','⌁','hint-icon'));tr.append(td);$('items').append(tr);}
  for(const item of result.items){
   const tr=el('tr'),price=el('td'),name=el('td'),button=el('button',undefined,'item-link');tr.dataset.item=String(item.id);
   button.type='button';button.setAttribute('aria-label','View '+item.name);button.append(icon(item),el('span',item.name,'item-name quality-'+item.quality));
   button.addEventListener('mouseenter',event=>showTooltip(item,button,event));button.addEventListener('mousemove',event=>positionTooltip(button,event));button.addEventListener('mouseleave',hideTooltip);button.addEventListener('focus',()=>showTooltip(item,button));button.addEventListener('blur',hideTooltip);
   button.addEventListener('click',()=>{selected=item.id;listingPage=1;for(const row of $('items').children)row.classList.toggle('selected',row===tr);loadDetail();});
   const external=wowheadLink('↗','item',item.id);external.classList.add('wowhead-shortcut');external.setAttribute('aria-label','View '+item.name+' on Wowhead');name.append(button,external);price.append(money(item.unit_price));
   tr.append(price,name,el('td',activeParams.get('category')==='9'?item.skill_rank:item.level),el('td',Number(item.quantity).toLocaleString()));$('items').append(tr);
  }
  const pages=Math.max(1,Math.ceil(Number(result.totals.items)/result.page_size));
  $('result-count').textContent=`${Number(result.totals.items).toLocaleString()} items · ${Number(result.totals.auctions).toLocaleString()} auctions`;
  $('empty').hidden=!!result.items.length;$('page-count').textContent=`${page} / ${pages}`;$('previous').disabled=page<=1;$('next').disabled=page>=pages;
 }
 async function load(){
  const version=++searchVersion;searchController?.abort();detailController?.abort();++detailVersion;searchController=new AbortController();closeDetail();error('');$('refresh').disabled=true;$('previous').disabled=true;$('next').disabled=true;$('items').replaceChildren();$('empty').hidden=true;$('result-count').textContent='Loading the market…';activeParams=params();
  try{const result=await request('/api/auctions?'+activeParams,searchController.signal);if(version!==searchVersion)return;renderItems(result);$('updated').textContent='Snapshot '+new Date(result.refreshed_at).toLocaleTimeString();$('category-status').textContent=categoryLabel();const url=new URL(location.href);url.search=activeParams.toString();history.replaceState(null,'',url);}
  catch(e){if(e.name!=='AbortError'&&version===searchVersion){error(e.message);$('result-count').textContent='Market unavailable';$('updated').textContent='Refresh failed';}}
  finally{if(version===searchVersion)$('refresh').disabled=false;}
 }
 function card(label,value,isMoney=false){const n=el('div',undefined,'price-card'),strong=el('strong');strong.append(isMoney?money(value):document.createTextNode(Number(value).toLocaleString()));n.append(el('span',label),strong);return n;}
 function houseName(id){return id<=3?'Alliance':id<=6?'Horde':'Neutral';}
 function timeLeft(expires){const seconds=Number(expires)-Date.now()/1000;return seconds<=0?'Awaiting removal':seconds<1800?'Under 30 minutes':seconds<7200?'30 min – 2 hours':seconds<43200?'2 – 12 hours':'Over 12 hours';}
 function renderDetail(data){const item=data.items[0];if(!item){placeholder('This item no longer has active auctions in this house. Refresh the market to see current stock.');return;}
 const detail=$('detail'),head=el('header',undefined,'detail-heading'),title=el('div');title.append(itemTitle(item),el('p',`Item level ${item.level} · Requires level ${item.required_level} · #${item.id}`));head.append(icon(item),title);const cards=el('div',undefined,'price-cards');cards.append(card('Minimum buyout / item',item.unit_price,true),card('Minimum current bid / item',item.bid_price,true),card('Available quantity',item.quantity),card('Active auctions',item.auctions));detail.replaceChildren(closeButton(),head,cards,el('p','Base item types are grouped together. Random properties and enchantments can differ between individual listings. Tooltips include server effects and set requirements where available; active bonuses and combat totals are not simulated.','detail-note'));
 const sell=el('p','Vendor sell price / item: ');sell.append(money(item.sell_price||0));detail.append(sell);if(item.description)detail.append(el('p',item.description,'tooltip-description'));if(item.required_skill)detail.append(el('p','Requires profession skill #'+item.required_skill+' at '+item.skill_rank));
 detail.append(el('h4','Current buyout distribution','detail-subheading'));if(data.prices.length){const chart=el('div',undefined,'price-chart');chart.setAttribute('role','img');chart.setAttribute('aria-label','Current stock by unit buyout price, from lowest to highest. Each bar describes its price and quantity.');const prices=data.prices,max=Math.max(...prices.map(p=>Number(p.quantity)));const bucketSize=Math.max(1,Math.ceil(prices.length/32)),buckets=[];for(let i=0;i<prices.length;i+=bucketSize){const group=prices.slice(i,i+bucketSize);buckets.push({low:group[0].unit_price,high:group.at(-1).unit_price,quantity:group.reduce((a,p)=>a+Number(p.quantity),0)});}const peak=Math.max(max,...buckets.map(p=>p.quantity));for(const p of buckets){const bar=el('div',undefined,'price-bar level-'+Math.max(1,Math.ceil(p.quantity/peak*8)));bar.tabIndex=0;bar.title=`${Number(p.low).toFixed(2)} – ${Number(p.high).toFixed(2)} copper per item · ${p.quantity} items`;bar.setAttribute('aria-label',`${Number(p.low).toFixed(2)} to ${Number(p.high).toFixed(2)} copper per item; ${p.quantity} items`);chart.append(bar);}const labels=el('div',undefined,'chart-labels');labels.append(money(prices[0].unit_price),money(prices.at(-1).unit_price));detail.append(chart,labels,el('p',data.prices_truncated?'Lowest 200 price points shown. Current listings only; no historical prices recorded.':'Stock at each buyout price, lowest to highest. Current listings only; no historical prices recorded.','detail-note'));}else detail.append(el('p','These auctions accept bids only.','detail-note'));
 detail.append(el('h4','Current listings','detail-subheading'));const scroll=el('div',undefined,'listing-scroll'),table=el('table',undefined,'listing-table'),thead=el('thead'),hr=el('tr');for(const label of ['Seller / time left','Stack','Buyout / item','Stack total']){const th=el('th',label);th.scope='col';hr.append(th);}thead.append(hr);table.append(thead);const tbody=el('tbody');for(const listing of data.listings){const row=el('tr'),seller=el('td',listing.seller);seller.append(el('small',houseName(listing.house)+' · '+timeLeft(listing.expires)));if(listing.random_property)seller.append(el('small','Random property #'+listing.random_property));if(listing.enchantments?.split(/\s+/).some(v=>Number(v)>0))seller.append(el('small','Enchanted variant'));const unit=el('td'),total=el('td');unit.append(money(listing.unit_price));total.append(listing.buyout?money(listing.buyout):el('span','Bid only'));total.append(el('small','Bid: '+Number(listing.bid).toLocaleString()+' copper / stack'));row.append(seller,el('td',listing.quantity),unit,total);tbody.append(row);}table.append(tbody);scroll.append(table);detail.append(scroll);const pages=Math.max(1,Math.ceil(item.auctions/data.page_size)),pager=el('div',undefined,'listing-pagination'),prev=el('button','‹ Previous','metal-button'),next=el('button','Next ›','metal-button');prev.type=next.type='button';prev.disabled=listingPage<=1;next.disabled=listingPage>=pages;prev.addEventListener('click',()=>{--listingPage;loadDetail();});next.addEventListener('click',()=>{++listingPage;loadDetail();});pager.append(prev,el('span',`Listings ${listingPage} / ${pages}`),next);detail.append(pager,el('p','Observed '+new Date(data.refreshed_at).toLocaleTimeString()+'. Expired auctions are excluded. Bids shown are current amounts, not the next required bid.','detail-note'));}
 async function loadDetail(){const version=++detailVersion;detailController?.abort();detailController=new AbortController();placeholder('Reading listings…');try{const p=new URLSearchParams({house:activeParams.get('house'),id:String(selected),page:String(listingPage)});const result=await request('/api/auctions/item?'+p,detailController.signal);if(version===detailVersion)renderDetail(result);}catch(e){if(e.name!=='AbortError'&&version===detailVersion)placeholder(e.message);}}
 $('search-form').addEventListener('submit',e=>{e.preventDefault();page=1;load();});
 $('house').addEventListener('change',()=>{page=1;load();});
 $('sort').addEventListener('change',()=>{page=1;load();});
 for(const button of document.querySelectorAll('.market-table th button'))button.addEventListener('click',()=>{const values=pairs[button.dataset.sort];$('sort').value=$('sort').value===values[0]?values[1]:values[0];page=1;load();});
 $('refresh').addEventListener('click',load);
 $('previous').addEventListener('click',()=>{--page;load();});$('next').addEventListener('click',()=>{++page;load();});
 $('filter-toggle').addEventListener('click',()=>{$('filters').hidden=!$('filters').hidden;$('filter-toggle').setAttribute('aria-expanded',String(!$('filters').hidden));});
 $('reset').addEventListener('click',()=>{$('search').value='';$('quality').value='';$('min-level').value='';$('max-level').value='';selectNode(treeNodes[0],false);page=1;load();});
 $('fullscreen').addEventListener('click',async()=>{hideTooltip();try{if(document.fullscreenElement)await document.exitFullscreen();else await $('exchange').requestFullscreen();}catch{$('category-status').textContent='Full screen is unavailable in this browser.';}});
 document.addEventListener('fullscreenchange',()=>{const text=document.fullscreenElement?'Exit full screen':'Use full screen';$('fullscreen').setAttribute('aria-label',text);$('fullscreen').title=text;});
 document.addEventListener('keydown',event=>{if(event.key==='Escape'){hideTooltip();if(!$('detail').hidden)closeDetail();}});
 $('items').parentElement.parentElement.addEventListener('scroll',hideTooltip,true);window.addEventListener('resize',hideTooltip);
 const initial=new URLSearchParams(location.search);
 for(const [key,id] of [['house','house'],['q','search'],['quality','quality'],['min','min-level'],['max','max-level'],['sort','sort']])if(initial.has(key))$(id).value=initial.get(key);
 if(!$('house').value)$('house').value='all';if(!$('sort').value)$('sort').value='price';
 // Header sorts for recipe skill have no separate menu entries until used.
 for(const [value,label] of [['skill','Highest skill'],['skill_asc','Lowest skill'],['auctions_asc','Fewest auctions']]){const option=el('option',label);option.value=value;$('sort').append(option);}
 if(['skill','skill_asc','auctions_asc'].includes(initial.get('sort')))$('sort').value=initial.get('sort');
 const match=treeNodes.filter(n=>String(n.values.category??'')===(initial.get('category')||'')&&String(n.values.subclass??'')===(initial.get('subclass')||'')&&String(n.values.slot??'')===(initial.get('slot')||'')).at(-1)||treeNodes[0];
 for(const n of treeNodes)if(match.key.startsWith(n.key+'/'))expanded.add(n.key);
 if(match.children)expanded.add(match.key);selectNode(match,false);
 const initialPage=Number(initial.get('page'));if(Number.isInteger(initialPage)&&initialPage>=1&&initialPage<=10000)page=initialPage;
 if(['quality','min','max'].some(k=>initial.get(k))){$('filters').hidden=false;$('filter-toggle').setAttribute('aria-expanded','true');}load();
})();
