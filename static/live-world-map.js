'use strict';

window.LiveWorldMap = (() => {
  const names = {0:'Eastern Kingdoms', 1:'Kalimdor', 530:'Outland', 571:'Northrend'};
  const $ = id => document.getElementById(id);
  let metadata, useBackgrounds = false;
  let continent = 0, zoom = 1, center = [500, 335], current, selectZone, selectCharacter;
  const tileAvailability = new Map();
  const surface = $('live-map-surface');
  const hoverName = $('live-map-hover-name');
  let pointer = null;
  function showZoneName(target) {
    const zone = target?.closest?.('.live-map-zone');
    hoverName.textContent = zone?.dataset.zoneName || '';
    hoverName.hidden = !hoverName.textContent;
  }
  surface.addEventListener('pointermove', event => {
    pointer = [event.clientX, event.clientY];
    showZoneName(event.target);
  });
  surface.addEventListener('pointerleave', () => {
    pointer = null;
    showZoneName(null);
  });
  surface.addEventListener('focusin', event => showZoneName(event.target));
  surface.addEventListener('focusout', event => showZoneName(event.relatedTarget));
  const picker = $('live-map-continent');
  for (const [id, name] of Object.entries(names)) picker.add(new Option(name, id));

  function project(x, y, bounds) {
    if (!bounds || !Number.isFinite(x) || !Number.isFinite(y)) return null;
    const [x1,x2,y1,y2] = bounds;
    return [1000 * (y-y1)/(y2-y1), 670 * (x-x1)/(x2-x1)];
  }

  function zoneInfo(map, zone) {
    return metadata?.zones[map + ':' + zone];
  }

  function svg(tag, attrs, text) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if (text) node.textContent = text;
    return node;
  }

  function activate(node, label, callback) {
    node.setAttribute('role', 'button');
    node.setAttribute('tabindex', '0');
    node.setAttribute('aria-label', label);
    node.append(svg('title', {}, label));
    node.addEventListener('click', callback);
    node.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        callback();
      }
    });
  }

  function makeBackground(key, selected) {
    const [map, zone] = selected || [continent, 0];
    const route = '/live-world-tiles/'+map+'/'+zone+'/';
    const result = tileAvailability.get(key);
    if (result === undefined) {
      tileAvailability.set(key, 'pending');
      fetch(route+'index').then(response => response.ok ? response.json() : null)
        .then(data => { tileAvailability.set(key, data?.tiles === 12 ? data : false); draw(); })
        .catch(() => { tileAvailability.set(key, false); draw(); });
      return null;
    }
    if (result === 'pending') return null;
    if (!result) return svg('image', {
      href:'/live-world-background/'+key+'.webp', width:1000, height:670,
      preserveAspectRatio:'none', 'data-map-background':key, 'aria-hidden':'true'
    });
    const layer = svg('svg', {
      width:1000,height:670,viewBox:'0 0 1002 668',preserveAspectRatio:'none',
      'data-map-background':key,'aria-hidden':'true'
    });
    for (let index=0;index<12;index++) {
      layer.append(svg('image', {
        href:route+(index+1)+'.png', x:(index%4)*256, y:Math.floor(index/4)*256,
        width:256, height:256
      }));
    }
    (result.overlays || []).forEach(([x,y,width,height], index) => {
      const crop = svg('svg', {x,y,width,height,overflow:'hidden'});
      // The last BLP tile can contain power-of-two padding outside its overlay.
      const dimension = n => 2 ** Math.ceil(Math.log2(n));
      crop.append(svg('image', {
        href:route+(13+index)+'.png', width:dimension(width), height:dimension(height)
      }));
      layer.append(crop);
    });
    return layer;
  }

  function reset() { zoom = 1; center = [500, 335]; }

  function updateViewport() {
    const width = 1000 / zoom, height = 670 / zoom;
    const left = Math.min(1000-width, Math.max(0, center[0]-width/2));
    const top = Math.min(670-height, Math.max(0, center[1]-height/2));
    center = [left + width/2, top + height/2];
    surface.setAttribute('viewBox', [left,top,width,height].join(' '));
  }

  function mapPoint(x, y) {
    const matrix = surface.getScreenCTM();
    return matrix ? new DOMPoint(x, y).matrixTransform(matrix.inverse()) : null;
  }

  let drag = null;
  let suppressClick = false;
  surface.addEventListener('pointerdown', event => {
    if (event.button !== 0 || !event.isPrimary) return;
    suppressClick = false;
    if (zoom <= 1) return;
    drag = {id:event.pointerId, x:event.clientX, y:event.clientY, moved:false};
  });
  surface.addEventListener('pointermove', event => {
    if (!drag || drag.id !== event.pointerId) return;
    if (!(event.buttons & 1)) {
      endDrag(event);
      return;
    }
    if (!drag.moved) {
      if (Math.hypot(event.clientX-drag.x, event.clientY-drag.y) < 5) return;
      drag.moved = suppressClick = true;
      surface.setPointerCapture(event.pointerId);
      surface.classList.add('is-panning');
    }
    const before = mapPoint(drag.x, drag.y);
    const after = mapPoint(event.clientX, event.clientY);
    if (before && after) {
      center = [center[0]+before.x-after.x, center[1]+before.y-after.y];
      updateViewport();
    }
    drag.x = event.clientX;
    drag.y = event.clientY;
  });
  function endDrag(event) {
    if (!drag || drag.id !== event.pointerId) return;
    drag = null;
    surface.classList.remove('is-panning');
  }
  for (const event of ['pointerup','pointercancel','lostpointercapture']) {
    surface.addEventListener(event, endDrag);
  }
  surface.addEventListener('pointerleave', event => {
    if (!drag?.moved) endDrag(event);
  });
  surface.addEventListener('click', event => {
    if (!suppressClick || event.detail === 0) return;
    suppressClick = false;
    event.preventDefault();
    event.stopPropagation();
  }, true);
  surface.addEventListener('wheel', event => {
    if (!event.ctrlKey || !event.deltaY) return;
    event.preventDefault();
    const anchor = mapPoint(event.clientX, event.clientY);
    const nextZoom = Math.min(8, Math.max(1, zoom * (event.deltaY < 0 ? 1.25 : 0.8)));
    if (!anchor || nextZoom === zoom) return;
    const scale = zoom/nextZoom;
    center = [anchor.x + (center[0]-anchor.x)*scale, anchor.y + (center[1]-anchor.y)*scale];
    zoom = nextZoom;
    draw();
  }, {passive:false});

  function draw() {
    if (!current) return;
    const {data, selected} = current;
    const zone = selected && zoneInfo(...selected);
    const bounds = selected ? zone?.bounds : metadata?.maps[continent];
    updateViewport();
    showZoneName(null);
    const backgroundKey = useBackgrounds && bounds
      ? (selected ? 'zone-'+selected.join('-') : 'continent-'+continent)
      : null;
    const oldBackground = surface.querySelector('[data-map-background]');
    const background = oldBackground?.dataset.mapBackground === backgroundKey ? oldBackground : null;
    for (const child of [...surface.children]) if (child !== background) child.remove();
    if (backgroundKey && !background) {
      const next = makeBackground(backgroundKey, selected);
      if (next) surface.append(next);
    }
    surface.classList.toggle('can-pan', zoom > 1);
    $('live-map-back').hidden = !selected;
    const zoneTitle = zone?.name || $('zone-title').textContent;
    if (selected && zone?.name) $('zone-title').textContent = zoneTitle;
    $('live-map-title').textContent = selected ? zoneTitle : names[continent];
    $('live-map-zoom-out').disabled = zoom === 1;
    $('live-map-zoom-in').disabled = zoom >= 8;
    if (!bounds || data.state !== 'running') {
      $('live-map-note').textContent = data.state !== 'running' ? 'Live locations are unavailable while capture is off, starting or stale.'
        : metadata ? 'This zone has no supported outdoor map bounds. Use the character table below.'
        : 'Map bounds are unavailable. Prepare them from a local Wrath client.';
      return;
    }
    for (let n=1; n<10; n++) {
      surface.append(svg('path',{d:'M'+n*100+' 0 V670 M0 '+n*67+' H1000',class:'live-map-grid'}));
    }
    if (!selected) {
      const populations = new Map(data.zones.map(area=>[area.map_id+':'+area.zone_id, area]));
      const regions = Object.entries(metadata.zones)
        .filter(([key, info]) => info.continent === continent && (info.name || populations.has(key)))
        .map(([key, info]) => {
          const [x1,x2,y1,y2] = info.bounds;
          const [x,y] = project(x1,y1,bounds);
          const [endX,endY] = project(x2,y2,bounds);
          return {key,info,x,y,endX,endY};
        }).sort((a,b)=>(b.endX-b.x)*(b.endY-b.y)-(a.endX-a.x)*(a.endY-a.y));
      for (const {key,info,x,y,endX,endY} of regions) {
        const [mapId,zoneId] = key.split(':').map(Number);
        const area = populations.get(key);
        const bots = area?.bots || 0;
        const name = info.name || area.name;
        const label = info.levels ? name+' ('+info.levels.join('–')+')' : name;
        const region = svg('g',{class:'live-map-zone','data-zone-name':label});
        region.append(svg('rect',{x,y,width:endX-x,height:endY-y}));
        if (bots) region.append(svg('text',{x:(x+endX)/2,y:(y+endY)/2},String(bots)));
        activate(region, label+', '+bots+' bots online. Open zone map', () => selectZone(mapId,zoneId));
        surface.append(region);
      }
    }
    const clusters = new Map();
    let mapped = 0, omitted = 0, otherMaps = 0;
    for (const p of data.map_points || []) {
      const info = zoneInfo(p.map_id,p.zone_id);
      if (!selected && (p.instance_id || !names[info?.continent ?? p.map_id])) {
        otherMaps++;
        continue;
      }
      if (selected ? p.map_id !== Number(selected[0]) || p.zone_id !== Number(selected[1])
                   : (info?.continent ?? p.map_id) !== continent) continue;
      const xy = project(p.x,p.y,bounds);
      if (p.instance_id || !xy || xy.some((v,i) => v < 0 || v > [1000,670][i])) {
        omitted++;
        continue;
      }
      mapped++;
      const cell = 21 / zoom;
      const key = xy.map(n=>Math.floor(n/cell)).join(':');
      if (!clusters.has(key)) clusters.set(key, []);
      clusters.get(key).push({p, xy});
    }
    for (const dots of clusters.values()) {
      const [x,y] = [0,1].map(i=>dots.reduce((sum,d)=>sum+d.xy[i],0)/dots.length);
      const cluster = dots.length > 1;
      const {p} = dots[0];
      const marker = svg('g',{class:cluster?'live-map-cluster':'live-map-dot class-'+Number(p.class)});
      marker.append(svg('circle',{cx:x,cy:y,r:(cluster?12:6)/zoom}));
      if (cluster) marker.append(svg('text',{x,y,'font-size':11/zoom},dots.length));
      activate(marker, cluster ? dots.length+' characters. Show names' : p.name+' · '+p.bot_type.replaceAll('_',' '),
        () => {
          const list = $('live-map-cluster-list');
          list.replaceChildren();
          if (!cluster) { selectCharacter(p); return; }
          for (const dot of dots) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'subtle-button class-'+Number(dot.p.class);
            button.textContent = dot.p.name;
            button.addEventListener('click', () => selectCharacter(dot.p));
            list.append(button);
          }
          if (zoom < 8) { center=[x,y]; zoom=Math.min(8, zoom*2); draw(); }
          list.firstElementChild?.focus();
        });
      surface.append(marker);
    }
    if (pointer) showZoneName(document.elementFromPoint(...pointer));
    $('live-map-note').textContent = mapped+' characters mapped'+(omitted?' · '+omitted+' outside the supported bounds or inside instances':'')+(!selected && otherMaps?' · '+otherMaps+' in instances or on unsupported maps across the realm':'')+'. Hover over a zone for its name and level range. Click a zone or character dot. Ctrl+wheel to zoom and drag to pan.';
  }

  let warmRequested = false;
  function warmMaps() {
    if (warmRequested || !useBackgrounds || !metadata || current?.data.state !== 'running') return;
    warmRequested = true;
    fetch('/api/session').then(response => response.json()).then(session =>
      fetch('/api/live-world/warm-maps', {
        method:'POST', headers:{'Content-Type':'application/json','X-Dashboard-Token':session.token}, body:'{}'
      })).catch(() => {});
  }

  function render(data, selected, onZone, onCharacter) {
    if (String(current?.selected) !== String(selected)) {
      reset();
      $('live-map-cluster-list').replaceChildren();
    }
    current = {data, selected};
    selectZone = onZone;
    selectCharacter = onCharacter;
    draw();
    warmMaps();
  }

  picker.addEventListener('change', () => {
    continent = Number(picker.value);
    reset();
    $('live-map-cluster-list').replaceChildren();
    selectZone?.();
  });
  function returnToContinent() {
    const info = current?.selected && zoneInfo(...current.selected);
    if (info && names[info.continent]) picker.value = continent = info.continent;
    selectZone?.();
  }

  $('live-map-back').addEventListener('click', returnToContinent);
  surface.addEventListener('contextmenu', event => {
    if (!current?.selected) return;
    event.preventDefault();
    returnToContinent();
  });
  $('live-map-zoom-in').addEventListener('click', () => { zoom=Math.min(8,zoom*2); draw(); });
  $('live-map-zoom-out').addEventListener('click', () => { zoom=Math.max(1,zoom/2); draw(); });
  fetch('/api/settings').then(response => response.ok ? response.json() : null)
    .then(data => { useBackgrounds = data?.settings?.map_backgrounds === true; draw(); warmMaps(); }).catch(() => {});
  fetch('/live-world-map-bounds.json').then(response => response.ok ? response.json() : null)
    .then(data => { metadata=data; draw(); warmMaps(); }).catch(() => {});
  return {render};
})();
