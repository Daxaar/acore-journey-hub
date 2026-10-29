'use strict';
const $=id=>document.getElementById(id);
const categories=['Adventures','Guild Business','Notable Characters','Disasters'];
const initialParams=new URLSearchParams(location.search);
let token=null,selected=initialParams.get('id'),entry=null,listing=null,page=0;
let groups={selected:null,groups:[]},watched=[],draftCharacters=[],draftGroups=[],suggestionTouched=false;
let listRequest=0,detailRequest=0,editing=null,dirty=false,saving=false,opener=null;
function node(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
function error(message){$('journal-error').textContent=message||'';$('journal-error').hidden=!message;}
function today(){const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
function dateLabel(day){return new Date(day+'T12:00:00').toLocaleDateString(undefined,{year:'numeric',month:'long',day:'numeric'});}
async function request(url,options={}){
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),60000);
 try{const response=await fetch(url,{cache:'no-store',...options,signal:controller.signal});const result=await response.json();
  if(!response.ok||result.ok===false)throw new Error(result.error||'The archive could not be reached.');return result;
 }catch(e){if(e.name==='AbortError')throw new Error('The archive request timed out. Please retry.');throw e;}
 finally{clearTimeout(timeout);}
}
function knownNames(){return [...new Set([...(listing?.characters||[]),...groups.groups.flatMap(g=>g.members),...watched,...draftCharacters,...draftGroups.flatMap(g=>g.members)])].sort((a,b)=>a.localeCompare(b));}
function peopleNames(people){
 const parts=String(people||'').split(/[,;\n]+|\s+(?:and|&)\s+/i).map(s=>s.trim()).filter(s=>/^[A-Z][A-Za-z]{1,11}$/.test(s));
 const words=new Set((String(people||'').match(/[A-Za-z]+/g)||[]).map(s=>s.toLowerCase()));
 return [...new Set([...parts,...knownNames().filter(name=>words.has(name.toLowerCase()))].map(name=>name[0].toUpperCase()+name.slice(1).toLowerCase()))];
}
function renderNameOptions(){
 $('journal-character-options').replaceChildren(...knownNames().map(name=>{const option=node('option');option.value=name;return option;}));
 $('journal-character-clear').hidden=!$('journal-character').value;
}
function saveURL(){
 const params=new URLSearchParams();if(selected)params.set('id',selected);
 for(const [key,id] of [['q','journal-search'],['character','journal-character'],['category','journal-category']])if($(id).value.trim())params.set(key,$(id).value.trim());
 if($('journal-order').value==='oldest')params.set('order','oldest');if(page)params.set('page',page);
 history.replaceState(null,'','/journal'+(params.size?'?'+params:''));
}
function filterCharacter(name){$('journal-character').value=name;page=0;selected=null;renderNameOptions();loadList();}
function characterChip(name){const button=node('button',name,'journal-character-tag');button.type='button';button.title='Show chronicles involving '+name;button.addEventListener('click',()=>filterCharacter(name));return button;}
function renderEntryTags(pane){
 const names=[...new Set([...(entry.character_tags||[]),...peopleNames(entry.people)])];
 if(!names.length&&!(entry.group_tags||[]).length)return;
 pane.append(node('p','Characters in this account','journal-character-heading'));
 const direct=node('div',null,'journal-tags');for(const name of names)direct.append(characterChip(name));if(names.length)pane.append(direct);
 for(const group of entry.group_tags||[]){const section=node('div',null,'journal-tag-group'),members=node('div',null,'journal-tags');section.append(node('span',group.name+' · tagged group'));for(const name of group.members)members.append(characterChip(name));section.append(members);pane.append(section);}
}
function renderList(){
 $('journal-count').textContent=listing.total+' '+(listing.total===1?'record':'records')+' in the register';
 $('journal-list').replaceChildren(...listing.entries.map(item=>{
  const b=node('button',null,'chronicle-link');b.type='button';b.dataset.entryId=item.id;b.setAttribute('aria-pressed',String(item.id===selected));
  b.append(node('strong',item.title),node('small',dateLabel(item.entry_date)+' · '+item.category),node('small',(item.location||'')+(item.image_count?' · '+item.image_count+' illustration'+(item.image_count===1?'':'s'):'')));
  b.addEventListener('click',()=>select(item.id));return b;
 }));
 if(!listing.entries.length)$('journal-list').append(node('p','No chronicles match this register.','archive-status'));
 $('journal-page').textContent=`${listing.page+1} / ${Math.max(1,Math.ceil(listing.total/50))}`;
 $('journal-prev').disabled=page===0;$('journal-next').disabled=(page+1)*50>=listing.total;
}
function empty(){entry=null;$('journal-page-content').replaceChildren(node('div','The first page awaits. Inscribe an account, or choose another search.','archive-empty'));}
async function loadList(){
 const serial=++listRequest;++detailRequest;error('');
 try{
  const params=new URLSearchParams({q:$('journal-search').value.trim(),category:$('journal-category').value,order:$('journal-order').value,character:$('journal-character').value.trim(),page});
  const result=await request('/api/journal?'+params);if(serial!==listRequest)return;listing=result.result;renderNameOptions();
  if(page>0&&!listing.entries.length){page=0;return loadList();}
  if(!selected)selected=listing.entries[0]?.id||null;renderList();
  if(selected)await select(selected);else {empty();saveURL();}
 }catch(e){if(serial===listRequest)error(e.message+(listing?' The last successful register is still shown.':''));}
}
async function select(id){
 selected=id;saveURL();
 document.querySelectorAll('.chronicle-link').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.entryId===id)));
 const serial=++detailRequest;if(entry?.id!==id){entry=null;$('journal-page-content').replaceChildren(node('p','Unfolding the record…'));}
 try{const result=await request('/api/journal?id='+encodeURIComponent(id));if(serial!==detailRequest)return;entry=result.entry;renderEntry();}
 catch(e){if(serial===detailRequest)error(e.message);}
}
function story(text){
 const container=node('div',null,'journal-story');let lines=[],quoted=null;
 const flush=()=>{if(!lines.length)return;const p=node('p',lines.join('\n'));if(quoted){const block=node('blockquote');block.append(p);container.append(block);}else container.append(p);lines=[];};
 for(const line of text.replace(/\r\n?/g,'\n').split('\n')){
  if(!line.trim()){if(!quoted)flush();else lines.push('');continue;}
  const quote=/^\s*>/.test(line);if(quoted!==null&&quoted!==quote)flush();quoted=quote;
  lines.push(quote?line.replace(/^\s*> ?/,''):line);
 }flush();return container;
}
function renderEntry(){
 const pane=$('journal-page-content');pane.replaceChildren();
 const prelude=node('div',null,'document-prelude');prelude.append(node('span',entry.category),node('span','Record '+entry.id.slice(0,8).toUpperCase()));
 pane.append(prelude,node('h2',entry.title),node('p',[entry.date_label||dateLabel(entry.entry_date),entry.location,entry.people].filter(Boolean).join(' · '),'document-context'),node('div','❧','document-ornament'),story(entry.story));
 renderEntryTags(pane);
 if(entry.screenshots.length){const gallery=node('div',null,'journal-gallery');
  for(const image of entry.screenshots){const figure=node('figure'),a=node('a'),img=node('img');a.href='/journal-images/'+image.id;a.target='_blank';a.rel='noopener';img.src=a.href;img.alt=image.name;img.loading='lazy';a.append(img);figure.append(a,node('figcaption',image.name));gallery.append(figure);}pane.append(gallery);
 }
 const foot=node('div',null,'document-attestation');foot.append(node('p','Entered into the archive on '+new Date(entry.created_at).toLocaleDateString()+'.'),node('p','Event dated '+dateLabel(entry.entry_date)+'.'+(entry.revision>1?' Amended under seal · revision '+entry.revision+'.':'')));
 pane.append(foot);const actions=node('div',null,'document-actions'),edit=node('button','✒ Amend this record'),remove=node('button','Remove entry');edit.type=remove.type='button';
 edit.addEventListener('click',()=>openEditor(entry,edit));remove.addEventListener('click',()=>removeEntry(remove));actions.append(edit,remove);pane.append(actions);
}
function openEditor(value=null,button=$('journal-new')){
 if(saving)return;opener=button;editing=value;dirty=false;$('journal-form').reset();$('editor-error').textContent='';
 $('editor-title').textContent=value?'Amend a chronicle':'Inscribe a chronicle';
 for(const key of ['title','story','date_label','location','people'])$('entry-'+key.replace('_','-')).value=value?.[key]||'';
 draftCharacters=[...(value?.character_tags||[])];draftGroups=(value?.group_tags||[]).map(g=>({...g,members:[...g.members]}));suggestionTouched=false;renderTagGroupPicker();renderTagEditor();
 refreshTagSuggestions();
 $('entry-date').value=value?.entry_date||today();$('entry-category').value=value?.category||'Adventures';
 $('entry-existing-images').replaceChildren(...(value?.screenshots||[]).map(image=>{
  const label=node('label'),check=node('input');check.type='checkbox';check.value=image.id;label.append(check,document.createTextNode('Remove illustration: '+image.name));return label;
 }));$('entry-pending-images').replaceChildren();$('journal-editor').showModal();$('entry-title').focus();
}
function closeEditor(){if(saving)return;if(dirty&&!confirm('Discard the unsealed changes to this account?'))return;dirty=false;$('journal-editor').close();opener?.focus();}
function base64(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('Could not read '+file.name));reader.readAsDataURL(file);});}
$('journal-form').addEventListener('input',()=>{dirty=true;});
$('entry-images').addEventListener('change',()=>{
 dirty=true;$('entry-pending-images').replaceChildren(...[...$('entry-images').files].map(file=>node('p',file.name+' · '+(file.size/1024/1024).toFixed(1)+' MiB')));
});
$('journal-form').addEventListener('submit',async e=>{
 e.preventDefault();if(saving)return;saving=true;$('editor-error').textContent='';
 const controls=[...$('journal-form').querySelectorAll('input,textarea,select,button')];controls.forEach(c=>c.disabled=true);
 try{
  const files=[...$('entry-images').files],removed=[...document.querySelectorAll('#entry-existing-images input:checked')].map(i=>i.value);
  if(files.length+(editing?.screenshots.length||0)-removed.length>4)throw new Error('Keep up to four illustrations per entry.');
  for(const f of files)if(f.size>5*1024*1024||!['image/png','image/jpeg'].includes(f.type))throw new Error('Use PNG or JPEG screenshots up to 5 MiB each.');
  const payload={action:'save',id:editing?.id||null,revision:editing?.revision||null,entry_date:$('entry-date').value,category:$('entry-category').value,remove_images:removed};
  for(const key of ['title','story','date_label','location','people'])payload[key]=$('entry-'+key.replace('_','-')).value;
  payload.character_tags=[...draftCharacters];payload.group_tags=draftGroups.map(g=>({...g,members:[...g.members]}));
  payload.images=await Promise.all(files.map(async file=>({name:file.name,data:await base64(file)})));
  if(!token)token=(await request('/api/session')).token;
  const result=await request('/api/journal',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':token},body:JSON.stringify(payload)});
  selected=result.entry.id;dirty=false;$('journal-editor').close();$('journal-status').textContent='The account has been sealed into the archive.';
  $('journal-search').value='';$('journal-character').value='';$('journal-category').value='';page=0;await loadList();opener?.focus();
 }catch(e){$('editor-error').textContent=e.message+' Your unsealed account is still here.';}
 finally{saving=false;controls.forEach(c=>c.disabled=false);if($('journal-editor').open){renderTagGroupPicker();renderTagEditor();}}
});
async function removeEntry(button){
 if(!entry||!confirm('Permanently remove “'+entry.title+'” and its illustrations from the journal?'))return;
 button.disabled=true;
 try{if(!token)token=(await request('/api/session')).token;
  await request('/api/journal',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':token},body:JSON.stringify({action:'delete',id:entry.id,revision:entry.revision})});
  selected=null;entry=null;saveURL();$('journal-status').textContent='The entry has been removed.';await loadList();
 }catch(e){error(e.message);button.disabled=false;}
}
$('journal-new').addEventListener('click',()=>openEditor());$('entry-cancel').addEventListener('click',closeEditor);
$('journal-editor').addEventListener('cancel',e=>{e.preventDefault();closeEditor();});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
$('journal-filters').addEventListener('submit',e=>{e.preventDefault();page=0;selected=null;loadList();});
for(const id of ['journal-category','journal-order'])$(id).addEventListener('change',()=>{page=0;selected=null;loadList();});
$('journal-prev').addEventListener('click',()=>{if(page>0){--page;selected=null;loadList();}});$('journal-next').addEventListener('click',()=>{++page;selected=null;loadList();});
for(const category of categories){const a=node('option',category);a.value=category;$('journal-category').append(a);const b=a.cloneNode(true);$('entry-category').append(b);}
for(const [key,id] of [['q','journal-search'],['character','journal-character'],['category','journal-category'],['order','journal-order']])if(initialParams.has(key))$(id).value=initialParams.get(key);
if(!$('journal-order').value)$('journal-order').value='newest';
if(/^\d{1,5}$/.test(initialParams.get('page')||''))page=Math.min(10000,Number(initialParams.get('page')));
refreshTagSuggestions();loadList();

function renderTagGroupPicker(){
 const select=$('entry-tag-group'),previous=select.value;
 select.replaceChildren(...groups.groups.map(group=>{const option=node('option',group.name);option.value=group.id;return option;}));
 if(!groups.groups.length){const option=node('option','No saved groups');option.value='';select.append(option);}
 select.value=(suggestionTouched&&groups.groups.some(g=>g.id===previous))?previous:groups.selected||'';
 select.disabled=!groups.groups.length;$('entry-tag-whole-group').disabled=!groups.groups.length;
}
function toggleCharacter(name){
 const index=draftCharacters.indexOf(name);if(index<0)draftCharacters.push(name);else draftCharacters.splice(index,1);dirty=true;renderTagEditor();
 [...$('entry-tag-characters').querySelectorAll('button')].find(b=>b.dataset.character===name)?.focus({preventScroll:true});
}
function renderOtherCharacters(){
 const select=$('entry-tag-name'),previous=select.value;
 const group=groups.groups.find(g=>g.id===$('entry-tag-group').value);
 const excluded=new Set([...(group?.members||[]),...draftCharacters,...draftGroups.flatMap(g=>g.members)].map(name=>name.toLowerCase()));
 const available=knownNames().filter(name=>!excluded.has(name.toLowerCase()));
 const placeholder=node('option',available.length?'Choose a character…':'No other characters available');placeholder.value='';
 select.replaceChildren(placeholder,...available.map(name=>{const option=node('option',name);option.value=name;return option;}));
 select.value=available.includes(previous)?previous:'';select.disabled=!available.length;
 $('entry-tag-add').disabled=!select.value;
}
function renderTagEditor(){
 renderNameOptions();const tagged=$('entry-tags');tagged.replaceChildren();
 for(const name of draftCharacters){const button=node('button',name+' ×','journal-tag-selected');button.type='button';button.setAttribute('aria-label','Remove character tag '+name);button.addEventListener('click',()=>{draftCharacters=draftCharacters.filter(n=>n!==name);dirty=true;renderTagEditor();});tagged.append(button);}
 for(const group of draftGroups){const button=node('button',group.name+' · '+group.members.length+' members ×','journal-group-tag journal-tag-selected');button.type='button';button.title=group.members.join(', ');button.setAttribute('aria-label','Remove group tag '+group.name);button.addEventListener('click',()=>{draftGroups=draftGroups.filter(g=>g.id!==group.id);dirty=true;renderTagEditor();});tagged.append(button);}
 const group=groups.groups.find(g=>g.id===$('entry-tag-group').value),suggestions=$('entry-tag-characters');suggestions.replaceChildren();
 for(const name of group?.members||[]){const button=node('button',name);button.type='button';button.dataset.character=name;button.setAttribute('aria-pressed',String(draftCharacters.includes(name)));button.addEventListener('click',()=>toggleCharacter(name));suggestions.append(button);}
 const people=$('entry-people-suggestions');people.replaceChildren();const mentioned=peopleNames($('entry-people').value).filter(n=>!draftCharacters.includes(n));
 if(mentioned.length){people.append(node('span','From Persons Concerned:'));for(const name of mentioned){const button=node('button','+ '+name);button.type='button';button.addEventListener('click',()=>{draftCharacters.push(name);dirty=true;renderTagEditor();});people.append(button);}}
 renderOtherCharacters();
 $('entry-tag-status').textContent=draftCharacters.length+' character tags · '+draftGroups.length+' group tags. Group membership is saved with the entry.';
}
async function refreshTagSuggestions(){
 try{const session=await request('/api/session');token=session.token;groups=session.groups||{selected:null,groups:[]};watched=session.bots||[];renderNameOptions();if($('journal-editor').open&&!saving){renderTagGroupPicker();renderTagEditor();}}
 catch{if($('journal-editor').open)$('entry-tag-status').textContent='Group suggestions unavailable. You can still add character names below.';}
}
$('entry-tag-group').addEventListener('change',()=>{suggestionTouched=true;renderTagEditor();});
$('entry-tag-whole-group').addEventListener('click',()=>{const group=groups.groups.find(g=>g.id===$('entry-tag-group').value);if(!group)return;draftGroups=draftGroups.filter(g=>g.id!==group.id);draftGroups.push({id:group.id,name:group.name,members:[...group.members]});dirty=true;renderTagEditor();});
function addCharacterTag(){const name=$('entry-tag-name').value;if(!name||$('entry-tag-name').disabled)return;if(!draftCharacters.includes(name))draftCharacters.push(name);$('entry-tag-name').value='';dirty=true;renderTagEditor();}
$('entry-tag-add').addEventListener('click',addCharacterTag);$('entry-tag-name').addEventListener('change',()=>{$('entry-tag-add').disabled=!$('entry-tag-name').value;});
$('entry-people').addEventListener('input',renderTagEditor);
$('journal-character-clear').addEventListener('click',()=>filterCharacter(''));
$('journal-character').addEventListener('input',()=>{$('journal-character-clear').hidden=!$('journal-character').value;});
$('journal-character').addEventListener('change',()=>{if($('journal-character').checkValidity()){page=0;selected=null;loadList();}});
