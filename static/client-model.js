'use strict';
// On-demand static WebGL preview: no animation loop, external assets or world-server calls.
(() => {
  const fields = ['race','gender','skin','face','hairStyle','hairColor','facialStyle'];
  const figure = document.querySelector('.character-figure');
  const fallback = figure.querySelector('img');
  const caption = figure.querySelector('.figure-caption');
  const host = document.getElementById('client-model');
  const canvas = document.getElementById('model-canvas');
  let currentCharacter, currentEquipment, lastKey, generation = 0, dispose = () => {}, draw = () => {}, angle = 0, zoom = 1;
  function paperdoll() {
    dispose(); dispose = () => {}; draw = () => {};
    host.hidden = true; fallback.hidden = false; caption.textContent = 'PAPER-DOLL PREVIEW';
  }
  function render(model) {
    const gl = canvas.getContext('webgl', {alpha:true, antialias:true, preserveDrawingBuffer:true});
    if (!gl) throw new Error('WebGL unavailable');
    const resources = [];
    dispose = () => { for (const [kind,value] of resources) gl[kind](value); };
    function shader(type, source) {
      const shader = gl.createShader(type); resources.push(['deleteShader',shader]);
      gl.shaderSource(shader,source); gl.compileShader(shader);
      if (!gl.getShaderParameter(shader,gl.COMPILE_STATUS)) throw new Error('Shader unavailable');
      return shader;
    }
    const program = gl.createProgram();resources.push(['deleteProgram',program]);
    gl.attachShader(program,shader(gl.VERTEX_SHADER,`
      attribute vec3 position; attribute vec3 normal; attribute vec2 uv;
      uniform float yaw; uniform float scale; uniform float aspect; uniform float center; uniform float horizontalCenter; uniform float depth;
      varying vec2 texcoord; varying float light;
      void main() {
        float c=cos(yaw),s=sin(yaw);
        float horizontal=-position.y*c+position.x*s;
        float distance=position.x*c+position.y*s;
        gl_Position=vec4((horizontal-horizontalCenter)*scale/aspect,(position.z-center)*scale,-distance/depth,1.0);
        vec3 n=vec3(normal.x*c+normal.y*s,-normal.x*s+normal.y*c,normal.z);
        light=.55+.45*abs(dot(normalize(n),normalize(vec3(.7,-.4,.8))));texcoord=uv;
      }`));
    gl.attachShader(program,shader(gl.FRAGMENT_SHADER,`
      precision mediump float; varying vec2 texcoord; varying float light; uniform sampler2D image;
      void main(){vec4 color=texture2D(image,texcoord);if(color.a<.15)discard;gl_FragColor=vec4(color.rgb*light,color.a);}`));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program,gl.LINK_STATUS)) throw new Error('Renderer unavailable');
    gl.useProgram(program);
    const vertices = new Float32Array(model.vertices.flat()), indices = new Uint16Array(model.indices);
    const buffer = gl.createBuffer(), elements = gl.createBuffer();
    resources.push(['deleteBuffer',buffer],['deleteBuffer',elements]);
    gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,vertices,gl.STATIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,elements);gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,indices,gl.STATIC_DRAW);
    for (const [name,size,offset] of [['position',3,0],['normal',3,12],['uv',2,24]]) {
      const location=gl.getAttribLocation(program,name);gl.enableVertexAttribArray(location);gl.vertexAttribPointer(location,size,gl.FLOAT,false,32,offset);
    }
    const textures=model.textures.map(image => {
      const texture=gl.createTexture();resources.push(['deleteTexture',texture]);gl.bindTexture(gl.TEXTURE_2D,texture);
      const rgba=Uint8Array.from(atob(image.rgba),c=>c.charCodeAt(0));
      if (rgba.length!==image.width*image.height*4) throw new Error('Texture incomplete');
      gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,image.width,image.height,0,gl.RGBA,gl.UNSIGNED_BYTE,rgba);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
      return texture;
    });
    let low=Infinity,high=-Infinity,radius=0;
    for (const index of model.indices) {
      const v=model.vertices[index];low=Math.min(low,v[2]);high=Math.max(high,v[2]);radius=Math.max(radius,Math.hypot(v[0],v[1]));
    }
    if (!Number.isFinite(low) || high<=low || !radius) throw new Error('Model bounds unavailable');
    gl.enable(gl.DEPTH_TEST);gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
    const uniforms=Object.fromEntries(['yaw','scale','aspect','center','horizontalCenter','depth'].map(name=>[name,gl.getUniformLocation(program,name)]));
    angle=0;zoom=1;
    draw = () => {
      try {
        const rect=canvas.getBoundingClientRect(),pixel=Math.min(devicePixelRatio || 1,2);
        canvas.width=Math.max(1,Math.round(rect.width*pixel));canvas.height=Math.max(1,Math.round(rect.height*pixel));
        gl.viewport(0,0,canvas.width,canvas.height);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
        const aspect=canvas.width/canvas.height;
        let left=Infinity,right=-Infinity;
        for(const index of model.indices){const v=model.vertices[index],x=-v[1]*Math.cos(angle)+v[0]*Math.sin(angle);left=Math.min(left,x);right=Math.max(right,x);}
        gl.uniform1f(uniforms.horizontalCenter,(left+right)/2);
        gl.uniform1f(uniforms.yaw,angle);gl.uniform1f(uniforms.scale,Math.min(1.8/(high-low),1.8*aspect/Math.max(.01,right-left))*zoom);
        gl.uniform1f(uniforms.aspect,aspect);gl.uniform1f(uniforms.center,(low+high)/2);gl.uniform1f(uniforms.depth,radius*5);
        for (const group of model.groups) {
          gl.bindTexture(gl.TEXTURE_2D,textures[group.texture]);gl.drawElements(gl.TRIANGLES,group.count,gl.UNSIGNED_SHORT,group.start*2);
        }
        if (gl.getError()!==gl.NO_ERROR || gl.isContextLost()) throw new Error('Renderer unavailable');
      } catch (_) { paperdoll(); }
    };
    fallback.hidden=true;host.hidden=false;caption.textContent='3D EQUIPPED PREVIEW';draw();
  }
  let drag=null;
  canvas.addEventListener('pointerdown',event=>{drag=event.clientX;canvas.setPointerCapture(event.pointerId);});
  canvas.addEventListener('pointermove',event=>{if(drag!==null){angle+=(event.clientX-drag)*.015;drag=event.clientX;draw();}});
  for (const name of ['pointerup','pointercancel','lostpointercapture']) canvas.addEventListener(name,()=>{drag=null;});
  canvas.addEventListener('keydown',event=>{
    if (!['ArrowLeft','ArrowRight','+','-','0'].includes(event.key)) return;
    event.preventDefault();if(event.key==='ArrowLeft')angle-=.2;if(event.key==='ArrowRight')angle+=.2;
    if(event.key==='+')zoom=Math.min(1.8,zoom+.1);if(event.key==='-')zoom=Math.max(.6,zoom-.1);
    if(event.key==='0'){angle=0;zoom=1;}draw();
  });
  canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();paperdoll();});
  document.getElementById('model-reset').addEventListener('click',()=>{angle=0;zoom=1;draw();});
  window.addEventListener('resize',()=>draw());
  document.getElementById('model-weapon-view').addEventListener('change',()=>{if(currentCharacter)window.CharacterHubModel.update(currentCharacter,currentEquipment);});
  window.CharacterHubModel = {
    clear() { generation++;lastKey=null;paperdoll(); },
    async update(character, equipment = []) {
      currentCharacter=character;currentEquipment=equipment;
      const appearance=Object.fromEntries(fields.map(key=>[key,character[key]]));
      const gear=equipment.filter(e=>e.item).map(e=>({slot:e.slot,displayid:e.item.displayid,inventory_type:e.item.InventoryType}));
      const weaponMode=document.getElementById('model-weapon-view').value;
      const key=JSON.stringify([appearance,gear,weaponMode]);if(key===lastKey)return;
      lastKey=key;const active=++generation;paperdoll();
      try {
        const params=new URLSearchParams({...appearance,equipment:JSON.stringify(gear),weapon_mode:weaponMode});
        // Preparation reads local MPQs in one background worker. No automatic game database polling.
        for (let attempt=0;attempt<15;attempt++) {
          if(active!==generation)return;
          const response=await fetch('/api/model?'+params,{signal:AbortSignal.timeout(5000)});
          if(!response.ok) return;
          const result=await response.json();if(active!==generation)return;
          if(result.available){render(result.model);return;}
          if(!result.pending)return;
          await new Promise(resolve=>setTimeout(resolve,1000));
        }
      } catch (_) { if(active===generation)paperdoll(); }
    }
  };
})();
