'use strict';
window.JourneyHubSkills = (() => {
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
  const trainingText=skill=>`${skill.name}: ${skill.training.rank} training available (${skill.value}/${skill.max} → cap ${skill.training.cap}; requires skill ${skill.training.required_skill}, level ${skill.training.required_level}).`;
  function bar(skill,interactive=true) {
    const row=node(interactive?'button':'div',null,'game-skill-row');if(interactive)row.type='button';
    const numeric=![7,8].includes(skill.category)&&skill.max>1;
    row.classList.toggle('passive',!numeric);
    if(skill.training){row.classList.add('profession-trainable');row.title=trainingText(skill);}

    const fill=node('span',null,'game-skill-fill');fill.style.width=skill.max>0?Math.max(0,Math.min(100,skill.value/skill.max*100))+'%':'0%';
    const label=node('span',skill.name,'game-skill-name'),count=node('span',numeric?`${skill.value}/${skill.max}`:'','game-skill-value');
    row.append(fill,label,count);row.setAttribute('aria-label',`${skill.name}: ${skill.value}/${skill.max} saved base skill`);
    return row;
  }
  function render(container,character) {
    container.replaceChildren();
    const frame=node('section',null,'game-skills-window');
    const title=node('header',null,'game-window-heading');title.append(node('span','✦','game-window-emblem'),node('h2',character.name),node('span','Skills','game-window-label'));frame.append(title);
    frame.append(node('div','All','game-skills-all'));
    if(!character.found){frame.append(node('p','No saved character found.','game-empty'));container.append(frame);return;}
    const list=node('div',null,'game-skills-list');const detail=node('div',null,'game-skill-detail');
    const show=skill=>{
      list.querySelectorAll('.game-skill-row').forEach(row=>row.classList.toggle('selected',row.dataset.skill===String(skill.id)));
      const title=node('h3');title.append(wowheadLink(skill.name,'skill',skill.id));detail.replaceChildren(title,node('p',skill.description||'No additional skill description is stored.'),node('p',`${skill.value}/${skill.max} · saved base values`,'game-detail-note'));
      if(skill.profession){const link=node('a','Open profession →');link.href='/professions?name='+encodeURIComponent(character.name)+'&skill='+skill.id;detail.append(link);}
    };
    const groups=new Map();
    for(const skill of character.skills){
      let section=groups.get(skill.group);
      if(!section){section=node('details',null,'game-skill-group');section.open=true;section.append(node('summary',skill.group));groups.set(skill.group,section);list.append(section);}
      const row=bar(skill);row.dataset.skill=skill.id;row.addEventListener('click',()=>show(skill));section.append(row);
    }
    if(!character.skills.length)list.append(node('p','No saved skills were found.','game-empty'));
    detail.append(node('p','Select a skill to see its description.','game-detail-note'));
    frame.append(list,detail,node('p','Saved base skills · Equipment, racial and temporary bonuses are not calculated.','game-skills-note'));
    container.append(frame);
  }
  return {bar,render,trainingText};
})();
