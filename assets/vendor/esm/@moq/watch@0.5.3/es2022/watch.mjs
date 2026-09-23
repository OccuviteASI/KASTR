/* esm.sh - @moq/watch@0.5.3 */
import{Time as p}from"../../net@^0.3.4.target-es2022.mjs";import{Effect as At,Signal as B,getter as F,readonlys as kt}from"../../signals@^0.2.3.target-es2022.mjs";function z(t){return t==="instant"?{min:p.Milli.zero,max:p.Milli.zero}:t==="real-time"||typeof t=="number"?{min:t,max:t}:{min:t.min??"real-time",max:t.max??"real-time"}}function xt(t,e){return t===e?t:{min:t,max:e}}var Rt=p.Milli(20),Y=p.Milli(100),St=class U{in;#t={reference:new B(void 0),buffer:new B(p.Milli.zero),jitter:new B(Y),timestamp:new B(void 0),buffered:new B(!1),maxBuffer:new B(p.Milli.zero)};out=kt(this.#t);#e;#n=new Map;#i;#s=new At;constructor(e){this.in={latency:F(e?.latency??"real-time"),connection:F(e?.connection),audio:F(e?.audio),video:F(e?.video)},this.#e=Promise.withResolvers(),this.#s.run(this.#o.bind(this)),this.#s.run(this.#l.bind(this)),this.#s.run(this.#a.bind(this))}#a(e){let{max:n}=z(e.get(this.in.latency)),i=e.get(this.#t.buffer);n==="real-time"?(this.#t.buffered.set(!1),this.#t.maxBuffer.set(i)):(this.#t.buffered.set(n>i),this.#t.maxBuffer.set(p.Milli.max(n,i)))}#r(){let{max:e}=z(this.in.latency.peek()),n=this.#t.buffer.peek();return e==="real-time"?n:p.Milli.max(e,n)}#o(e){let{min:n}=z(e.get(this.in.latency));if(typeof n=="number"){this.#i=void 0,this.#t.jitter.set(n);return}let i=e.get(this.in.connection),s=i&&e.get(i.probe).rtt;if(s!==void 0){this.#i=this.#i===void 0?s:Math.min(this.#i,s);let a=p.Milli(Math.max(Rt,this.#i*1.25));this.#t.jitter.set(a);return}this.#i=void 0,this.#t.jitter.set(Y)}#l(e){let n=e.get(this.#t.jitter),i=e.get(this.in.video)??p.Milli.zero,s=e.get(this.in.audio)??p.Milli.zero,a=p.Milli.add(p.Milli.max(i,s),n);this.#t.buffer.set(a),this.#e.resolve(),this.#e=Promise.withResolvers()}received(e,n=""){this.#t.timestamp.update(l=>l===void 0||e>l?e:l);let i=p.Milli.now(),s=p.Milli.sub(i,e),a=this.#t.reference.peek();if(a===void 0){this.#c(s);return}let r=this.#t.buffer.peek(),o=p.Milli.add(p.Milli.sub(a,s),r);if(o<0){let l=this.#n.get(n);l?(l.count++,l.maxMs=Math.max(l.maxMs,-o)):this.#n.set(n,{count:1,maxMs:-o})}else{let l=this.#n.get(n);if(l){let h=n?`sync[${n}]`:"sync",u=U.#h(l.maxMs);console.debug(`${h}: ${l.count} late frame(s), max ${u} behind`),this.#n.delete(n)}}if(s>=a)return;let c=this.#r();o<=c||this.#c(p.Milli.add(s,p.Milli.sub(c,r)))}#c(e){this.#t.reference.set(e),this.#e.resolve(),this.#e=Promise.withResolvers()}reset(){this.#t.reference.set(void 0),this.#n.clear(),this.#e.resolve(),this.#e=Promise.withResolvers()}now(){let e=this.#t.reference.peek();if(e!==void 0)return p.Milli.sub(p.Milli.sub(p.Milli.now(),e),this.#t.buffer.peek())}async wait(e){if(this.#t.reference.peek()===void 0)throw Error("reference not set; call received() first");for(;;){let n=p.Milli.now(),i=p.Milli.sub(n,e),s=this.#t.reference.peek();if(s===void 0)return;let a=p.Milli.add(p.Milli.sub(s,i),this.#t.buffer.peek());if(a<=0||a<5)return;let r=new Promise(o=>setTimeout(o,a)).then(()=>!0);if(await Promise.race([this.#e.promise,r]))return}}static#h(e){if(e=Math.round(e),e<1e3)return`${e}ms`;let n=e/1e3;if(n<60)return`${Math.round(n*10)/10}s`;let i=n/60;return`${Math.round(i*10)/10}m`}close(){this.#s.close()}};import{Path as H,Time as f}from"../../net@^0.3.4.target-es2022.mjs";import{Effect as R,Signal as d,getter as w,readonlys as L}from"../../signals@^0.2.3.target-es2022.mjs";import*as y from"../../hang@^0.4.2/catalog.target-es2022.mjs";import{u53 as O}from"../../hang@^0.4.2/catalog.target-es2022.mjs";import*as g from"../../hang@^0.4.2/container.target-es2022.mjs";import*as v from"../../hang@^0.4.2/util.target-es2022.mjs";import*as tt from"../../json.target-es2022.mjs";import*as et from"../../msf@^0.2.1.target-es2022.mjs";function j(t){let e=atob(t),n=new Uint8Array(e.length);for(let i=0;i<e.length;i++)n[i]=e.charCodeAt(i);return n}var A=0,W=1,C=2,Et=3,Tt=4294967295n;function I(t,e){return BigInt(t>>>0)<<32n|BigInt(e>>>0)}function S(t){return Number(t>>32n)|0}function k(t){return Number(t&Tt)|0}function Ot(t){return t<=1?1:1<<32-Math.clz32(t-1)}function nt(t,e,n,i=!1){if(t<=0)throw Error("invalid channels");if(e<=0||e>2**30)throw Error("invalid capacity");if(n<=0)throw Error("invalid sample rate");e=Ot(e);let s=new SharedArrayBuffer(t*e*Float32Array.BYTES_PER_ELEMENT),a=new SharedArrayBuffer(Et*Int32Array.BYTES_PER_ELEMENT),r=new SharedArrayBuffer(BigInt64Array.BYTES_PER_ELEMENT),o=new Int32Array(a);return Atomics.store(o,C,1),{channels:t,capacity:e,rate:n,samples:s,control:a,state:r,buffered:i}}function K(t,e){return(t-e|0)>0?t:e}function _(t,e){return t&e-1}var It=class it{channels;capacity;rate;buffered;init;#t;#e;#n;#i=!1;#s=0;#a=0;#r=0;constructor(e,n){this.channels=e.channels,this.capacity=e.capacity,this.rate=e.rate,this.buffered=e.buffered,this.init=e,this.#t=new Int32Array(e.control),this.#e=new BigInt64Array(e.state),this.#n=[];for(let i=0;i<this.channels;i++)this.#n.push(new Float32Array(e.samples,i*this.capacity*Float32Array.BYTES_PER_ELEMENT,this.capacity));n!==void 0&&this.#o(n)}#o(e){if(e.channels!==this.channels||e.rate!==this.rate)return;let n=Atomics.load(e.#e,0);for(;;){let i=Atomics.load(this.#e,0);if(S(i)!==S(n)||(k(n)-k(i)|0)<=0)return;let s=I(S(i),k(n));if(Atomics.compareExchange(this.#e,0,i,s)===i)return}}#l(e){for(;;){let n=Atomics.load(this.#e,0);if((e-k(n)|0)<=0)return;let i=I(S(n),e);if(Atomics.compareExchange(this.#e,0,n,i)===n)return}}insert(e,n){if(n.length!==this.channels)throw Error("wrong number of channels");let i=Math.round(f.Second.fromMicro(e)*this.rate),s=n[0].length,a=0;if(!this.#i){this.#s=i;let M=S(Atomics.load(this.#e,0));Atomics.store(this.#e,0,I(M+1|0,0)),Atomics.store(this.#t,A,0),this.#i=!0,this.#a=0,this.#r=0}i=i-this.#s|0;let r=i+s|0,o=k(Atomics.load(this.#e,0)),c=o-i|0;if(c>0){if(c>=s)return;a=c,i=i+c|0}let l=s-a;(r-o|0)>this.capacity&&this.#l(r-this.capacity|0);let h=Atomics.load(this.#t,A),u=i-h|0;if(u>0){let M=Math.min(u,this.capacity);for(let E=0;E<this.channels;E++){let D=this.#n[E];for(let T=0;T<M;T++)D[_(h+T|0,this.capacity)]=0}}for(let M=0;M<this.channels;M++){let E=n[M],D=this.#n[M];for(let T=0;T<l;T++)D[_(i+T|0,this.capacity)]=E[a+T]}Atomics.store(this.#t,A,K(Atomics.load(this.#t,A),r));let m=k(Atomics.load(this.#e,0)),b=Atomics.load(this.#t,A),x=Atomics.load(this.#t,W);(b-m|0)>=x&&x>0&&Atomics.store(this.#t,C,0)}read(e){let n=Atomics.load(this.#e,0);if(Atomics.load(this.#t,C)===1)return 0;let i=k(n),s=Atomics.load(this.#t,A),a=Atomics.load(this.#t,W),r=s-i|0;if(!this.buffered&&a>0&&r>a){let h=s-a|0;(h-i|0)>0&&(i=h)}let o=s-i|0,c=Math.min(o,e[0].length);if(c<=0)return(i-k(n)|0)>0&&Atomics.compareExchange(this.#e,0,n,I(S(n),i)),0;for(let h=0;h<this.channels;h++){let u=this.#n[h],m=e[h];for(let b=0;b<c;b++)m[b]=u[_(i+b|0,this.capacity)]}let l=I(S(n),i+c|0);if(Atomics.compareExchange(this.#e,0,n,l)!==n){for(let h=0;h<this.channels;h++)e[h].fill(0,0,c);return 0}return c}setLatency(e){Atomics.store(this.#t,W,e)}truncate(e){let n=Math.round(f.Second.fromMicro(e)*this.rate)-this.#s|0;for(;;){let i=Atomics.load(this.#t,A);if((i-n|0)<=0)return;let s=K(n,k(Atomics.load(this.#e,0)));if((i-s|0)<=0||Atomics.compareExchange(this.#t,A,i,s)===i)return}}reset(){this.#i=!1,Atomics.store(this.#t,C,1);let e=Atomics.load(this.#t,A),n=Atomics.load(this.#e,0);Atomics.store(this.#e,0,I(S(n),e))}resize(e){let n=nt(this.channels,e,this.rate,this.buffered),i=new it(n);i.#i=this.#i,i.#s=this.#s;let s=Atomics.load(this.#e,0),a=k(s),r=Atomics.load(this.#t,A),o=Atomics.load(this.#t,W),c=Atomics.load(this.#t,C),l=r-a|0,h=Math.max(0,Math.min(l,i.capacity)),u=r-h|0;for(let m=0;m<this.channels;m++){let b=this.#n[m],x=i.#n[m];for(let M=0;M<h;M++){let E=u+M|0;x[_(E,i.capacity)]=b[_(E,this.capacity)]}}return Atomics.store(i.#e,0,I(S(s),u)),Atomics.store(i.#t,A,r),Atomics.store(i.#t,W,o),Atomics.store(i.#t,C,c),i.#a=this.#c(a)+(u-a|0),i.#r=u,i}#c(e){return this.#a+=e-this.#r|0,this.#r=e,this.#a}#h(){return this.#c(k(Atomics.load(this.#e,0)))}get timestamp(){return f.Micro.fromSecond((this.#s+this.#h())/this.rate)}get stalled(){return Atomics.load(this.#t,C)===1}get length(){return Atomics.load(this.#t,A)-k(Atomics.load(this.#e,0))|0}},st=class{#t;#e;#n=[];constructor(t,e){this.#t=t,this.#e=e}setHeadroom(t){this.#e=t}wait(t,e){return!this.#t||e>=(t-this.#e|0)?Promise.resolve():new Promise(n=>this.#n.push({timestamp:t,resolve:n}))}advance(t){this.#n.length!==0&&(this.#n=this.#n.filter(({timestamp:e,resolve:n})=>t<(e-this.#e|0)||(n(),!1)))}flush(){for(let{resolve:t}of this.#n)t();this.#n=[]}};function N(t,e){return f.Micro.fromSecond(t/e)}function Ct(){return!(typeof SharedArrayBuffer>"u"||typeof crossOriginIsolated<"u"&&!crossOriginIsolated)}function Lt(t,e,n,i,s=!1){return Ct()?(console.log("[audio] using SharedArrayBuffer audio buffer"),new Bt(t,e,n,i,s)):(console.warn("[audio] SharedArrayBuffer unavailable, falling back to the higher latency postMessage audio buffer. Serve the page cross-origin isolated (Cross-Origin-Opener-Policy: same-origin, Cross-Origin-Embedder-Policy: require-corp) to avoid this."),new zt(t,e,n,i,s))}var Bt=class{rate;channels;#t;#e;#n=new d(0);timestamp=this.#n;#i=new d(!0);stalled=this.#i;#s;#a=new R;constructor(t,e,n,i,s){this.#t=t,this.channels=e,this.rate=n;let a=Math.max(n,i*2);this.#s=new st(s,N(i,n));let r=nt(e,a,n,s);this.#e=new It(r),this.#e.setLatency(i);let o={type:"init-shared",...r};t.port.postMessage(o),this.#a.interval(()=>{let c=this.#e.stalled;this.#n.set(this.#e.timestamp),this.#i.set(c),c?this.#s.flush():this.#s.advance(this.#e.timestamp)},50)}insert(t,e){this.#e.insert(t,e)}setLatency(t){if(this.#s.setHeadroom(N(t,this.rate)),this.#e.capacity<t*1.5){let e=Math.max(this.rate,t*2);this.#e=this.#e.resize(e),this.#e.setLatency(t);let n={type:"init-shared",...this.#e.init};this.#t.port.postMessage(n)}else this.#e.setLatency(t)}truncate(t){this.#e.truncate(t)}reset(){this.#e.reset(),this.#s.flush()}wait(t){return this.#e.stalled?Promise.resolve():this.#s.wait(t,this.#e.timestamp)}close(){this.#s.flush(),this.#a.close()}},zt=class{rate;channels;#t;#e=new d(0);timestamp=this.#e;#n=new d(!0);stalled=this.#n;#i;#s=new R;constructor(t,e,n,i,s){this.#t=t,this.channels=e,this.rate=n,this.#i=new st(s,N(i,n));let a={type:"init-post",channels:e,rate:n,latency:f.Milli.fromSecond(i/n),buffered:s};t.port.postMessage(a),this.#s.event(t.port,"message",r=>{let o=r.data;o?.type==="state"&&(this.#e.set(o.timestamp),this.#n.set(o.stalled),o.stalled?this.#i.flush():this.#i.advance(o.timestamp))}),t.port.start()}insert(t,e){let n={type:"data",data:e,timestamp:t};this.#t.port.postMessage(n,e.map(i=>i.buffer))}setLatency(t){this.#i.setHeadroom(N(t,this.rate));let e={type:"latency",latency:f.Milli.fromSecond(t/this.rate)};this.#t.port.postMessage(e)}truncate(t){let e={type:"truncate",timestamp:t};this.#t.port.postMessage(e)}reset(){this.#t.port.postMessage({type:"reset"}),this.#i.flush()}wait(t){return this.#n.peek()?Promise.resolve():this.#i.wait(t,this.#e.peek())}close(){this.#i.flush(),this.#s.close()}},Pt=class{#t=!1;#e=!1;opened(){this.#t&&(this.#e=!0),this.#t=!0}takeover(){let t=this.#e;return this.#e=!1,t}},Wt=new Blob([`var __defProp = Object.defineProperty;
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
`],{type:"application/javascript"}),_t=URL.createObjectURL(Wt);function jt(t,{broadcast:e,track:n,maxLatency:i}){let s=y.PRIORITY.audio,a=Math.ceil(i.peek()),r=e.track(n).subscribe({priority:s,latencyMax:a});return t.cleanup(()=>r.close()),t.run(o=>{let c=Math.ceil(o.get(i));c!==a&&(a=c,r.update({priority:s,latencyMax:a}))}),r}var Ft=class{#t=0;#e;#n;#i=0;#s;get end(){return this.#e}clear(t=0){this.#t=0,this.#e=void 0,this.#i=t,this.#a()}update(t){let e=t.discontinuity!==this.#t;return e&&(this.#t=t.discontinuity,this.#e=void 0,this.#a()),t.frame&&this.#n===void 0&&(this.#n=t.frame.timestamp),t.end!==void 0&&(this.#e=t.end),e}span(t){let e=this.#n??t.timestamp;this.#n=e;let n=Math.floor(this.#i*t.sampleRate/48e3),i=this.#s??n,s=Math.min(i,t.numberOfFrames);this.#s=i-s;let a=Math.round(n*1e6/t.sampleRate),r=Math.max(e,t.timestamp-a),o=t.numberOfFrames-s;if(this.#e!==void 0)if(this.#e<=r)o=0;else{let c=this.#e-r,l=Math.round(c*t.sampleRate/1e6);o=Math.min(o,l)}return{timestamp:r,frameOffset:s,frames:o}}#a(){this.#n=void 0,this.#s=void 0}};function Nt(t,e){let n=new d(e.state==="running");t.event(e,"statechange",()=>n.set(e.state==="running")),t.run(i=>{if(i.get(n))return;let s=()=>{e.resume().catch(()=>{})};s(),i.event(document,"pointerdown",s),i.event(document,"keydown",s)})}var Dt=class{#t;constructor(t){this.#t=t}drop(){return this.#t!==0&&(this.#t--,!0)}},Ht=150,$t=3,at=class{in;source;sync;#t={context:new d(void 0),root:new d(void 0),sampleRate:new d(void 0),stats:new d(void 0),timestamp:new d(void 0),stalled:new d(!0),buffered:new d([])};out=L(this.#t);#e=new d([]);#n;#i=new d(void 0);#s=new Ft;#a;#r=new Pt;#o=new R;constructor(t,e,n){this.in={enabled:w(n?.enabled??!1)},this.source=t,this.sync=e,this.#o.run(this.#l.bind(this)),this.#o.run(this.#c.bind(this)),this.#o.run(this.#h.bind(this)),this.#o.run(this.#f.bind(this)),this.#o.run(this.#m.bind(this))}#l(t){let e=t.get(this.source.out.config);if(!e)return;let n=t.get(this.#i)??e.sampleRate,i=e.numberOfChannels;t.set(this.#t.sampleRate,n);let s=new AudioContext({latencyHint:"interactive",sampleRate:n});t.set(this.#t.context,s),t.cleanup(()=>s.close()),t.spawn(async()=>{if(!await Promise.race([s.audioWorklet.addModule(_t).then(()=>!0),t.cancel]))return;let a=new AudioWorkletNode(s,"render",{channelCount:i,channelCountMode:"explicit",outputChannelCount:[i]});t.cleanup(()=>a.disconnect());let r=this.sync.out.buffer.peek(),o=Math.ceil(n*f.Second.fromMilli(r)),c=this.sync.out.buffered.peek(),l=Lt(a,i,n,o,c);this.#n=l,t.cleanup(()=>{l.close(),this.#n=void 0}),t.run(h=>{let u=f.Milli.fromMicro(h.get(l.timestamp));this.#t.timestamp.set(u),this.#y(u)}),t.run(h=>{this.#t.stalled.set(h.get(l.stalled))}),t.set(this.#t.root,a)})}#c(t){if(!t.get(this.in.enabled))return;let e=t.get(this.#t.context);e&&Nt(t,e)}#h(t){if(!t.get(this.#t.root))return;let e=this.#n;if(!e)return;let n=t.get(this.sync.out.buffer),i=Math.ceil(e.rate*f.Second.fromMilli(n));e.setLatency(i)}#f(t){let e=z(t.get(this.sync.in.latency)).min;if(this.#a===void 0){this.#a=e;return}let n=this.#a;t.timer(()=>{let i=s=>s==="real-time"?0:s;i(e)>i(n)&&this.reset(),this.#a=e},Ht)}#m(t){if(!t.get(this.in.enabled))return;let e=t.get(this.source.in.broadcast);if(!e)return;let n=t.get(this.source.out.track);if(!n)return;let i=t.get(this.source.out.config);if(!i)return;let s=e.relativeBroadcast(t,i.broadcast);if(!s)return;this.#r.opened();let a=jt(t,{broadcast:s,track:n,maxLatency:this.sync.out.maxBuffer});i.container.kind==="cmaf"?this.#g(t,a,i):this.#p(t,a,i)}#p(t,e,n){let i=n.codec==="opus"&&n.description?v.Opus.preSkip(v.Hex.toBytes(n.description)):0;this.#s.clear(i);let s=n.container.kind==="loc"?new g.Loc.Format:new g.Legacy.Format,a=new g.Consumer(e,{format:s,latency:this.sync.out.maxBuffer});t.cleanup(()=>a.close()),t.run(r=>{let o=r.get(a.buffered),c=r.get(this.#e);this.#t.buffered.update(()=>g.mergeBufferedRanges(o,c))}),t.spawn(async()=>{if(!await v.Libav.polyfill())return;let r=new Dt($t),o=new AudioDecoder({output:h=>{let u=this.#s.span(h);if(r.drop()){h.close();return}this.#d(h,u)},error:h=>console.error("audio decoder error",h)});t.cleanup(()=>{o.state!=="closed"&&o.close()});let c=n.codec==="opus"?void 0:n.description?v.Hex.toBytes(n.description):void 0,l={...n,description:c};for(o.configure(l);;){let h=await a.next();if(!h)break;if(this.#u(h)&&(o.reset(),o.configure(l)),h.end!==void 0)continue;let{frame:u}=h;if(!u)continue;let m=f.Milli.fromMicro(u.timestamp);this.sync.received(m,"audio"),this.#t.stats.update(x=>({bytesReceived:(x?.bytesReceived??0)+u.payload.byteLength})),await this.#n?.wait(u.timestamp);let b=new EncodedAudioChunk({type:u.keyframe?"key":"delta",data:u.payload,timestamp:u.timestamp});if(o.state==="closed")break;o.decode(b)}})}#g(t,e,n){if(n.container.kind!=="cmaf")return;let i=j(n.container.init),s=g.Cmaf.decodeInitSegment(i),a=n.description?v.Hex.toBytes(n.description):s.description,r=n.codec==="opus"&&a?v.Opus.preSkip(a):0;this.#s.clear(r);let o=n.codec==="opus"?void 0:n.description?v.Hex.toBytes(n.description):s.description,c=new g.Consumer(e,{format:new g.Cmaf.Format(s),latency:this.sync.out.maxBuffer});t.cleanup(()=>c.close()),t.run(l=>{let h=l.get(c.buffered),u=l.get(this.#e);this.#t.buffered.update(()=>g.mergeBufferedRanges(h,u))}),t.spawn(async()=>{if(!await v.Libav.polyfill())return;let l=new AudioDecoder({output:u=>this.#d(u),error:u=>console.error("audio decoder error",u)});t.cleanup(()=>{l.state!=="closed"&&l.close()});let h={codec:n.codec,sampleRate:n.sampleRate,numberOfChannels:n.numberOfChannels,description:o};for(l.configure(h);;){let u=await c.next();if(!u)break;this.#u(u)&&(l.reset(),l.configure(h));let{frame:m}=u;if(!m)continue;let b=f.Milli.fromMicro(m.timestamp);if(this.sync.received(b,"audio"),this.#t.stats.update(x=>({bytesReceived:(x?.bytesReceived??0)+m.payload.byteLength})),await this.#n?.wait(m.timestamp),l.state==="closed")break;l.decode(new EncodedAudioChunk({type:m.keyframe?"key":"delta",data:m.payload,timestamp:m.timestamp}))}})}#d(t,e=this.#s.span(t)){let{timestamp:n,frameOffset:i,frames:s}=e,a=f.Milli.fromMicro(n);if(s===0){t.close();return}let r=this.#n;if(!r){t.close();return}if(t.sampleRate!==r.rate){this.#i.set(t.sampleRate),t.close();return}let o=s/t.sampleRate*1e6,c=f.Milli.fromMicro(o),l=f.Milli.add(a,c);this.#r.takeover()&&(r.truncate(n),this.#w(a)),this.#b(a,l);let h=Math.min(t.numberOfChannels,r.channels),u=[];for(let m=0;m<h;m++){let b=new Float32Array(s);t.copyTo(b,{format:"f32-planar",planeIndex:m,frameOffset:i,frameCount:s}),u.push(b)}r.insert(n,u),t.close()}#b(t,e){t>e||this.#e.mutate(n=>{for(let i of n)if(t<=i.end+1&&e>=i.start){i.start=f.Milli.min(i.start,t),i.end=f.Milli.max(i.end,e);return}n.push({start:t,end:e}),n.sort((i,s)=>i.start-s.start)})}#w(t){this.#e.mutate(e=>{for(;e.length>0&&e[e.length-1].start>=t;)e.pop();let n=e[e.length-1];n&&n.end>t&&(n.end=t)})}#y(t){this.#e.mutate(e=>{for(;e.length>0;){if(e[0].end>=t){e[0].start=f.Milli.max(e[0].start,t);break}e.shift()}})}reset(){this.#n?.reset()}#u(t){return this.#s.update(t)?(this.#n?.reset(),this.sync.reset(),!0):!1}close(){this.#o.close()}static supported=Yt};async function Yt(t){if(!y.containerSupported(t.container)){let n=t.container.kind==="unknown"?t.container.raw.kind:t.container.kind;return console.warn(`audio: ignoring rendition with unknown container: ${n}`),!1}t.codec==="opus"&&!v.Opus.supportsRate(t.sampleRate)&&console.warn(`audio: opus advertised at ${t.sampleRate}Hz, which some browsers cannot decode`);let e;if(t.codec!=="opus"){if(t.description)e=v.Hex.toBytes(t.description);else if(t.container.kind==="cmaf")try{e=g.Cmaf.decodeInitSegment(j(t.container.init)).description}catch(n){return console.warn(`audio: malformed CMAF init segment for codec ${t.codec}`,n),!1}}return(await AudioDecoder.isConfigSupported({...t,description:e})).supported??!1}var V=.001,$=.2,rt=class{source;in;#t={enabled:new d(!1)};out=L(this.#t);#e=new R;#n=new d(void 0);constructor(t,e){this.source=t,this.in={volume:w(e?.volume??.5),muted:w(e?.muted??!1),paused:w(e?.paused??!1)},this.#e.run(n=>{let i=!n.get(this.in.paused)&&!n.get(this.in.muted);this.#t.enabled.set(i)}),this.#e.run(n=>{let i=n.get(this.source.out.root);if(!i)return;let s=new GainNode(i.context,{gain:n.get(this.in.volume)});i.connect(s),n.set(this.#n,s),n.run(a=>{a.get(this.#t.enabled)&&(s.connect(i.context.destination),a.cleanup(()=>s.disconnect()))})}),this.#e.run(n=>{let i=n.get(this.#n);if(!i)return;n.cleanup(()=>i.gain.cancelScheduledValues(i.context.currentTime));let s=n.get(this.in.volume);s<V?(i.gain.exponentialRampToValueAtTime(V,i.context.currentTime+$),i.gain.setValueAtTime(0,i.context.currentTime+$+.01)):i.gain.exponentialRampToValueAtTime(s,i.context.currentTime+$)})}close(){this.#e.close()}},Ut=128,ot=class{in;#t={catalog:new d(void 0),available:new d({}),track:new d(void 0),config:new d(void 0),jitter:new d(void 0)};out=L(this.#t);#e=new R;constructor(t){this.in={broadcast:w(t?.broadcast),target:w(t?.target),supported:w(t?.supported)},this.#e.run(this.#n.bind(this)),this.#e.run(this.#i.bind(this)),this.#e.run(this.#s.bind(this))}#n(t){let e=t.get(this.in.broadcast);if(!e)return;let n=t.get(e.out.catalog)?.audio;n&&t.set(this.#t.catalog,n)}#i(t){let e=t.get(this.#t.catalog)?.renditions??{},n=t.get(this.in.supported);n&&t.spawn(async()=>{let i={},s=t.cancel.then(()=>{});for(let[a,r]of Object.entries(e)){let o=await Promise.race([n(r),s]);if(t.abort.aborted)return;o&&(i[a]=r)}Object.keys(i).length===0&&Object.keys(e).length>0&&console.warn("no supported audio renditions found:",e),this.#t.available.set(i)})}#s(t){let e=t.get(this.#t.available);if(Object.keys(e).length===0)return;let n=t.get(this.in.target),i;if(n?.name&&n.name in e)i={track:n.name,config:e[n.name]};else if(i=this.#a(e),!i)return;t.set(this.#t.track,i.track),t.set(this.#t.config,i.config);let s=(i.config.jitter??Kt(i.config)??0)+Math.ceil(Ut/i.config.sampleRate*1e3);t.set(this.#t.jitter,f.Milli(s))}#a(t){let e=Object.entries(t);if(e.length!==0){for(let[n,i]of e)if(i.container.kind==="legacy")return{track:n,config:i};for(let[n,i]of e)if(i.container.kind==="loc")return{track:n,config:i};for(let[n,i]of e)if(i.container.kind==="cmaf")return{track:n,config:i}}}close(){this.#e.close()}};function Kt(t){if(t.codec.startsWith("opus"))return 20;if(t.codec.startsWith("mp4a"))return Math.ceil(1024/t.sampleRate*1e3);if(t.codec==="mp3"){let e=t.sampleRate>=32e3?1152:576;return Math.ceil(e/t.sampleRate*1e3)}}var Vt=48e3,q=2;function qt(t){let e="";for(let n=0;n<t.length;n++)e+=t[n].toString(16).padStart(2,"0");return e}function ct(t){let e;try{e=t.initData?j(t.initData):void 0}catch{e=void 0}let n=e?qt(e):void 0;switch(t.packaging){case"cmaf":return!t.initData||!e?void 0:{container:{kind:"cmaf",init:t.initData},description:void 0};case"loc":return{container:{kind:"loc"},description:n};case"legacy":return{container:{kind:"legacy"},description:n};default:return}}function Jt(t){if(!t.codec)return;let e=ct(t);if(!e)return;let{container:n,description:i}=e;return{codec:t.codec,container:n,description:i,codedWidth:t.width==null?void 0:O(t.width),codedHeight:t.height==null?void 0:O(t.height),framerate:t.framerate,bitrate:t.bitrate==null?void 0:O(t.bitrate),stalled:t.stalled,jitter:t.jitter==null?void 0:O(t.jitter)}}function Gt(t){if(!t.codec)return;let e=(()=>{if(!t.channelConfig)return q;let a=Number.parseInt(t.channelConfig,10);return Number.isFinite(a)?a:q})(),n=ct(t);if(!n)return;let{container:i,description:s}=n;return{codec:t.codec,container:i,description:s,sampleRate:O(t.samplerate??Vt),numberOfChannels:O(e),bitrate:t.bitrate==null?void 0:O(t.bitrate),jitter:t.jitter==null?void 0:O(t.jitter)}}function Qt(t){let e={},n={};for(let s of t.tracks)if(s.role==="video"){let a=Jt(s);a&&(e[s.name]=a)}else if(s.role==="audio"){let a=Gt(s);a&&(n[s.name]=a)}let i={};return Object.keys(e).length>0&&(i.video={renditions:e}),Object.keys(n).length>0&&(i.audio={renditions:n}),i}var J=new WeakSet;function G(t){return!t.discovery&&(J.has(t)||(J.add(t),console.warn("relay does not support broadcast discovery; subscribing to siblings blind.")),!0)}function Q(t,e){return Object.fromEntries(Object.entries(t).filter(([,n])=>e(n.broadcast)))}function Xt(t,e){return{...t,video:t.video?{...t.video,renditions:Q(t.video.renditions,e)}:void 0,audio:t.audio?{...t.audio,renditions:Q(t.audio.renditions,e)}:void 0}}var lt=[...y.FORMATS,"hangz","manual"];function Zt(t){if(t!==null)return lt.find(e=>e===t)}var te=class{in;#t={status:new d("offline"),active:new d(void 0),catalog:new d(void 0)};out=L(this.#t);#e=new d(void 0);#n=new d(!1);#i=new d(void 0);#s=new R;constructor(t){this.in={connection:w(t?.connection),name:w(t?.name??H.empty()),enabled:w(t?.enabled??!1),reload:w(t?.reload??!0),catalogFormat:w(t?.catalogFormat),catalog:w(t?.catalog)},this.#s.run(this.#a.bind(this)),this.#s.run(this.#l.bind(this)),this.#s.run(this.#c.bind(this)),this.#s.run(this.#r.bind(this))}#a(t){if(this.#e.set(void 0),!t.get(this.#n)||!t.get(this.in.reload))return;let e=t.get(this.in.connection);if(!e||G(e))return;let n=e.announced(H.empty());t.cleanup(()=>n.close()),this.#e.set(new Set),t.spawn(async()=>{for(;;){let i=await Promise.race([t.cancel,n.next()]);if(!i)break;this.#e.mutate(s=>{s&&(i.active?s.add(i.path):s.delete(i.path))})}})}#r(t){let e=t.get(this.#i);t.set(this.#t.catalog,e?Xt(e,n=>this.#h(t,n)!==void 0):void 0)}#o(t,e){if(!t.get(this.in.reload))return!0;let n=t.get(this.in.connection);if(!n||G(n))return!0;this.#n.set(!0);let i=t.get(this.#e);return i?i.has(e):!1}#l(t){if(!t.get(this.in.enabled))return;let e=t.get(this.in.connection);if(!e)return;let n=t.get(this.in.name);if(!t.get(this.in.reload)){let s=e.consume(n);t.cleanup(()=>s.close()),t.set(this.#t.active,s,void 0);return}let i=e.announcedBroadcast(n);t.cleanup(()=>i.close()),t.run(s=>{s.set(this.#t.active,s.get(i.active),void 0)})}#c(t){if(!t.get(this.in.enabled))return;let e=t.get(this.in.catalogFormat),n=t.get(this.in.name),i=e??y.detectFormat(n)??y.DEFAULT_FORMAT;if(i==="manual"){let c=t.get(this.in.catalog);this.#i.set(c,!0),t.cleanup(()=>this.#i.set(void 0,!0)),this.#t.status.set(c?"live":"loading");return}let s=t.get(this.out.active);if(!s)return;this.#t.status.set("loading");let a=i==="hang"?y.TRACK:i==="hangz"?y.TRACK_COMPRESSED:"catalog",r=s.track(a).subscribe({priority:y.PRIORITY.catalog});t.cleanup(()=>r.close());let o;if(i==="hang"||i==="hangz"){let c=new tt.Snapshot.Consumer(r,{schema:y.RootSchema,compression:i==="hangz"});o=()=>c.next()}else o=async()=>{let c=await et.fetch(r);return c?Qt(c):void 0};t.spawn(async()=>{try{for(;;){let c=await Promise.race([t.cancel,o()]);if(!c)break;console.debug("received catalog",i,this.in.name.peek(),c),this.#i.set(c,!0),this.#t.status.set("live")}}catch(c){console.warn("error fetching catalog",this.in.name.peek(),c)}finally{this.#i.set(void 0),this.#t.status.set("offline")}})}#h(t,e){if(!e)return{local:!0};let n=t.get(this.in.name),i=H.tryResolve(n,e);if(i!==void 0){if(i===n)return{local:!0};if(this.#o(t,i))return{local:!1,path:i}}}relativeBroadcast(t,e){let n=this.#h(t,e);if(!n)return;if(n.local)return t.get(this.out.active);if(!t.get(this.in.enabled))return;let i=t.get(this.in.connection);if(!i)return;let s=i.consume(n.path);return t.cleanup(()=>s.close()),s}close(){this.#s.close()}},ht=Symbol("supportCacheKey");function dt(t){return{broadcast:t.broadcast,decoder:{codec:t.codec,container:t.container,description:t.description,displayAspectWidth:t.displayAspectWidth,displayAspectHeight:t.displayAspectHeight,optimizeForLatency:t.optimizeForLatency??!0}}}function ee(t){return JSON.stringify(dt(t).decoder)}var ne=f.Milli(100);function X(t){if(t.jitter!==void 0)return f.Milli(t.jitter);if(t.framerate)return f.Milli(Math.ceil(1e3/t.framerate))}function ie(t){return t.active===void 0||f.Milli.add(t.playhead,ne)>=t.active}function ut(t=0){let e=(t%360+360)%360;return Math.round(e/90)%4*90}function ft(t,e=0){let n=ut(e);return n===90||n===270?{width:t.height,height:t.width}:{width:t.width,height:t.height}}function P(t){return Object.is(t,-0)?0:t}function se(t,e){let[n,i,s,a,r,o]=t;return[P(-n),P(i),P(-s),P(a),P(e-r),P(o)]}function ae(t,e){let n=ut(e?.rotation),i=ft(t,n),s;switch(n){case 90:s=[0,1,-1,0,t.width,0];break;case 180:s=[-1,0,0,-1,t.width,t.height];break;case 270:s=[0,-1,1,0,0,t.height];break;default:s=[1,0,0,1,0,0]}return e?.flip&&(s=se(s,t.width)),{matrix:s,source:i}}var re=f.Milli(500),mt=class{in;source;sync;#t={frame:new d(void 0),timestamp:new d(void 0),display:new d(void 0),stalled:new d(!1),stats:new d(void 0),buffered:new d([])};out=L(this.#t);#e=new d(void 0);#n;#i=new R;#s(){this.#t.frame.update(t=>{t?.close()}),this.#t.timestamp.set(void 0)}constructor(t,e,n){this.in={enabled:w(n?.enabled??!1),paced:w(n?.paced??!0)},this.source=t,this.sync=e,this.#n=this.#i.computed(i=>{let s=i.get(this.source.out.config);return s?dt(s):void 0}),this.#i.run(this.#a.bind(this)),this.#i.run(this.#r.bind(this)),this.#i.run(this.#o.bind(this)),this.#i.run(this.#l.bind(this))}#a(t){let e=t.getAll([this.in.enabled,this.source.in.broadcast,this.source.out.track,this.#n]);if(!e){this.#e.set(void 0);return}let[n,i,s,a]=e,r=i.relativeBroadcast(t,a.broadcast);if(!r){this.#e.set(void 0),this.#s(),this.#t.buffered.set([]);return}let o=new oe({sync:this.sync,paced:this.in.paced,broadcast:r,track:s,config:a.decoder,stats:this.#t.stats});t.cleanup(()=>o?.close()),t.run(c=>{if(!o)return;let l=c.get(this.#e);if(l){let h=c.get(o.timestamp);if(h===void 0||!ie({playhead:h,active:c.get(l.timestamp)}))return}this.#e.set(o),o=void 0,c.close()})}#r(t){let e=t.get(this.#e);if(!e){this.#t.buffered.set([]);return}t.cleanup(()=>e.close()),t.run(n=>{let i=n.get(e.frame);this.#t.frame.update(s=>(s?.close(),i?.clone()))}),t.proxy(this.#t.timestamp,e.timestamp),t.proxy(this.#t.buffered,e.buffered)}#o(t){let e=t.get(this.source.out.catalog);if(!e)return;let n=e.display;if(n){t.set(this.#t.display,{width:n.width,height:n.height});return}let i=t.get(this.#t.frame);i&&t.set(this.#t.display,ft({width:i.displayWidth,height:i.displayHeight},e.rotation))}#l(t){if(t.get(this.in.enabled)){if(!t.get(this.#t.frame)){this.#t.stalled.set(!0);return}this.#t.stalled.set(!1),t.timer(()=>{this.#t.stalled.set(!0)},re)}}close(){this.#s(),this.#i.close()}static supported=pt},oe=class{sync;paced;broadcast;track;config;stats;timestamp=new d(void 0);frame=new d(void 0);buffered=new d([]);#t=new d([]);#e=new d(f.Milli.zero);#n=0;#i=new R;constructor(t){this.sync=t.sync,this.paced=t.paced,this.broadcast=t.broadcast,this.track=t.track,this.config=t.config,this.stats=t.stats,this.#i.run(e=>{let n=e.get(this.paced);this.#e.set(n?e.get(this.sync.out.buffer):f.Milli.zero)}),this.#i.run(this.#s.bind(this))}#s(t){let e=this.broadcast.track(this.track).subscribe({priority:y.PRIORITY.video});t.cleanup(()=>e.close());let n=new VideoDecoder({output:async i=>{try{let s=this.#n,a=f.Milli.fromMicro(i.timestamp);if(a<(this.timestamp.peek()??0)||this.paced.peek()&&(this.sync.out.reference.peek()===void 0||(this.frame.peek()===void 0&&this.frame.set(i.clone()),!await this.#l(a,t))||s!==this.#n||a<(this.timestamp.peek()??0)))return;this.timestamp.set(a),this.#h(a),this.frame.update(r=>(r?.close(),i.clone()))}finally{i.close()}},error:i=>{console.error(i),t.close()}});t.cleanup(()=>{n.state!=="closed"&&n.close()}),this.config.container.kind==="cmaf"?this.#r(t,e,n):this.#a(t,e,n)}#a(t,e,n){let i=this.config.container.kind==="loc"?new g.Loc.Format:new g.Legacy.Format,s=new g.Consumer(e,{format:i,latency:this.#e});t.cleanup(()=>s.close()),t.run(r=>{let o=r.get(s.buffered),c=r.get(this.#t);this.buffered.update(()=>g.mergeBufferedRanges(o,c))}),n.configure({codec:this.config.codec,description:this.config.description?v.Hex.toBytes(this.config.description):void 0,displayAspectWidth:this.config.displayAspectWidth,displayAspectHeight:this.config.displayAspectHeight,optimizeForLatency:this.config.optimizeForLatency,flip:!1});let a;t.spawn(async()=>{for(;;){let r=await s.next();if(!r)break;this.#o(r.discontinuity)&&(a=void 0);let{frame:o}=r;if(!o)continue;let c=f.Milli.fromMicro(o.timestamp);this.sync.received(c,"video");let l=new EncodedVideoChunk({type:o.keyframe?"key":"delta",data:o.payload,timestamp:o.timestamp});this.stats.update(h=>({frameCount:(h?.frameCount??0)+1,bytesReceived:(h?.bytesReceived??0)+o.payload.byteLength})),a!==void 0&&r.continuous&&this.#c(f.Milli.fromMicro(a),f.Milli.fromMicro(o.timestamp)),a=o.timestamp,n.decode(l)}})}#r(t,e,n){let i=this.config.container;if(i.kind!=="cmaf")return;let s=j(i.init),a=g.Cmaf.decodeInitSegment(s),r=this.config.description?v.Hex.toBytes(this.config.description):a.description,o=new g.Consumer(e,{format:new g.Cmaf.Format(a),latency:this.#e});t.cleanup(()=>o.close()),t.run(l=>{let h=l.get(o.buffered),u=l.get(this.#t);this.buffered.update(()=>g.mergeBufferedRanges(h,u))}),n.configure({codec:this.config.codec,description:r,displayAspectWidth:this.config.displayAspectWidth,displayAspectHeight:this.config.displayAspectHeight,optimizeForLatency:this.config.optimizeForLatency,flip:!1});let c;t.spawn(async()=>{for(;;){let l=await o.next();if(!l)break;this.#o(l.discontinuity)&&(c=void 0);let{frame:h}=l;if(!h)continue;let u=f.Milli.fromMicro(h.timestamp);if(this.sync.received(u,"video"),this.stats.update(m=>({frameCount:(m?.frameCount??0)+1,bytesReceived:(m?.bytesReceived??0)+h.payload.byteLength})),c!==void 0&&l.continuous&&this.#c(f.Milli.fromMicro(c),f.Milli.fromMicro(h.timestamp)),c=h.timestamp,n.state==="closed")break;n.decode(new EncodedVideoChunk({type:h.keyframe?"key":"delta",data:h.payload,timestamp:h.timestamp}))}})}#o(t){return t!==this.#n&&(this.#n=t,this.timestamp.set(void 0),this.#t.set([]),this.sync.reset(),!0)}async#l(t,e){let n;try{let i=new Promise(a=>{n=this.paced.changed(()=>a(!this.paced.peek()))}),s=this.sync.wait(t).then(()=>!0);return await Promise.race([s,i,e.cancel])??!1}finally{n?.()}}#c(t,e){t>e||this.#t.mutate(n=>{for(let i of n)if(i.start<=e&&i.end>=t){i.start=f.Milli.min(i.start,t),i.end=f.Milli.max(i.end,e);return}n.push({start:t,end:e}),n.sort((i,s)=>i.start-s.start)})}#h(t){this.#t.mutate(e=>{for(;e.length>0;){if(e[0].end>=t){e[0].start=f.Milli.max(e[0].start,t);break}e.shift()}})}close(){this.#i.close(),this.frame.update(t=>{t?.close()})}};async function pt(t){if(!y.containerSupported(t.container)){let i=t.container.kind==="unknown"?t.container.raw.kind:t.container.kind;return console.warn(`video: ignoring rendition with unknown container: ${i}`),!1}let e;if(t.description)e=v.Hex.toBytes(t.description);else if(t.container.kind==="cmaf")try{e=g.Cmaf.decodeInitSegment(j(t.container.init)).description}catch(i){return console.warn(`video: malformed CMAF init segment for codec ${t.codec}`,i),!1}let{supported:n}=await VideoDecoder.isConfigSupported({codec:t.codec,description:e,displayAspectWidth:t.displayAspectWidth,displayAspectHeight:t.displayAspectHeight,optimizeForLatency:t.optimizeForLatency??!0});if(n)return!0;if(t.codec.startsWith("avc3.")){let i=`avc1.${t.codec.slice(5)}`;if((await VideoDecoder.isConfigSupported({codec:i,description:e,displayAspectWidth:t.displayAspectWidth,displayAspectHeight:t.displayAspectHeight,optimizeForLatency:t.optimizeForLatency??!0})).supported)return t.codec=i,!0}return!1}Object.assign(pt,{[ht]:ee});var Z=.01,gt=class{decoder;in;#t={frame:new d(void 0),timestamp:new d(void 0),visible:new d(!1)};out=L(this.#t);#e=new d(void 0);#n=new R;constructor(t,e){this.decoder=t,this.in={canvas:w(e?.canvas),visible:w(e?.visible??"20%")},this.#n.run(n=>{let i=n.get(this.in.canvas);this.#e.set(i?.getContext("2d")??void 0)}),this.#n.run(this.#s.bind(this)),this.#n.run(this.#a.bind(this)),this.#n.run(this.#i.bind(this))}#i(t){let e=t.getAll([this.in.canvas,this.decoder.out.display]);if(!e)return;let[n,i]=e;(n.width!==i.width||n.height!==i.height)&&(n.width=i.width,n.height=i.height)}#s(t){let e=t.get(this.in.visible);if(e==="never"){this.#t.visible.set(!1);return}if(e==="always"){this.#t.visible.set(!0),t.cleanup(()=>this.#t.visible.set(!1));return}let n=t.get(this.in.canvas);if(!n){this.#t.visible.set(!1);return}let i=!1,s=()=>{this.#t.visible.set(i&&!document.hidden)},a=o=>{for(let c of o)i=c.isIntersecting,s()},r;try{r=new IntersectionObserver(a,{threshold:Z,rootMargin:e})}catch{console.warn(`moq-watch: invalid visible margin "${e}", using "0px"`),r=new IntersectionObserver(a,{threshold:Z})}s(),t.event(document,"visibilitychange",s),r.observe(n),t.cleanup(()=>r.disconnect()),t.cleanup(()=>this.#t.visible.set(!1))}#a(t){let e=t.get(this.#e);if(!e)return;let n=t.get(this.decoder.out.frame),i=t.get(this.decoder.source.out.catalog),s=requestAnimationFrame(()=>{this.#r(e,n,i),n?(this.#t.frame.update(a=>(a?.close(),n.clone())),this.#t.timestamp.set(f.Milli.fromMicro(n.timestamp))):(this.#t.frame.update(a=>{a?.close()}),this.#t.timestamp.set(void 0)),s=void 0});t.cleanup(()=>{s!==void 0&&cancelAnimationFrame(s)})}#r(t,e,n){if(!e){t.fillStyle="#000",t.fillRect(0,0,t.canvas.width,t.canvas.height);return}if(t.save(),t.fillStyle="#000",t.fillRect(0,0,t.canvas.width,t.canvas.height),!n?.rotation)n?.flip&&(t.scale(-1,1),t.translate(-t.canvas.width,0)),t.drawImage(e,0,0,t.canvas.width,t.canvas.height);else{let i=ae(t.canvas,n);t.setTransform(...i.matrix),t.drawImage(e,0,0,i.source.width,i.source.height)}t.restore()}close(){this.#t.frame.update(t=>{t?.close()}),this.#t.timestamp.set(void 0),this.#n.close()}};function ce(t){return e=>{let n=[],i=[];for(let[s,a]of e)if(a.codedWidth&&a.codedHeight){let r=a.codedWidth*a.codedHeight;r<=t?n.push({name:s,size:r}):i.push({name:s,size:r})}return n.sort((s,a)=>a.size-s.size),n.length>0?n.map(s=>s.name):i.length>0?(i.sort((s,a)=>s.size-a.size),[i[0].name]):e.map(([s])=>s)}}function bt(t,e){return n=>{let i=[],s=[];for(let[a,r]of n){if(!r.codedWidth||!r.codedHeight)continue;let o=r.codedWidth*r.codedHeight,c=t==null||r.codedWidth<=t,l=e==null||r.codedHeight<=e;c&&l?i.push({name:a,size:o}):s.push({name:a,size:o})}return i.sort((a,r)=>r.size-a.size),i.length>0?i.map(a=>a.name):s.length>0?(s.sort((a,r)=>a.size-r.size),[s[0].name]):n.map(([a])=>a)}}function wt(t){return e=>{let n=[],i=[];for(let[s,a]of e)a.bitrate!=null&&a.bitrate<=t?n.push({name:s,bitrate:a.bitrate}):a.bitrate!=null&&i.push({name:s,bitrate:a.bitrate});return n.sort((s,a)=>a.bitrate-s.bitrate),n.length>0?n.map(s=>s.name):i.length>0?(i.sort((s,a)=>s.bitrate-a.bitrate),[i[0].name]):e.map(([s])=>s)}}function le(t){let e=t[0];for(let n of t){let[,i]=n,[,s]=e,a=(i.codedWidth??0)*(i.codedHeight??0),r=(s.codedWidth??0)*(s.codedHeight??0);if(a!==r){a>r&&(e=n);continue}(i.bitrate??0)>(s.bitrate??0)&&(e=n)}return e[0]}function he(t){let e=Object.entries(t).filter(([,a])=>!a.stalled);if(e.length>0)return Object.fromEntries(e);let n=Object.entries(t);if(n.length===0)return{};let i=wt(0)(n),s=i.length===1?i[0]:bt(0,0)(n)[0];return{[s]:t[s]}}var yt=class{in;#t={catalog:new d(void 0),available:new d({}),error:new d(void 0),track:new d(void 0),config:new d(void 0),jitter:new d(void 0)};out=L(this.#t);#e=new R;#n=new WeakMap;constructor(t){this.in={broadcast:w(t?.broadcast),target:w(t?.target),supported:w(t?.supported)},this.#e.run(this.#i.bind(this)),this.#e.run(this.#s.bind(this)),this.#e.run(this.#a.bind(this))}#i(t){let e=t.get(this.in.broadcast);if(!e)return;let n=t.get(e.out.catalog)?.video;n&&t.set(this.#t.catalog,n)}#s(t){let e=t.get(this.in.supported);if(!e){this.#t.error.set(void 0);return}let n=t.get(this.#t.catalog)?.renditions??{};this.#t.error.set(void 0);let i=this.#n.get(e);i||(i=new Map,this.#n.set(e,i));let s=new Set(Object.keys(n));for(let a of i.keys())s.has(a)||i.delete(a);t.spawn(async()=>{let a={},r=t.cancel.then(()=>{});for(let[c,l]of Object.entries(n)){let h=e[ht],u=h?h(l):JSON.stringify(l),m=i.get(c),b=!1;if(m?.key===u)b=m.supported;else{let x=!1;try{b=await Promise.race([e(l),r])}catch(M){x=!0,console.warn(`[Source] video rendition ${c} (${l.codec}) support probe failed; treating as unsupported`,M)}!x&&b!==void 0&&i.set(c,{key:h?h(l):JSON.stringify(l),supported:b})}if(t.abort.aborted)return;b&&(a[c]=l)}let o=Object.keys(a).length===0&&Object.keys(n).length>0?"unsupported":void 0;o==="unsupported"&&console.warn("[Source] No supported video renditions found:",n),this.#t.error.set(o),this.#t.available.set(a)})}#a(t){let e=he(t.get(this.#t.available));if(Object.keys(e).length===0)return;let n=t.get(this.in.target);if(n?.name&&n.name in e){let r=e[n.name];t.set(this.#t.track,n.name),t.set(this.#t.config,r),t.set(this.#t.jitter,X(r));return}let i=n;if(!n?.bitrate){let r=t.get(this.in.broadcast),o=r?t.get(r.in.connection):void 0,c=o&&t.get(o.probe).estimatedRecvRate;if(c!=null){let l=Math.round(c*.8);i={...n,bitrate:l}}}let s=this.#r(e,i);if(!s)return;let a=e[s];t.set(this.#t.track,s),t.set(this.#t.config,a),t.set(this.#t.jitter,X(a))}#r(t,e){let n=Object.entries(t);if(n.length===0)return;if(n.length===1)return n[0][0];let i=[];if(e?.pixels!=null&&i.push(ce(e.pixels)),(e?.width!=null||e?.height!=null)&&i.push(bt(e.width,e.height)),e?.bitrate!=null&&i.push(wt(e.bitrate)),i.length===0)return le(n);let s=i.map(r=>r(n)),a=s.map(r=>new Set(r));for(let r of s[0])if(a.every(o=>o.has(r)))return r;console.warn("conflicting rendition filters, no rendition satisfies all criteria")}close(){this.#e.close()}};import*as Pe from"../../hang@^0.4.2.target-es2022.mjs";import*as We from"../../net@^0.3.4.target-es2022.mjs";import*as _e from"../../signals@^0.2.3.target-es2022.mjs";var vt=Object.defineProperty,Mt=(t,e)=>{let n={};for(var i in t)vt(n,i,{get:t[i],enumerable:!0});return e||vt(n,Symbol.toStringTag,{value:"Module"}),n},je=Mt({Decoder:()=>at,Emitter:()=>rt,Source:()=>ot}),Fe=Mt({Decoder:()=>mt,Renderer:()=>gt,Source:()=>yt});export{je as Audio,te as Broadcast,lt as CATALOG_FORMATS,Pe as Hang,We as Net,_e as Signals,St as Sync,Fe as Video,z as latencyBounds,xt as latencyFromBounds,Zt as parseCatalogFormat};
//# sourceMappingURL=watch.mjs.map