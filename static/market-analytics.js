'use strict';

(() => {
  const byId = id => document.getElementById(id);
  const range = byId('market-range');
  const hour = 3600000;
  const hours = {'24h':24,'7d':168,'30d':720};
  const colors = ['#6acaaa','#f5c36b','#9bb0ef'];
  const format = number => Number(number).toLocaleString();
  const percent = (count,total) => total ? (100*count/total).toFixed(1) : '0.0';
  let report, version = 0;

  function chart(canvas, series, max, unit) {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    const scale = window.devicePixelRatio || 1;
    canvas.width = width*scale;
    canvas.height = height*scale;
    const ctx = canvas.getContext('2d');
    ctx.scale(scale,scale);
    const left=48, right=width-10, top=12, bottom=height-24;
    const end=Date.now(), start=end-hours[range.value]*hour;
    const x = stamp => left + (stamp-start)/(end-start)*(right-left);
    const y = value => bottom - value/max*(bottom-top);
    ctx.font='11px system-ui';
    ctx.strokeStyle='rgba(175,175,175,.25)';
    ctx.fillStyle=getComputedStyle(canvas).color;
    for (const value of [0,max/2,max]) {
      ctx.beginPath(); ctx.moveTo(left,y(value)); ctx.lineTo(right,y(value)); ctx.stroke();
      ctx.fillText(format(Math.round(value))+unit,1,y(value)+4);
    }
    ctx.fillText(new Date(start).toLocaleDateString([], {month:'short',day:'numeric'}), left, height-5);
    ctx.textAlign='right';
    ctx.fillText('Now',right,height-5);
    for (const [points,color] of series) {
      ctx.strokeStyle=ctx.fillStyle=color;
      ctx.lineWidth=2;
      ctx.beginPath();
      points.forEach(([stamp,value],i) => {
        const gap = i && stamp-points[i-1][0]>2*hour;
        if (!i || gap) ctx.moveTo(x(stamp),y(value)); else ctx.lineTo(x(stamp),y(value));
      });
      ctx.stroke();
      for (const [stamp,value] of points) {
        ctx.beginPath(); ctx.arc(x(stamp),y(value),3,0,2*Math.PI); ctx.fill();
      }
    }
  }

  function salesList(id, rows, slow=false) {
    const list=byId(id);
    list.replaceChildren();
    const max=slow ? 1 : Math.max(1,...rows.map(row=>row.vol24));
    for (const row of rows) {
      const item=document.createElement('li');
      const name=document.createElement('strong');
      name.textContent=row.name;
      const description=document.createElement('small');
      description.textContent=format(row.vol24)+' estimated sold / '+format(row.listed)+' listed'
        +(row.sure24==null?'':' | '+format(row.sure24)+' confirmed units');
      const meter=document.createElement('meter');
      meter.max=max;
      meter.value=slow ? Math.min(1,row.vol24/row.listed) : row.vol24;
      meter.setAttribute('aria-label',row.name+(slow?' sales per listed unit':' estimated units sold'));
      item.append(name,description,meter);
      list.append(item);
    }
  }

  function render() {
    if (!report) return;
    const {local,imports,top,slow}=report;
    const last=local.at(-1);
    byId('market-coverage-chart-summary').textContent=last
      ? percent(last.forever+last.anniversary,last.total)+'% exact price matches | '
        +percent(last.covered,last.total)+'% of listings have an eligible published item ID | '+format(last.total)+' bot listings'
      : 'No local auction samples in this range.';
    const latest=imports.at(-1);
    byId('market-import-chart-summary').textContent=(latest?format(latest.item_count)+' Forever items':'No Forever snapshot in this range')
      +(last?' | '+format(last.published)+' published prices, '+format(last.anniversary_items)+' from Anniversary':'');
    const share = key => local.map(row=>[row.stamp,row.total?100*row[key]/row.total:0]);
    chart(byId('market-coverage-chart'),[
      [share('forever'),colors[0]],[share('anniversary'),colors[1]],[share('covered'),colors[2]],
    ],100,'%');
    chart(byId('market-import-chart'),[
      [imports.map(row=>[row.stamp,row.item_count]),colors[0]],
      [local.map(row=>[row.stamp,row.anniversary_items]),colors[1]],
      [local.map(row=>[row.stamp,row.published]),colors[2]],
    ],Math.max(1000,Math.ceil(Math.max(0,...imports.map(r=>r.item_count),...local.map(r=>r.published))/1000)*1000),'');
    salesList('market-top',top);
    salesList('market-slow',slow,true);
  }

  async function load() {
    const id=++version;
    const status=byId('market-analytics-status');
    status.textContent='Loading market history...';
    try {
      const response=await fetch('/api/market-preview/analytics?range='+encodeURIComponent(range.value));
      const data=await response.json();
      if (id!==version) return;
      if (!response.ok) throw new Error(data.error);
      report=data.result;
      render();
      status.textContent='Local listing history starts with the first sample. Gaps are left blank.';
    } catch (error) {
      if (id===version) status.textContent=error.message;
    }
  }
  range.addEventListener('change',load);
  window.addEventListener('resize',render);
  load();
})();
