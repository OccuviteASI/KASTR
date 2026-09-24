/* esm.sh - @moq/watch@0.6.0/player-DiUmUis6 */
import{Announce as Dt,Error as U,Path as D,Time as d}from"../../net@^0.4.0.target-es2022.mjs";import{Effect as M,Signal as u,getter as p,readonlys as I}from"../../signals@^0.2.4.target-es2022.mjs";import*as w from"../../hang@^0.5.0/catalog.target-es2022.mjs";import{u53 as z}from"../../hang@^0.5.0/catalog.target-es2022.mjs";import*as b from"../../hang@^0.5.0/container.target-es2022.mjs";import*as A from"../../hang@^0.5.0/util.target-es2022.mjs";import*as wt from"../../json@^0.4.0.target-es2022.mjs";import*as yt from"../../msf@^0.3.0.target-es2022.mjs";function V(t){let e=atob(t),i=new Uint8Array(e.length);for(let n=0;n<e.length;n++)i[n]=e.charCodeAt(n);return i}function et(t,e){if(t.get(e.broadcast.closed)!==void 0)return;let i=e.broadcast.track(e.track).subscribe({priority:e.priority,maxAge:e.maxAge.peek()});return t.cleanup(()=>i.close()),t.run(n=>{i.update({priority:e.priority,maxAge:n.get(e.maxAge)})}),i}async function G(t){try{return await t.next()}catch(e){if(!(e instanceof U.Stream))throw e;console.debug("media subscription ended",e);return}}var E=0,W=1,B=2,P=3,Yt=4,Vt=4294967295n;function C(t,e){return BigInt(t>>>0)<<32n|BigInt(e>>>0)}function O(t){return Number(t>>32n)|0}function qt(t){return!!(O(t)&1)}function R(t){return Number(t&Vt)|0}function Kt(t){return t<=1?1:1<<32-Math.clz32(t-1)}function vt(t,e,i,n=!1){if(t<=0)throw Error("invalid channels");if(e<=0||e>2**30)throw Error("invalid capacity");if(i<=0)throw Error("invalid sample rate");e=Kt(e);let s=new SharedArrayBuffer(t*e*Float32Array.BYTES_PER_ELEMENT),r=new SharedArrayBuffer(Yt*Int32Array.BYTES_PER_ELEMENT),a=new SharedArrayBuffer(BigInt64Array.BYTES_PER_ELEMENT),o=new Int32Array(r);return Atomics.store(o,B,1),{channels:t,capacity:e,rate:i,samples:s,control:r,state:a,buffered:n}}function st(t,e){return(t-e|0)>0?t:e}function _(t,e){return t&e-1}var Ut=class At{channels;capacity;rate;buffered;init;#t;#e;#i;#n=!1;#s=0;#r=0;#a=0;constructor(e,i){this.channels=e.channels,this.capacity=e.capacity,this.rate=e.rate,this.buffered=e.buffered,this.init=e,this.#t=new Int32Array(e.control),this.#e=new BigInt64Array(e.state),this.#i=[];for(let n=0;n<this.channels;n++)this.#i.push(new Float32Array(e.samples,n*this.capacity*Float32Array.BYTES_PER_ELEMENT,this.capacity));i!==void 0&&this.#o(i)}#o(e){if(e.channels!==this.channels||e.rate!==this.rate)return;let i=Atomics.load(e.#t,P),n=Atomics.load(e.#e,0);for(;;){let s=Atomics.load(this.#e,0);if(Atomics.load(this.#t,P)!==i||(R(n)-R(s)|0)<=0)return;let r=C(O(s),R(n));if(Atomics.compareExchange(this.#e,0,s,r)===s)return}}#c(e){for(;;){let i=Atomics.load(this.#e,0);if((e-R(i)|0)<=0)return;let n=C(O(i),e);if(Atomics.compareExchange(this.#e,0,i,n)===i)return}}#l(){for(;;){let e=Atomics.load(this.#e,0),i=C(O(e)+1|0,R(e));if(Atomics.compareExchange(this.#e,0,e,i)===e)return}}insert(e,i){if(i.length!==this.channels)throw Error("wrong number of channels");let n=Math.round(d.Second.fromMicro(e)*this.rate),s=i[0].length,r=0;if(!this.#n){this.#s=n;let y=O(Atomics.load(this.#e,0));Atomics.add(this.#t,P,1),Atomics.store(this.#e,0,C(y+2|0,0)),Atomics.store(this.#t,E,0),this.#n=!0,this.#r=0,this.#a=0}n=n-this.#s|0;let a=n+s|0,o=R(Atomics.load(this.#e,0)),c=o-n|0;if(c>0){if(c>=s)return;r=c,n=n+c|0}let l=s-r;(a-o|0)>this.capacity&&this.#c(a-this.capacity|0);let h=Atomics.load(this.#t,E),f=n-h|0;if(f>0){let y=Math.min(f,this.capacity);for(let v=0;v<this.channels;v++){let T=this.#i[v];for(let S=0;S<y;S++)T[_(h+S|0,this.capacity)]=0}}for(let y=0;y<this.channels;y++){let v=i[y],T=this.#i[y];for(let S=0;S<l;S++)T[_(n+S|0,this.capacity)]=v[r+S]}Atomics.store(this.#t,E,st(Atomics.load(this.#t,E),a));let m=R(Atomics.load(this.#e,0)),g=Atomics.load(this.#t,E),k=Atomics.load(this.#t,W);(g-m|0)>=k&&k>0&&Atomics.store(this.#t,B,0)}read(e){let i=Atomics.load(this.#e,0);if(Atomics.load(this.#t,B)===1||qt(i))return 0;let n=R(i),s=Atomics.load(this.#t,E),r=Atomics.load(this.#t,W),a=s-n|0;if(!this.buffered&&r>0&&a>r){let h=s-r|0;(h-n|0)>0&&(n=h)}let o=s-n|0,c=Math.min(o,e[0].length);if(c<=0)return(n-R(i)|0)>0&&Atomics.compareExchange(this.#e,0,i,C(O(i),n)),0;for(let h=0;h<this.channels;h++){let f=this.#i[h],m=e[h];for(let g=0;g<c;g++)m[g]=f[_(n+g|0,this.capacity)]}let l=C(O(i),n+c|0);if(Atomics.compareExchange(this.#e,0,i,l)!==i){for(let h=0;h<this.channels;h++)e[h].fill(0,0,c);return 0}return c}setLatency(e){Atomics.store(this.#t,W,e)}truncate(e){let i=Math.round(d.Second.fromMicro(e)*this.rate)-this.#s|0;if(!((Atomics.load(this.#t,E)-i|0)<=0)){for(this.#l();;){let n=Atomics.load(this.#t,E),s=st(i,R(Atomics.load(this.#e,0)));if((n-s|0)<=0||Atomics.compareExchange(this.#t,E,n,s)===n)break}this.#l()}}reset(){this.#n=!1,Atomics.store(this.#t,B,1);let e=Atomics.load(this.#t,E),i=Atomics.load(this.#e,0);Atomics.store(this.#e,0,C(O(i),e))}resize(e){let i=vt(this.channels,e,this.rate,this.buffered),n=new At(i);n.#n=this.#n,n.#s=this.#s;let s=Atomics.load(this.#e,0),r=R(s),a=Atomics.load(this.#t,E),o=Atomics.load(this.#t,W),c=Atomics.load(this.#t,B),l=a-r|0,h=Math.max(0,Math.min(l,n.capacity)),f=a-h|0;for(let m=0;m<this.channels;m++){let g=this.#i[m],k=n.#i[m];for(let y=0;y<h;y++){let v=f+y|0;k[_(v,n.capacity)]=g[_(v,this.capacity)]}}return Atomics.store(n.#t,P,Atomics.load(this.#t,P)),Atomics.store(n.#e,0,C(O(s),f)),Atomics.store(n.#t,E,a),Atomics.store(n.#t,W,o),Atomics.store(n.#t,B,c),n.#r=this.#h(r)+(f-r|0),n.#a=f,n}#h(e){return this.#r+=e-this.#a|0,this.#a=e,this.#r}#d(){return this.#h(R(Atomics.load(this.#e,0)))}get timestamp(){return d.Micro.fromSecond((this.#s+this.#d())/this.rate)}get stalled(){return Atomics.load(this.#t,B)===1}get length(){return Atomics.load(this.#t,E)-R(Atomics.load(this.#e,0))|0}},xt=class{#t;#e;#i=[];constructor(t,e){this.#t=t,this.#e=e}setHeadroom(t){this.#e=t}wait(t,e){return!this.#t||e>=(t-this.#e|0)?Promise.resolve():new Promise(i=>this.#i.push({timestamp:t,resolve:i}))}advance(t){this.#i.length!==0&&(this.#i=this.#i.filter(({timestamp:e,resolve:i})=>t<(e-this.#e|0)||(i(),!1)))}flush(){for(let{resolve:t}of this.#i)t();this.#i=[]}};function J(t,e){return d.Micro.fromSecond(t/e)}function Gt(){return!(typeof SharedArrayBuffer>"u"||typeof crossOriginIsolated<"u"&&!crossOriginIsolated)}function Jt(t,e,i,n,s=!1){return Gt()?(console.log("[audio] using SharedArrayBuffer audio buffer"),new Xt(t,e,i,n,s)):(console.warn("[audio] SharedArrayBuffer unavailable, falling back to the higher latency postMessage audio buffer. Serve the page cross-origin isolated (Cross-Origin-Opener-Policy: same-origin, Cross-Origin-Embedder-Policy: require-corp) to avoid this."),new Qt(t,e,i,n,s))}var Xt=class{rate;channels;#t;#e;#i=new u(0);timestamp=this.#i;#n=new u(!0);stalled=this.#n;#s;#r=new M;constructor(t,e,i,n,s){this.#t=t,this.channels=e,this.rate=i;let r=Math.max(i,n*2);this.#s=new xt(s,J(n,i));let a=vt(e,r,i,s);this.#e=new Ut(a),this.#e.setLatency(n);let o={type:"init-shared",...a};t.port.postMessage(o),this.#r.interval(()=>{let c=this.#e.stalled;this.#i.set(this.#e.timestamp),this.#n.set(c),c?this.#s.flush():this.#s.advance(this.#e.timestamp)},50)}insert(t,e){this.#e.insert(t,e)}setLatency(t){if(this.#s.setHeadroom(J(t,this.rate)),this.#e.capacity<t*1.5){let e=Math.max(this.rate,t*2);this.#e=this.#e.resize(e),this.#e.setLatency(t);let i={type:"init-shared",...this.#e.init};this.#t.port.postMessage(i)}else this.#e.setLatency(t)}truncate(t){this.#e.truncate(t)}reset(){this.#e.reset(),this.#s.flush()}wait(t){return this.#e.stalled?Promise.resolve():this.#s.wait(t,this.#e.timestamp)}close(){this.#s.flush(),this.#r.close()}},Qt=class{rate;channels;#t;#e=new u(0);timestamp=this.#e;#i=new u(!0);stalled=this.#i;#n;#s=new M;constructor(t,e,i,n,s){this.#t=t,this.channels=e,this.rate=i,this.#n=new xt(s,J(n,i));let r={type:"init-post",channels:e,rate:i,latency:d.Milli.fromSecond(n/i),buffered:s};t.port.postMessage(r),this.#s.event(t.port,"message",a=>{let o=a.data;o?.type==="state"&&(this.#e.set(o.timestamp),this.#i.set(o.stalled),o.stalled?this.#n.flush():this.#n.advance(o.timestamp))}),t.port.start()}insert(t,e){let i={type:"data",data:e,timestamp:t};this.#t.port.postMessage(i,e.map(n=>n.buffer))}setLatency(t){this.#n.setHeadroom(J(t,this.rate));let e={type:"latency",latency:d.Milli.fromSecond(t/this.rate)};this.#t.port.postMessage(e)}truncate(t){let e={type:"truncate",timestamp:t};this.#t.port.postMessage(e)}reset(){this.#t.port.postMessage({type:"reset"}),this.#n.flush()}wait(t){return this.#i.peek()?Promise.resolve():this.#n.wait(t,this.#e.peek())}close(){this.#n.flush(),this.#s.close()}},Zt=128,te=20,ee=1024,ie=1152,ne=576,se=32e3;function kt(t){return{codec:t.codec,container:t.container,description:t.description,sampleRate:t.sampleRate,numberOfChannels:t.numberOfChannels}}function re(t){return{broadcast:t.broadcast,decoder:kt(t)}}function ae(t){let e=(t.jitter||oe(t))??0,i=Math.ceil(Zt/t.sampleRate*1e3);return d.Milli(e+i)}function oe(t){if(t.codec.startsWith("opus"))return te;if(t.codec.startsWith("mp4a"))return Math.ceil(ee/t.sampleRate*1e3);if(t.codec==="mp3"){let e=t.sampleRate>=se?ie:ne;return Math.ceil(e/t.sampleRate*1e3)}}var ce=class{#t=!1;#e=!1;opened(){this.#t&&(this.#e=!0),this.#t=!0}takeover(){let t=this.#e;return this.#e=!1,t}};function le(t){let e=typeof t.delay=="number"?t.delay:d.Milli.zero;return d.Milli.add(e,t.media??d.Milli.zero)}var he=128;function rt(t,e){return Math.max(he,Math.ceil(t*d.Second.fromMilli(e)))}var de=new Blob([`var __defProp = Object.defineProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};

// ../net/src/time.ts
var time_exports = {};
__export(time_exports, {
  Micro: () => Micro,
  Milli: () => Milli,
  Nano: () => Nano,
  Second: () => Second,
  Timescale: () => Timescale,
  Timestamp: () => Timestamp
});
var Nano = Object.assign((value) => value, {
  zero: 0,
  fromMicro: (us) => us * 1e3,
  fromMilli: (ms) => ms * 1e6,
  fromSecond: (s) => s * 1e9,
  toMicro: (ns) => ns / 1e3,
  toMilli: (ns) => ns / 1e6,
  toSecond: (ns) => ns / 1e9,
  now: () => performance.now() * 1e6,
  add: (a, b) => a + b,
  sub: (a, b) => a - b,
  mul: (a, b) => a * b,
  div: (a, b) => a / b,
  max: (a, b) => Math.max(a, b),
  min: (a, b) => Math.min(a, b)
});
var Micro = Object.assign((value) => value, {
  zero: 0,
  fromNano: (ns) => ns / 1e3,
  fromMilli: (ms) => ms * 1e3,
  fromSecond: (s) => s * 1e6,
  toNano: (us) => us * 1e3,
  toMilli: (us) => us / 1e3,
  toSecond: (us) => us / 1e6,
  now: () => performance.now() * 1e3,
  add: (a, b) => a + b,
  sub: (a, b) => a - b,
  mul: (a, b) => a * b,
  div: (a, b) => a / b,
  max: (a, b) => Math.max(a, b),
  min: (a, b) => Math.min(a, b)
});
var Milli = Object.assign((value) => value, {
  zero: 0,
  fromNano: (ns) => ns / 1e6,
  fromMicro: (us) => us / 1e3,
  fromSecond: (s) => s * 1e3,
  toNano: (ms) => ms * 1e6,
  toMicro: (ms) => ms * 1e3,
  toSecond: (ms) => ms / 1e3,
  now: () => performance.now(),
  add: (a, b) => a + b,
  sub: (a, b) => a - b,
  mul: (a, b) => a * b,
  div: (a, b) => a / b,
  max: (a, b) => Math.max(a, b),
  min: (a, b) => Math.min(a, b)
});
var Timescale = Object.assign(
  (unitsPerSecond) => {
    if (!Number.isSafeInteger(unitsPerSecond) || unitsPerSecond <= 0) {
      throw new RangeError(\`invalid timescale: \${unitsPerSecond}\`);
    }
    return unitsPerSecond;
  },
  {
    /** One unit per second. */
    SECOND: 1,
    /** 1,000 units per second. */
    MILLI: 1e3,
    /** 1,000,000 units per second. */
    MICRO: 1e6,
    /** 1,000,000,000 units per second. */
    NANO: 1e9
  }
);
function assertTimestampValue(value) {
  if (!Number.isFinite(value) || value < 0 || value > Number.MAX_SAFE_INTEGER) {
    throw new RangeError(\`invalid timestamp: \${value}\`);
  }
}
var Timestamp = class _Timestamp {
  /** The raw value, in \`scale\` units. */
  value;
  /** Units per second the {@link value} is measured in. */
  scale;
  /** Build a timestamp of \`value\` units at \`scale\`. */
  constructor(value, scale) {
    assertTimestampValue(value);
    this.value = value;
    this.scale = Timescale(scale);
  }
  /** Monotonic now (\`performance.now()\`, milliseconds since page load), not wall-clock time. */
  static now() {
    return new _Timestamp(performance.now(), Timescale.MILLI);
  }
  /** A timestamp of \`ms\` milliseconds. */
  static fromMillis(ms) {
    return new _Timestamp(ms, Timescale.MILLI);
  }
  /** A timestamp of \`us\` microseconds. */
  static fromMicros(us) {
    return new _Timestamp(us, Timescale.MICRO);
  }
  /** This timestamp's value re-expressed at \`scale\`; throws if the result is not in the safe range. */
  as(scale) {
    const dest = Timescale(scale);
    const converted = dest === this.scale ? this.value : this.value * dest / this.scale;
    assertTimestampValue(converted);
    return converted;
  }
  /** The value in milliseconds. */
  asMillis() {
    return this.as(Timescale.MILLI);
  }
  /** The value in microseconds. */
  asMicros() {
    return this.as(Timescale.MICRO);
  }
};
var Second = Object.assign((value) => value, {
  zero: 0,
  fromNano: (ns) => ns / 1e9,
  fromMicro: (us) => us / 1e6,
  fromMilli: (ms) => ms / 1e3,
  toNano: (s) => s * 1e9,
  toMicro: (s) => s * 1e6,
  toMilli: (s) => s * 1e3,
  now: () => performance.now() / 1e3,
  add: (a, b) => a + b,
  sub: (a, b) => a - b,
  mul: (a, b) => a * b,
  div: (a, b) => a / b,
  max: (a, b) => Math.max(a, b),
  min: (a, b) => Math.min(a, b)
});

// src/audio/ring-buffer.ts
var AudioRingBuffer = class {
  #buffer;
  #writeIndex = 0;
  #readIndex = 0;
  rate;
  channels;
  #stalled = true;
  // Buffered mode: play through everything buffered without skipping ahead.
  #buffered;
  // Un-stall threshold in samples (how much to buffer before playback starts).
  #latencySamples;
  // Whether the read/write indices have been anchored to the first inserted sample.
  #anchored = false;
  constructor(props) {
    if (props.channels <= 0) throw new Error("invalid channels");
    if (props.rate <= 0) throw new Error("invalid sample rate");
    if (props.latency <= 0) throw new Error("invalid latency");
    this.#latencySamples = Math.ceil(props.rate * time_exports.Second.fromMilli(props.latency));
    if (this.#latencySamples === 0) throw new Error("empty buffer");
    this.rate = props.rate;
    this.channels = props.channels;
    this.#buffered = props.buffered ?? false;
    const capacity = this.#capacityFor(this.#latencySamples);
    this.#buffer = [];
    for (let i = 0; i < this.channels; i++) {
      this.#buffer[i] = new Float32Array(capacity);
    }
  }
  #capacityFor(latencySamples) {
    return this.#buffered ? latencySamples * 2 : latencySamples;
  }
  get stalled() {
    return this.#stalled;
  }
  get timestamp() {
    return time_exports.Micro.fromSecond(this.#readIndex / this.rate);
  }
  get length() {
    return this.#writeIndex - this.#readIndex;
  }
  get capacity() {
    return this.#buffer[0]?.length;
  }
  resize(latency) {
    this.#latencySamples = Math.ceil(this.rate * time_exports.Second.fromMilli(latency));
    const newCapacity = this.#capacityFor(this.#latencySamples);
    if (newCapacity === this.capacity) return;
    if (newCapacity === 0) throw new Error("empty buffer");
    const newBuffer = [];
    for (let i = 0; i < this.channels; i++) {
      newBuffer[i] = new Float32Array(newCapacity);
    }
    const samplesToKeep = Math.min(this.length, newCapacity);
    if (samplesToKeep > 0) {
      const copyStart = this.#writeIndex - samplesToKeep;
      for (let channel = 0; channel < this.channels; channel++) {
        const src = this.#buffer[channel];
        const dst = newBuffer[channel];
        for (let i = 0; i < samplesToKeep; i++) {
          const srcPos = (copyStart + i) % src.length;
          const dstPos = (copyStart + i) % dst.length;
          dst[dstPos] = src[srcPos];
        }
      }
    }
    this.#buffer = newBuffer;
    this.#readIndex = this.#writeIndex - samplesToKeep;
    if (samplesToKeep === 0) this.#stalled = true;
  }
  write(timestamp, data) {
    if (data.length !== this.channels) throw new Error("wrong number of channels");
    let start = Math.round(time_exports.Second.fromMicro(timestamp) * this.rate);
    let samples = data[0].length;
    if (!this.#anchored) {
      this.#readIndex = start;
      this.#writeIndex = start;
      this.#anchored = true;
    }
    let offset = this.#readIndex - start;
    if (offset > samples) {
      return;
    } else if (offset > 0) {
      samples -= offset;
      start += offset;
    } else {
      offset = 0;
    }
    const end = start + samples;
    const overflow = end - this.#readIndex - this.#buffer[0].length;
    if (overflow >= 0) {
      this.#stalled = false;
      this.#readIndex += overflow;
    }
    if (start > this.#writeIndex) {
      const gapSize = Math.min(start - this.#writeIndex, this.#buffer[0].length);
      if (gapSize === 1) {
        console.warn("floating point inaccuracy detected");
      }
      for (let channel = 0; channel < this.channels; channel++) {
        const dst = this.#buffer[channel];
        for (let i = 0; i < gapSize; i++) {
          const writePos = (this.#writeIndex + i) % dst.length;
          dst[writePos] = 0;
        }
      }
    }
    for (let channel = 0; channel < this.channels; channel++) {
      let src = data[channel];
      src = src.subarray(src.length - samples);
      const dst = this.#buffer[channel];
      if (src.length !== samples) throw new Error("mismatching number of samples");
      for (let i = 0; i < samples; i++) {
        const writePos = (start + i) % dst.length;
        dst[writePos] = src[i];
      }
    }
    if (end > this.#writeIndex) {
      this.#writeIndex = end;
    }
    if (this.#buffered && this.length >= this.#latencySamples) {
      this.#stalled = false;
    }
  }
  /**
   * Drop buffered samples at or after \`timestamp\`, keeping whatever is already due.
   *
   * A successor track overwrites the slots its own samples land on, but anything the previous
   * track wrote beyond them would otherwise still play once the successor runs out.
   */
  truncate(timestamp) {
    const target = Math.round(time_exports.Second.fromMicro(timestamp) * this.rate);
    if (target >= this.#writeIndex) return;
    this.#writeIndex = Math.max(target, this.#readIndex);
  }
  // Flush all buffered samples and re-stall, ready to anchor the next utterance.
  reset() {
    this.#readIndex = 0;
    this.#writeIndex = 0;
    this.#stalled = true;
    this.#anchored = false;
  }
  read(output) {
    if (output.length !== this.channels) throw new Error("wrong number of channels");
    if (this.#stalled) return 0;
    const samples = Math.min(this.#writeIndex - this.#readIndex, output[0].length);
    if (samples === 0) return 0;
    for (let channel = 0; channel < this.channels; channel++) {
      const dst = output[channel];
      const src = this.#buffer[channel];
      if (dst.length !== output[0].length) throw new Error("mismatching number of samples");
      for (let i = 0; i < samples; i++) {
        const readPos = (this.#readIndex + i) % src.length;
        dst[i] = src[readPos];
      }
    }
    this.#readIndex += samples;
    return samples;
  }
};

// src/audio/shared-ring-buffer.ts
var WRITE = 0;
var LATENCY = 1;
var STALLED = 2;
var TIMELINE = 3;
var CONTROL_SLOTS = 4;
var CURSOR_MASK = 0xffffffffn;
function pack(epoch, read) {
  return BigInt(epoch >>> 0) << 32n | BigInt(read >>> 0);
}
function epochOf(state) {
  return Number(state >> 32n) | 0;
}
function retreating(state) {
  return (epochOf(state) & 1) !== 0;
}
function readOf(state) {
  return Number(state & CURSOR_MASK) | 0;
}
function ceilPow2(n) {
  return n <= 1 ? 1 : 1 << 32 - Math.clz32(n - 1);
}
function allocSharedRingBuffer(channels, capacity, rate, buffered = false) {
  if (channels <= 0) throw new Error("invalid channels");
  if (capacity <= 0 || capacity > 2 ** 30) throw new Error("invalid capacity");
  if (rate <= 0) throw new Error("invalid sample rate");
  capacity = ceilPow2(capacity);
  const samples = new SharedArrayBuffer(channels * capacity * Float32Array.BYTES_PER_ELEMENT);
  const control = new SharedArrayBuffer(CONTROL_SLOTS * Int32Array.BYTES_PER_ELEMENT);
  const state = new SharedArrayBuffer(BigInt64Array.BYTES_PER_ELEMENT);
  const ctrl = new Int32Array(control);
  Atomics.store(ctrl, STALLED, 1);
  return { channels, capacity, rate, samples, control, state, buffered };
}
function i32Max(a, b) {
  return (a - b | 0) > 0 ? a : b;
}
function slot(idx, capacity) {
  return idx & capacity - 1;
}
var SharedRingBuffer = class _SharedRingBuffer {
  channels;
  capacity;
  rate;
  buffered;
  init;
  #control;
  #state;
  #samples;
  // Whether READ/WRITE have been anchored to the first inserted sample.
  #anchored = false;
  // Absolute sample index of that first sample. READ/WRITE are stored relative to it, so
  // \`timestamp\` adds it back to recover media time. Main-thread only: the worklet reads by
  // difference and never needs an absolute position.
  #anchor = 0;
  // Unwrapped READ, in anchor-relative samples, plus the raw i32 it was last derived from.
  // READ is Int32 and wraps every ~13.5h at 44.1kHz. That is harmless for the modular
  // comparisons the ring runs on, but reading the negative half as a magnitude would report
  // the playhead jumping back 2^32 samples, so accumulate deltas here instead. Main-thread
  // only, and only accurate while \`timestamp\` is observed more often than READ can advance
  // 2^31 samples, which the 50ms poll in \`buffer.ts\` satisfies by six orders of magnitude.
  #position = 0;
  #lastRead = 0;
  /**
   * Wrap the shared memory described by \`init\`.
   *
   * Pass \`previous\` in the worklet when this ring replaces one already being read. \`resize\`
   * snapshots the playhead on the main thread and hands the replacement over by message, so the
   * reader keeps draining the old ring in the meantime. Carrying its cursor across means those
   * samples are not played twice.
   */
  constructor(init, previous) {
    this.channels = init.channels;
    this.capacity = init.capacity;
    this.rate = init.rate;
    this.buffered = init.buffered;
    this.init = init;
    this.#control = new Int32Array(init.control);
    this.#state = new BigInt64Array(init.state);
    this.#samples = [];
    for (let i = 0; i < this.channels; i++) {
      this.#samples.push(
        new Float32Array(init.samples, i * this.capacity * Float32Array.BYTES_PER_ELEMENT, this.capacity)
      );
    }
    if (previous !== void 0) this.#handoff(previous);
  }
  /**
   * Carry \`source\`'s playhead across, if the replacement is still the timeline it belongs to.
   *
   * Truncation changes the mutation epoch but preserves timeline identity. Sample state before
   * identity: a re-anchor publishes identity first, then replaces state. Either the identity
   * check rejects the old cursor, the exchange fails, or the re-anchor overwrites the carried
   * cursor. A truncate only forces a retry, preserving audio consumed since the resize.
   */
  #handoff(source) {
    if (source.channels !== this.channels || source.rate !== this.rate) return;
    const timeline = Atomics.load(source.#control, TIMELINE);
    const from = Atomics.load(source.#state, 0);
    for (; ; ) {
      const state = Atomics.load(this.#state, 0);
      if (Atomics.load(this.#control, TIMELINE) !== timeline) return;
      if ((readOf(from) - readOf(state) | 0) <= 0) return;
      const next = pack(epochOf(state), readOf(from));
      if (Atomics.compareExchange(this.#state, 0, state, next) === state) return;
    }
  }
  /**
   * Move the playhead forward to \`candidate\`, staying on whatever timeline is current.
   *
   * Retries while the word changes under it, and never steps backwards. Used by the writer's
   * overflow path; the reader publishes with its own exchange so it can tell a rebase apart
   * from losing a race.
   */
  #advance(candidate) {
    for (; ; ) {
      const state = Atomics.load(this.#state, 0);
      if ((candidate - readOf(state) | 0) <= 0) return;
      const next = pack(epochOf(state), candidate);
      if (Atomics.compareExchange(this.#state, 0, state, next) === state) return;
    }
  }
  /**
   * Step the epoch by one, leaving the playhead wherever the reader has taken it.
   *
   * Retries while the word changes under it: only the epoch half is the writer's to move.
   */
  #step() {
    for (; ; ) {
      const state = Atomics.load(this.#state, 0);
      const next = pack(epochOf(state) + 1 | 0, readOf(state));
      if (Atomics.compareExchange(this.#state, 0, state, next) === state) return;
    }
  }
  /**
   * Insert audio samples at the given timestamp.
   * Main thread only. Handles out-of-order writes, gap filling, and overflow.
   */
  insert(timestamp, data) {
    if (data.length !== this.channels) throw new Error("wrong number of channels");
    let start = Math.round(time_exports.Second.fromMicro(timestamp) * this.rate);
    const originalLength = data[0].length;
    let offset = 0;
    if (!this.#anchored) {
      this.#anchor = start;
      const epoch = epochOf(Atomics.load(this.#state, 0));
      Atomics.add(this.#control, TIMELINE, 1);
      Atomics.store(this.#state, 0, pack(epoch + 2 | 0, 0));
      Atomics.store(this.#control, WRITE, 0);
      this.#anchored = true;
      this.#position = 0;
      this.#lastRead = 0;
    }
    start = start - this.#anchor | 0;
    const end = start + originalLength | 0;
    const read = readOf(Atomics.load(this.#state, 0));
    const behind = read - start | 0;
    if (behind > 0) {
      if (behind >= originalLength) {
        return;
      }
      offset = behind;
      start = start + behind | 0;
    }
    const samples = originalLength - offset;
    if ((end - read | 0) > this.capacity) {
      this.#advance(end - this.capacity | 0);
    }
    const write = Atomics.load(this.#control, WRITE);
    const gap = start - write | 0;
    if (gap > 0) {
      const gapSize = Math.min(gap, this.capacity);
      for (let channel = 0; channel < this.channels; channel++) {
        const dst = this.#samples[channel];
        for (let i = 0; i < gapSize; i++) {
          dst[slot(write + i | 0, this.capacity)] = 0;
        }
      }
    }
    for (let channel = 0; channel < this.channels; channel++) {
      const src = data[channel];
      const dst = this.#samples[channel];
      for (let i = 0; i < samples; i++) {
        dst[slot(start + i | 0, this.capacity)] = src[offset + i];
      }
    }
    Atomics.store(this.#control, WRITE, i32Max(Atomics.load(this.#control, WRITE), end));
    const currentRead = readOf(Atomics.load(this.#state, 0));
    const currentWrite = Atomics.load(this.#control, WRITE);
    const latency = Atomics.load(this.#control, LATENCY);
    if ((currentWrite - currentRead | 0) >= latency && latency > 0) {
      Atomics.store(this.#control, STALLED, 0);
    }
  }
  /**
   * Read audio samples into the output buffers.
   * AudioWorklet only. Returns the number of samples read.
   */
  read(output) {
    const state = Atomics.load(this.#state, 0);
    if (Atomics.load(this.#control, STALLED) === 1) return 0;
    if (retreating(state)) return 0;
    let read = readOf(state);
    const write = Atomics.load(this.#control, WRITE);
    const latency = Atomics.load(this.#control, LATENCY);
    const buffered = write - read | 0;
    if (!this.buffered && latency > 0 && buffered > latency) {
      const skipTo = write - latency | 0;
      if ((skipTo - read | 0) > 0) read = skipTo;
    }
    const available = write - read | 0;
    const count = Math.min(available, output[0].length);
    if (count <= 0) {
      if ((read - readOf(state) | 0) > 0) {
        Atomics.compareExchange(this.#state, 0, state, pack(epochOf(state), read));
      }
      return 0;
    }
    for (let channel = 0; channel < this.channels; channel++) {
      const src = this.#samples[channel];
      const dst = output[channel];
      for (let i = 0; i < count; i++) {
        dst[i] = src[slot(read + i | 0, this.capacity)];
      }
    }
    const next = pack(epochOf(state), read + count | 0);
    if (Atomics.compareExchange(this.#state, 0, state, next) !== state) {
      for (let channel = 0; channel < this.channels; channel++) output[channel].fill(0, 0, count);
      return 0;
    }
    return count;
  }
  /** Update the target latency in samples. */
  setLatency(samples) {
    Atomics.store(this.#control, LATENCY, samples);
  }
  /**
   * Drop buffered samples at or after \`timestamp\`, keeping whatever is already due.
   * Main thread only.
   *
   * A successor track overwrites the slots its own samples land on, but anything the previous
   * track wrote beyond them would otherwise still play once the successor runs out.
   */
  truncate(timestamp) {
    const target = Math.round(time_exports.Second.fromMicro(timestamp) * this.rate) - this.#anchor | 0;
    if ((Atomics.load(this.#control, WRITE) - target | 0) <= 0) return;
    this.#step();
    for (; ; ) {
      const write = Atomics.load(this.#control, WRITE);
      const clamped = i32Max(target, readOf(Atomics.load(this.#state, 0)));
      if ((write - clamped | 0) <= 0) break;
      if (Atomics.compareExchange(this.#control, WRITE, write, clamped) === write) break;
    }
    this.#step();
  }
  /**
   * Flush buffered samples and re-stall, ready to anchor the next utterance (buffered mode).
   * Main thread only. The worklet reader sees STALLED and stops until the next insert.
   */
  reset() {
    this.#anchored = false;
    Atomics.store(this.#control, STALLED, 1);
    const write = Atomics.load(this.#control, WRITE);
    const state = Atomics.load(this.#state, 0);
    Atomics.store(this.#state, 0, pack(epochOf(state), write));
  }
  /**
   * Allocate a new ring with \`newCapacity\` samples and copy the unread window
   * [READ, WRITE) plus control state into it. Used when growing capacity so
   * we don't drop buffered audio. If \`newCapacity\` is smaller than the unread
   * span, the oldest samples are truncated.
   *
   * Main thread only. \`resize()\` reads from the source \`SharedRingBuffer\` and
   * writes into a freshly allocated buffer from \`allocSharedRingBuffer\`, so it
   * relies on the same invariant as \`insert()\`: no concurrent main-thread
   * writers. The AudioWorklet reader is tolerated via the CAS discipline used
   * by READ/WRITE elsewhere.
   */
  resize(newCapacity) {
    const init = allocSharedRingBuffer(this.channels, newCapacity, this.rate, this.buffered);
    const dst = new _SharedRingBuffer(init);
    dst.#anchored = this.#anchored;
    dst.#anchor = this.#anchor;
    const state = Atomics.load(this.#state, 0);
    const read = readOf(state);
    const write = Atomics.load(this.#control, WRITE);
    const latency = Atomics.load(this.#control, LATENCY);
    const stalled = Atomics.load(this.#control, STALLED);
    const available = write - read | 0;
    const copyCount = Math.max(0, Math.min(available, dst.capacity));
    const copyStart = write - copyCount | 0;
    for (let channel = 0; channel < this.channels; channel++) {
      const src = this.#samples[channel];
      const out = dst.#samples[channel];
      for (let i = 0; i < copyCount; i++) {
        const idx = copyStart + i | 0;
        out[slot(idx, dst.capacity)] = src[slot(idx, this.capacity)];
      }
    }
    Atomics.store(dst.#control, TIMELINE, Atomics.load(this.#control, TIMELINE));
    Atomics.store(dst.#state, 0, pack(epochOf(state), copyStart));
    Atomics.store(dst.#control, WRITE, write);
    Atomics.store(dst.#control, LATENCY, latency);
    Atomics.store(dst.#control, STALLED, stalled);
    dst.#position = this.#foldRead(read) + (copyStart - read | 0);
    dst.#lastRead = copyStart;
    return dst;
  }
  /**
   * Fold an observed READ into \`#position\`, so the returned offset keeps counting up across
   * the i32 wrap. Idempotent: folding the same value twice adds a zero delta.
   */
  #foldRead(read) {
    this.#position += read - this.#lastRead | 0;
    this.#lastRead = read;
    return this.#position;
  }
  /** \`#foldRead\` against the current READ. */
  #unwrapRead() {
    return this.#foldRead(readOf(Atomics.load(this.#state, 0)));
  }
  /**
   * Current playback timestamp derived from READ position.
   *
   * Main thread only, and stateful: it advances the unwrapped read position, so it has to be
   * polled rather than sampled once. See \`#position\`.
   */
  get timestamp() {
    return time_exports.Micro.fromSecond((this.#anchor + this.#unwrapRead()) / this.rate);
  }
  /** Whether the buffer is stalled (waiting to fill). */
  get stalled() {
    return Atomics.load(this.#control, STALLED) === 1;
  }
  /**
   * Number of buffered samples (WRITE - READ).
   *
   * Non-atomic: WRITE and READ are loaded separately, so a concurrent
   * writer/reader can make the two loads inconsistent. Intended for
   * tests and diagnostics, not control-flow decisions.
   */
  get length() {
    return Atomics.load(this.#control, WRITE) - readOf(Atomics.load(this.#state, 0)) | 0;
  }
};

// src/audio/render-worklet.ts
var Render = class extends AudioWorkletProcessor {
  // Set after init, depending on which path the main thread chose.
  #backend;
  #underflow = 0;
  #stateCounter = 0;
  constructor() {
    super();
    this.port.onmessage = (event) => {
      const msg = event.data;
      if (msg.type === "init-shared") {
        console.log("[audio-worklet] init-shared: using SharedArrayBuffer path");
        const previous = this.#backend instanceof SharedRingBuffer ? this.#backend : void 0;
        this.#backend = new SharedRingBuffer(msg, previous);
        this.#underflow = 0;
      } else if (msg.type === "init-post") {
        console.log("[audio-worklet] init-post: using postMessage path");
        this.#backend = new AudioRingBuffer(msg);
        this.#underflow = 0;
      } else if (msg.type === "data") {
        if (this.#backend instanceof AudioRingBuffer) this.#backend.write(msg.timestamp, msg.data);
      } else if (msg.type === "latency") {
        if (this.#backend instanceof AudioRingBuffer) this.#backend.resize(msg.latency);
      } else if (msg.type === "truncate") {
        if (this.#backend instanceof AudioRingBuffer) this.#backend.truncate(msg.timestamp);
      } else if (msg.type === "reset") {
        if (this.#backend instanceof AudioRingBuffer) this.#backend.reset();
      }
    };
  }
  process(_inputs, outputs, _parameters) {
    const output = outputs[0];
    const backend = this.#backend;
    const samplesRead = backend?.read(output) ?? 0;
    if (samplesRead < output[0].length) {
      this.#underflow += output[0].length - samplesRead;
    } else if (this.#underflow > 0 && backend) {
      console.debug(\`audio underflow: \${Math.round(1e3 * this.#underflow / backend.rate)}ms\`);
      this.#underflow = 0;
    }
    if (backend instanceof AudioRingBuffer) {
      this.#stateCounter++;
      if (this.#stateCounter >= 5) {
        this.#stateCounter = 0;
        const state = {
          type: "state",
          timestamp: backend.timestamp,
          stalled: backend.stalled
        };
        this.port.postMessage(state);
      }
    }
    return true;
  }
};
registerProcessor("render", Render);
`],{type:"application/javascript"}),ue=URL.createObjectURL(de),fe=class{#t=0;#e;#i;#n=0;#s;get end(){return this.#e}clear(t=0){this.#t=0,this.#e=void 0,this.#n=t,this.#r()}update(t){let e=t.discontinuity!==this.#t;return e&&(this.#t=t.discontinuity,this.#e=void 0,this.#r()),t.frame&&this.#i===void 0&&(this.#i=t.frame.timestamp),t.end!==void 0&&(this.#e=t.end),e}span(t){let e=this.#i??t.timestamp;this.#i=e;let i=Math.floor(this.#n*t.sampleRate/48e3),n=this.#s??i,s=Math.min(n,t.numberOfFrames);this.#s=n-s;let r=Math.round(i*1e6/t.sampleRate),a=Math.max(e,t.timestamp-r),o=t.numberOfFrames-s;if(this.#e!==void 0)if(this.#e<=a)o=0;else{let c=this.#e-a,l=Math.round(c*t.sampleRate/1e6);o=Math.min(o,l)}return{timestamp:a,frameOffset:s,frames:o}}#r(){this.#i=void 0,this.#s=void 0}};function pe(t,e){let i=new u(e.state==="running");t.event(e,"statechange",()=>i.set(e.state==="running")),t.run(n=>{if(n.get(i))return;let s=()=>{e.resume().catch(()=>{})};s(),n.event(document,"pointerdown",s),n.event(document,"keydown",s)})}var me=class{#t;constructor(t){this.#t=t}drop(){return this.#t!==0&&(this.#t--,!0)}},ge=150,be=3,at=class{in;source;sync;#t={context:new u(void 0),root:new u(void 0),sampleRate:new u(void 0),stats:new u(void 0),timestamp:new u(void 0),stalled:new u(!0),buffered:new u([])};out=I(this.#t);#e=new u([]);#i;#n=new u(void 0);#s=new fe;#r;#a=new ce;#o=new M;#c;#l;constructor(t){this.in={enabled:p(t?.enabled??!0)},this.source=t.source,this.sync=t.sync,this.#o.cleanup(this.sync.register(this.source.out.jitter)),this.#c=this.#o.computed(e=>{let i=e.get(this.source.out.config);return i?re(i):void 0}),this.#l=this.#o.computed(e=>{let i=e.get(this.source.out.config);return i?kt(i):void 0}),this.#o.run(this.#h.bind(this)),this.#o.run(this.#d.bind(this)),this.#o.run(this.#p.bind(this)),this.#o.run(this.#m.bind(this)),this.#o.run(this.#g.bind(this))}#h(t){let e=t.get(this.#l);if(!e)return;let i=t.get(this.#n)??e.sampleRate,n=e.numberOfChannels;t.set(this.#t.sampleRate,i);let s=new AudioContext({latencyHint:"interactive",sampleRate:i});t.set(this.#t.context,s),t.cleanup(()=>s.close()),t.spawn(async()=>{if(!await Promise.race([s.audioWorklet.addModule(ue).then(()=>!0),t.cancel]))return;let r=new AudioWorkletNode(s,"render",{channelCount:n,channelCountMode:"explicit",outputChannelCount:[n]});t.cleanup(()=>r.disconnect());let a=this.sync.out.delay.peek(),o=rt(i,a),c=this.sync.out.buffered.peek(),l=Jt(r,n,i,o,c);this.#i=l,t.cleanup(()=>{l.close(),this.#i=void 0}),t.run(h=>{let f=d.Milli.fromMicro(h.get(l.timestamp));this.#t.timestamp.set(f),this.#A(f)}),t.run(h=>{this.#t.stalled.set(h.get(l.stalled))}),t.set(this.#t.root,r)})}#d(t){if(!t.get(this.in.enabled))return;if(t.get(this.sync.in.delay)==="instant"){this.reset();return}let e=t.get(this.#t.context);e&&pe(t,e)}#p(t){if(!t.get(this.#t.root))return;let e=this.#i;if(!e)return;let i=t.get(this.sync.out.delay);e.setLatency(rt(e.rate,i))}#m(t){let e=t.get(this.sync.out.delay),i=t.get(this.sync.out.jitter),n=le({delay:t.get(this.sync.in.delay),media:d.Milli.sub(e,i)});if(this.#r===void 0){this.#r=n;return}let s=this.#r;t.timer(()=>{n>s&&this.reset(),this.#r=n},ge)}#g(t){if(!t.get(this.in.enabled)||t.get(this.sync.in.delay)==="instant")return;let e=t.get(this.source.in.broadcast);if(!e)return;let i=t.get(this.source.out.track);if(!i)return;let n=t.get(this.#c);if(!n)return;let s=n.decoder,r=e.relativeBroadcast(t,n.broadcast);if(!r)return;this.#a.opened();let a=et(t,{broadcast:r,track:i,priority:w.PRIORITY.audio,maxAge:this.sync.out.maxAge});a&&(s.container.kind==="cmaf"?this.#w(t,a,s):this.#b(t,a,s))}#b(t,e,i){let n=i.codec==="opus"&&i.description?A.Opus.preSkip(A.Hex.toBytes(i.description)):0;this.#s.clear(n);let s=i.container.kind==="loc"?new b.Loc.Format("audio"):new b.Legacy.Format(i),r=new b.Consumer(e,{format:s,maxAge:this.sync.out.maxAge});t.cleanup(()=>r.close()),t.run(a=>{let o=a.get(r.buffered),c=a.get(this.#e);this.#t.buffered.update(()=>b.mergeBufferedRanges(o,c))}),t.spawn(async()=>{if(!await A.Libav.polyfill())return;let a=new me(be),o=new AudioDecoder({output:h=>{let f=this.#s.span(h);if(a.drop()){h.close();return}this.#u(h,f)},error:h=>console.error("audio decoder error",h)});t.cleanup(()=>{o.state!=="closed"&&o.close()});let c=i.codec==="opus"?void 0:i.description?A.Hex.toBytes(i.description):void 0,l={codec:i.codec,sampleRate:i.sampleRate,numberOfChannels:i.numberOfChannels,description:c};for(o.configure(l);;){let h=await G(r);if(!h)break;if(this.#f(h)&&(o.reset(),o.configure(l)),h.end!==void 0)continue;let{frame:f}=h;if(!f)continue;let m=d.Milli.fromMicro(f.timestamp);this.sync.received(m,"audio"),this.#t.stats.update(k=>({bytesReceived:(k?.bytesReceived??0)+f.payload.byteLength})),await this.#i?.wait(f.timestamp);let g=new EncodedAudioChunk({type:f.keyframe?"key":"delta",data:f.payload,timestamp:f.timestamp});if(o.state==="closed")break;o.decode(g)}})}#w(t,e,i){if(i.container.kind!=="cmaf")return;let n=V(i.container.init),s=b.Cmaf.decodeInitSegment(n),r=i.description?A.Hex.toBytes(i.description):s.description,a=i.codec==="opus"&&r?A.Opus.preSkip(r):0;this.#s.clear(a);let o=i.codec==="opus"?void 0:i.description?A.Hex.toBytes(i.description):s.description,c=new b.Consumer(e,{format:new b.Cmaf.Format(s),maxAge:this.sync.out.maxAge});t.cleanup(()=>c.close()),t.run(l=>{let h=l.get(c.buffered),f=l.get(this.#e);this.#t.buffered.update(()=>b.mergeBufferedRanges(h,f))}),t.spawn(async()=>{if(!await A.Libav.polyfill())return;let l=new AudioDecoder({output:f=>this.#u(f),error:f=>console.error("audio decoder error",f)});t.cleanup(()=>{l.state!=="closed"&&l.close()});let h={codec:i.codec,sampleRate:i.sampleRate,numberOfChannels:i.numberOfChannels,description:o};for(l.configure(h);;){let f=await G(c);if(!f)break;this.#f(f)&&(l.reset(),l.configure(h));let{frame:m}=f;if(!m)continue;let g=d.Milli.fromMicro(m.timestamp);if(this.sync.received(g,"audio"),this.#t.stats.update(k=>({bytesReceived:(k?.bytesReceived??0)+m.payload.byteLength})),await this.#i?.wait(m.timestamp),l.state==="closed")break;l.decode(new EncodedAudioChunk({type:m.keyframe?"key":"delta",data:m.payload,timestamp:m.timestamp}))}})}#u(t,e=this.#s.span(t)){let{timestamp:i,frameOffset:n,frames:s}=e,r=d.Milli.fromMicro(i);if(s===0){t.close();return}let a=this.#i;if(!a){t.close();return}if(t.sampleRate!==a.rate){this.#n.set(t.sampleRate),t.close();return}let o=s/t.sampleRate*1e6,c=d.Milli.fromMicro(o),l=d.Milli.add(r,c);this.#a.takeover()&&(a.truncate(i),this.#v(r)),this.#y(r,l);let h=Math.min(t.numberOfChannels,a.channels),f=[];for(let m=0;m<h;m++){let g=new Float32Array(s);t.copyTo(g,{format:"f32-planar",planeIndex:m,frameOffset:n,frameCount:s}),f.push(g)}a.insert(i,f),t.close()}#y(t,e){t>e||this.#e.mutate(i=>{for(let n of i)if(t<=n.end+1&&e>=n.start){n.start=d.Milli.min(n.start,t),n.end=d.Milli.max(n.end,e);return}i.push({start:t,end:e}),i.sort((n,s)=>n.start-s.start)})}#v(t){this.#e.mutate(e=>{for(;e.length>0&&e[e.length-1].start>=t;)e.pop();let i=e[e.length-1];i&&i.end>t&&(i.end=t)})}#A(t){this.#e.mutate(e=>{for(;e.length>0;){if(e[0].end>=t){e[0].start=d.Milli.max(e[0].start,t);break}e.shift()}})}reset(){this.#i?.reset()}#f(t){return this.#s.update(t)?(this.#i?.reset(),this.sync.reset(),!0):!1}close(){this.#o.close()}static supported=we};async function we(t){if(!w.containerSupported(t.container)){let i=t.container.kind==="unknown"?t.container.raw.kind:t.container.kind;return console.warn(`audio: ignoring rendition with unknown container: ${i}`),!1}t.codec==="opus"&&!A.Opus.supportsRate(t.sampleRate)&&console.warn(`audio: opus advertised at ${t.sampleRate}Hz, which some browsers cannot decode`);let e;if(t.codec!=="opus"){if(t.description)e=A.Hex.toBytes(t.description);else if(t.container.kind==="cmaf")try{e=b.Cmaf.decodeInitSegment(V(t.container.init)).description}catch(i){return console.warn(`audio: malformed CMAF init segment for codec ${t.codec}`,i),!1}}return(await AudioDecoder.isConfigSupported({...t,description:e})).supported??!1}var ot=.001,Q=.2,ye=class{source;in;#t={enabled:new u(!1)};out=I(this.#t);#e=new M;#i=new u(void 0);constructor(t){this.source=t.source,this.in={volume:p(t?.volume??.5),muted:p(t?.muted??!1),paused:p(t?.paused??!1)},this.#e.run(e=>{let i=!e.get(this.in.paused)&&!e.get(this.in.muted);this.#t.enabled.set(i)}),this.#e.run(e=>{let i=e.get(this.source.out.root);if(!i)return;let n=new GainNode(i.context,{gain:e.get(this.in.volume)});i.connect(n),e.set(this.#i,n),e.run(s=>{s.get(this.#t.enabled)&&(n.connect(i.context.destination),s.cleanup(()=>n.disconnect()))})}),this.#e.run(e=>{let i=e.get(this.#i);if(!i)return;e.cleanup(()=>i.gain.cancelScheduledValues(i.context.currentTime));let n=e.get(this.in.volume);n<ot?(i.gain.exponentialRampToValueAtTime(ot,i.context.currentTime+Q),i.gain.setValueAtTime(0,i.context.currentTime+Q+.01)):i.gain.exponentialRampToValueAtTime(n,i.context.currentTime+Q)})}close(){this.#e.close()}},ve=class{in;#t={catalog:new u(void 0),available:new u({}),track:new u(void 0),config:new u(void 0),jitter:new u(void 0)};out=I(this.#t);#e=new M;constructor(t){this.in={broadcast:p(t?.broadcast),target:p(t?.target),supported:p(t?.supported)},this.#e.run(this.#i.bind(this)),this.#e.run(this.#n.bind(this)),this.#e.run(this.#s.bind(this))}#i(t){let e=t.get(this.in.broadcast);if(!e)return;let i=t.get(e.out.catalog)?.audio;i&&t.set(this.#t.catalog,i)}#n(t){let e=t.get(this.#t.catalog)?.renditions??{},i=t.get(this.in.supported);i&&t.spawn(async()=>{let n={},s=t.cancel.then(()=>{});for(let[r,a]of Object.entries(e)){let o=await Promise.race([i(a),s]);if(t.abort.aborted)return;o&&(n[r]=a)}Object.keys(n).length===0&&Object.keys(e).length>0&&console.warn("no supported audio renditions found:",e),this.#t.available.set(n)})}#s(t){let e=t.get(this.#t.available);if(Object.keys(e).length===0)return;let i=t.get(this.in.target),n;if(i?.name&&i.name in e)n={track:i.name,config:e[i.name]};else if(n=this.#r(e),!n)return;t.set(this.#t.track,n.track),t.set(this.#t.config,n.config),t.set(this.#t.jitter,ae(n.config))}#r(t){let e=Object.entries(t);if(e.length!==0){for(let[i,n]of e)if(n.container.kind==="legacy")return{track:i,config:n};for(let[i,n]of e)if(n.container.kind==="loc")return{track:i,config:n};for(let[i,n]of e)if(n.container.kind==="cmaf")return{track:i,config:n}}}close(){this.#e.close()}},Ae=48e3,ct=2;function xe(t){let e="";for(let i=0;i<t.length;i++)e+=t[i].toString(16).padStart(2,"0");return e}function Mt(t){let e;try{e=t.initData?V(t.initData):void 0}catch{e=void 0}let i=e?xe(e):void 0;switch(t.packaging){case"cmaf":return!t.initData||!e?void 0:{container:{kind:"cmaf",init:t.initData},description:void 0};case"loc":return{container:{kind:"loc"},description:i};case"legacy":return{container:{kind:"legacy"},description:i};default:return}}function ke(t){if(!t.codec)return;let e=Mt(t);if(!e)return;let{container:i,description:n}=e;return{codec:t.codec,container:i,description:n,codedWidth:t.width==null?void 0:z(t.width),codedHeight:t.height==null?void 0:z(t.height),framerate:t.framerate,bitrate:t.bitrate==null?void 0:z(t.bitrate),stalled:t.stalled,jitter:t.jitter==null?void 0:z(t.jitter)}}function Me(t){if(!t.codec)return;let e=(()=>{if(!t.channelConfig)return ct;let r=Number.parseInt(t.channelConfig,10);return Number.isFinite(r)?r:ct})(),i=Mt(t);if(!i)return;let{container:n,description:s}=i;return{codec:t.codec,container:n,description:s,sampleRate:z(t.samplerate??Ae),numberOfChannels:z(e),bitrate:t.bitrate==null?void 0:z(t.bitrate),jitter:t.jitter==null?void 0:z(t.jitter)}}function Te(t){let e={},i={};for(let s of t.tracks)if(s.role==="video"){let r=ke(s);r&&(e[s.name]=r)}else if(s.role==="audio"){let r=Me(s);r&&(i[s.name]=r)}let n={};return Object.keys(e).length>0&&(n.video={renditions:e}),Object.keys(i).length>0&&(n.audio={renditions:i}),n}function Tt(t,e){let i=[...Object.entries(e.video?.renditions??{}),...Object.entries(e.audio?.renditions??{}),...Object.entries(e.text?.renditions??{})];for(let[n,s]of i)if(s.broadcast&&D.tryResolve(t,s.broadcast)===void 0)return n}function Ee(t,e){let i=Tt(t,e);if(i!==void 0)throw Error(`rendition ${JSON.stringify(i)}: broadcast reference escapes the root ${t}`);return e}function Z(t,e){return Object.fromEntries(Object.entries(t).filter(([,i])=>e(i.broadcast)))}function Re(t,e){return{...t,video:t.video?{...t.video,renditions:Z(t.video.renditions,e)}:void 0,audio:t.audio?{...t.audio,renditions:Z(t.audio.renditions,e)}:void 0,text:t.text?{...t.text,renditions:Z(t.text.renditions,e)}:void 0}}var Qi=[...w.FORMATS,"hangz","manual"],Se=class{in;#t={status:new u("offline"),active:new u(void 0),catalog:new u(void 0)};out=I(this.#t);#e=new u(void 0);#i=new u(!1);#n=new u(void 0);#s;constructor(t){if(t&&"reload"in t)throw Error("Watch.Broadcast: `reload` was renamed to `announced`");this.#s=new M,this.in={origin:p(t?.origin),name:p(t?.name??D.empty()),enabled:p(t?.enabled??!0),announced:p(t?.announced??!0),catalogFormat:p(t?.catalogFormat),catalog:p(t?.catalog)},this.#s.run(this.#r.bind(this)),this.#s.run(this.#l.bind(this)),this.#s.run(this.#h.bind(this)),this.#s.run(this.#a.bind(this))}#r(t){if(this.#e.set(void 0),!t.get(this.#i)||!t.get(this.in.announced))return;let e=t.get(this.in.origin);if(!e)return;let i=e.announced();t.cleanup(()=>i.close()),this.#e.set(new Set),t.spawn(async()=>{for(;;){let n=await Promise.race([t.cancel,i.next()]);if(!n)break;this.#e.mutate(s=>{s&&(Dt.isActive(n.kind)?s.add(n.prefix):s.delete(n.prefix))})}})}#a(t){let e=t.get(this.#n);t.set(this.#t.catalog,e?Re(e,i=>this.#d(t,i)!==void 0):void 0)}#o(t,e){this.#i.set(!0);let i=t.get(this.#e);if(!i)return!1;if(i.has(e))return!0;for(let n of i)if(D.hasPrefix(n,e))return!0;return!1}#c(t,e,i){let n=e.request(i);return t.cleanup(()=>n.close()),t.get(n.active)}#l(t){if(!t.get(this.in.enabled))return;let e=t.get(this.in.origin);if(!e)return;let i=t.get(this.in.name);if(!t.get(this.in.announced)){t.set(this.#t.active,this.#c(t,e,i),void 0);return}let n=e.request(i,{announced:!0});t.cleanup(()=>n.close()),t.run(s=>{s.set(this.#t.active,s.get(n.active),void 0)})}#h(t){if(!t.get(this.in.enabled))return;let e=t.get(this.in.catalogFormat),i=t.get(this.in.name),n=e??w.detectFormat(i)??w.DEFAULT_FORMAT;if(n==="manual"){let c=t.get(this.in.catalog),l=c&&Tt(i,c);l!==void 0&&console.error("rejecting catalog: broadcast reference escapes the root",i,l);let h=l===void 0?c:void 0;this.#n.set(h,!0),t.cleanup(()=>this.#n.set(void 0,!0)),this.#t.status.set(h?"live":"loading");return}let s=t.get(this.out.active);if(!s||t.get(s.closed)!==void 0)return;this.#t.status.set("loading");let r=n==="hang"?w.TRACK:n==="hangz"?w.TRACK_COMPRESSED:"catalog",a=s.track(r).subscribe({priority:w.PRIORITY.catalog});t.cleanup(()=>a.close());let o;if(n==="hang"||n==="hangz"){let c=new wt.Snapshot.Consumer({track:a,schema:w.RootSchema,compression:n==="hangz"?"deflate":"none"});o=()=>c.next()}else{let c=a.ordered();o=async()=>{let l=await yt.fetch(c);return l?Te(l):void 0}}t.spawn(async()=>{try{for(;;){let c=await Promise.race([t.cancel,o()]);if(!c)break;console.debug("received catalog",n,this.in.name.peek(),c),this.#n.set(Ee(i,c),!0),this.#t.status.set("live")}}catch(c){c instanceof U.Stream?console.debug("catalog subscription ended",this.in.name.peek(),c):console.error("error fetching catalog",this.in.name.peek(),c)}finally{this.#n.set(void 0),this.#t.status.set("offline")}})}#d(t,e){if(!e)return{local:!0};let i=t.get(this.in.name),n=D.tryResolve(i,e);if(n===void 0){console.warn("ignoring rendition: broadcast reference escapes the root",i,e);return}if(n===i)return{local:!0};let s=t.get(this.in.origin);if(!s||!(t.get(this.in.announced)&&t.get(s.discovery)!==!1&&!this.#o(t,n)))return{local:!1,path:n}}relativeBroadcast(t,e){let i=this.#d(t,e);if(!i)return;if(i.local)return t.get(this.out.active);if(!t.get(this.in.enabled))return;let n=t.get(this.in.origin);if(n)return this.#c(t,n,i.path)}close(){this.#s.close()}},Ie=d.Milli(20),lt=d.Milli(100),Oe=class Et{in;#t={reference:new u(void 0),delay:new u(d.Milli.zero),jitter:new u(lt),timestamp:new u(void 0),buffered:new u(!1),maxAge:new u(d.Milli.zero)};out=I(this.#t);#e;#i=new Map;#n;#s=new u([]);#r=new M;constructor(e){this.in={delay:p(e?.delay??"auto"),buffer:p(e?.buffer??d.Milli.zero),probe:p(e?.probe)},this.#e=Promise.withResolvers(),this.#r.run(this.#o.bind(this)),this.#r.run(this.#c.bind(this)),this.#r.run(this.#a.bind(this))}register(e){let i={jitter:e};return this.#s.update(n=>[...n,i]),()=>this.#s.update(n=>n.filter(s=>s!==i))}#a(e){let i=e.get(this.#t.delay),n=e.get(this.in.delay)==="instant"?d.Milli.zero:e.get(this.in.buffer);this.#t.buffered.set(n>0),this.#t.maxAge.set(d.Milli.add(i,n))}#o(e){let i=e.get(this.in.delay);if(i==="instant"){this.#n=void 0,this.#t.jitter.set(d.Milli.zero);return}if(typeof i=="number"){this.#n=void 0,this.#t.jitter.set(i);return}let n=e.get(this.in.probe)?.rtt;if(n!==void 0){this.#n=this.#n===void 0?n:Math.min(this.#n,n);let s=d.Milli(Math.max(Ie,this.#n*1.25));this.#t.jitter.set(s);return}this.#n=void 0,this.#t.jitter.set(lt)}#c(e){let i=e.get(this.#t.jitter),n=d.Milli.zero;for(let r of e.get(this.#s))n=d.Milli.max(n,e.get(r.jitter)??d.Milli.zero);let s=e.get(this.in.delay)==="instant"?d.Milli.zero:d.Milli.add(n,i);this.#t.delay.set(s),this.#e.resolve(),this.#e=Promise.withResolvers()}received(e,i=""){this.#t.timestamp.update(l=>l===void 0||e>l?e:l);let n=d.Milli.now(),s=d.Milli.sub(n,e),r=this.#t.reference.peek();if(r===void 0){this.#l(s);return}let a=this.#t.delay.peek(),o=d.Milli.add(d.Milli.sub(r,s),a);if(o<0){let l=this.#i.get(i);l?(l.count++,l.maxMs=Math.max(l.maxMs,-o)):this.#i.set(i,{count:1,maxMs:-o})}else{let l=this.#i.get(i);if(l){let h=i?`sync[${i}]`:"sync",f=Et.#h(l.maxMs);console.debug(`${h}: ${l.count} late frame(s), max ${f} behind`),this.#i.delete(i)}}if(s>=r)return;let c=this.#t.maxAge.peek();o<=c||this.#l(d.Milli.add(s,d.Milli.sub(c,a)))}#l(e){this.#t.reference.set(e),this.#e.resolve(),this.#e=Promise.withResolvers()}reset(){this.#t.reference.set(void 0),this.#i.clear(),this.#e.resolve(),this.#e=Promise.withResolvers()}now(){let e=this.#t.reference.peek();if(e!==void 0)return d.Milli.sub(d.Milli.sub(d.Milli.now(),e),this.#t.delay.peek())}async wait(e){if(this.in.delay.peek()!=="instant"){if(this.#t.reference.peek()===void 0)throw Error("reference not set; call received() first");for(;;){if(this.in.delay.peek()==="instant")return;let i=d.Milli.now(),n=d.Milli.sub(i,e),s=this.#t.reference.peek();if(s===void 0)return;let r=d.Milli.add(d.Milli.sub(s,n),this.#t.delay.peek());if(r<=0||r<5)return;let a=new Promise(o=>setTimeout(o,r)).then(()=>!0);if(await Promise.race([this.#e.promise,a]))return}}}static#h(e){if(e=Math.round(e),e<1e3)return`${e}ms`;let i=e/1e3;if(i<60)return`${Math.round(i*10)/10}s`;let n=i/60;return`${Math.round(n*10)/10}m`}close(){this.#r.close()}},Zi={LoadFail:0,BadSignature:1,BadTimestamp:2,BadSettingValue:3,BadFormat:4,UnknownSetting:5},tn=class extends Error{code;line;constructor(t){super(t.reason),this.code=t.code,this.line=t.line}},Ce=/\r?\n|\r/gm;async function Le(t,e){return ze(new ReadableStream({start(i){let n=t.split(Ce);for(let s of n)i.enqueue(s);i.close()}}),e)}async function ze(t,e){let i=e?.type??"vtt",n;if(typeof i=="string")switch(i){case"srt":n=(await import("./srt-parser-nCurN93p.mjs")).default;break;case"ssa":case"ass":n=(await import("./ssa-parser-BR32ptTi.mjs")).default;break;default:n=(await Promise.resolve().then(function(){return Qe})).default}else n=i;let s,r=t.getReader(),a=n(),o=!!e?.strict||!!e?.errors;await a.init({strict:!1,...e,errors:o,type:i,cancel(){r.cancel(),s=a.done(!0)}});let c=1;for(;;){let{value:l,done:h}=await r.read();if(h){a.parse("",c),s=a.done(!1);break}a.parse(l,c),c++}return s}var je=window.VTTCue,Rt=class extends je{region=null;vertical="";snapToLines=!0;line="auto";lineAlign="start";position="auto";positionAlign="auto";size=100;align="center";style},Be=class{id="";width=100;lines=3;regionAnchorX=0;regionAnchorY=100;viewportAnchorX=0;viewportAnchorY=100;scroll=""},ht=",",Ne="%";function Fe(t){let e=parseInt(t,10);return Number.isNaN(e)?null:e}function $(t){let e=parseInt(t.replace(Ne,""),10);return!Number.isNaN(e)&&e>=0&&e<=100?e:null}function dt(t){if(!t.includes(ht))return null;let[e,i]=t.split(ht).map($);return e!==null&&i!==null?[e,i]:null}function We(t){let e=parseFloat(t);return Number.isNaN(e)?null:e}var Pe="WEBVTT",ut=",",_e="%",N=/[:=]/,He=/^[\s\t]*(region|vertical|line|position|size|align)[:=]/,$e="NOTE",De="REGION",Ye=/^REGION:?[\s\t]+/,H=/[\s\t]+/,Ve="-->",qe=/[\s\t]*-->[\s\t]+/,Ke=/start|center|end|left|right/,Ue=/start|center|end/,Ge=/line-(?:left|right)|center|auto/,Je=/^(?:(\d{1,2}):)?(\d{2}):(\d{2})(?:\.(\d{1,3}))?$/,St=(t=>(t[t.None=0]="None",t[t.Header=1]="Header",t[t.Cue=2]="Cue",t[t.Region=3]="Region",t[t.Note=4]="Note",t))(St||{}),It=class{f;c=0;g={};h={};j=[];a=null;b=null;k=[];d;l="";async init(t){this.f=t,t.strict&&(this.c=1),t.errors&&(this.d=(await import("./errors-BiEpf0Gg.mjs")).ParseErrorBuilder)}parse(t,e){if(t==="")this.a?(this.j.push(this.a),this.f.onCue?.(this.a),this.a=null):this.b?(this.h[this.b.id]=this.b,this.f.onRegion?.(this.b),this.b=null):this.c===1&&(this.i(t,e),this.f.onHeaderMetadata?.(this.g)),this.c=0;else if(this.c)switch(this.c){case 1:this.i(t,e);break;case 2:if(this.a){let i=this.a.text.length>0;!i&&He.test(t)?this.m(t.split(H),e):this.a.text+=(i?`
`:"")+t}break;case 3:this.n(t.split(H),e)}else if(t.startsWith($e))this.c=4;else if(t.startsWith(De))this.c=3,this.b=new Be,this.n(t.replace(Ye,"").split(H),e);else if(t.includes(Ve)){let i=this.o(t,e);i&&(this.a=new Rt(i[0],i[1],""),this.a.id=this.l,this.m(i[2],e)),this.c=2}else e===1&&this.i(t,e);this.l=t}done(){return{metadata:this.g,cues:this.j,regions:Object.values(this.h),errors:this.k}}i(t,e){if(e>1){if(N.test(t)){let[i,n]=t.split(N);i&&(this.g[i]=(n||"").replace(H,""))}}else t.startsWith(Pe)?this.c=1:this.e(this.d?.p())}o(t,e){let[i,n=""]=t.split(qe),[s,...r]=n.split(H),a=X(i),o=X(s);if(a!==null&&o!==null&&o>a)return[a,o,r];a===null&&this.e(this.d?.q(i,e)),o===null&&this.e(this.d?.r(s,e)),a!=null&&o!==null&&o>a&&this.e(this.d?.s(a,o,e))}n(t,e){let i;for(let n=0;n<t.length;n++)if(N.test(t[n])){i=!1;let[s,r]=t[n].split(N);switch(s){case"id":this.b.id=r;break;case"width":let a=$(r);a===null?i=!0:this.b.width=a;break;case"lines":let o=Fe(r);o===null?i=!0:this.b.lines=o;break;case"regionanchor":let c=dt(r);c===null?i=!0:(this.b.regionAnchorX=c[0],this.b.regionAnchorY=c[1]);break;case"viewportanchor":let l=dt(r);l===null?i=!0:(this.b.viewportAnchorX=l[0],this.b.viewportAnchorY=l[1]);break;case"scroll":r==="up"?this.b.scroll="up":i=!0;break;default:this.e(this.d?.t(s,r,e))}i&&this.e(this.d?.u(s,r,e))}}m(t,e){let i;for(let n=0;n<t.length;n++)if(i=!1,N.test(t[n])){let[s,r]=t[n].split(N);switch(s){case"region":let a=this.h[r];a&&(this.a.region=a);break;case"vertical":r==="lr"||r==="rl"?(this.a.vertical=r,this.a.region=null):i=!0;break;case"line":let[o,c]=r.split(ut);if(o.includes(_e)){let g=$(o);g===null?i=!0:(this.a.line=g,this.a.snapToLines=!1)}else{let g=We(o);g===null?i=!0:this.a.line=g}Ue.test(c)?this.a.lineAlign=c:c&&(i=!0),this.a.line!=="auto"&&(this.a.region=null);break;case"position":let[l,h]=r.split(ut),f=$(l);f===null?i=!0:this.a.position=f,h&&Ge.test(h)?this.a.positionAlign=h:h&&(i=!0);break;case"size":let m=$(r);m===null?i=!0:(this.a.size=m,m<100&&(this.a.region=null));break;case"align":Ke.test(r)?this.a.align=r:i=!0;break;default:this.e(this.d?.v(s,r,e))}i&&this.e(this.d?.w(s,r,e))}}e(t){if(t){if(this.k.push(t),this.f.strict)throw this.f.cancel(),t;this.f.onError?.(t)}}};function X(t){let e=t.match(Je);if(!e)return null;let i=e[1]?parseInt(e[1],10):0,n=parseInt(e[2],10),s=parseInt(e[3],10),r=e[4]?parseInt(e[4].padEnd(3,"0"),10):0,a=i*3600+n*60+s+r/1e3;return i<0||n<0||s<0||r<0||n>59||s>59?null:a}function Xe(){return new It}var Qe=Object.freeze({__proto__:null,VTTBlock:St,VTTParser:It,default:Xe,parseVTTTimestamp:X}),Ze=/[0-9]/,ti=/[\s\t]+/,Ot={c:"span",i:"i",b:"b",u:"u",ruby:"ruby",rt:"rt",v:"span",lang:"span",timestamp:"span"},ei={"&amp;":"&","&lt;":"<","&gt;":">","&quot;":'"',"&#39;":"'","&nbsp;":"\xA0","&lrm;":"\u200E","&rlm;":"\u200F"},ii=/&(?:amp|lt|gt|quot|#(0+)?39|nbsp|lrm|rlm);/g,ni=new Set(["white","lime","cyan","red","yellow","magenta","blue","black"]),si=new Set(Object.keys(Ot));function ri(t){let e="",i=1,n=[],s=[],r;for(let l=0;l<t.text.length;l++){let h=t.text[l];switch(i){case 1:h==="<"?(c(),i=2):e+=h;break;case 2:switch(h){case`
`:case"	":case" ":a(),i=4;break;case".":a(),i=3;break;case"/":i=5;break;case">":a(),i=1;break;default:!e&&Ze.test(h)&&(i=6),e+=h}break;case 3:switch(h){case"	":case" ":case`
`:o(),r&&r.class?.trim(),i=4;break;case".":o();break;case">":o(),r&&r.class?.trim(),i=1;break;default:e+=h}break;case 4:h===">"?(e=e.replace(ti," "),r?.type==="v"?r.voice=tt(e):r?.type==="lang"&&(r.lang=tt(e)),e="",i=1):e+=h;break;case 5:h===">"&&(e="",r=s.pop(),i=1);break;case 6:if(h===">"){let f=X(e);f!==null&&f>=t.startTime&&f<=t.endTime&&(e="timestamp",a(),r.time=f),e="",i=1}else e+=h}}function a(){if(si.has(e)){let l=r;r=ai(e),l?(s[s.length-1]!==l&&s.push(l),l.children.push(r)):n.push(r)}e="",i=1}function o(){if(r&&e){let l=e.replace("bg_","");ni.has(l)?r[e.startsWith("bg_")?"bgColor":"color"]=l:r.class=r.class?r.class+" "+e:e}e=""}function c(){if(!e)return;let l={type:"text",data:tt(e)};r?r.children.push(l):n.push(l),e=""}return i===1&&c(),n}function ai(t){return{tagName:Ot[t],type:t,children:[]}}function tt(t){return t.replace(ii,e=>ei[e]||"'")}function x(t,e,i){t.style.setProperty(`--${e}`,i+"")}function L(t,e,i=!0){t.setAttribute(`data-${e}`,i===!0?"":i+"")}function q(t,e){t.setAttribute("part",e)}function oi(t){return parseFloat(getComputedStyle(t).lineHeight)||0}function ci(t,e=0){return Ct(ri(t),e)}function Ct(t,e=0){let i,n="";for(let s of t)if(s.type==="text")n+=s.data;else{let r=s.type==="timestamp";i={},i.class=s.class,i.title=s.type==="v"&&s.voice,i.lang=s.type==="lang"&&s.lang,i.part=s.type==="v"&&"voice",r&&(i.part="timed",i["data-time"]=s.time,i["data-future"]=s.time>e,i["data-past"]=s.time<e),i.style=`${s.color?`color: ${s.color};`:""}${s.bgColor?`background-color: ${s.bgColor};`:""}`;let a=Object.entries(i).filter(o=>o[1]).map(o=>`${o[0]}="${o[1]===!0?"":o[1]}"`).join(" ");n+=`<${s.tagName}${a?" "+a:""}>${Ct(s.children)}</${s.tagName}>`}return n}function li(t,e){for(let i of t.querySelectorAll('[part="timed"]')){let n=Number(i.getAttribute("data-time"));Number.isNaN(n)||(n>e?L(i,"future"):i.removeAttribute("data-future"),n<e?L(i,"past"):i.removeAttribute("data-past"))}}function hi(t,e){let i=null,n;function s(){r(),t(...n),n=void 0}function r(){clearTimeout(i),i=null}function a(){n=[].slice.call(arguments),r(),i=setTimeout(s,e)}return a}var j=Symbol(0);function it(t){return t instanceof HTMLElement?{top:t.offsetTop,width:t.clientWidth,height:t.clientHeight,left:t.offsetLeft,right:t.offsetLeft+t.clientWidth,bottom:t.offsetTop+t.clientHeight}:{...t}}function K(t,e,i){switch(e){case"+x":t.left+=i,t.right+=i;break;case"-x":t.left-=i,t.right-=i;break;case"+y":t.top+=i,t.bottom+=i;break;case"-y":t.top-=i,t.bottom-=i}}function di(t,e){return t.left<=e.right&&t.right>=e.left&&t.top<=e.bottom&&t.bottom>=e.top}function ui(t,e){for(let i=0;i<e.length;i++)if(di(t,e[i]))return e[i];return null}function ft(t,e){return e.top>=0&&e.bottom<=t.height&&e.left>=0&&e.right<=t.width}function fi(t,e,i){switch(i){case"+x":return e.left<0;case"-x":return e.right>t.width;case"+y":return e.top<0;case"-y":return e.bottom>t.height}}function pi(t,e){return Math.max(0,Math.min(t.width,e.right)-Math.max(0,e.left))*Math.max(0,Math.min(t.height,e.bottom)-Math.max(0,e.top))/(t.height*t.width)}function nt(t,e){return{top:e.top/t.height,left:e.left/t.width,right:(t.width-e.right)/t.width,bottom:(t.height-e.bottom)/t.height}}function Lt(t,e){return e.top*=t.height,e.left*=t.width,e.right=t.width-e.right*t.width,e.bottom=t.height-e.bottom*t.height,e}var zt=["top","left","right","bottom"];function jt(t,e,i,n){let s=nt(e,i);for(let r of zt)x(t,`${n}-${r}`,s[r]*100+"%")}function Bt(t,e,i,n){let s=1,r,a={...e};for(let o=0;o<n.length;o++){for(;fi(t,e,n[o])||ft(t,e)&&ui(e,i);)K(e,n[o],1);if(ft(t,e))return e;let c=pi(t,e);s>c&&(r={...e},s=c),e={...a}}return r||a}var Y=Symbol(0);function mi(t,e,i,n){let s=i.firstElementChild,r=wi(e),a,o=[];if(i[j]||(i[j]=gi(t,i)),a=Lt(t,{...i[j]}),i[Y])o=[i[Y]==="top"?"+y":"-y","+x","-x"];else if(e.snapToLines){let c;switch(e.vertical){case"":o=["+y","-y"],c="height";break;case"rl":o=["+x","-x"],c="width";break;case"lr":o=["-x","+x"],c="width"}let l=oi(s),h=l*Math.round(r),f=t[c]+l,m=o[0];Math.abs(h)>f&&(h=h<0?-1:1,h*=Math.ceil(f/l)*l),r<0&&(h+=e.vertical===""?t.height:t.width,o=o.reverse()),K(a,m,h)}else{let c=e.vertical==="",l=c?"+y":"+x",h=c?a.height:a.width;K(a,l,(c?t.height:t.width)*r/100),K(a,l,e.lineAlign==="center"?h/2:e.lineAlign==="end"?h:0),o=c?["-y","+y","-x","+x"]:["-x","+x","-y","+y"]}return a=Bt(t,a,n,o),jt(i,t,a,"cue"),a}function gi(t,e){let i=it(e),n=bi(e);if(e[Y]=!1,n.top&&(i.top=n.top,i.bottom=n.top+i.height,e[Y]="top"),n.bottom){let s=t.height-n.bottom;i.top=s-i.height,i.bottom=s,e[Y]="bottom"}return n.left&&(i.left=n.left),n.right&&(i.right=t.width-n.right),nt(t,i)}function bi(t){let e={};for(let i of zt)e[i]=parseFloat(t.style.getPropertyValue(`--cue-${i}`));return e}function wi(t){return t.line==="auto"?t.snapToLines?-1:100:t.line}function yi(t){if(t.position==="auto")switch(t.align){case"start":case"left":return 0;case"right":case"end":return 100;default:return 50}return t.position}function vi(t,e){if(t.positionAlign==="auto")switch(t.align){case"start":return e==="ltr"?"line-left":"line-right";case"end":return e==="ltr"?"line-right":"line-left";case"center":return"center";default:return`line-${t.align}`}return t.positionAlign}var Ai=["-y","+y","-x","+x"];function xi(t,e,i,n){let s=Array.from(i.querySelectorAll('[part="cue-display"]')),r=0,a=Math.max(0,s.length-e.lines);for(let c=s.length-1;c>=a;c--)r+=s[c].offsetHeight;x(i,"region-height",r+"px"),i[j]||(i[j]=nt(t,it(i)));let o={...i[j]};return o=Lt(t,o),o.width=i.clientWidth,o.height=r,o.right=o.left+o.width,o.bottom=o.top+r,o=Bt(t,o,n,Ai),jt(i,t,o,"region"),o}var ki=class{overlay;z;A=0;C="ltr";B=[];D=!1;E;h=new Map;j=new Map;get dir(){return this.C}set dir(t){this.C=t,L(this.overlay,"dir",t)}get currentTime(){return this.A}set currentTime(t){this.A=t,this.update()}constructor(t,e){this.overlay=t,this.dir=e?.dir??"ltr",t.setAttribute("translate","yes"),t.setAttribute("aria-live","off"),t.setAttribute("aria-atomic","true"),q(t,"captions"),this.G(),this.E=new ResizeObserver(this.I.bind(this)),this.E.observe(t)}changeTrack({regions:t,cues:e}){this.reset(),this.J(t);for(let i of e)this.j.set(i,null);this.update()}addCue(t){this.j.set(t,null),this.update()}removeCue(t){this.j.delete(t),this.update()}update(t=!1){this.H(t)}reset(){this.j.clear(),this.h.clear(),this.B=[],this.overlay.textContent=""}destroy(){this.reset(),this.E.disconnect()}I(){this.D=!0,this.K()}K=hi(()=>{this.D=!1,this.G();for(let t of this.h.values())t[j]=null;for(let t of this.j.values())t&&(t[j]=null);this.H(!0)},50);G(){this.z=it(this.overlay),x(this.overlay,"overlay-width",this.z.width+"px"),x(this.overlay,"overlay-height",this.z.height+"px")}H(t=!1){if(!this.j.size||this.D)return;let e,i=[...this.j.keys()].filter(s=>this.A>=s.startTime&&this.A<=s.endTime).sort((s,r)=>s.startTime===r.startTime?s.endTime-r.endTime:s.startTime-r.startTime),n=i.map(s=>s.region);for(let s=0;s<this.B.length;s++){if(e=this.B[s],i[s]===e)continue;if(e.region&&!n.includes(e.region)){let a=this.h.get(e.region.id);a&&(a.removeAttribute("data-active"),t=!0)}let r=this.j.get(e);r&&(r.remove(),t=!0)}for(let s=0;s<i.length;s++){e=i[s];let r=this.j.get(e);r||this.j.set(e,r=this.L(e));let a=this.F(e)&&this.h.get(e.region.id);a&&!a.hasAttribute("data-active")&&(requestAnimationFrame(()=>L(a,"active")),t=!0),r.isConnected||((a||this.overlay).append(r),t=!0)}if(t){let s=[],r=new Set;for(let a=i.length-1;a>=0;a--){if(e=i[a],r.has(e.region||e))continue;let o=this.F(e),c=o?this.h.get(e.region.id):this.j.get(e);o?s.push(xi(this.z,e.region,c,s)):s.push(mi(this.z,e,c,s)),r.add(o?e.region:e)}}li(this.overlay,this.A),this.B=i}J(t){if(t)for(let e of t){let i=this.M(e);this.h.set(e.id,i),this.overlay.append(i)}}M(t){let e=document.createElement("div");return q(e,"region"),L(e,"id",t.id),L(e,"scroll",t.scroll),x(e,"region-width",t.width+"%"),x(e,"region-anchor-x",t.regionAnchorX),x(e,"region-anchor-y",t.regionAnchorY),x(e,"region-viewport-anchor-x",t.viewportAnchorX),x(e,"region-viewport-anchor-y",t.viewportAnchorY),x(e,"region-lines",t.lines),e}L(t){let e=document.createElement("div"),i=yi(t),n=vi(t,this.C);if(q(e,"cue-display"),t.vertical!==""&&L(e,"vertical"),x(e,"cue-text-align",t.align),t.style)for(let r of Object.keys(t.style))e.style.setProperty(r,t.style[r]);if(this.F(t))x(e,"cue-offset",`${i-(n==="line-right"?100:n==="center"?50:0)}%`);else if(x(e,"cue-writing-mode",t.vertical===""?"horizontal-tb":t.vertical==="lr"?"vertical-lr":"vertical-rl"),!t.style?.["--cue-width"]){let r=i;n==="line-left"?r=100-i:n==="center"&&i<=50?r=i*2:n==="center"&&i>50&&(r=(100-i)*2);let a=t.size<r?t.size:r;t.vertical===""?x(e,"cue-width",a+"%"):x(e,"cue-height",a+"%")}let s=document.createElement("div");return q(s,"cue"),t.id&&L(s,"id",t.id),s.innerHTML=ci(t),e.append(s),e}F(t){return t.region&&t.size===100&&t.vertical===""&&t.line==="auto"}},Mi=`:where([part=captions]){--overlay-padding:1%;--cue-color:white;--cue-bg-color:#000c;--cue-font-size:calc(var(--overlay-height) / 100 * 5);--cue-line-height:calc(var(--cue-font-size) * 1.2);--cue-padding-x:calc(var(--cue-font-size) * .6);--cue-padding-y:calc(var(--cue-font-size) * .4);z-index:1;contain:content;margin:var(--overlay-padding);font-size:var(--cue-font-size);box-sizing:border-box;pointer-events:none;user-select:none;word-spacing:normal;word-break:break-word;font-family:sans-serif;position:absolute;inset:0}:where([part=captions]>[part=cue-display]){contain:content;top:var(--cue-top);left:var(--cue-left);right:var(--cue-right);bottom:var(--cue-bottom);width:var(--cue-width,auto);height:var(--cue-height,auto);box-sizing:border-box;transform:var(--cue-transform);text-align:var(--cue-text-align);writing-mode:var(--cue-writing-mode,unset);white-space:pre-line;direction:ltr;unicode-bidi:plaintext;min-width:min-content;min-height:min-content;position:absolute;overflow:visible}:where([data-dir=rtl] [part=cue-display]){direction:rtl}:where([part=captions] [part=cue]){padding:var(--cue-padding-y) var(--cue-padding-x);line-height:var(--cue-line-height);background-color:var(--cue-bg-color);box-sizing:border-box;color:var(--cue-color);box-shadow:var(--cue-box-shadow);white-space:var(--cue-white-space,pre-wrap);outline:var(--cue-outline);text-shadow:var(--cue-text-shadow);display:inline-block}:where([part=captions] [part=cue-display][data-vertical] [part=cue]){padding:var(--cue-padding-x) var(--cue-padding-y)}
:where([part=captions] [part=region]){width:var(--region-width);height:var(--region-height);min-height:0;max-height:var(--region-height);writing-mode:horizontal-tb;top:calc(var(--region-top,var(--overlay-height) * var(--region-viewport-anchor-y) / 100 - var(--region-height) * var(--region-anchor-y) / 100));left:var(--region-left,calc(calc(var(--region-viewport-anchor-x) * 1%) - calc(var(--region-width) * var(--region-anchor-x) / 100)));right:var(--region-right);bottom:var(--region-bottom);overflow-wrap:break-word;box-sizing:border-box;flex-flow:column;justify-content:flex-start;display:inline-flex;position:absolute;overflow:hidden}:where([part=captions] [part=region][data-scroll=up]){justify-content:end}:where([part=captions] [part=region][data-active][data-scroll=up]){transition:top .433s}:where([part=captions] [part=region]>[part=cue-display]){width:auto;left:var(--cue-offset);height:var(--cue-height,auto);text-align:var(--cue-text-align);unicode-bidi:plaintext;margin-top:1px;position:relative}:where([part=captions] [part=region] [part=cue]){padding:calc(var(--cue-padding-y) / 2) var(--cue-padding-x);border-radius:0;position:relative}`,Ti=d.Milli(3e4),Ei=d.Milli(3e4),Ri=d.Milli(1e3);function pt(t){return t.replaceAll("&","&amp;amp;").replaceAll("<","&amp;lt;").replaceAll(">","&amp;gt;").replaceAll('"',"&amp;quot;")}function mt(t,e){let i=t.length;for(;i>0&&t[i-1].startTime>e.startTime;)i--;t.splice(i,0,e)}function Si(t,e){let{cues:i,clears:n}=t,s=0;for(let a of n)a>=e&&(n[s++]=a);n.length=s;let r=0;for(let a of i)a.endTime>=e&&(i[r++]=a);return r!==i.length&&(i.length=r,!0)}function Ii(t,e){let{cues:i,clears:n}=t,s=i.indexOf(e),r=s>0?i[s-1]:void 0;r&&r.endTime>e.startTime&&(r.endTime=e.startTime);let a=i[s+1];a&&e.endTime>a.startTime&&(e.endTime=a.startTime);let o=n.find(c=>c>e.startTime);o!==void 0&&e.endTime>o&&(e.endTime=o)}function Oi(t,e){let{cues:i,clears:n}=t,s=n.length;for(;s>0&&n[s-1]>e;)s--;n[s]!==e&&n.splice(s,0,e);for(let r=i.length-1;r>=0;r--){let a=i[r];if(!(a.startTime>e)){a.endTime>e&&(a.endTime=e);return}}}var Ci=class{source;sync;in;#t=new M;#e=!1;constructor(t){this.source=t.source,this.sync=t.sync,this.in={container:p(t?.container),enabled:p(t?.enabled??!0)},this.#t.run(this.#i.bind(this))}#i(t){let e=t.getAll([this.in.enabled,this.in.container,this.source.out.track,this.source.out.config,this.source.in.broadcast]);if(!e)return;let[i,n,s,r,a]=e,o=a.relativeBroadcast(t,r.broadcast);if(!o)return;this.#e=!1;let c;if(r.container.kind==="legacy")c=new b.Legacy.Format("data");else if(r.container.kind==="loc")c=new b.Loc.Format;else{console.warn(`captions: unsupported container "${r.container.kind}" for track ${s}`);return}let l=document.createElement("style");l.textContent=Mi,n.appendChild(l),t.cleanup(()=>l.remove());let h=document.createElement("div");h.style.position="absolute",h.style.inset="0",h.style.pointerEvents="none",n.appendChild(h),t.cleanup(()=>h.remove());let f=new ki(h);t.cleanup(()=>f.destroy());let m=et(t,{broadcast:o,track:s,priority:w.PRIORITY.text,maxAge:this.sync.out.maxAge});if(!m)return;let g={cues:[],regions:new Map,clears:[]},k=()=>f.changeTrack({cues:[...g.cues],regions:[...g.regions.values()]}),y=()=>{let v=this.sync.now();v!==void 0&&(f.currentTime=v/1e3,Si(g,(v-Ti)/1e3)&&k()),t.animate(y)};t.animate(y),t.spawn(async()=>{for(;;){let v=await m.recvGroup().catch(T=>{if(!(T instanceof U.Stream))throw T;console.debug("captions subscription ended",T)});if(!v)break;t.spawn(async()=>{try{for(;;){let T=await v.readFrame();if(!T)break;for(let S of c.decode(T.payload))await this.#n(r.format,S,g)}}catch(T){if(!(T instanceof U.Stream))throw T}finally{v.close()}k()})}})}async#n(t,e,i){let n=new TextDecoder().decode(e.payload),s=e.timestamp/1e6;if(t==="utf8"){if(n.length===0){Oi(i,s);return}let o=new Rt(s,s+Ei/1e3,pt(n));mt(i.cues,o),Ii(i,o);return}if(n.length===0)return;let r;try{r=await Le(n,{type:"vtt"})}catch(o){console.warn("captions: failed to parse VTT cue",o);return}let a=r.cues.at(0);!this.#e&&a&&Math.abs(a.startTime-s)>Ri/1e3&&(this.#e=!0,console.warn(`captions: cue timing is ${(a.startTime-s).toFixed(3)}s off its frame timestamp; the payload must carry absolute times on the media clock`));for(let o of r.regions)i.regions.set(o.id,o);for(let o of r.cues)o.text=pt(o.text),mt(i.cues,o)}close(){this.#t.close()}},Li=new Set(["vtt","utf8"]);function zi(t){return Li.has(t.format)}var ji=class{in;#t={catalog:new u(void 0),available:new u({}),track:new u(void 0),config:new u(void 0)};out=I(this.#t);#e=new M;constructor(t){this.in={broadcast:p(t?.broadcast),target:p(t?.target)},this.#e.run(this.#i.bind(this)),this.#e.run(this.#n.bind(this))}#i(t){let e=t.get(this.in.broadcast),i=e?t.get(e.out.catalog)?.text:void 0;t.set(this.#t.catalog,i),this.#t.available.set(i?.renditions??{})}#n(t){let e=t.get(this.#t.available),i=t.get(this.in.target),n=i?e[i]:void 0;if(!i||!n){t.set(this.#t.track,void 0),t.set(this.#t.config,void 0);return}zi(n)||console.warn(`captions: unsupported format ${JSON.stringify(n.format)} for track ${i}`),t.set(this.#t.track,i),t.set(this.#t.config,n)}close(){this.#e.close()}},Nt=Symbol("supportCacheKey");function Ft(t){return{broadcast:t.broadcast,decoder:{codec:t.codec,container:t.container,description:t.description,displayAspectWidth:t.displayAspectWidth,displayAspectHeight:t.displayAspectHeight,optimizeForLatency:t.optimizeForLatency??!0}}}function Bi(t){return JSON.stringify(Ft(t).decoder)}var Ni=d.Milli(100);function Fi(t){if(t.jitter!==void 0)return d.Milli(t.jitter);if(t.framerate)return d.Milli(Math.ceil(1e3/t.framerate))}function Wi(t){return t.active===void 0||d.Milli.add(t.playhead,Ni)>=t.active}function Pi(t){return t.active===void 0?t.pending:t.pending===void 0?t.active:d.Milli.max(t.active,t.pending)}function Wt(t=0){let e=(t%360+360)%360;return Math.round(e/90)%4*90}function Pt(t,e=0){let i=Wt(e);return i===90||i===270?{width:t.height,height:t.width}:{width:t.width,height:t.height}}function F(t){return Object.is(t,-0)?0:t}function _i(t,e){let[i,n,s,r,a,o]=t;return[F(-i),F(n),F(-s),F(r),F(e-a),F(o)]}function Hi(t,e){let i=Wt(e?.rotation),n=Pt(t,i),s;switch(i){case 90:s=[0,1,-1,0,t.width,0];break;case 180:s=[-1,0,0,-1,t.width,t.height];break;case 270:s=[0,-1,1,0,0,t.height];break;default:s=[1,0,0,1,0,0]}return e?.flip&&(s=_i(s,t.width)),{matrix:s,source:n}}var $i=d.Milli(500),gt=class{in;source;sync;#t={frame:new u(void 0),timestamp:new u(void 0),display:new u(void 0),stalled:new u(!1),stats:new u(void 0),jitter:new u(void 0),buffered:new u([])};out=I(this.#t);#e=new u(void 0);#i=new u(void 0);#n;#s=new M;#r(){this.#t.frame.update(t=>{t?.close()}),this.#t.timestamp.set(void 0)}constructor(t){this.in={enabled:p(t?.enabled??!0)},this.source=t.source,this.sync=t.sync,this.#s.cleanup(this.sync.register(this.out.jitter)),this.#n=this.#s.computed(e=>{let i=e.get(this.source.out.config);return i?Ft(i):void 0}),this.#s.run(this.#a.bind(this)),this.#s.run(this.#o.bind(this)),this.#s.run(this.#c.bind(this)),this.#s.run(this.#l.bind(this)),this.#s.run(this.#h.bind(this))}#a(t){let e=t.get(this.#e)?.jitter,i=t.get(this.#i);t.set(this.#t.jitter,Pi({active:e,pending:i}))}#o(t){let e=t.getAll([this.in.enabled,this.source.in.broadcast,this.source.out.track,this.#n]);if(!e){this.#e.set(void 0);return}let[i,n,s,r]=e,a=n.relativeBroadcast(t,r.broadcast);if(!a){this.#e.set(void 0),this.#r(),this.#t.buffered.set([]);return}let o=new Di({sync:this.sync,broadcast:a,track:s,config:r.decoder,stats:this.#t.stats});t.set(this.#i,o.jitter),t.cleanup(()=>o?.close()),t.run(c=>{if(!o)return;let l=c.get(this.#e);if(l){let h=c.get(o.timestamp);if(h===void 0||!Wi({playhead:h,active:c.get(l.timestamp)}))return}this.#e.set(o),this.#i.set(void 0),o=void 0,c.close()})}#c(t){let e=t.get(this.#e);if(!e){this.#t.buffered.set([]);return}t.cleanup(()=>e.close()),t.run(i=>{let n=i.get(e.frame);this.#t.frame.update(s=>(s?.close(),n?.clone()))}),t.proxy(this.#t.timestamp,e.timestamp),t.proxy(this.#t.buffered,e.buffered)}#l(t){let e=t.get(this.source.out.catalog);if(!e)return;let i=e.display;if(i){t.set(this.#t.display,{width:i.width,height:i.height});return}let n=t.get(this.#t.frame);n&&t.set(this.#t.display,Pt({width:n.displayWidth,height:n.displayHeight},e.rotation))}#h(t){if(t.get(this.in.enabled)){if(!t.get(this.#t.frame)){this.#t.stalled.set(!0);return}this.#t.stalled.set(!1),t.timer(()=>{this.#t.stalled.set(!0)},$i)}}close(){this.#r(),this.#s.close()}static supported=_t},Di=class{sync;broadcast;track;config;stats;jitter;timestamp=new u(void 0);frame=new u(void 0);buffered=new u([]);#t=new u([]);#e=0;#i=new M;constructor(t){this.sync=t.sync,this.broadcast=t.broadcast,this.track=t.track,this.config=t.config,this.stats=t.stats,this.jitter=Fi(t.config),this.#i.run(this.#n.bind(this))}#n(t){let e=et(t,{broadcast:this.broadcast,track:this.track,priority:w.PRIORITY.video,maxAge:this.sync.out.maxAge});if(!e)return;let i=new VideoDecoder({output:async n=>{try{let s=this.#e,r=d.Milli.fromMicro(n.timestamp);if(r<(this.timestamp.peek()??0)||this.sync.out.reference.peek()===void 0)return;this.frame.peek()===void 0&&this.frame.set(n.clone());let a=this.sync.wait(r).then(()=>!0);if(!await Promise.race([a,t.cancel])||s!==this.#e||r<(this.timestamp.peek()??0))return;this.timestamp.set(r),this.#c(r),this.frame.update(o=>(o?.close(),n.clone()))}finally{n.close()}},error:n=>{console.error("video decoder error",n),t.close()}});t.cleanup(()=>{i.state!=="closed"&&i.close()}),this.config.container.kind==="cmaf"?this.#r(t,e,i):this.#s(t,e,i)}#s(t,e,i){let n=this.config.container.kind==="loc"?new b.Loc.Format("video"):new b.Legacy.Format(this.config),s=new b.Consumer(e,{format:n,maxAge:this.sync.out.maxAge});t.cleanup(()=>s.close()),t.run(a=>{let o=a.get(s.buffered),c=a.get(this.#t);this.buffered.update(()=>b.mergeBufferedRanges(o,c))}),i.configure({codec:this.config.codec,description:this.config.description?A.Hex.toBytes(this.config.description):void 0,displayAspectWidth:this.config.displayAspectWidth,displayAspectHeight:this.config.displayAspectHeight,optimizeForLatency:this.config.optimizeForLatency,flip:!1});let r;t.spawn(async()=>{for(;;){let a=await G(s);if(!a)break;this.#a(a.discontinuity)&&(r=void 0);let{frame:o}=a;if(!o)continue;let c=d.Milli.fromMicro(o.timestamp);this.sync.received(c,"video");let l=new EncodedVideoChunk({type:o.keyframe?"key":"delta",data:o.payload,timestamp:o.timestamp});this.stats.update(h=>({frameCount:(h?.frameCount??0)+1,bytesReceived:(h?.bytesReceived??0)+o.payload.byteLength})),r!==void 0&&a.continuous&&this.#o(d.Milli.fromMicro(r),d.Milli.fromMicro(o.timestamp)),r=o.timestamp,i.decode(l)}})}#r(t,e,i){let n=this.config.container;if(n.kind!=="cmaf")return;let s=V(n.init),r=b.Cmaf.decodeInitSegment(s),a=this.config.description?A.Hex.toBytes(this.config.description):r.description,o=new b.Consumer(e,{format:new b.Cmaf.Format(r),maxAge:this.sync.out.maxAge});t.cleanup(()=>o.close()),t.run(l=>{let h=l.get(o.buffered),f=l.get(this.#t);this.buffered.update(()=>b.mergeBufferedRanges(h,f))}),i.configure({codec:this.config.codec,description:a,displayAspectWidth:this.config.displayAspectWidth,displayAspectHeight:this.config.displayAspectHeight,optimizeForLatency:this.config.optimizeForLatency,flip:!1});let c;t.spawn(async()=>{for(;;){let l=await G(o);if(!l)break;this.#a(l.discontinuity)&&(c=void 0);let{frame:h}=l;if(!h)continue;let f=d.Milli.fromMicro(h.timestamp);if(this.sync.received(f,"video"),this.stats.update(m=>({frameCount:(m?.frameCount??0)+1,bytesReceived:(m?.bytesReceived??0)+h.payload.byteLength})),c!==void 0&&l.continuous&&this.#o(d.Milli.fromMicro(c),d.Milli.fromMicro(h.timestamp)),c=h.timestamp,i.state==="closed")break;i.decode(new EncodedVideoChunk({type:h.keyframe?"key":"delta",data:h.payload,timestamp:h.timestamp}))}})}#a(t){return t!==this.#e&&(this.#e=t,this.timestamp.set(void 0),this.#t.set([]),this.sync.reset(),!0)}#o(t,e){t>e||this.#t.mutate(i=>{for(let n of i)if(n.start<=e&&n.end>=t){n.start=d.Milli.min(n.start,t),n.end=d.Milli.max(n.end,e);return}i.push({start:t,end:e}),i.sort((n,s)=>n.start-s.start)})}#c(t){this.#t.mutate(e=>{for(;e.length>0;){if(e[0].end>=t){e[0].start=d.Milli.max(e[0].start,t);break}e.shift()}})}close(){this.#i.close(),this.frame.update(t=>{t?.close()})}};async function _t(t){if(!w.containerSupported(t.container)){let n=t.container.kind==="unknown"?t.container.raw.kind:t.container.kind;return console.warn(`video: ignoring rendition with unknown container: ${n}`),!1}let e;if(t.description)e=A.Hex.toBytes(t.description);else if(t.container.kind==="cmaf")try{e=b.Cmaf.decodeInitSegment(V(t.container.init)).description}catch(n){return console.warn(`video: malformed CMAF init segment for codec ${t.codec}`,n),!1}let{supported:i}=await VideoDecoder.isConfigSupported({codec:t.codec,description:e,displayAspectWidth:t.displayAspectWidth,displayAspectHeight:t.displayAspectHeight,optimizeForLatency:t.optimizeForLatency??!0});if(i)return!0;if(t.codec.startsWith("avc3.")){let n=`avc1.${t.codec.slice(5)}`;if((await VideoDecoder.isConfigSupported({codec:n,description:e,displayAspectWidth:t.displayAspectWidth,displayAspectHeight:t.displayAspectHeight,optimizeForLatency:t.optimizeForLatency??!0})).supported)return t.codec=n,!0}return!1}Object.assign(_t,{[Nt]:Bi});var bt=.01,Yi=class{decoder;in;#t={frame:new u(void 0),timestamp:new u(void 0),visible:new u(!1)};out=I(this.#t);#e=new u(void 0);#i=new M;constructor(t){this.decoder=t.decoder,this.in={canvas:p(t?.canvas),visible:p(t?.visible??"20%")},this.#i.run(e=>{let i=e.get(this.in.canvas);this.#e.set(i?.getContext("2d")??void 0)}),this.#i.run(this.#s.bind(this)),this.#i.run(this.#r.bind(this)),this.#i.run(this.#n.bind(this))}#n(t){let e=t.getAll([this.in.canvas,this.decoder.out.display]);if(!e)return;let[i,n]=e;(i.width!==n.width||i.height!==n.height)&&(i.width=n.width,i.height=n.height)}#s(t){let e=t.get(this.in.visible);if(e==="never"){this.#t.visible.set(!1);return}if(e==="always"){this.#t.visible.set(!0),t.cleanup(()=>this.#t.visible.set(!1));return}let i=t.get(this.in.canvas);if(!i){this.#t.visible.set(!1);return}let n=!1,s=()=>{this.#t.visible.set(n&&!document.hidden)},r=o=>{for(let c of o)n=c.isIntersecting,s()},a;try{a=new IntersectionObserver(r,{threshold:bt,rootMargin:e})}catch{console.warn(`moq-watch: invalid visible margin "${e}", using "0px"`),a=new IntersectionObserver(r,{threshold:bt})}s(),t.event(document,"visibilitychange",s),a.observe(i),t.cleanup(()=>a.disconnect()),t.cleanup(()=>this.#t.visible.set(!1))}#r(t){let e=t.get(this.#e);if(!e)return;let i=t.get(this.decoder.out.frame),n=t.get(this.decoder.source.out.catalog),s=requestAnimationFrame(()=>{this.#a(e,i,n),i?(this.#t.frame.update(r=>(r?.close(),i.clone())),this.#t.timestamp.set(d.Milli.fromMicro(i.timestamp))):(this.#t.frame.update(r=>{r?.close()}),this.#t.timestamp.set(void 0)),s=void 0});t.cleanup(()=>{s!==void 0&&cancelAnimationFrame(s)})}#a(t,e,i){if(!e){t.fillStyle="#000",t.fillRect(0,0,t.canvas.width,t.canvas.height);return}if(t.save(),t.fillStyle="#000",t.fillRect(0,0,t.canvas.width,t.canvas.height),!i?.rotation)i?.flip&&(t.scale(-1,1),t.translate(-t.canvas.width,0)),t.drawImage(e,0,0,t.canvas.width,t.canvas.height);else{let n=Hi(t.canvas,i);t.setTransform(...n.matrix),t.drawImage(e,0,0,n.source.width,n.source.height)}t.restore()}close(){this.#t.frame.update(t=>{t?.close()}),this.#t.timestamp.set(void 0),this.#i.close()}};function Vi(t){return e=>{let i=[],n=[];for(let[s,r]of e)if(r.codedWidth&&r.codedHeight){let a=r.codedWidth*r.codedHeight;a<=t?i.push({name:s,size:a}):n.push({name:s,size:a})}return i.sort((s,r)=>r.size-s.size),i.length>0?i.map(s=>s.name):n.length>0?(n.sort((s,r)=>s.size-r.size),[n[0].name]):e.map(([s])=>s)}}function Ht(t,e){return i=>{let n=[],s=[];for(let[r,a]of i){if(!a.codedWidth||!a.codedHeight)continue;let o=a.codedWidth*a.codedHeight,c=t==null||a.codedWidth<=t,l=e==null||a.codedHeight<=e;c&&l?n.push({name:r,size:o}):s.push({name:r,size:o})}return n.sort((r,a)=>a.size-r.size),n.length>0?n.map(r=>r.name):s.length>0?(s.sort((r,a)=>r.size-a.size),[s[0].name]):i.map(([r])=>r)}}function $t(t){return e=>{let i=[],n=[];for(let[s,r]of e)r.bitrate!=null&&r.bitrate<=t?i.push({name:s,bitrate:r.bitrate}):r.bitrate!=null&&n.push({name:s,bitrate:r.bitrate});return i.sort((s,r)=>r.bitrate-s.bitrate),i.length>0?i.map(s=>s.name):n.length>0?(n.sort((s,r)=>s.bitrate-r.bitrate),[n[0].name]):e.map(([s])=>s)}}function qi(t){let e=t[0];for(let i of t){let[,n]=i,[,s]=e,r=(n.codedWidth??0)*(n.codedHeight??0),a=(s.codedWidth??0)*(s.codedHeight??0);if(r!==a){r>a&&(e=i);continue}(n.bitrate??0)>(s.bitrate??0)&&(e=i)}return e[0]}function Ki(t){let e=Object.entries(t).filter(([,r])=>!r.stalled);if(e.length>0)return Object.fromEntries(e);let i=Object.entries(t);if(i.length===0)return{};let n=$t(0)(i),s=n.length===1?n[0]:Ht(0,0)(i)[0];return{[s]:t[s]}}var Ui=class{in;#t={catalog:new u(void 0),available:new u({}),error:new u(void 0),track:new u(void 0),config:new u(void 0)};out=I(this.#t);#e=new M;#i=new WeakMap;constructor(t){this.in={broadcast:p(t?.broadcast),target:p(t?.target),supported:p(t?.supported),probe:p(t?.probe)},this.#e.run(this.#n.bind(this)),this.#e.run(this.#s.bind(this)),this.#e.run(this.#r.bind(this))}#n(t){let e=t.get(this.in.broadcast);if(!e)return;let i=t.get(e.out.catalog)?.video;i&&t.set(this.#t.catalog,i)}#s(t){let e=t.get(this.in.supported);if(!e){this.#t.error.set(void 0);return}let i=t.get(this.#t.catalog)?.renditions??{};this.#t.error.set(void 0);let n=this.#i.get(e);n||(n=new Map,this.#i.set(e,n));let s=new Set(Object.keys(i));for(let r of n.keys())s.has(r)||n.delete(r);t.spawn(async()=>{let r={},a=t.cancel.then(()=>{});for(let[c,l]of Object.entries(i)){let h=e[Nt],f=h?h(l):JSON.stringify(l),m=n.get(c),g=!1;if(m?.key===f)g=m.supported;else{let k=!1;try{g=await Promise.race([e(l),a])}catch(y){k=!0,console.warn(`[Source] video rendition ${c} (${l.codec}) support probe failed; treating as unsupported`,y)}!k&&g!==void 0&&n.set(c,{key:h?h(l):JSON.stringify(l),supported:g})}if(t.abort.aborted)return;g&&(r[c]=l)}let o=Object.keys(r).length===0&&Object.keys(i).length>0?"unsupported":void 0;o==="unsupported"&&console.warn("[Source] No supported video renditions found:",i),this.#t.error.set(o),this.#t.available.set(r)})}#r(t){let e=t.get(this.#t.available),i=t.get(this.in.target);if(i?.name&&i.name in e){let o=e[i.name];t.set(this.#t.track,i.name),t.set(this.#t.config,o);return}let n=Ki(e);if(Object.keys(n).length===0)return;let s=i;if(!i?.bitrate){let o=t.get(this.in.probe)?.estimatedRecvRate;if(o!=null){let c=Math.round(o*.8);s={...i,bitrate:c}}}let r=this.#a(n,s);if(!r)return;let a=n[r];t.set(this.#t.track,r),t.set(this.#t.config,a)}#a(t,e){let i=Object.entries(t);if(i.length===0)return;if(i.length===1)return i[0][0];let n=[];if(e?.pixels!=null&&n.push(Vi(e.pixels)),(e?.width!=null||e?.height!=null)&&n.push(Ht(e.width,e.height)),e?.bitrate!=null&&n.push($t(e.bitrate)),n.length===0)return qi(i);let s=n.map(a=>a(i)),r=s.map(a=>new Set(a));for(let a of s[0])if(r.every(o=>o.has(a)))return a;console.warn("conflicting rendition filters, no rendition satisfies all criteria")}close(){this.#e.close()}},en=class{in;broadcast;sync;text;video;audio;renderer;emitter;textRenderer;#t=new u(!1);#e=new u(!1);#i=new u(!1);#n=new M;constructor(t={}){this.in=I({origin:p(t.origin),name:p(t.name??D.empty()),enabled:p(t.enabled??!0),announced:p(t.announced??!0),catalogFormat:p(t.catalogFormat),catalog:p(t.catalog),probe:p(t.probe),canvas:p(t.canvas),container:p(t.container),paused:p(t.paused??!1),volume:p(t.volume??.5),muted:p(t.muted??!1),visible:p(t.visible??"20%"),delay:p(t.delay??"auto"),buffer:p(t.buffer??d.Milli.zero),target:p(t.target),captions:p(t.captions)}),this.broadcast=new Se(this.in),this.#n.cleanup(()=>this.broadcast.close());let e=new Ui({broadcast:this.broadcast,target:this.in.target,supported:gt.supported,probe:this.in.probe}),i=new ve({broadcast:this.broadcast,supported:at.supported});this.#n.cleanup(()=>{e.close(),i.close()}),this.text=new ji({broadcast:this.broadcast,target:this.in.captions}),this.#n.cleanup(()=>this.text.close()),this.sync=new Oe({delay:this.in.delay,buffer:this.in.buffer,probe:this.in.probe}),this.#n.cleanup(()=>this.sync.close()),this.video=new gt({source:e,sync:this.sync,enabled:this.#t}),this.audio=new at({source:i,sync:this.sync,enabled:this.#e}),this.#n.cleanup(()=>{this.video.close(),this.audio.close()}),this.emitter=new ye({source:this.audio,volume:this.in.volume,muted:this.in.muted,paused:this.in.paused}),this.renderer=new Yi({decoder:this.video,canvas:this.in.canvas,visible:this.in.visible}),this.#n.cleanup(()=>{this.emitter.close(),this.renderer.close()}),this.textRenderer=new Ci({source:this.text,sync:this.sync,container:this.in.container,enabled:this.#i}),this.#n.cleanup(()=>this.textRenderer.close()),this.#n.run(n=>{this.#i.set(n.get(this.in.enabled)&&!n.get(this.in.paused))}),this.#n.run(n=>{this.#e.set(n.get(this.in.enabled)&&n.get(this.emitter.out.enabled))}),this.#n.run(n=>{let s=n.get(this.renderer.out.visible);n.get(this.in.enabled)?n.get(this.in.paused)?this.#t.set(s&&!n.get(this.renderer.out.frame)):this.#t.set(s):this.#t.set(!1)})}reset(){this.sync.reset(),this.audio.reset()}close(){this.#n.close()}};export{ye as C,ve as S,It as _,ji as a,Se as b,Oi as c,Ii as d,pt as f,Rt as g,St as h,gt as i,mt as l,Zi as m,Ui as n,zi as o,tn as p,Yi as r,Ci as s,en as t,Si as u,X as v,at as w,Qi as x,Oe as y};
//# sourceMappingURL=player-DiUmUis6.mjs.map