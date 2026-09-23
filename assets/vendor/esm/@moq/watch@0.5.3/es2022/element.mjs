/* esm.sh - @moq/watch@0.5.3/element */
import{Time as p}from"../../net@^0.3.4.target-es2022.mjs";import{Effect as St,Signal as j,getter as D,readonlys as Et}from"../../signals@^0.2.3.target-es2022.mjs";function S(t){return t==="instant"?{min:p.Milli.zero,max:p.Milli.zero}:t==="real-time"||typeof t=="number"?{min:t,max:t}:{min:t.min??"real-time",max:t.max??"real-time"}}function Y(t,e){return t===e?t:{min:t,max:e}}var Tt=p.Milli(20),G=p.Milli(100),Q=class X{in;#t={reference:new j(void 0),buffer:new j(p.Milli.zero),jitter:new j(G),timestamp:new j(void 0),buffered:new j(!1),maxBuffer:new j(p.Milli.zero)};out=Et(this.#t);#e;#i=new Map;#n;#s=new St;constructor(e){this.in={latency:D(e?.latency??"real-time"),connection:D(e?.connection),audio:D(e?.audio),video:D(e?.video)},this.#e=Promise.withResolvers(),this.#s.run(this.#o.bind(this)),this.#s.run(this.#h.bind(this)),this.#s.run(this.#a.bind(this))}#a(e){let{max:i}=S(e.get(this.in.latency)),n=e.get(this.#t.buffer);i==="real-time"?(this.#t.buffered.set(!1),this.#t.maxBuffer.set(n)):(this.#t.buffered.set(i>n),this.#t.maxBuffer.set(p.Milli.max(i,n)))}#r(){let{max:e}=S(this.in.latency.peek()),i=this.#t.buffer.peek();return e==="real-time"?i:p.Milli.max(e,i)}#o(e){let{min:i}=S(e.get(this.in.latency));if(typeof i=="number"){this.#n=void 0,this.#t.jitter.set(i);return}let n=e.get(this.in.connection),s=n&&e.get(n.probe).rtt;if(s!==void 0){this.#n=this.#n===void 0?s:Math.min(this.#n,s);let a=p.Milli(Math.max(Tt,this.#n*1.25));this.#t.jitter.set(a);return}this.#n=void 0,this.#t.jitter.set(G)}#h(e){let i=e.get(this.#t.jitter),n=e.get(this.in.video)??p.Milli.zero,s=e.get(this.in.audio)??p.Milli.zero,a=p.Milli.add(p.Milli.max(n,s),i);this.#t.buffer.set(a),this.#e.resolve(),this.#e=Promise.withResolvers()}received(e,i=""){this.#t.timestamp.update(c=>c===void 0||e>c?e:c);let n=p.Milli.now(),s=p.Milli.sub(n,e),a=this.#t.reference.peek();if(a===void 0){this.#l(s);return}let o=this.#t.buffer.peek(),r=p.Milli.add(p.Milli.sub(a,s),o);if(r<0){let c=this.#i.get(i);c?(c.count++,c.maxMs=Math.max(c.maxMs,-r)):this.#i.set(i,{count:1,maxMs:-r})}else{let c=this.#i.get(i);if(c){let h=i?`sync[${i}]`:"sync",u=X.#c(c.maxMs);console.debug(`${h}: ${c.count} late frame(s), max ${u} behind`),this.#i.delete(i)}}if(s>=a)return;let l=this.#r();r<=l||this.#l(p.Milli.add(s,p.Milli.sub(l,o)))}#l(e){this.#t.reference.set(e),this.#e.resolve(),this.#e=Promise.withResolvers()}reset(){this.#t.reference.set(void 0),this.#i.clear(),this.#e.resolve(),this.#e=Promise.withResolvers()}now(){let e=this.#t.reference.peek();if(e!==void 0)return p.Milli.sub(p.Milli.sub(p.Milli.now(),e),this.#t.buffer.peek())}async wait(e){if(this.#t.reference.peek()===void 0)throw Error("reference not set; call received() first");for(;;){let i=p.Milli.now(),n=p.Milli.sub(i,e),s=this.#t.reference.peek();if(s===void 0)return;let a=p.Milli.add(p.Milli.sub(s,n),this.#t.buffer.peek());if(a<=0||a<5)return;let o=new Promise(r=>setTimeout(r,a)).then(()=>!0);if(await Promise.race([this.#e.promise,o]))return}}static#c(e){if(e=Math.round(e),e<1e3)return`${e}ms`;let i=e/1e3;if(i<60)return`${Math.round(i*10)/10}s`;let n=i/60;return`${Math.round(n*10)/10}m`}close(){this.#s.close()}};import{Path as U,Time as f}from"../../net@^0.3.4.target-es2022.mjs";import{Effect as E,Signal as d,getter as w,readonlys as P}from"../../signals@^0.2.3.target-es2022.mjs";import*as y from"../../hang@^0.4.2/catalog.target-es2022.mjs";import{u53 as L}from"../../hang@^0.4.2/catalog.target-es2022.mjs";import*as g from"../../hang@^0.4.2/container.target-es2022.mjs";import*as v from"../../hang@^0.4.2/util.target-es2022.mjs";import*as ot from"../../json.target-es2022.mjs";import*as lt from"../../msf@^0.2.1.target-es2022.mjs";function N(t){let e=atob(t),i=new Uint8Array(e.length);for(let n=0;n<e.length;n++)i[n]=e.charCodeAt(n);return i}var k=0,F=1,z=2,It=3,Ot=4294967295n;function B(t,e){return BigInt(t>>>0)<<32n|BigInt(e>>>0)}function T(t){return Number(t>>32n)|0}function x(t){return Number(t&Ot)|0}function Ct(t){return t<=1?1:1<<32-Math.clz32(t-1)}function ct(t,e,i,n=!1){if(t<=0)throw Error("invalid channels");if(e<=0||e>2**30)throw Error("invalid capacity");if(i<=0)throw Error("invalid sample rate");e=Ct(e);let s=new SharedArrayBuffer(t*e*Float32Array.BYTES_PER_ELEMENT),a=new SharedArrayBuffer(It*Int32Array.BYTES_PER_ELEMENT),o=new SharedArrayBuffer(BigInt64Array.BYTES_PER_ELEMENT),r=new Int32Array(a);return Atomics.store(r,z,1),{channels:t,capacity:e,rate:i,samples:s,control:a,state:o,buffered:n}}function Z(t,e){return(t-e|0)>0?t:e}function _(t,e){return t&e-1}var Lt=class ht{channels;capacity;rate;buffered;init;#t;#e;#i;#n=!1;#s=0;#a=0;#r=0;constructor(e,i){this.channels=e.channels,this.capacity=e.capacity,this.rate=e.rate,this.buffered=e.buffered,this.init=e,this.#t=new Int32Array(e.control),this.#e=new BigInt64Array(e.state),this.#i=[];for(let n=0;n<this.channels;n++)this.#i.push(new Float32Array(e.samples,n*this.capacity*Float32Array.BYTES_PER_ELEMENT,this.capacity));i!==void 0&&this.#o(i)}#o(e){if(e.channels!==this.channels||e.rate!==this.rate)return;let i=Atomics.load(e.#e,0);for(;;){let n=Atomics.load(this.#e,0);if(T(n)!==T(i)||(x(i)-x(n)|0)<=0)return;let s=B(T(n),x(i));if(Atomics.compareExchange(this.#e,0,n,s)===n)return}}#h(e){for(;;){let i=Atomics.load(this.#e,0);if((e-x(i)|0)<=0)return;let n=B(T(i),e);if(Atomics.compareExchange(this.#e,0,i,n)===i)return}}insert(e,i){if(i.length!==this.channels)throw Error("wrong number of channels");let n=Math.round(f.Second.fromMicro(e)*this.rate),s=i[0].length,a=0;if(!this.#n){this.#s=n;let A=T(Atomics.load(this.#e,0));Atomics.store(this.#e,0,B(A+1|0,0)),Atomics.store(this.#t,k,0),this.#n=!0,this.#a=0,this.#r=0}n=n-this.#s|0;let o=n+s|0,r=x(Atomics.load(this.#e,0)),l=r-n|0;if(l>0){if(l>=s)return;a=l,n=n+l|0}let c=s-a;(o-r|0)>this.capacity&&this.#h(o-this.capacity|0);let h=Atomics.load(this.#t,k),u=n-h|0;if(u>0){let A=Math.min(u,this.capacity);for(let O=0;O<this.channels;O++){let $=this.#i[O];for(let C=0;C<A;C++)$[_(h+C|0,this.capacity)]=0}}for(let A=0;A<this.channels;A++){let O=i[A],$=this.#i[A];for(let C=0;C<c;C++)$[_(n+C|0,this.capacity)]=O[a+C]}Atomics.store(this.#t,k,Z(Atomics.load(this.#t,k),o));let m=x(Atomics.load(this.#e,0)),b=Atomics.load(this.#t,k),R=Atomics.load(this.#t,F);(b-m|0)>=R&&R>0&&Atomics.store(this.#t,z,0)}read(e){let i=Atomics.load(this.#e,0);if(Atomics.load(this.#t,z)===1)return 0;let n=x(i),s=Atomics.load(this.#t,k),a=Atomics.load(this.#t,F),o=s-n|0;if(!this.buffered&&a>0&&o>a){let h=s-a|0;(h-n|0)>0&&(n=h)}let r=s-n|0,l=Math.min(r,e[0].length);if(l<=0)return(n-x(i)|0)>0&&Atomics.compareExchange(this.#e,0,i,B(T(i),n)),0;for(let h=0;h<this.channels;h++){let u=this.#i[h],m=e[h];for(let b=0;b<l;b++)m[b]=u[_(n+b|0,this.capacity)]}let c=B(T(i),n+l|0);if(Atomics.compareExchange(this.#e,0,i,c)!==i){for(let h=0;h<this.channels;h++)e[h].fill(0,0,l);return 0}return l}setLatency(e){Atomics.store(this.#t,F,e)}truncate(e){let i=Math.round(f.Second.fromMicro(e)*this.rate)-this.#s|0;for(;;){let n=Atomics.load(this.#t,k);if((n-i|0)<=0)return;let s=Z(i,x(Atomics.load(this.#e,0)));if((n-s|0)<=0||Atomics.compareExchange(this.#t,k,n,s)===n)return}}reset(){this.#n=!1,Atomics.store(this.#t,z,1);let e=Atomics.load(this.#t,k),i=Atomics.load(this.#e,0);Atomics.store(this.#e,0,B(T(i),e))}resize(e){let i=ct(this.channels,e,this.rate,this.buffered),n=new ht(i);n.#n=this.#n,n.#s=this.#s;let s=Atomics.load(this.#e,0),a=x(s),o=Atomics.load(this.#t,k),r=Atomics.load(this.#t,F),l=Atomics.load(this.#t,z),c=o-a|0,h=Math.max(0,Math.min(c,n.capacity)),u=o-h|0;for(let m=0;m<this.channels;m++){let b=this.#i[m],R=n.#i[m];for(let A=0;A<h;A++){let O=u+A|0;R[_(O,n.capacity)]=b[_(O,this.capacity)]}}return Atomics.store(n.#e,0,B(T(s),u)),Atomics.store(n.#t,k,o),Atomics.store(n.#t,F,r),Atomics.store(n.#t,z,l),n.#a=this.#l(a)+(u-a|0),n.#r=u,n}#l(e){return this.#a+=e-this.#r|0,this.#r=e,this.#a}#c(){return this.#l(x(Atomics.load(this.#e,0)))}get timestamp(){return f.Micro.fromSecond((this.#s+this.#c())/this.rate)}get stalled(){return Atomics.load(this.#t,z)===1}get length(){return Atomics.load(this.#t,k)-x(Atomics.load(this.#e,0))|0}},dt=class{#t;#e;#i=[];constructor(t,e){this.#t=t,this.#e=e}setHeadroom(t){this.#e=t}wait(t,e){return!this.#t||e>=(t-this.#e|0)?Promise.resolve():new Promise(i=>this.#i.push({timestamp:t,resolve:i}))}advance(t){this.#i.length!==0&&(this.#i=this.#i.filter(({timestamp:e,resolve:i})=>t<(e-this.#e|0)||(i(),!1)))}flush(){for(let{resolve:t}of this.#i)t();this.#i=[]}};function H(t,e){return f.Micro.fromSecond(t/e)}function Bt(){return!(typeof SharedArrayBuffer>"u"||typeof crossOriginIsolated<"u"&&!crossOriginIsolated)}function zt(t,e,i,n,s=!1){return Bt()?(console.log("[audio] using SharedArrayBuffer audio buffer"),new Pt(t,e,i,n,s)):(console.warn("[audio] SharedArrayBuffer unavailable, falling back to the higher latency postMessage audio buffer. Serve the page cross-origin isolated (Cross-Origin-Opener-Policy: same-origin, Cross-Origin-Embedder-Policy: require-corp) to avoid this."),new jt(t,e,i,n,s))}var Pt=class{rate;channels;#t;#e;#i=new d(0);timestamp=this.#i;#n=new d(!0);stalled=this.#n;#s;#a=new E;constructor(t,e,i,n,s){this.#t=t,this.channels=e,this.rate=i;let a=Math.max(i,n*2);this.#s=new dt(s,H(n,i));let o=ct(e,a,i,s);this.#e=new Lt(o),this.#e.setLatency(n);let r={type:"init-shared",...o};t.port.postMessage(r),this.#a.interval(()=>{let l=this.#e.stalled;this.#i.set(this.#e.timestamp),this.#n.set(l),l?this.#s.flush():this.#s.advance(this.#e.timestamp)},50)}insert(t,e){this.#e.insert(t,e)}setLatency(t){if(this.#s.setHeadroom(H(t,this.rate)),this.#e.capacity<t*1.5){let e=Math.max(this.rate,t*2);this.#e=this.#e.resize(e),this.#e.setLatency(t);let i={type:"init-shared",...this.#e.init};this.#t.port.postMessage(i)}else this.#e.setLatency(t)}truncate(t){this.#e.truncate(t)}reset(){this.#e.reset(),this.#s.flush()}wait(t){return this.#e.stalled?Promise.resolve():this.#s.wait(t,this.#e.timestamp)}close(){this.#s.flush(),this.#a.close()}},jt=class{rate;channels;#t;#e=new d(0);timestamp=this.#e;#i=new d(!0);stalled=this.#i;#n;#s=new E;constructor(t,e,i,n,s){this.#t=t,this.channels=e,this.rate=i,this.#n=new dt(s,H(n,i));let a={type:"init-post",channels:e,rate:i,latency:f.Milli.fromSecond(n/i),buffered:s};t.port.postMessage(a),this.#s.event(t.port,"message",o=>{let r=o.data;r?.type==="state"&&(this.#e.set(r.timestamp),this.#i.set(r.stalled),r.stalled?this.#n.flush():this.#n.advance(r.timestamp))}),t.port.start()}insert(t,e){let i={type:"data",data:e,timestamp:t};this.#t.port.postMessage(i,e.map(n=>n.buffer))}setLatency(t){this.#n.setHeadroom(H(t,this.rate));let e={type:"latency",latency:f.Milli.fromSecond(t/this.rate)};this.#t.port.postMessage(e)}truncate(t){let e={type:"truncate",timestamp:t};this.#t.port.postMessage(e)}reset(){this.#t.port.postMessage({type:"reset"}),this.#n.flush()}wait(t){return this.#i.peek()?Promise.resolve():this.#n.wait(t,this.#e.peek())}close(){this.#n.flush(),this.#s.close()}},Wt=class{#t=!1;#e=!1;opened(){this.#t&&(this.#e=!0),this.#t=!0}takeover(){let t=this.#e;return this.#e=!1,t}},Ft=new Blob([`var __defProp = Object.defineProperty;
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
    if (!Number.isInteger(unitsPerSecond) || unitsPerSecond <= 0) {
      throw new Error(\`invalid timescale: \${unitsPerSecond}\`);
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
var Timestamp = class _Timestamp {
  /** The raw value, in \`scale\` units. */
  value;
  /** Units per second the {@link value} is measured in. */
  scale;
  /** Build a timestamp of \`value\` units at \`scale\`. */
  constructor(value, scale) {
    if (!Number.isFinite(value) || value < 0) {
      throw new Error(\`invalid timestamp: \${value}\`);
    }
    this.value = value;
    this.scale = scale;
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
  /** This timestamp's value re-expressed at \`scale\` (a raw number, not a new Timestamp). */
  as(scale) {
    return scale === this.scale ? this.value : this.value * scale / this.scale;
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
var CONTROL_SLOTS = 3;
var CURSOR_MASK = 0xffffffffn;
function pack(epoch, read) {
  return BigInt(epoch >>> 0) << 32n | BigInt(read >>> 0);
}
function epochOf(state) {
  return Number(state >> 32n) | 0;
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
   * \`resize\` copies the epoch, so a destination that re-anchored since has a different one and
   * the cursor is dropped rather than applied to audio the reader has never played. The check
   * and the write are the same exchange, so a re-anchor landing mid-handoff makes it fail
   * instead of slipping through the gap that separate operations would leave.
   */
  #handoff(source) {
    if (source.channels !== this.channels || source.rate !== this.rate) return;
    const from = Atomics.load(source.#state, 0);
    for (; ; ) {
      const state = Atomics.load(this.#state, 0);
      if (epochOf(state) !== epochOf(from)) return;
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
      Atomics.store(this.#state, 0, pack(epoch + 1 | 0, 0));
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
    for (; ; ) {
      const write = Atomics.load(this.#control, WRITE);
      if ((write - target | 0) <= 0) return;
      const clamped = i32Max(target, readOf(Atomics.load(this.#state, 0)));
      if ((write - clamped | 0) <= 0) return;
      if (Atomics.compareExchange(this.#control, WRITE, write, clamped) === write) return;
    }
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
`],{type:"application/javascript"}),_t=URL.createObjectURL(Ft);function Nt(t,{broadcast:e,track:i,maxLatency:n}){let s=y.PRIORITY.audio,a=Math.ceil(n.peek()),o=e.track(i).subscribe({priority:s,latencyMax:a});return t.cleanup(()=>o.close()),t.run(r=>{let l=Math.ceil(r.get(n));l!==a&&(a=l,o.update({priority:s,latencyMax:a}))}),o}var Dt=class{#t=0;#e;#i;#n=0;#s;get end(){return this.#e}clear(t=0){this.#t=0,this.#e=void 0,this.#n=t,this.#a()}update(t){let e=t.discontinuity!==this.#t;return e&&(this.#t=t.discontinuity,this.#e=void 0,this.#a()),t.frame&&this.#i===void 0&&(this.#i=t.frame.timestamp),t.end!==void 0&&(this.#e=t.end),e}span(t){let e=this.#i??t.timestamp;this.#i=e;let i=Math.floor(this.#n*t.sampleRate/48e3),n=this.#s??i,s=Math.min(n,t.numberOfFrames);this.#s=n-s;let a=Math.round(i*1e6/t.sampleRate),o=Math.max(e,t.timestamp-a),r=t.numberOfFrames-s;if(this.#e!==void 0)if(this.#e<=o)r=0;else{let l=this.#e-o,c=Math.round(l*t.sampleRate/1e6);r=Math.min(r,c)}return{timestamp:o,frameOffset:s,frames:r}}#a(){this.#i=void 0,this.#s=void 0}};function Ht(t,e){let i=new d(e.state==="running");t.event(e,"statechange",()=>i.set(e.state==="running")),t.run(n=>{if(n.get(i))return;let s=()=>{e.resume().catch(()=>{})};s(),n.event(document,"pointerdown",s),n.event(document,"keydown",s)})}var $t=class{#t;constructor(t){this.#t=t}drop(){return this.#t!==0&&(this.#t--,!0)}},Yt=150,Ut=3,q=class{in;source;sync;#t={context:new d(void 0),root:new d(void 0),sampleRate:new d(void 0),stats:new d(void 0),timestamp:new d(void 0),stalled:new d(!0),buffered:new d([])};out=P(this.#t);#e=new d([]);#i;#n=new d(void 0);#s=new Dt;#a;#r=new Wt;#o=new E;constructor(t,e,i){this.in={enabled:w(i?.enabled??!1)},this.source=t,this.sync=e,this.#o.run(this.#h.bind(this)),this.#o.run(this.#l.bind(this)),this.#o.run(this.#c.bind(this)),this.#o.run(this.#f.bind(this)),this.#o.run(this.#d.bind(this))}#h(t){let e=t.get(this.source.out.config);if(!e)return;let i=t.get(this.#n)??e.sampleRate,n=e.numberOfChannels;t.set(this.#t.sampleRate,i);let s=new AudioContext({latencyHint:"interactive",sampleRate:i});t.set(this.#t.context,s),t.cleanup(()=>s.close()),t.spawn(async()=>{if(!await Promise.race([s.audioWorklet.addModule(_t).then(()=>!0),t.cancel]))return;let a=new AudioWorkletNode(s,"render",{channelCount:n,channelCountMode:"explicit",outputChannelCount:[n]});t.cleanup(()=>a.disconnect());let o=this.sync.out.buffer.peek(),r=Math.ceil(i*f.Second.fromMilli(o)),l=this.sync.out.buffered.peek(),c=zt(a,n,i,r,l);this.#i=c,t.cleanup(()=>{c.close(),this.#i=void 0}),t.run(h=>{let u=f.Milli.fromMicro(h.get(c.timestamp));this.#t.timestamp.set(u),this.#y(u)}),t.run(h=>{this.#t.stalled.set(h.get(c.stalled))}),t.set(this.#t.root,a)})}#l(t){if(!t.get(this.in.enabled))return;let e=t.get(this.#t.context);e&&Ht(t,e)}#c(t){if(!t.get(this.#t.root))return;let e=this.#i;if(!e)return;let i=t.get(this.sync.out.buffer),n=Math.ceil(e.rate*f.Second.fromMilli(i));e.setLatency(n)}#f(t){let e=S(t.get(this.sync.in.latency)).min;if(this.#a===void 0){this.#a=e;return}let i=this.#a;t.timer(()=>{let n=s=>s==="real-time"?0:s;n(e)>n(i)&&this.reset(),this.#a=e},Yt)}#d(t){if(!t.get(this.in.enabled))return;let e=t.get(this.source.in.broadcast);if(!e)return;let i=t.get(this.source.out.track);if(!i)return;let n=t.get(this.source.out.config);if(!n)return;let s=e.relativeBroadcast(t,n.broadcast);if(!s)return;this.#r.opened();let a=Nt(t,{broadcast:s,track:i,maxLatency:this.sync.out.maxBuffer});n.container.kind==="cmaf"?this.#m(t,a,n):this.#u(t,a,n)}#u(t,e,i){let n=i.codec==="opus"&&i.description?v.Opus.preSkip(v.Hex.toBytes(i.description)):0;this.#s.clear(n);let s=i.container.kind==="loc"?new g.Loc.Format:new g.Legacy.Format,a=new g.Consumer(e,{format:s,latency:this.sync.out.maxBuffer});t.cleanup(()=>a.close()),t.run(o=>{let r=o.get(a.buffered),l=o.get(this.#e);this.#t.buffered.update(()=>g.mergeBufferedRanges(r,l))}),t.spawn(async()=>{if(!await v.Libav.polyfill())return;let o=new $t(Ut),r=new AudioDecoder({output:h=>{let u=this.#s.span(h);if(o.drop()){h.close();return}this.#p(h,u)},error:h=>console.error("audio decoder error",h)});t.cleanup(()=>{r.state!=="closed"&&r.close()});let l=i.codec==="opus"?void 0:i.description?v.Hex.toBytes(i.description):void 0,c={...i,description:l};for(r.configure(c);;){let h=await a.next();if(!h)break;if(this.#g(h)&&(r.reset(),r.configure(c)),h.end!==void 0)continue;let{frame:u}=h;if(!u)continue;let m=f.Milli.fromMicro(u.timestamp);this.sync.received(m,"audio"),this.#t.stats.update(R=>({bytesReceived:(R?.bytesReceived??0)+u.payload.byteLength})),await this.#i?.wait(u.timestamp);let b=new EncodedAudioChunk({type:u.keyframe?"key":"delta",data:u.payload,timestamp:u.timestamp});if(r.state==="closed")break;r.decode(b)}})}#m(t,e,i){if(i.container.kind!=="cmaf")return;let n=N(i.container.init),s=g.Cmaf.decodeInitSegment(n),a=i.description?v.Hex.toBytes(i.description):s.description,o=i.codec==="opus"&&a?v.Opus.preSkip(a):0;this.#s.clear(o);let r=i.codec==="opus"?void 0:i.description?v.Hex.toBytes(i.description):s.description,l=new g.Consumer(e,{format:new g.Cmaf.Format(s),latency:this.sync.out.maxBuffer});t.cleanup(()=>l.close()),t.run(c=>{let h=c.get(l.buffered),u=c.get(this.#e);this.#t.buffered.update(()=>g.mergeBufferedRanges(h,u))}),t.spawn(async()=>{if(!await v.Libav.polyfill())return;let c=new AudioDecoder({output:u=>this.#p(u),error:u=>console.error("audio decoder error",u)});t.cleanup(()=>{c.state!=="closed"&&c.close()});let h={codec:i.codec,sampleRate:i.sampleRate,numberOfChannels:i.numberOfChannels,description:r};for(c.configure(h);;){let u=await l.next();if(!u)break;this.#g(u)&&(c.reset(),c.configure(h));let{frame:m}=u;if(!m)continue;let b=f.Milli.fromMicro(m.timestamp);if(this.sync.received(b,"audio"),this.#t.stats.update(R=>({bytesReceived:(R?.bytesReceived??0)+m.payload.byteLength})),await this.#i?.wait(m.timestamp),c.state==="closed")break;c.decode(new EncodedAudioChunk({type:m.keyframe?"key":"delta",data:m.payload,timestamp:m.timestamp}))}})}#p(t,e=this.#s.span(t)){let{timestamp:i,frameOffset:n,frames:s}=e,a=f.Milli.fromMicro(i);if(s===0){t.close();return}let o=this.#i;if(!o){t.close();return}if(t.sampleRate!==o.rate){this.#n.set(t.sampleRate),t.close();return}let r=s/t.sampleRate*1e6,l=f.Milli.fromMicro(r),c=f.Milli.add(a,l);this.#r.takeover()&&(o.truncate(i),this.#w(a)),this.#b(a,c);let h=Math.min(t.numberOfChannels,o.channels),u=[];for(let m=0;m<h;m++){let b=new Float32Array(s);t.copyTo(b,{format:"f32-planar",planeIndex:m,frameOffset:n,frameCount:s}),u.push(b)}o.insert(i,u),t.close()}#b(t,e){t>e||this.#e.mutate(i=>{for(let n of i)if(t<=n.end+1&&e>=n.start){n.start=f.Milli.min(n.start,t),n.end=f.Milli.max(n.end,e);return}i.push({start:t,end:e}),i.sort((n,s)=>n.start-s.start)})}#w(t){this.#e.mutate(e=>{for(;e.length>0&&e[e.length-1].start>=t;)e.pop();let i=e[e.length-1];i&&i.end>t&&(i.end=t)})}#y(t){this.#e.mutate(e=>{for(;e.length>0;){if(e[0].end>=t){e[0].start=f.Milli.max(e[0].start,t);break}e.shift()}})}reset(){this.#i?.reset()}#g(t){return this.#s.update(t)?(this.#i?.reset(),this.sync.reset(),!0):!1}close(){this.#o.close()}static supported=Kt};async function Kt(t){if(!y.containerSupported(t.container)){let i=t.container.kind==="unknown"?t.container.raw.kind:t.container.kind;return console.warn(`audio: ignoring rendition with unknown container: ${i}`),!1}t.codec==="opus"&&!v.Opus.supportsRate(t.sampleRate)&&console.warn(`audio: opus advertised at ${t.sampleRate}Hz, which some browsers cannot decode`);let e;if(t.codec!=="opus"){if(t.description)e=v.Hex.toBytes(t.description);else if(t.container.kind==="cmaf")try{e=g.Cmaf.decodeInitSegment(N(t.container.init)).description}catch(i){return console.warn(`audio: malformed CMAF init segment for codec ${t.codec}`,i),!1}}return(await AudioDecoder.isConfigSupported({...t,description:e})).supported??!1}var tt=.001,K=.2,ut=class{source;in;#t={enabled:new d(!1)};out=P(this.#t);#e=new E;#i=new d(void 0);constructor(t,e){this.source=t,this.in={volume:w(e?.volume??.5),muted:w(e?.muted??!1),paused:w(e?.paused??!1)},this.#e.run(i=>{let n=!i.get(this.in.paused)&&!i.get(this.in.muted);this.#t.enabled.set(n)}),this.#e.run(i=>{let n=i.get(this.source.out.root);if(!n)return;let s=new GainNode(n.context,{gain:i.get(this.in.volume)});n.connect(s),i.set(this.#i,s),i.run(a=>{a.get(this.#t.enabled)&&(s.connect(n.context.destination),a.cleanup(()=>s.disconnect()))})}),this.#e.run(i=>{let n=i.get(this.#i);if(!n)return;i.cleanup(()=>n.gain.cancelScheduledValues(n.context.currentTime));let s=i.get(this.in.volume);s<tt?(n.gain.exponentialRampToValueAtTime(tt,n.context.currentTime+K),n.gain.setValueAtTime(0,n.context.currentTime+K+.01)):n.gain.exponentialRampToValueAtTime(s,n.context.currentTime+K)})}close(){this.#e.close()}},qt=128,ft=class{in;#t={catalog:new d(void 0),available:new d({}),track:new d(void 0),config:new d(void 0),jitter:new d(void 0)};out=P(this.#t);#e=new E;constructor(t){this.in={broadcast:w(t?.broadcast),target:w(t?.target),supported:w(t?.supported)},this.#e.run(this.#i.bind(this)),this.#e.run(this.#n.bind(this)),this.#e.run(this.#s.bind(this))}#i(t){let e=t.get(this.in.broadcast);if(!e)return;let i=t.get(e.out.catalog)?.audio;i&&t.set(this.#t.catalog,i)}#n(t){let e=t.get(this.#t.catalog)?.renditions??{},i=t.get(this.in.supported);i&&t.spawn(async()=>{let n={},s=t.cancel.then(()=>{});for(let[a,o]of Object.entries(e)){let r=await Promise.race([i(o),s]);if(t.abort.aborted)return;r&&(n[a]=o)}Object.keys(n).length===0&&Object.keys(e).length>0&&console.warn("no supported audio renditions found:",e),this.#t.available.set(n)})}#s(t){let e=t.get(this.#t.available);if(Object.keys(e).length===0)return;let i=t.get(this.in.target),n;if(i?.name&&i.name in e)n={track:i.name,config:e[i.name]};else if(n=this.#a(e),!n)return;t.set(this.#t.track,n.track),t.set(this.#t.config,n.config);let s=(n.config.jitter??Vt(n.config)??0)+Math.ceil(qt/n.config.sampleRate*1e3);t.set(this.#t.jitter,f.Milli(s))}#a(t){let e=Object.entries(t);if(e.length!==0){for(let[i,n]of e)if(n.container.kind==="legacy")return{track:i,config:n};for(let[i,n]of e)if(n.container.kind==="loc")return{track:i,config:n};for(let[i,n]of e)if(n.container.kind==="cmaf")return{track:i,config:n}}}close(){this.#e.close()}};function Vt(t){if(t.codec.startsWith("opus"))return 20;if(t.codec.startsWith("mp4a"))return Math.ceil(1024/t.sampleRate*1e3);if(t.codec==="mp3"){let e=t.sampleRate>=32e3?1152:576;return Math.ceil(e/t.sampleRate*1e3)}}var Jt=48e3,et=2;function Gt(t){let e="";for(let i=0;i<t.length;i++)e+=t[i].toString(16).padStart(2,"0");return e}function mt(t){let e;try{e=t.initData?N(t.initData):void 0}catch{e=void 0}let i=e?Gt(e):void 0;switch(t.packaging){case"cmaf":return!t.initData||!e?void 0:{container:{kind:"cmaf",init:t.initData},description:void 0};case"loc":return{container:{kind:"loc"},description:i};case"legacy":return{container:{kind:"legacy"},description:i};default:return}}function Qt(t){if(!t.codec)return;let e=mt(t);if(!e)return;let{container:i,description:n}=e;return{codec:t.codec,container:i,description:n,codedWidth:t.width==null?void 0:L(t.width),codedHeight:t.height==null?void 0:L(t.height),framerate:t.framerate,bitrate:t.bitrate==null?void 0:L(t.bitrate),stalled:t.stalled,jitter:t.jitter==null?void 0:L(t.jitter)}}function Xt(t){if(!t.codec)return;let e=(()=>{if(!t.channelConfig)return et;let a=Number.parseInt(t.channelConfig,10);return Number.isFinite(a)?a:et})(),i=mt(t);if(!i)return;let{container:n,description:s}=i;return{codec:t.codec,container:n,description:s,sampleRate:L(t.samplerate??Jt),numberOfChannels:L(e),bitrate:t.bitrate==null?void 0:L(t.bitrate),jitter:t.jitter==null?void 0:L(t.jitter)}}function Zt(t){let e={},i={};for(let s of t.tracks)if(s.role==="video"){let a=Qt(s);a&&(e[s.name]=a)}else if(s.role==="audio"){let a=Xt(s);a&&(i[s.name]=a)}let n={};return Object.keys(e).length>0&&(n.video={renditions:e}),Object.keys(i).length>0&&(n.audio={renditions:i}),n}var it=new WeakSet;function nt(t){return!t.discovery&&(it.has(t)||(it.add(t),console.warn("relay does not support broadcast discovery; subscribing to siblings blind.")),!0)}function st(t,e){return Object.fromEntries(Object.entries(t).filter(([,i])=>e(i.broadcast)))}function te(t,e){return{...t,video:t.video?{...t.video,renditions:st(t.video.renditions,e)}:void 0,audio:t.audio?{...t.audio,renditions:st(t.audio.renditions,e)}:void 0}}var ee=[...y.FORMATS,"hangz","manual"];function pt(t){if(t!==null)return ee.find(e=>e===t)}var gt=class{in;#t={status:new d("offline"),active:new d(void 0),catalog:new d(void 0)};out=P(this.#t);#e=new d(void 0);#i=new d(!1);#n=new d(void 0);#s=new E;constructor(t){this.in={connection:w(t?.connection),name:w(t?.name??U.empty()),enabled:w(t?.enabled??!1),reload:w(t?.reload??!0),catalogFormat:w(t?.catalogFormat),catalog:w(t?.catalog)},this.#s.run(this.#a.bind(this)),this.#s.run(this.#h.bind(this)),this.#s.run(this.#l.bind(this)),this.#s.run(this.#r.bind(this))}#a(t){if(this.#e.set(void 0),!t.get(this.#i)||!t.get(this.in.reload))return;let e=t.get(this.in.connection);if(!e||nt(e))return;let i=e.announced(U.empty());t.cleanup(()=>i.close()),this.#e.set(new Set),t.spawn(async()=>{for(;;){let n=await Promise.race([t.cancel,i.next()]);if(!n)break;this.#e.mutate(s=>{s&&(n.active?s.add(n.path):s.delete(n.path))})}})}#r(t){let e=t.get(this.#n);t.set(this.#t.catalog,e?te(e,i=>this.#c(t,i)!==void 0):void 0)}#o(t,e){if(!t.get(this.in.reload))return!0;let i=t.get(this.in.connection);if(!i||nt(i))return!0;this.#i.set(!0);let n=t.get(this.#e);return n?n.has(e):!1}#h(t){if(!t.get(this.in.enabled))return;let e=t.get(this.in.connection);if(!e)return;let i=t.get(this.in.name);if(!t.get(this.in.reload)){let s=e.consume(i);t.cleanup(()=>s.close()),t.set(this.#t.active,s,void 0);return}let n=e.announcedBroadcast(i);t.cleanup(()=>n.close()),t.run(s=>{s.set(this.#t.active,s.get(n.active),void 0)})}#l(t){if(!t.get(this.in.enabled))return;let e=t.get(this.in.catalogFormat),i=t.get(this.in.name),n=e??y.detectFormat(i)??y.DEFAULT_FORMAT;if(n==="manual"){let l=t.get(this.in.catalog);this.#n.set(l,!0),t.cleanup(()=>this.#n.set(void 0,!0)),this.#t.status.set(l?"live":"loading");return}let s=t.get(this.out.active);if(!s)return;this.#t.status.set("loading");let a=n==="hang"?y.TRACK:n==="hangz"?y.TRACK_COMPRESSED:"catalog",o=s.track(a).subscribe({priority:y.PRIORITY.catalog});t.cleanup(()=>o.close());let r;if(n==="hang"||n==="hangz"){let l=new ot.Snapshot.Consumer(o,{schema:y.RootSchema,compression:n==="hangz"});r=()=>l.next()}else r=async()=>{let l=await lt.fetch(o);return l?Zt(l):void 0};t.spawn(async()=>{try{for(;;){let l=await Promise.race([t.cancel,r()]);if(!l)break;console.debug("received catalog",n,this.in.name.peek(),l),this.#n.set(l,!0),this.#t.status.set("live")}}catch(l){console.warn("error fetching catalog",this.in.name.peek(),l)}finally{this.#n.set(void 0),this.#t.status.set("offline")}})}#c(t,e){if(!e)return{local:!0};let i=t.get(this.in.name),n=U.tryResolve(i,e);if(n!==void 0){if(n===i)return{local:!0};if(this.#o(t,n))return{local:!1,path:n}}}relativeBroadcast(t,e){let i=this.#c(t,e);if(!i)return;if(i.local)return t.get(this.out.active);if(!t.get(this.in.enabled))return;let n=t.get(this.in.connection);if(!n)return;let s=n.consume(i.path);return t.cleanup(()=>s.close()),s}close(){this.#s.close()}},bt=Symbol("supportCacheKey");function wt(t){return{broadcast:t.broadcast,decoder:{codec:t.codec,container:t.container,description:t.description,displayAspectWidth:t.displayAspectWidth,displayAspectHeight:t.displayAspectHeight,optimizeForLatency:t.optimizeForLatency??!0}}}function ie(t){return JSON.stringify(wt(t).decoder)}var ne=f.Milli(100);function at(t){if(t.jitter!==void 0)return f.Milli(t.jitter);if(t.framerate)return f.Milli(Math.ceil(1e3/t.framerate))}function se(t){return t.active===void 0||f.Milli.add(t.playhead,ne)>=t.active}function yt(t=0){let e=(t%360+360)%360;return Math.round(e/90)%4*90}function vt(t,e=0){let i=yt(e);return i===90||i===270?{width:t.height,height:t.width}:{width:t.width,height:t.height}}function W(t){return Object.is(t,-0)?0:t}function ae(t,e){let[i,n,s,a,o,r]=t;return[W(-i),W(n),W(-s),W(a),W(e-o),W(r)]}function re(t,e){let i=yt(e?.rotation),n=vt(t,i),s;switch(i){case 90:s=[0,1,-1,0,t.width,0];break;case 180:s=[-1,0,0,-1,t.width,t.height];break;case 270:s=[0,-1,1,0,0,t.height];break;default:s=[1,0,0,1,0,0]}return e?.flip&&(s=ae(s,t.width)),{matrix:s,source:n}}var oe=f.Milli(500),V=class{in;source;sync;#t={frame:new d(void 0),timestamp:new d(void 0),display:new d(void 0),stalled:new d(!1),stats:new d(void 0),buffered:new d([])};out=P(this.#t);#e=new d(void 0);#i;#n=new E;#s(){this.#t.frame.update(t=>{t?.close()}),this.#t.timestamp.set(void 0)}constructor(t,e,i){this.in={enabled:w(i?.enabled??!1),paced:w(i?.paced??!0)},this.source=t,this.sync=e,this.#i=this.#n.computed(n=>{let s=n.get(this.source.out.config);return s?wt(s):void 0}),this.#n.run(this.#a.bind(this)),this.#n.run(this.#r.bind(this)),this.#n.run(this.#o.bind(this)),this.#n.run(this.#h.bind(this))}#a(t){let e=t.getAll([this.in.enabled,this.source.in.broadcast,this.source.out.track,this.#i]);if(!e){this.#e.set(void 0);return}let[i,n,s,a]=e,o=n.relativeBroadcast(t,a.broadcast);if(!o){this.#e.set(void 0),this.#s(),this.#t.buffered.set([]);return}let r=new le({sync:this.sync,paced:this.in.paced,broadcast:o,track:s,config:a.decoder,stats:this.#t.stats});t.cleanup(()=>r?.close()),t.run(l=>{if(!r)return;let c=l.get(this.#e);if(c){let h=l.get(r.timestamp);if(h===void 0||!se({playhead:h,active:l.get(c.timestamp)}))return}this.#e.set(r),r=void 0,l.close()})}#r(t){let e=t.get(this.#e);if(!e){this.#t.buffered.set([]);return}t.cleanup(()=>e.close()),t.run(i=>{let n=i.get(e.frame);this.#t.frame.update(s=>(s?.close(),n?.clone()))}),t.proxy(this.#t.timestamp,e.timestamp),t.proxy(this.#t.buffered,e.buffered)}#o(t){let e=t.get(this.source.out.catalog);if(!e)return;let i=e.display;if(i){t.set(this.#t.display,{width:i.width,height:i.height});return}let n=t.get(this.#t.frame);n&&t.set(this.#t.display,vt({width:n.displayWidth,height:n.displayHeight},e.rotation))}#h(t){if(t.get(this.in.enabled)){if(!t.get(this.#t.frame)){this.#t.stalled.set(!0);return}this.#t.stalled.set(!1),t.timer(()=>{this.#t.stalled.set(!0)},oe)}}close(){this.#s(),this.#n.close()}static supported=Mt},le=class{sync;paced;broadcast;track;config;stats;timestamp=new d(void 0);frame=new d(void 0);buffered=new d([]);#t=new d([]);#e=new d(f.Milli.zero);#i=0;#n=new E;constructor(t){this.sync=t.sync,this.paced=t.paced,this.broadcast=t.broadcast,this.track=t.track,this.config=t.config,this.stats=t.stats,this.#n.run(e=>{let i=e.get(this.paced);this.#e.set(i?e.get(this.sync.out.buffer):f.Milli.zero)}),this.#n.run(this.#s.bind(this))}#s(t){let e=this.broadcast.track(this.track).subscribe({priority:y.PRIORITY.video});t.cleanup(()=>e.close());let i=new VideoDecoder({output:async n=>{try{let s=this.#i,a=f.Milli.fromMicro(n.timestamp);if(a<(this.timestamp.peek()??0)||this.paced.peek()&&(this.sync.out.reference.peek()===void 0||(this.frame.peek()===void 0&&this.frame.set(n.clone()),!await this.#h(a,t))||s!==this.#i||a<(this.timestamp.peek()??0)))return;this.timestamp.set(a),this.#c(a),this.frame.update(o=>(o?.close(),n.clone()))}finally{n.close()}},error:n=>{console.error(n),t.close()}});t.cleanup(()=>{i.state!=="closed"&&i.close()}),this.config.container.kind==="cmaf"?this.#r(t,e,i):this.#a(t,e,i)}#a(t,e,i){let n=this.config.container.kind==="loc"?new g.Loc.Format:new g.Legacy.Format,s=new g.Consumer(e,{format:n,latency:this.#e});t.cleanup(()=>s.close()),t.run(o=>{let r=o.get(s.buffered),l=o.get(this.#t);this.buffered.update(()=>g.mergeBufferedRanges(r,l))}),i.configure({codec:this.config.codec,description:this.config.description?v.Hex.toBytes(this.config.description):void 0,displayAspectWidth:this.config.displayAspectWidth,displayAspectHeight:this.config.displayAspectHeight,optimizeForLatency:this.config.optimizeForLatency,flip:!1});let a;t.spawn(async()=>{for(;;){let o=await s.next();if(!o)break;this.#o(o.discontinuity)&&(a=void 0);let{frame:r}=o;if(!r)continue;let l=f.Milli.fromMicro(r.timestamp);this.sync.received(l,"video");let c=new EncodedVideoChunk({type:r.keyframe?"key":"delta",data:r.payload,timestamp:r.timestamp});this.stats.update(h=>({frameCount:(h?.frameCount??0)+1,bytesReceived:(h?.bytesReceived??0)+r.payload.byteLength})),a!==void 0&&o.continuous&&this.#l(f.Milli.fromMicro(a),f.Milli.fromMicro(r.timestamp)),a=r.timestamp,i.decode(c)}})}#r(t,e,i){let n=this.config.container;if(n.kind!=="cmaf")return;let s=N(n.init),a=g.Cmaf.decodeInitSegment(s),o=this.config.description?v.Hex.toBytes(this.config.description):a.description,r=new g.Consumer(e,{format:new g.Cmaf.Format(a),latency:this.#e});t.cleanup(()=>r.close()),t.run(c=>{let h=c.get(r.buffered),u=c.get(this.#t);this.buffered.update(()=>g.mergeBufferedRanges(h,u))}),i.configure({codec:this.config.codec,description:o,displayAspectWidth:this.config.displayAspectWidth,displayAspectHeight:this.config.displayAspectHeight,optimizeForLatency:this.config.optimizeForLatency,flip:!1});let l;t.spawn(async()=>{for(;;){let c=await r.next();if(!c)break;this.#o(c.discontinuity)&&(l=void 0);let{frame:h}=c;if(!h)continue;let u=f.Milli.fromMicro(h.timestamp);if(this.sync.received(u,"video"),this.stats.update(m=>({frameCount:(m?.frameCount??0)+1,bytesReceived:(m?.bytesReceived??0)+h.payload.byteLength})),l!==void 0&&c.continuous&&this.#l(f.Milli.fromMicro(l),f.Milli.fromMicro(h.timestamp)),l=h.timestamp,i.state==="closed")break;i.decode(new EncodedVideoChunk({type:h.keyframe?"key":"delta",data:h.payload,timestamp:h.timestamp}))}})}#o(t){return t!==this.#i&&(this.#i=t,this.timestamp.set(void 0),this.#t.set([]),this.sync.reset(),!0)}async#h(t,e){let i;try{let n=new Promise(a=>{i=this.paced.changed(()=>a(!this.paced.peek()))}),s=this.sync.wait(t).then(()=>!0);return await Promise.race([s,n,e.cancel])??!1}finally{i?.()}}#l(t,e){t>e||this.#t.mutate(i=>{for(let n of i)if(n.start<=e&&n.end>=t){n.start=f.Milli.min(n.start,t),n.end=f.Milli.max(n.end,e);return}i.push({start:t,end:e}),i.sort((n,s)=>n.start-s.start)})}#c(t){this.#t.mutate(e=>{for(;e.length>0;){if(e[0].end>=t){e[0].start=f.Milli.max(e[0].start,t);break}e.shift()}})}close(){this.#n.close(),this.frame.update(t=>{t?.close()})}};async function Mt(t){if(!y.containerSupported(t.container)){let n=t.container.kind==="unknown"?t.container.raw.kind:t.container.kind;return console.warn(`video: ignoring rendition with unknown container: ${n}`),!1}let e;if(t.description)e=v.Hex.toBytes(t.description);else if(t.container.kind==="cmaf")try{e=g.Cmaf.decodeInitSegment(N(t.container.init)).description}catch(n){return console.warn(`video: malformed CMAF init segment for codec ${t.codec}`,n),!1}let{supported:i}=await VideoDecoder.isConfigSupported({codec:t.codec,description:e,displayAspectWidth:t.displayAspectWidth,displayAspectHeight:t.displayAspectHeight,optimizeForLatency:t.optimizeForLatency??!0});if(i)return!0;if(t.codec.startsWith("avc3.")){let n=`avc1.${t.codec.slice(5)}`;if((await VideoDecoder.isConfigSupported({codec:n,description:e,displayAspectWidth:t.displayAspectWidth,displayAspectHeight:t.displayAspectHeight,optimizeForLatency:t.optimizeForLatency??!0})).supported)return t.codec=n,!0}return!1}Object.assign(Mt,{[bt]:ie});var rt=.01,At=class{decoder;in;#t={frame:new d(void 0),timestamp:new d(void 0),visible:new d(!1)};out=P(this.#t);#e=new d(void 0);#i=new E;constructor(t,e){this.decoder=t,this.in={canvas:w(e?.canvas),visible:w(e?.visible??"20%")},this.#i.run(i=>{let n=i.get(this.in.canvas);this.#e.set(n?.getContext("2d")??void 0)}),this.#i.run(this.#s.bind(this)),this.#i.run(this.#a.bind(this)),this.#i.run(this.#n.bind(this))}#n(t){let e=t.getAll([this.in.canvas,this.decoder.out.display]);if(!e)return;let[i,n]=e;(i.width!==n.width||i.height!==n.height)&&(i.width=n.width,i.height=n.height)}#s(t){let e=t.get(this.in.visible);if(e==="never"){this.#t.visible.set(!1);return}if(e==="always"){this.#t.visible.set(!0),t.cleanup(()=>this.#t.visible.set(!1));return}let i=t.get(this.in.canvas);if(!i){this.#t.visible.set(!1);return}let n=!1,s=()=>{this.#t.visible.set(n&&!document.hidden)},a=r=>{for(let l of r)n=l.isIntersecting,s()},o;try{o=new IntersectionObserver(a,{threshold:rt,rootMargin:e})}catch{console.warn(`moq-watch: invalid visible margin "${e}", using "0px"`),o=new IntersectionObserver(a,{threshold:rt})}s(),t.event(document,"visibilitychange",s),o.observe(i),t.cleanup(()=>o.disconnect()),t.cleanup(()=>this.#t.visible.set(!1))}#a(t){let e=t.get(this.#e);if(!e)return;let i=t.get(this.decoder.out.frame),n=t.get(this.decoder.source.out.catalog),s=requestAnimationFrame(()=>{this.#r(e,i,n),i?(this.#t.frame.update(a=>(a?.close(),i.clone())),this.#t.timestamp.set(f.Milli.fromMicro(i.timestamp))):(this.#t.frame.update(a=>{a?.close()}),this.#t.timestamp.set(void 0)),s=void 0});t.cleanup(()=>{s!==void 0&&cancelAnimationFrame(s)})}#r(t,e,i){if(!e){t.fillStyle="#000",t.fillRect(0,0,t.canvas.width,t.canvas.height);return}if(t.save(),t.fillStyle="#000",t.fillRect(0,0,t.canvas.width,t.canvas.height),!i?.rotation)i?.flip&&(t.scale(-1,1),t.translate(-t.canvas.width,0)),t.drawImage(e,0,0,t.canvas.width,t.canvas.height);else{let n=re(t.canvas,i);t.setTransform(...n.matrix),t.drawImage(e,0,0,n.source.width,n.source.height)}t.restore()}close(){this.#t.frame.update(t=>{t?.close()}),this.#t.timestamp.set(void 0),this.#i.close()}};function ce(t){return e=>{let i=[],n=[];for(let[s,a]of e)if(a.codedWidth&&a.codedHeight){let o=a.codedWidth*a.codedHeight;o<=t?i.push({name:s,size:o}):n.push({name:s,size:o})}return i.sort((s,a)=>a.size-s.size),i.length>0?i.map(s=>s.name):n.length>0?(n.sort((s,a)=>s.size-a.size),[n[0].name]):e.map(([s])=>s)}}function kt(t,e){return i=>{let n=[],s=[];for(let[a,o]of i){if(!o.codedWidth||!o.codedHeight)continue;let r=o.codedWidth*o.codedHeight,l=t==null||o.codedWidth<=t,c=e==null||o.codedHeight<=e;l&&c?n.push({name:a,size:r}):s.push({name:a,size:r})}return n.sort((a,o)=>o.size-a.size),n.length>0?n.map(a=>a.name):s.length>0?(s.sort((a,o)=>a.size-o.size),[s[0].name]):i.map(([a])=>a)}}function xt(t){return e=>{let i=[],n=[];for(let[s,a]of e)a.bitrate!=null&&a.bitrate<=t?i.push({name:s,bitrate:a.bitrate}):a.bitrate!=null&&n.push({name:s,bitrate:a.bitrate});return i.sort((s,a)=>a.bitrate-s.bitrate),i.length>0?i.map(s=>s.name):n.length>0?(n.sort((s,a)=>s.bitrate-a.bitrate),[n[0].name]):e.map(([s])=>s)}}function he(t){let e=t[0];for(let i of t){let[,n]=i,[,s]=e,a=(n.codedWidth??0)*(n.codedHeight??0),o=(s.codedWidth??0)*(s.codedHeight??0);if(a!==o){a>o&&(e=i);continue}(n.bitrate??0)>(s.bitrate??0)&&(e=i)}return e[0]}function de(t){let e=Object.entries(t).filter(([,a])=>!a.stalled);if(e.length>0)return Object.fromEntries(e);let i=Object.entries(t);if(i.length===0)return{};let n=xt(0)(i),s=n.length===1?n[0]:kt(0,0)(i)[0];return{[s]:t[s]}}var Rt=class{in;#t={catalog:new d(void 0),available:new d({}),error:new d(void 0),track:new d(void 0),config:new d(void 0),jitter:new d(void 0)};out=P(this.#t);#e=new E;#i=new WeakMap;constructor(t){this.in={broadcast:w(t?.broadcast),target:w(t?.target),supported:w(t?.supported)},this.#e.run(this.#n.bind(this)),this.#e.run(this.#s.bind(this)),this.#e.run(this.#a.bind(this))}#n(t){let e=t.get(this.in.broadcast);if(!e)return;let i=t.get(e.out.catalog)?.video;i&&t.set(this.#t.catalog,i)}#s(t){let e=t.get(this.in.supported);if(!e){this.#t.error.set(void 0);return}let i=t.get(this.#t.catalog)?.renditions??{};this.#t.error.set(void 0);let n=this.#i.get(e);n||(n=new Map,this.#i.set(e,n));let s=new Set(Object.keys(i));for(let a of n.keys())s.has(a)||n.delete(a);t.spawn(async()=>{let a={},o=t.cancel.then(()=>{});for(let[l,c]of Object.entries(i)){let h=e[bt],u=h?h(c):JSON.stringify(c),m=n.get(l),b=!1;if(m?.key===u)b=m.supported;else{let R=!1;try{b=await Promise.race([e(c),o])}catch(A){R=!0,console.warn(`[Source] video rendition ${l} (${c.codec}) support probe failed; treating as unsupported`,A)}!R&&b!==void 0&&n.set(l,{key:h?h(c):JSON.stringify(c),supported:b})}if(t.abort.aborted)return;b&&(a[l]=c)}let r=Object.keys(a).length===0&&Object.keys(i).length>0?"unsupported":void 0;r==="unsupported"&&console.warn("[Source] No supported video renditions found:",i),this.#t.error.set(r),this.#t.available.set(a)})}#a(t){let e=de(t.get(this.#t.available));if(Object.keys(e).length===0)return;let i=t.get(this.in.target);if(i?.name&&i.name in e){let o=e[i.name];t.set(this.#t.track,i.name),t.set(this.#t.config,o),t.set(this.#t.jitter,at(o));return}let n=i;if(!i?.bitrate){let o=t.get(this.in.broadcast),r=o?t.get(o.in.connection):void 0,l=r&&t.get(r.probe).estimatedRecvRate;if(l!=null){let c=Math.round(l*.8);n={...i,bitrate:c}}}let s=this.#r(e,n);if(!s)return;let a=e[s];t.set(this.#t.track,s),t.set(this.#t.config,a),t.set(this.#t.jitter,at(a))}#r(t,e){let i=Object.entries(t);if(i.length===0)return;if(i.length===1)return i[0][0];let n=[];if(e?.pixels!=null&&n.push(ce(e.pixels)),(e?.width!=null||e?.height!=null)&&n.push(kt(e.width,e.height)),e?.bitrate!=null&&n.push(xt(e.bitrate)),n.length===0)return he(i);let s=n.map(o=>o(i)),a=s.map(o=>new Set(o));for(let o of s[0])if(a.every(r=>r.has(o)))return o;console.warn("conflicting rendition filters, no rendition satisfies all criteria")}close(){this.#e.close()}};import*as I from"../../net@^0.3.4.target-es2022.mjs";import{Effect as ue,Signal as M}from"../../signals@^0.2.3.target-es2022.mjs";var fe=["url","name","paused","volume","muted","visible","reload","latency","latency-min","latency-max","jitter","catalog-format"];function me(t){let e=t?.trim();return e?e==="never"||e==="always"||/^-?\d+(\.\d+)?(px|%)$/.test(e)?e:/^-?\d+(\.\d+)?$/.test(e)?`${e}px`:(console.warn(`moq-watch: invalid visible="${t}", expected "never", "always", or a CSS length like "200px"`),"20%"):"20%"}function J(t,e){if(t===null)return e;let i=t.trim().toLowerCase();return i!=="false"&&i!=="0"}var pe=new FinalizationRegistry(t=>t.close()),ge=class extends HTMLElement{static observedAttributes=fe;connection;broadcast;video;audio;renderer;emitter;sync;controls={paused:new M(!1),volume:new M(.5),muted:new M(!1),visible:new M("20%"),latency:new M("real-time"),target:new M(void 0)};#t=new M(I.Path.empty());#e=new M(!0);#i=new M(void 0);#n=new M(void 0);#s=new M(void 0);#a=new M(!1);#r=new M(!1);#o=!1;#h=new M(!0);#l=new M("real-time");#c=new M(!1);#f=.5;signals=new ue;constructor(){super(),pe.register(this,this.signals),this.connection=new I.Connection.Reload({enabled:this.#c}),this.signals.cleanup(()=>this.connection.close()),this.broadcast=new gt({connection:this.connection.established,enabled:this.#c,name:this.#t,reload:this.#e,catalogFormat:this.#i,catalog:this.#n}),this.signals.cleanup(()=>this.broadcast.close());let t=new Rt({broadcast:this.broadcast,target:this.controls.target,supported:V.supported}),e=new ft({broadcast:this.broadcast,supported:q.supported});this.signals.cleanup(()=>{t.close(),e.close()}),this.signals.run(r=>{let l=r.get(this.controls.latency);this.#l.set(l==="instant"?I.Time.Milli.zero:l)}),this.sync=new Q({latency:this.#l,connection:this.connection.established,video:t.out.jitter,audio:e.out.jitter}),this.signals.cleanup(()=>this.sync.close()),this.signals.run(r=>{this.#h.set(r.get(this.controls.latency)!=="instant")}),this.video=new V(t,this.sync,{enabled:this.#a,paced:this.#h}),this.audio=new q(e,this.sync,{enabled:this.#r}),this.signals.cleanup(()=>{this.video.close(),this.audio.close()}),this.emitter=new ut(this.audio,{volume:this.controls.volume,muted:this.controls.muted,paused:this.controls.paused}),this.renderer=new At(this.video,{canvas:this.#s,visible:this.controls.visible}),this.signals.cleanup(()=>{this.emitter.close(),this.renderer.close()}),this.signals.run(r=>{let l=r.get(this.emitter.out.enabled);this.#r.set(l&&r.get(this.controls.latency)!=="instant")}),this.signals.run(r=>{r.get(this.controls.latency)==="instant"&&this.audio.reset()}),this.signals.run(r=>{let l=r.get(this.renderer.out.visible);if(!r.get(this.controls.paused)){this.#a.set(l);return}let c=r.get(this.renderer.out.frame);this.#a.set(l&&!c)}),this.signals.run(r=>{r.get(this.controls.muted)?(this.#f=this.controls.volume.peek()||.5,this.controls.volume.set(0)):this.controls.volume.set(this.#f)}),this.signals.run(r=>{let l=r.get(this.controls.volume);this.controls.muted.set(l===0)});let i=()=>{let r=this.querySelector("canvas")??void 0;!r&&this.querySelector("video")&&console.warn("moq-watch: rendering requires a <canvas> child; a <video> child does nothing."),this.#s.set(r)},n=new MutationObserver(i);n.observe(this,{childList:!0,subtree:!0}),this.signals.cleanup(()=>n.disconnect()),i(),this.signals.run(r=>{let l=r.get(this.connection.url);l?this.setAttribute("url",l.toString()):this.removeAttribute("url")}),this.signals.run(r=>{let l=r.get(this.#t);this.setAttribute("name",l.toString())}),this.signals.run(r=>{r.get(this.controls.muted)?this.setAttribute("muted",""):this.removeAttribute("muted")}),this.signals.run(r=>{r.get(this.controls.paused)?this.setAttribute("paused",""):this.removeAttribute("paused")}),this.signals.run(r=>{let l=r.get(this.controls.volume);this.setAttribute("volume",l.toString())}),this.signals.run(r=>{let l=r.get(this.controls.visible);this.setAttribute("visible",l)}),this.signals.run(r=>{let l=r.get(this.controls.latency);if(l==="instant"){this.#u("instant");return}let{min:c,max:h}=S(l);if(c!==h){this.getAttribute("latency")==="instant"&&this.#u(void 0);return}if(c==="real-time")this.#u("real-time");else{let u=Math.floor(r.get(this.sync.out.jitter));this.#u(u.toString())}});let s=(r,l)=>{if(r<=0||l<=0)return;let c=window.devicePixelRatio||1;this.controls.target.update(h=>({...h,width:Math.round(r*c),height:Math.round(l*c)}))},a=new ResizeObserver(r=>{let l=r[0];l&&s(l.contentRect.width,l.contentRect.height)});a.observe(this),this.signals.cleanup(()=>a.disconnect());let o=this.getBoundingClientRect();s(o.width,o.height)}connectedCallback(){this.#c.set(!0),this.style.display="block",this.style.position="relative"}disconnectedCallback(){this.#c.set(!1)}#d(t){if(!t||t==="real-time")return"real-time";if(t==="instant")return console.warn('moq-watch: "instant" is not a bound, use latency="instant"'),"real-time";let e=Number.parseFloat(t);return I.Time.Milli(Number.isFinite(e)?e:100)}#u(t){this.#o=!0;try{t===void 0?this.removeAttribute("latency"):this.setAttribute("latency",t)}finally{this.#o=!1}}#m(t){return t?.trim()==="instant"?"instant":this.#d(t)}attributeChangedCallback(t,e,i){if(e!==i)if(t==="url")this.connection.url.set(i?new URL(i):void 0);else if(t==="name")this.#t.set(I.Path.from(i??""));else if(t==="paused")this.controls.paused.set(J(i,!1));else if(t==="volume"){let n=i?Number.parseFloat(i):.5;this.controls.volume.set(n)}else if(t==="muted")this.controls.muted.set(J(i,!1));else if(t==="visible")this.controls.visible.set(me(i));else if(t==="reload")this.#e.set(J(i,!0));else if(t==="latency")this.#o||(this.latency=this.#m(i));else if(t==="latency-min")this.latencyMin=this.#d(i);else if(t==="latency-max")this.latencyMax=this.#d(i);else if(t==="jitter")this.latency=this.#d(i);else if(t==="catalog-format")this.#i.set(pt(i));else throw Error(`Invalid attribute: ${t}`)}get url(){return this.connection.url.peek()}set url(t){this.connection.url.set(t?new URL(t):void 0)}get name(){return this.#t.peek()}set name(t){this.#t.set(I.Path.from(t))}get paused(){return this.controls.paused.peek()}set paused(t){this.controls.paused.set(t)}get volume(){return this.controls.volume.peek()}set volume(t){this.controls.volume.set(t)}get muted(){return this.controls.muted.peek()}set muted(t){this.controls.muted.set(t)}get visible(){return this.controls.visible.peek()}set visible(t){this.controls.visible.set(t)}get reload(){return this.#e.peek()}set reload(t){this.#e.set(t)}get latency(){return this.controls.latency.peek()}set latency(t){this.controls.latency.set(t)}get latencyMin(){return S(this.controls.latency.peek()).min}set latencyMin(t){let{max:e}=S(this.controls.latency.peek());this.controls.latency.set(Y(t,e))}get latencyMax(){return S(this.controls.latency.peek()).max}set latencyMax(t){let{min:e}=S(this.controls.latency.peek());this.controls.latency.set(Y(e,t))}get jitter(){return this.sync.out.jitter.peek()}reset(){this.sync.reset(),this.audio.reset()}get catalogFormat(){return this.#i.peek()}set catalogFormat(t){this.#i.set(t)}get catalog(){return this.broadcast.out.catalog.peek()}set catalog(t){this.#n.set(t)}};customElements.define("moq-watch",ge);export{ge as default};
//# sourceMappingURL=element.mjs.map