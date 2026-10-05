/* esm.sh - @moq/watch@0.6.2/player-DqpNnBDT */
import{Announce as bt,Error as _,Path as W,Time as h}from"../../net@^0.4.2.target-es2022.mjs";import{Effect as M,Signal as u,getter as m,readonlys as E}from"../../signals@^0.2.5.target-es2022.mjs";import*as b from"../../hang@^0.5.2/catalog.target-es2022.mjs";import{u53 as I}from"../../hang@^0.5.2/catalog.target-es2022.mjs";import*as y from"../../hang@^0.5.2/container.target-es2022.mjs";import*as w from"../../hang@^0.5.2/util.target-es2022.mjs";import*as tt from"../../json@^0.4.2.target-es2022.mjs";import*as et from"../../msf@^0.3.1.target-es2022.mjs";import{CaptionsRenderer as yt,VTTCue as wt,parseText as vt}from"../../../media-captions@0.0.18/es2022/media-captions.mjs";function F(t){let e=atob(t),i=new Uint8Array(e.length);for(let n=0;n<e.length;n++)i[n]=e.charCodeAt(n);return i}function $(t,e){if(t.get(e.broadcast.closed)!==void 0)return;let i=e.broadcast.track(e.track).subscribe({priority:e.priority,maxAge:e.maxAge.peek()});return t.cleanup(()=>i.close()),t.run(n=>{i.update({priority:e.priority,maxAge:n.get(e.maxAge)})}),i}async function P(t){try{return await t.next()}catch(e){if(!(e instanceof _.Stream))throw e;console.debug("media subscription ended",e);return}}var k=0,z=1,C=2,B=3,At=4,Mt=4294967295n;function O(t,e){return BigInt(t>>>0)<<32n|BigInt(e>>>0)}function S(t){return Number(t>>32n)|0}function kt(t){return!!(S(t)&1)}function x(t){return Number(t&Mt)|0}function xt(t){return t<=1?1:1<<32-Math.clz32(t-1)}function it(t,e,i,n=!1){if(t<=0)throw Error("invalid channels");if(e<=0||e>2**30)throw Error("invalid capacity");if(i<=0)throw Error("invalid sample rate");e=xt(e);let s=new SharedArrayBuffer(t*e*Float32Array.BYTES_PER_ELEMENT),a=new SharedArrayBuffer(At*Int32Array.BYTES_PER_ELEMENT),r=new SharedArrayBuffer(BigInt64Array.BYTES_PER_ELEMENT),o=new Int32Array(a);return Atomics.store(o,C,1),{channels:t,capacity:e,rate:i,samples:s,control:a,state:r,buffered:n}}function Y(t,e){return(t-e|0)>0?t:e}function j(t,e){return t&e-1}var Rt=class nt{channels;capacity;rate;buffered;init;#t;#e;#i;#n=!1;#s=0;#a=0;#r=0;constructor(e,i){this.channels=e.channels,this.capacity=e.capacity,this.rate=e.rate,this.buffered=e.buffered,this.init=e,this.#t=new Int32Array(e.control),this.#e=new BigInt64Array(e.state),this.#i=[];for(let n=0;n<this.channels;n++)this.#i.push(new Float32Array(e.samples,n*this.capacity*Float32Array.BYTES_PER_ELEMENT,this.capacity));i!==void 0&&this.#o(i)}#o(e){if(e.channels!==this.channels||e.rate!==this.rate)return;let i=Atomics.load(e.#t,B),n=Atomics.load(e.#e,0);for(;;){let s=Atomics.load(this.#e,0);if(Atomics.load(this.#t,B)!==i||(x(n)-x(s)|0)<=0)return;let a=O(S(s),x(n));if(Atomics.compareExchange(this.#e,0,s,a)===s)return}}#c(e){for(;;){let i=Atomics.load(this.#e,0);if((e-x(i)|0)<=0)return;let n=O(S(i),e);if(Atomics.compareExchange(this.#e,0,i,n)===i)return}}#l(e){for(;;){let i=Atomics.load(this.#e,0),n=O(S(i)+e|0,x(i));if(Atomics.compareExchange(this.#e,0,i,n)===i)return}}insert(e,i){if(i.length!==this.channels)throw Error("wrong number of channels");let n=Math.round(h.Second.fromMicro(e)*this.rate),s=i[0].length,a=0;if(!this.#n){this.#s=n;let p=S(Atomics.load(this.#e,0));Atomics.add(this.#t,B,1),Atomics.store(this.#e,0,O(p+2|0,0)),Atomics.store(this.#t,k,0),this.#n=!0,this.#a=0,this.#r=0}n=n-this.#s|0;let r=n+s|0,o=x(Atomics.load(this.#e,0)),c=o-n|0;if(c>0){if(c>=s)return;a=c,n=n+c|0}let l=s-a;(r-o|0)>this.capacity&&this.#c(r-this.capacity|0);let d=Atomics.load(this.#t,k),f=n-d|0;if(f>0){let p=Math.min(f,this.capacity);for(let g=0;g<this.channels;g++){let v=this.#i[g];for(let A=0;A<p;A++)v[j(d+A|0,this.capacity)]=0}}for(let p=0;p<this.channels;p++){let g=i[p],v=this.#i[p];for(let A=0;A<l;A++)v[j(n+A|0,this.capacity)]=g[a+A]}Atomics.store(this.#t,k,Y(Atomics.load(this.#t,k),r)),this.#h()}#h(){let e=x(Atomics.load(this.#e,0)),i=Atomics.load(this.#t,k),n=Atomics.load(this.#t,z);(i-e|0)>=n&&n>0&&Atomics.store(this.#t,C,0)}read(e){let i=Atomics.load(this.#e,0);if(Atomics.load(this.#t,C)===1||kt(i))return 0;let n=x(i),s=Atomics.load(this.#t,k),a=Atomics.load(this.#t,z),r=s-n|0;if(!this.buffered&&a>0&&r>a){let d=s-a|0;(d-n|0)>0&&(n=d)}let o=s-n|0,c=Math.min(o,e[0].length);if(c<=0)return(n-x(i)|0)>0&&Atomics.compareExchange(this.#e,0,i,O(S(i),n)),0;for(let d=0;d<this.channels;d++){let f=this.#i[d],p=e[d];for(let g=0;g<c;g++)p[g]=f[j(n+g|0,this.capacity)]}let l=O(S(i),n+c|0);if(Atomics.compareExchange(this.#e,0,i,l)!==i){for(let d=0;d<this.channels;d++)e[d].fill(0,0,c);return 0}return c}setLatency(e){let i=Atomics.exchange(this.#t,z,e);i>0&&e>i&&(Atomics.store(this.#t,C,1),this.#l(2)),this.#h()}truncate(e){let i=Math.round(h.Second.fromMicro(e)*this.rate)-this.#s|0;if(!((Atomics.load(this.#t,k)-i|0)<=0)){for(this.#l(1);;){let n=Atomics.load(this.#t,k),s=Y(i,x(Atomics.load(this.#e,0)));if((n-s|0)<=0||Atomics.compareExchange(this.#t,k,n,s)===n)break}this.#l(1)}}reset(){this.#n=!1,Atomics.store(this.#t,C,1);let e=Atomics.load(this.#t,k),i=Atomics.load(this.#e,0);Atomics.store(this.#e,0,O(S(i),e))}resize(e){let i=it(this.channels,e,this.rate,this.buffered),n=new nt(i);n.#n=this.#n,n.#s=this.#s;let s=Atomics.load(this.#e,0),a=x(s),r=Atomics.load(this.#t,k),o=Atomics.load(this.#t,z),c=Atomics.load(this.#t,C),l=r-a|0,d=Math.max(0,Math.min(l,n.capacity)),f=r-d|0;for(let p=0;p<this.channels;p++){let g=this.#i[p],v=n.#i[p];for(let A=0;A<d;A++){let R=f+A|0;v[j(R,n.capacity)]=g[j(R,this.capacity)]}}return Atomics.store(n.#t,B,Atomics.load(this.#t,B)),Atomics.store(n.#e,0,O(S(s),f)),Atomics.store(n.#t,k,r),Atomics.store(n.#t,z,o),Atomics.store(n.#t,C,c),n.#a=this.#d(a)+(f-a|0),n.#r=f,n}#d(e){return this.#a+=e-this.#r|0,this.#r=e,this.#a}#u(){return this.#d(x(Atomics.load(this.#e,0)))}get timestamp(){return h.Micro.fromSecond((this.#s+this.#u())/this.rate)}get stalled(){return Atomics.load(this.#t,C)===1}get length(){return Atomics.load(this.#t,k)-x(Atomics.load(this.#e,0))|0}},st=class{#t;#e;#i=[];constructor(t,e){this.#t=t,this.#e=e}setHeadroom(t){this.#e=t}wait(t,e){return!this.#t||e>=(t-this.#e|0)?Promise.resolve():new Promise(i=>this.#i.push({timestamp:t,resolve:i}))}advance(t){this.#i.length!==0&&(this.#i=this.#i.filter(({timestamp:e,resolve:i})=>t<(e-this.#e|0)||(i(),!1)))}flush(){for(let{resolve:t}of this.#i)t();this.#i=[]}};function D(t,e){return h.Micro.fromSecond(t/e)}function Et(){return!(typeof SharedArrayBuffer>"u"||typeof crossOriginIsolated<"u"&&!crossOriginIsolated)}function Tt(t,e,i,n,s=!1){return Et()?(console.log("[audio] using SharedArrayBuffer audio buffer"),new St(t,e,i,n,s)):(console.warn("[audio] SharedArrayBuffer unavailable, falling back to the higher latency postMessage audio buffer. Serve the page cross-origin isolated (Cross-Origin-Opener-Policy: same-origin, Cross-Origin-Embedder-Policy: require-corp) to avoid this."),new It(t,e,i,n,s))}var St=class{rate;channels;#t;#e;#i=new u(0);timestamp=this.#i;#n=new u(!0);stalled=this.#n;#s;#a=new M;constructor(t,e,i,n,s){this.#t=t,this.channels=e,this.rate=i;let a=Math.max(i,n*2);this.#s=new st(s,D(n,i));let r=it(e,a,i,s);this.#e=new Rt(r),this.#e.setLatency(n);let o={type:"init-shared",...r};t.port.postMessage(o),this.#a.interval(()=>{let c=this.#e.stalled;this.#i.set(this.#e.timestamp),this.#n.set(c),c?this.#s.flush():this.#s.advance(this.#e.timestamp)},50)}insert(t,e){this.#e.insert(t,e)}setLatency(t){if(this.#s.setHeadroom(D(t,this.rate)),this.#e.setLatency(t),this.#e.capacity<t*1.5){let e=Math.max(this.rate,t*2);this.#e=this.#e.resize(e);let i={type:"init-shared",...this.#e.init};this.#t.port.postMessage(i)}}truncate(t){this.#e.truncate(t)}reset(){this.#e.reset(),this.#s.flush()}wait(t){return this.#e.stalled?Promise.resolve():this.#s.wait(t,this.#e.timestamp)}close(){this.#s.flush(),this.#a.close()}},It=class{rate;channels;#t;#e=new u(0);timestamp=this.#e;#i=new u(!0);stalled=this.#i;#n;#s=new M;constructor(t,e,i,n,s){this.#t=t,this.channels=e,this.rate=i,this.#n=new st(s,D(n,i));let a={type:"init-post",channels:e,rate:i,latency:h.Milli.fromSecond(n/i),buffered:s};t.port.postMessage(a),this.#s.event(t.port,"message",r=>{let o=r.data;o?.type==="state"&&(this.#e.set(o.timestamp),this.#i.set(o.stalled),o.stalled?this.#n.flush():this.#n.advance(o.timestamp))}),t.port.start()}insert(t,e){let i={type:"data",data:e,timestamp:t};this.#t.port.postMessage(i,e.map(n=>n.buffer))}setLatency(t){this.#n.setHeadroom(D(t,this.rate));let e={type:"latency",latency:h.Milli.fromSecond(t/this.rate)};this.#t.port.postMessage(e)}truncate(t){let e={type:"truncate",timestamp:t};this.#t.port.postMessage(e)}reset(){this.#t.port.postMessage({type:"reset"}),this.#n.flush()}wait(t){return this.#i.peek()?Promise.resolve():this.#n.wait(t,this.#e.peek())}close(){this.#n.flush(),this.#s.close()}},Ot=128,Ct=20,Lt=1024,zt=1152,Bt=576,jt=32e3;function at(t){return{codec:t.codec,container:t.container,description:t.description,sampleRate:t.sampleRate,numberOfChannels:t.numberOfChannels}}function Nt(t){return{broadcast:t.broadcast,decoder:at(t)}}function Ft(t){/* KASTR-PATCH: catalog-delay-cap */let w=Wt(t)??0,e=Math.min((t.jitter||w)??0,Math.max(w,40)),i=Math.ceil(Ot/t.sampleRate*1e3);return h.Milli(e+i)}function Wt(t){if(t.codec.startsWith("opus"))return Ct;if(t.codec.startsWith("mp4a"))return Math.ceil(Lt/t.sampleRate*1e3);if(t.codec==="mp3"){let e=t.sampleRate>=jt?zt:Bt;return Math.ceil(e/t.sampleRate*1e3)}}var _t=class{#t=!1;#e=!1;opened(){this.#t&&(this.#e=!0),this.#t=!0}takeover(){let t=this.#e;return this.#e=!1,t}},Pt=128;function V(t,e){return Math.max(Pt,Math.ceil(t*h.Second.fromMilli(e)))}var Dt=new Blob([`var __defProp = Object.defineProperty;
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
    const latencySamples = Math.ceil(this.rate * time_exports.Second.fromMilli(latency));
    if (latencySamples > this.#latencySamples) this.#stalled = true;
    this.#latencySamples = latencySamples;
    const newCapacity = this.#capacityFor(this.#latencySamples);
    if (newCapacity !== this.capacity) this.#reallocate(newCapacity);
    if (latencySamples > 0 && this.length >= latencySamples) this.#stalled = false;
  }
  #reallocate(newCapacity) {
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
   * Step the epoch by \`by\`, leaving the playhead wherever the reader has taken it.
   *
   * Retries while the word changes under it: only the epoch half is the writer's to move.
   */
  #step(by) {
    for (; ; ) {
      const state = Atomics.load(this.#state, 0);
      const next = pack(epochOf(state) + by | 0, readOf(state));
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
    this.#resume();
  }
  // Un-stall once the buffered data covers LATENCY.
  #resume() {
    const read = readOf(Atomics.load(this.#state, 0));
    const write = Atomics.load(this.#control, WRITE);
    const latency = Atomics.load(this.#control, LATENCY);
    if ((write - read | 0) >= latency && latency > 0) {
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
  /**
   * Update the target latency in samples. Main thread only.
   *
   * A deeper floor parks playback until it refills. Video holds the extra delay on its own, so
   * audio that kept draining at the old depth would run ahead by the difference. Parking keeps
   * what is buffered, so a rise costs only its own size in silence, and none if the buffer
   * already covers the new floor.
   */
  setLatency(samples) {
    const previous = Atomics.exchange(this.#control, LATENCY, samples);
    if (previous > 0 && samples > previous) {
      Atomics.store(this.#control, STALLED, 1);
      this.#step(2);
    }
    this.#resume();
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
    this.#step(1);
    for (; ; ) {
      const write = Atomics.load(this.#control, WRITE);
      const clamped = i32Max(target, readOf(Atomics.load(this.#state, 0)));
      if ((write - clamped | 0) <= 0) break;
      if (Atomics.compareExchange(this.#control, WRITE, write, clamped) === write) break;
    }
    this.#step(1);
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
`],{type:"application/javascript"}),Ht=URL.createObjectURL(Dt),$t=class{#t=0;#e;#i;#n;#s=0;#a;get end(){return this.#e}clear(t=0){this.#t=0,this.#e=void 0,this.#s=t,this.#r()}update(t){let e=t.discontinuity!==this.#t;return e&&(this.#t=t.discontinuity,this.#e=void 0,this.#r()),t.frame&&t.group!==this.#i&&(this.#e=void 0),t.frame&&this.#n===void 0&&(this.#n=t.frame.timestamp),t.end!==void 0&&(this.#e=t.end,this.#i=t.group),e}span(t){let e=this.#n??t.timestamp;this.#n=e;let i=Math.floor(this.#s*t.sampleRate/48e3),n=this.#a??i,s=Math.min(n,t.numberOfFrames);this.#a=n-s;let a=Math.round(i*1e6/t.sampleRate),r=Math.max(e,t.timestamp-a),o=t.numberOfFrames-s;if(this.#e!==void 0)if(this.#e<=r)o=0;else{let c=this.#e-r,l=Math.round(c*t.sampleRate/1e6);o=Math.min(o,l)}return{timestamp:r,frameOffset:s,frames:o}}#r(){this.#n=void 0,this.#a=void 0}},Yt=class{#t;constructor(t){this.#t=t}drop(){return this.#t!==0&&(this.#t--,!0)}},Vt=3,U=class{in;source;sync;#t={context:new u(void 0),root:new u(void 0),sampleRate:new u(void 0),stats:new u(void 0),timestamp:new u(void 0),stalled:new u(!0),buffered:new u([])};out=E(this.#t);#e=new u([]);#i;#n=new u(void 0);#s=new $t;#a=new _t;#r=new M;#o;#c;constructor(t){this.in={enabled:m(t?.enabled??!0)},this.source=t.source,this.sync=t.sync,this.#r.cleanup(this.sync.register(this.source.out.jitter)),this.#o=this.#r.computed(e=>{let i=e.get(this.source.out.config);return i?Nt(i):void 0}),this.#c=this.#r.computed(e=>{let i=e.get(this.source.out.config);return i?at(i):void 0}),this.#r.run(this.#l.bind(this)),this.#r.run(this.#h.bind(this)),this.#r.run(this.#d.bind(this)),this.#r.run(this.#u.bind(this))}#l(t){let e=t.get(this.#c);if(!e)return;let i=t.get(this.#n)??e.sampleRate,n=e.numberOfChannels;t.set(this.#t.sampleRate,i);let s=new AudioContext({latencyHint:"interactive",sampleRate:i});t.set(this.#t.context,s),t.cleanup(()=>s.close()),t.spawn(async()=>{if(!await t.race(s.audioWorklet.addModule(Ht).then(()=>!0)))return;let a=new AudioWorkletNode(s,"render",{channelCount:n,channelCountMode:"explicit",outputChannelCount:[n]});t.cleanup(()=>a.disconnect());let r=this.sync.out.delay.peek(),o=V(i,r),c=this.sync.out.buffered.peek(),l=Tt(a,n,i,o,c);this.#i=l,t.cleanup(()=>{l.close(),this.#i=void 0}),t.run(d=>{let f=h.Milli.fromMicro(d.get(l.timestamp));this.#t.timestamp.set(f),this.#w(f)}),t.run(d=>{this.#t.stalled.set(d.get(l.stalled))}),t.set(this.#t.root,a)})}#h(t){if(!t.get(this.in.enabled))return;if(t.get(this.sync.in.delay)==="instant"){this.reset();return}let e=t.get(this.#t.context);e&&w.Gesture.unlock(t,e)}#d(t){if(!t.get(this.#t.root))return;let e=this.#i;if(!e)return;let i=t.get(this.sync.out.delay);e.setLatency(V(e.rate,i))}#u(t){if(!t.get(this.in.enabled)||t.get(this.sync.in.delay)==="instant")return;/* KASTR-PATCH: audio-maxage-floor */this.kastrAudioMaxAge=new u(Math.max(Number(this.sync.out.maxAge.peek())||0,1e3));let e=t.get(this.source.in.broadcast);if(!e)return;let i=t.get(this.source.out.track);if(!i)return;let n=t.get(this.#o);if(!n)return;let s=n.decoder,a=e.relativeBroadcast(t,n.broadcast);if(!a)return;this.#a.opened();let r=$(t,{broadcast:a,track:i,priority:b.PRIORITY.audio,maxAge:this.kastrAudioMaxAge});r&&(s.container.kind==="cmaf"?this.#g(t,r,s):this.#m(t,r,s))}#m(t,e,i){let n=i.codec==="opus"&&i.description?w.Opus.preSkip(w.Hex.toBytes(i.description)):0;this.#s.clear(n);let s=i.container.kind==="loc"?new y.Loc.Format("audio"):new y.Legacy.Format(i),a=new y.Consumer(e,{format:s,maxAge:this.kastrAudioMaxAge});t.cleanup(()=>a.close()),t.run(r=>{let o=r.get(a.buffered),c=r.get(this.#e);this.#t.buffered.update(()=>y.mergeBufferedRanges(o,c))}),t.spawn(async()=>{if(!await w.Libav.polyfill())return;let r=new Yt(Vt),o=new AudioDecoder({output:d=>{let f=this.#s.span(d);if(r.drop()){d.close();return}this.#f(d,f)},error:d=>console.error("audio decoder error",d)});t.cleanup(()=>{o.state!=="closed"&&o.close()});let c=i.codec==="opus"?void 0:i.description?w.Hex.toBytes(i.description):void 0,l={codec:i.codec,sampleRate:i.sampleRate,numberOfChannels:i.numberOfChannels,description:c};for(o.configure(l);;){let d=await P(a);if(!d)break;if(this.#p(d)&&(o.reset(),o.configure(l)),d.end!==void 0)continue;let{frame:f}=d;if(!f)continue;let p=h.Milli.fromMicro(f.timestamp);this.sync.received(p,"audio"),this.#t.stats.update(v=>({bytesReceived:(v?.bytesReceived??0)+f.payload.byteLength})),await this.#i?.wait(f.timestamp);let g=new EncodedAudioChunk({type:f.keyframe?"key":"delta",data:f.payload,timestamp:f.timestamp});if(o.state==="closed")break;o.decode(g)}})}#g(t,e,i){if(i.container.kind!=="cmaf")return;let n=F(i.container.init),s=y.Cmaf.decodeInitSegment(n),a=i.description?w.Hex.toBytes(i.description):s.description,r=i.codec==="opus"&&a?w.Opus.preSkip(a):0;this.#s.clear(r);let o=i.codec==="opus"?void 0:i.description?w.Hex.toBytes(i.description):s.description,c=new y.Consumer(e,{format:new y.Cmaf.Format(s),maxAge:this.kastrAudioMaxAge});t.cleanup(()=>c.close()),t.run(l=>{let d=l.get(c.buffered),f=l.get(this.#e);this.#t.buffered.update(()=>y.mergeBufferedRanges(d,f))}),t.spawn(async()=>{if(!await w.Libav.polyfill())return;let l=new AudioDecoder({output:f=>this.#f(f),error:f=>console.error("audio decoder error",f)});t.cleanup(()=>{l.state!=="closed"&&l.close()});let d={codec:i.codec,sampleRate:i.sampleRate,numberOfChannels:i.numberOfChannels,description:o};for(l.configure(d);;){let f=await P(c);if(!f)break;this.#p(f)&&(l.reset(),l.configure(d));let{frame:p}=f;if(!p)continue;let g=h.Milli.fromMicro(p.timestamp);if(this.sync.received(g,"audio"),this.#t.stats.update(v=>({bytesReceived:(v?.bytesReceived??0)+p.payload.byteLength})),await this.#i?.wait(p.timestamp),l.state==="closed")break;l.decode(new EncodedAudioChunk({type:p.keyframe?"key":"delta",data:p.payload,timestamp:p.timestamp}))}})}#f(t,e=this.#s.span(t)){let{timestamp:i,frameOffset:n,frames:s}=e,a=h.Milli.fromMicro(i);if(s===0){t.close();return}let r=this.#i;if(!r){t.close();return}if(t.sampleRate!==r.rate){this.#n.set(t.sampleRate),t.close();return}let o=s/t.sampleRate*1e6,c=h.Milli.fromMicro(o),l=h.Milli.add(a,c);this.#a.takeover()&&(r.truncate(i),this.#y(a)),this.#b(a,l);let d=Math.min(t.numberOfChannels,r.channels),f=[];for(let p=0;p<d;p++){let g=new Float32Array(s);t.copyTo(g,{format:"f32-planar",planeIndex:p,frameOffset:n,frameCount:s}),f.push(g)}r.insert(i,f),t.close()}#b(t,e){t>e||this.#e.mutate(i=>{for(let n of i)if(t<=n.end+1&&e>=n.start){n.start=h.Milli.min(n.start,t),n.end=h.Milli.max(n.end,e);return}i.push({start:t,end:e}),i.sort((n,s)=>n.start-s.start)})}#y(t){this.#e.mutate(e=>{for(;e.length>0&&e[e.length-1].start>=t;)e.pop();let i=e[e.length-1];i&&i.end>t&&(i.end=t)})}#w(t){this.#e.mutate(e=>{for(;e.length>0;){if(e[0].end>=t){e[0].start=h.Milli.max(e[0].start,t);break}e.shift()}})}reset(){this.#i?.reset()}#p(t){return this.#s.update(t)?(this.#i?.reset(),this.sync.reset(),!0):!1}close(){this.#r.close()}static supported=Ut};async function Ut(t){if(!b.containerSupported(t.container)){let i=t.container.kind==="unknown"?t.container.raw.kind:t.container.kind;return console.warn(`audio: ignoring rendition with unknown container: ${i}`),!1}t.codec==="opus"&&!w.Opus.supportsRate(t.sampleRate)&&console.warn(`audio: opus advertised at ${t.sampleRate}Hz, which some browsers cannot decode`);let e;if(t.codec!=="opus"){if(t.description)e=w.Hex.toBytes(t.description);else if(t.container.kind==="cmaf")try{e=y.Cmaf.decodeInitSegment(F(t.container.init)).description}catch(i){return console.warn(`audio: malformed CMAF init segment for codec ${t.codec}`,i),!1}}return(await AudioDecoder.isConfigSupported({...t,description:e})).supported??!1}var K=.001,H=.2,Kt=class{source;in;#t={enabled:new u(!1)};out=E(this.#t);#e=new M;#i=new u(void 0);constructor(t){this.source=t.source,this.in={volume:m(t?.volume??.5),muted:m(t?.muted??!1),paused:m(t?.paused??!1)},this.#e.run(e=>{let i=!e.get(this.in.paused)&&!e.get(this.in.muted);this.#t.enabled.set(i)}),this.#e.run(e=>{let i=e.get(this.source.out.root);if(!i)return;let n=new GainNode(i.context,{gain:e.get(this.in.volume)});i.connect(n),e.set(this.#i,n),e.run(s=>{s.get(this.#t.enabled)&&(n.connect(i.context.destination),s.cleanup(()=>n.disconnect()))})}),this.#e.run(e=>{let i=e.get(this.#i);if(!i)return;e.cleanup(()=>i.gain.cancelScheduledValues(i.context.currentTime));let n=e.get(this.in.volume);n<K?(i.gain.exponentialRampToValueAtTime(K,i.context.currentTime+H),i.gain.setValueAtTime(0,i.context.currentTime+H+.01)):i.gain.exponentialRampToValueAtTime(n,i.context.currentTime+H)})}close(){this.#e.close()}},qt=class{in;#t={catalog:new u(void 0),available:new u({}),track:new u(void 0),config:new u(void 0),jitter:new u(void 0)};out=E(this.#t);#e=new M;constructor(t){this.in={broadcast:m(t?.broadcast),target:m(t?.target),supported:m(t?.supported)},this.#e.run(this.#i.bind(this)),this.#e.run(this.#n.bind(this)),this.#e.run(this.#s.bind(this))}#i(t){let e=t.get(this.in.broadcast);if(!e)return;let i=t.get(e.out.catalog)?.audio;i&&t.set(this.#t.catalog,i)}#n(t){let e=t.get(this.#t.catalog)?.renditions??{},i=t.get(this.in.supported);i&&t.spawn(async()=>{let n={};for(let[s,a]of Object.entries(e)){let r=await t.race(i(a));if(t.abort.aborted)return;r&&(n[s]=a)}Object.keys(n).length===0&&Object.keys(e).length>0&&console.warn("no supported audio renditions found:",e),this.#t.available.set(n)})}#s(t){let e=t.get(this.#t.available);if(Object.keys(e).length===0)return;let i=t.get(this.in.target),n;if(i?.name&&i.name in e)n={track:i.name,config:e[i.name]};else if(n=this.#a(e),!n)return;t.set(this.#t.track,n.track),t.set(this.#t.config,n.config),t.set(this.#t.jitter,Ft(n.config))}#a(t){let e=Object.entries(t);if(e.length!==0){for(let[i,n]of e)if(n.container.kind==="legacy")return{track:i,config:n};for(let[i,n]of e)if(n.container.kind==="loc")return{track:i,config:n};for(let[i,n]of e)if(n.container.kind==="cmaf")return{track:i,config:n}}}close(){this.#e.close()}},Gt=48e3,q=2;function Jt(t){let e="";for(let i=0;i<t.length;i++)e+=t[i].toString(16).padStart(2,"0");return e}function rt(t){let e;try{e=t.initData?F(t.initData):void 0}catch{e=void 0}let i=e?Jt(e):void 0;switch(t.packaging){case"cmaf":return!t.initData||!e?void 0:{container:{kind:"cmaf",init:t.initData},description:void 0};case"loc":return{container:{kind:"loc"},description:i};case"legacy":return{container:{kind:"legacy"},description:i};default:return}}function ot(t){if(!(t<=0))return I(Math.ceil(t))}function Xt(t){if(!t.codec)return;let e=rt(t);if(!e)return;let{container:i,description:n}=e;return{codec:t.codec,container:i,description:n,codedWidth:t.width==null?void 0:I(t.width),codedHeight:t.height==null?void 0:I(t.height),framerate:t.framerate,bitrate:t.bitrate==null?void 0:I(t.bitrate),stalled:t.stalled,jitter:t.jitter==null?void 0:I(t.jitter),delay:t.delay==null?void 0:ot(t.delay)}}function Qt(t){if(!t.codec)return;let e=(()=>{if(!t.channelConfig)return q;let a=Number.parseInt(t.channelConfig,10);return Number.isFinite(a)?a:q})(),i=rt(t);if(!i)return;let{container:n,description:s}=i;return{codec:t.codec,container:n,description:s,sampleRate:I(t.samplerate??Gt),numberOfChannels:I(e),bitrate:t.bitrate==null?void 0:I(t.bitrate),jitter:t.jitter==null?void 0:I(t.jitter),delay:t.delay==null?void 0:ot(t.delay)}}function Zt(t){let e={},i={};for(let s of t.tracks)if(s.role==="video"){let a=Xt(s);a&&(e[s.name]=a)}else if(s.role==="audio"){let a=Qt(s);a&&(i[s.name]=a)}let n={};return Object.keys(e).length>0&&(n.video={renditions:e}),Object.keys(i).length>0&&(n.audio={renditions:i}),n}function N(t,e){return Object.fromEntries(Object.entries(t).filter(([,i])=>e(i.broadcast)))}function te(t,e){return{...t,video:t.video?{...t.video,renditions:N(t.video.renditions,e)}:void 0,audio:t.audio?{...t.audio,renditions:N(t.audio.renditions,e)}:void 0,text:t.text?{...t.text,renditions:N(t.text.renditions,e)}:void 0,json:t.json?{...t.json,tracks:N(t.json.tracks,e)}:void 0,binary:t.binary?{...t.binary,tracks:N(t.binary.tracks,e)}:void 0}}var ze=[...b.FORMATS,"hangz","manual"],ee=class{in;#t={status:new u("offline"),active:new u(void 0),catalog:new u(void 0)};out=E(this.#t);#e=new u(void 0);#i=new u(!1);#n=new u(void 0);#s;constructor(t){if(t&&"reload"in t)throw Error("Watch.Broadcast: `reload` was renamed to `announced`");this.#s=new M,this.in={origin:m(t?.origin),name:m(t?.name??W.empty()),enabled:m(t?.enabled??!0),announced:m(t?.announced??!0),catalogFormat:m(t?.catalogFormat),catalog:m(t?.catalog)},this.#s.run(this.#a.bind(this)),this.#s.run(this.#l.bind(this)),this.#s.run(this.#h.bind(this)),this.#s.run(this.#r.bind(this))}#a(t){if(this.#e.set(void 0),!t.get(this.#i)||!t.get(this.in.announced))return;let e=t.get(this.in.origin);if(!e)return;let i=e.announced();t.cleanup(()=>i.close()),this.#e.set(new Set),t.spawn(async()=>{for(;;){let n=await t.race(i.next());if(!n)break;this.#e.mutate(s=>{s&&(bt.isActive(n.kind)?s.add(n.prefix):s.delete(n.prefix))})}})}#r(t){let e=t.get(this.#n);t.set(this.#t.catalog,e?te(e,i=>this.#d(t,i)!==void 0):void 0)}#o(t,e){this.#i.set(!0);let i=t.get(this.#e);if(!i)return!1;if(i.has(e))return!0;for(let n of i)if(W.hasPrefix(n,e))return!0;return!1}#c(t,e,i){let n=e.request(i);return t.cleanup(()=>n.close()),t.get(n.active)}#l(t){if(!t.get(this.in.enabled))return;let e=t.get(this.in.origin);if(!e)return;let i=t.get(this.in.name);if(!t.get(this.in.announced)){t.set(this.#t.active,this.#c(t,e,i),void 0);return}let n=e.request(i,{announced:!0});t.cleanup(()=>n.close()),t.run(s=>{s.set(this.#t.active,s.get(n.active),void 0)})}#h(t){if(!t.get(this.in.enabled))return;let e=t.get(this.in.catalogFormat),i=t.get(this.in.name),n=e??b.detectFormat(i)??b.DEFAULT_FORMAT;if(n==="manual"){let c=t.get(this.in.catalog),l;try{l=c&&b.checkResolvable(b.checkRenditions(c),i)}catch(d){console.error("rejecting catalog",i,d)}this.#n.set(l,!0),t.cleanup(()=>this.#n.set(void 0,!0)),this.#t.status.set(l?"live":"loading");return}let s=t.get(this.out.active);if(!s||t.get(s.closed)!==void 0)return;this.#t.status.set("loading");let a=n==="hang"?b.TRACK:n==="hangz"?b.TRACK_COMPRESSED:"catalog",r=s.track(a).subscribe({priority:b.PRIORITY.catalog});t.cleanup(()=>r.close());let o;if(n==="hang"||n==="hangz"){let c=new tt.Snapshot.Consumer({track:r,schema:b.RootSchema,compression:n==="hangz"?"deflate":"none"});o=()=>c.next()}else{let c=r.ordered();o=async()=>{let l=await et.fetch(c);return l?Zt(l):void 0}}t.spawn(async()=>{try{for(;;){let c=await t.race(o());if(!c)break;console.debug("received catalog",n,this.in.name.peek(),c),this.#n.set(b.checkResolvable(b.checkRenditions(c),i),!0),this.#t.status.set("live")}}catch(c){c instanceof _.Stream?console.debug("catalog subscription ended",this.in.name.peek(),c):console.error("error fetching catalog",this.in.name.peek(),c)}finally{this.#n.set(void 0),this.#t.status.set("offline")}})}#d(t,e){if(!e)return{local:!0};let i=t.get(this.in.name),n=W.tryResolve(i,e);if(n===void 0){console.warn("ignoring rendition: broadcast reference escapes the root",i,e);return}if(n===i)return{local:!0};let s=t.get(this.in.origin);if(!s||!(t.get(this.in.announced)&&t.get(s.discovery)!==!1&&!this.#o(t,n)))return{local:!1,path:n}}relativeBroadcast(t,e){let i=this.#d(t,e);if(!i)return;if(i.local)return t.get(this.out.active);if(!t.get(this.in.enabled))return;let n=t.get(this.in.origin);if(n)return this.#c(t,n,i.path)}close(){this.#s.close()}},ie=h.Milli(20),G=h.Milli(100),ne=class ct{in;#t={reference:new u(void 0),delay:new u(h.Milli.zero),jitter:new u(G),timestamp:new u(void 0),buffered:new u(!1),maxAge:new u(h.Milli.zero)};out=E(this.#t);#e=new Map;#i;#n=new u([]);#s=new M;constructor(e){this.in={delay:m(e?.delay??"auto"),buffer:m(e?.buffer??h.Milli.zero),probe:m(e?.probe)},this.#s.run(this.#r.bind(this)),this.#s.run(this.#o.bind(this)),this.#s.run(this.#a.bind(this))}register(e){let i={jitter:e};return this.#n.update(n=>[...n,i]),()=>this.#n.update(n=>n.filter(s=>s!==i))}#a(e){let i=e.get(this.#t.delay),n=e.get(this.in.delay)==="instant"?h.Milli.zero:e.get(this.in.buffer);this.#t.buffered.set(n>0),this.#t.maxAge.set(h.Milli.add(i,n))}#r(e){let i=e.get(this.in.delay);if(i==="instant"){this.#i=void 0,this.#t.jitter.set(h.Milli.zero);return}if(typeof i=="number"){this.#i=void 0,this.#t.jitter.set(i);return}let n=e.get(this.in.probe)?.rtt;if(n!==void 0){this.#i=this.#i===void 0?n:Math.min(this.#i,n);let s=h.Milli(Math.max(ie,this.#i*1.25));this.#t.jitter.set(s);return}this.#i=void 0,this.#t.jitter.set(G)}#o(e){let i=e.get(this.#t.jitter),n=h.Milli.zero;for(let a of e.get(this.#n))n=h.Milli.max(n,e.get(a.jitter)??h.Milli.zero);let s=e.get(this.in.delay)==="instant"?h.Milli.zero:h.Milli.add(n,i);this.#t.delay.set(s)}received(e,i=""){this.#t.timestamp.update(l=>l===void 0||e>l?e:l);let n=h.Milli.now(),s=h.Milli.sub(n,e),a=this.#t.reference.peek();if(a===void 0){this.#t.reference.set(s);return}let r=this.#t.delay.peek(),o=h.Milli.add(h.Milli.sub(a,s),r);if(o<0){let l=this.#e.get(i);l?(l.count++,l.maxMs=Math.max(l.maxMs,-o)):this.#e.set(i,{count:1,maxMs:-o})}else{let l=this.#e.get(i);if(l){let d=i?`sync[${i}]`:"sync",f=ct.#l(l.maxMs);console.debug(`${d}: ${l.count} late frame(s), max ${f} behind`),this.#e.delete(i)}}if(s>=a)return;let c=this.#t.maxAge.peek();o<=c||this.#t.reference.set(h.Milli.add(s,h.Milli.sub(c,r)))}reset(){this.#t.reference.set(void 0),this.#e.clear()}now(){let e=this.#t.reference.peek();if(e!==void 0)return h.Milli.sub(h.Milli.sub(h.Milli.now(),e),this.#t.delay.peek())}async wait(e){if(this.in.delay.peek()!=="instant"){if(this.#t.reference.peek()===void 0)throw Error("reference not set; call received() first");for(;;){if(this.in.delay.peek()==="instant")return;let i=h.Milli.now(),n=h.Milli.sub(i,e),s=this.#t.reference.peek();if(s===void 0)return;let a=h.Milli.add(h.Milli.sub(s,n),this.#t.delay.peek());if(a<=0||a<5||await this.#c(a))return}}}#c(e){return new Promise(i=>{let n=r=>{clearTimeout(s);for(let o of a)o();i(r)},s=setTimeout(()=>n(!0),e),a=[this.in.delay.changed(()=>n(!1)),this.#t.delay.changed(()=>n(!1)),this.#t.reference.changed(()=>n(!1))]})}static#l(e){if(e=Math.round(e),e<1e3)return`${e}ms`;let i=e/1e3;if(i<60)return`${Math.round(i*10)/10}s`;let n=i/60;return`${Math.round(n*10)/10}m`}close(){this.#s.close()}},se=`:where([part=captions]){--overlay-padding:1%;--cue-color:white;--cue-bg-color:#000c;--cue-font-size:calc(var(--overlay-height) / 100 * 5);--cue-line-height:calc(var(--cue-font-size) * 1.2);--cue-padding-x:calc(var(--cue-font-size) * .6);--cue-padding-y:calc(var(--cue-font-size) * .4);z-index:1;contain:content;margin:var(--overlay-padding);font-size:var(--cue-font-size);box-sizing:border-box;pointer-events:none;user-select:none;word-spacing:normal;word-break:break-word;font-family:sans-serif;position:absolute;inset:0}:where([part=captions]>[part=cue-display]){contain:content;top:var(--cue-top);left:var(--cue-left);right:var(--cue-right);bottom:var(--cue-bottom);width:var(--cue-width,auto);height:var(--cue-height,auto);box-sizing:border-box;transform:var(--cue-transform);text-align:var(--cue-text-align);writing-mode:var(--cue-writing-mode,unset);white-space:pre-line;direction:ltr;unicode-bidi:plaintext;min-width:min-content;min-height:min-content;position:absolute;overflow:visible}:where([data-dir=rtl] [part=cue-display]){direction:rtl}:where([part=captions] [part=cue]){padding:var(--cue-padding-y) var(--cue-padding-x);line-height:var(--cue-line-height);background-color:var(--cue-bg-color);box-sizing:border-box;color:var(--cue-color);box-shadow:var(--cue-box-shadow);white-space:var(--cue-white-space,pre-wrap);outline:var(--cue-outline);text-shadow:var(--cue-text-shadow);display:inline-block}:where([part=captions] [part=cue-display][data-vertical] [part=cue]){padding:var(--cue-padding-x) var(--cue-padding-y)}
:where([part=captions] [part=region]){width:var(--region-width);height:var(--region-height);min-height:0;max-height:var(--region-height);writing-mode:horizontal-tb;top:calc(var(--region-top,var(--overlay-height) * var(--region-viewport-anchor-y) / 100 - var(--region-height) * var(--region-anchor-y) / 100));left:var(--region-left,calc(calc(var(--region-viewport-anchor-x) * 1%) - calc(var(--region-width) * var(--region-anchor-x) / 100)));right:var(--region-right);bottom:var(--region-bottom);overflow-wrap:break-word;box-sizing:border-box;flex-flow:column;justify-content:flex-start;display:inline-flex;position:absolute;overflow:hidden}:where([part=captions] [part=region][data-scroll=up]){justify-content:end}:where([part=captions] [part=region][data-active][data-scroll=up]){transition:top .433s}:where([part=captions] [part=region]>[part=cue-display]){width:auto;left:var(--cue-offset);height:var(--cue-height,auto);text-align:var(--cue-text-align);unicode-bidi:plaintext;margin-top:1px;position:relative}:where([part=captions] [part=region] [part=cue]){padding:calc(var(--cue-padding-y) / 2) var(--cue-padding-x);border-radius:0;position:relative}`,ae=h.Milli(3e4),re=h.Milli(3e4),oe=h.Milli(1e3);function J(t){return t.replaceAll("&","&amp;amp;").replaceAll("<","&amp;lt;").replaceAll(">","&amp;gt;").replaceAll('"',"&amp;quot;")}function X(t,e){let i=t.length;for(;i>0&&t[i-1].startTime>e.startTime;)i--;t.splice(i,0,e)}function ce(t,e){let{cues:i,clears:n}=t,s=0;for(let r of n)r>=e&&(n[s++]=r);n.length=s;let a=0;for(let r of i)r.endTime>=e&&(i[a++]=r);return a!==i.length&&(i.length=a,!0)}function le(t,e){let{cues:i,clears:n}=t,s=i.indexOf(e),a=s>0?i[s-1]:void 0;a&&a.endTime>e.startTime&&(a.endTime=e.startTime);let r=i[s+1];r&&e.endTime>r.startTime&&(e.endTime=r.startTime);let o=n.find(c=>c>e.startTime);o!==void 0&&e.endTime>o&&(e.endTime=o)}function he(t,e){let{cues:i,clears:n}=t,s=n.length;for(;s>0&&n[s-1]>e;)s--;n[s]!==e&&n.splice(s,0,e);for(let a=i.length-1;a>=0;a--){let r=i[a];if(!(r.startTime>e)){r.endTime>e&&(r.endTime=e);return}}}var de=class{source;sync;in;#t=new M;#e=!1;constructor(t){this.source=t.source,this.sync=t.sync,this.in={container:m(t?.container),enabled:m(t?.enabled??!0)},this.#t.run(this.#i.bind(this))}#i(t){let e=t.getAll([this.in.enabled,this.in.container,this.source.out.track,this.source.out.config,this.source.in.broadcast]);if(!e)return;let[i,n,s,a,r]=e,o=r.relativeBroadcast(t,a.broadcast);if(!o)return;this.#e=!1;let c;if(a.container.kind==="legacy")c=new y.Legacy.Format("data");else if(a.container.kind==="loc")c=new y.Loc.Format;else{console.warn(`captions: unsupported container "${a.container.kind}" for track ${s}`);return}let l=document.createElement("style");l.textContent=se,n.appendChild(l),t.cleanup(()=>l.remove());let d=document.createElement("div");d.style.position="absolute",d.style.inset="0",d.style.pointerEvents="none",n.appendChild(d),t.cleanup(()=>d.remove());let f=new yt(d);t.cleanup(()=>f.destroy());let p=$(t,{broadcast:o,track:s,priority:b.PRIORITY.text,maxAge:this.sync.out.maxAge});if(!p)return;let g={cues:[],regions:new Map,clears:[]},v=()=>f.changeTrack({cues:[...g.cues],regions:[...g.regions.values()]}),A=()=>{let R=this.sync.now();R!==void 0&&(f.currentTime=R/1e3,ce(g,(R-ae)/1e3)&&v()),t.animate(A)};t.animate(A),t.spawn(async()=>{for(;;){let R=await p.recvGroup().catch(T=>{if(!(T instanceof _.Stream))throw T;console.debug("captions subscription ended",T)});if(!R)break;t.spawn(async()=>{try{for(;;){let T=await R.readFrame();if(!T)break;for(let gt of c.decode(T.payload))await this.#n(a.format,gt,g)}}catch(T){if(!(T instanceof _.Stream))throw T}finally{R.close()}v()})}})}async#n(t,e,i){let n=new TextDecoder().decode(e.payload),s=e.timestamp/1e6;if(t==="utf8"){if(n.length===0){he(i,s);return}let o=new wt(s,s+re/1e3,J(n));X(i.cues,o),le(i,o);return}if(n.length===0)return;let a;try{a=await vt(n,{type:"vtt"})}catch(o){console.warn("captions: failed to parse VTT cue",o);return}let r=a.cues.at(0);!this.#e&&r&&Math.abs(r.startTime-s)>oe/1e3&&(this.#e=!0,console.warn(`captions: cue timing is ${(r.startTime-s).toFixed(3)}s off its frame timestamp; the payload must carry absolute times on the media clock`));for(let o of a.regions)i.regions.set(o.id,o);for(let o of a.cues)o.text=J(o.text),X(i.cues,o)}close(){this.#t.close()}},ue=new Set(["vtt","utf8"]);function fe(t){return ue.has(t.format)}var pe=class{in;#t={catalog:new u(void 0),available:new u({}),track:new u(void 0),config:new u(void 0)};out=E(this.#t);#e=new M;constructor(t){this.in={broadcast:m(t?.broadcast),target:m(t?.target)},this.#e.run(this.#i.bind(this)),this.#e.run(this.#n.bind(this))}#i(t){let e=t.get(this.in.broadcast),i=e?t.get(e.out.catalog)?.text:void 0;t.set(this.#t.catalog,i),this.#t.available.set(i?.renditions??{})}#n(t){let e=t.get(this.#t.available),i=t.get(this.in.target),n=i?e[i]:void 0;if(!i||!n){t.set(this.#t.track,void 0),t.set(this.#t.config,void 0);return}fe(n)||console.warn(`captions: unsupported format ${JSON.stringify(n.format)} for track ${i}`),t.set(this.#t.track,i),t.set(this.#t.config,n)}close(){this.#e.close()}},lt=Symbol("supportCacheKey");function ht(t){return{broadcast:t.broadcast,decoder:{codec:t.codec,container:t.container,description:t.description,displayAspectWidth:t.displayAspectWidth,displayAspectHeight:t.displayAspectHeight,optimizeForLatency:t.optimizeForLatency??!0}}}function me(t){return JSON.stringify(ht(t).decoder)}var ge=h.Milli(100);function be(t){/* KASTR-PATCH: catalog-delay-cap */let f=t.framerate?Math.ceil(1e3/t.framerate):void 0,j=t.jitter===void 0?f:Math.min(Number(t.jitter)||0,f??100);return j===void 0?void 0:h.Milli(j)}function ye(t){return t.active===void 0||h.Milli.add(t.playhead,ge)>=t.active}function we(t){return t.active===void 0?t.pending:t.pending===void 0?t.active:h.Milli.max(t.active,t.pending)}function dt(t=0){let e=(t%360+360)%360;return Math.round(e/90)%4*90}function ut(t,e=0){let i=dt(e);return i===90||i===270?{width:t.height,height:t.width}:{width:t.width,height:t.height}}function L(t){return Object.is(t,-0)?0:t}function ve(t,e){let[i,n,s,a,r,o]=t;return[L(-i),L(n),L(-s),L(a),L(e-r),L(o)]}function Ae(t,e){let i=dt(e?.rotation),n=ut(t,i),s;switch(i){case 90:s=[0,1,-1,0,t.width,0];break;case 180:s=[-1,0,0,-1,t.width,t.height];break;case 270:s=[0,-1,1,0,0,t.height];break;default:s=[1,0,0,1,0,0]}return e?.flip&&(s=ve(s,t.width)),{matrix:s,source:n}}var Me=h.Milli(500),Q=class{in;source;sync;#t={frame:new u(void 0),timestamp:new u(void 0),display:new u(void 0),stalled:new u(!1),stats:new u(void 0),jitter:new u(void 0),buffered:new u([])};out=E(this.#t);#e=new u(void 0);#i=new u(void 0);#n;#s=new M;#a(){this.#t.frame.update(t=>{t?.close()}),this.#t.timestamp.set(void 0)}constructor(t){this.in={enabled:m(t?.enabled??!0)},this.source=t.source,this.sync=t.sync,this.#s.cleanup(this.sync.register(this.out.jitter)),this.#n=this.#s.computed(e=>{let i=e.get(this.source.out.config);return i?ht(i):void 0}),this.#s.run(this.#r.bind(this)),this.#s.run(this.#o.bind(this)),this.#s.run(this.#c.bind(this)),this.#s.run(this.#l.bind(this)),this.#s.run(this.#h.bind(this))}#r(t){let e=(r,o)=>{if(r===void 0||o===void 0)return;let c=t.get(o)?.video?.renditions?.[r];return c&&be(c)},i=t.get(this.#e),n=e(i?.track,i?.catalog),s=t.get(this.#i),a=e(s?.track,s?.catalog);t.set(this.#t.jitter,we({active:n,pending:a}))}#o(t){let e=t.getAll([this.in.enabled,this.source.in.broadcast,this.source.out.track,this.#n]);if(!e){this.#e.set(void 0);return}let[i,n,s,a]=e,r=n.relativeBroadcast(t,a.broadcast);if(!r){this.#e.set(void 0),this.#a(),this.#t.buffered.set([]);return}let o=new ke({sync:this.sync,broadcast:r,track:s,config:a.decoder,stats:this.#t.stats,catalog:n.out.catalog});t.set(this.#i,{track:s,catalog:n.out.catalog}),t.cleanup(()=>o?.close()),t.run(c=>{if(!o)return;let l=c.get(this.#e);if(l){let d=c.get(o.timestamp);if(d===void 0||!ye({playhead:d,active:c.get(l.timestamp)}))return}this.#e.set(o),this.#i.set(void 0),o=void 0,c.close()})}#c(t){let e=t.get(this.#e);if(!e){this.#t.buffered.set([]);return}t.cleanup(()=>e.close()),t.run(i=>{let n=i.get(e.frame);n&&(this.#t.timestamp.set(h.Milli.fromMicro(n.timestamp)),this.#t.frame.update(s=>(s?.close(),n.clone())))}),t.proxy(this.#t.buffered,e.buffered)}#l(t){let e=t.get(this.source.out.catalog);if(!e)return;let i=e.display;if(i){t.set(this.#t.display,{width:i.width,height:i.height});return}let n=t.get(this.#t.frame);n&&t.set(this.#t.display,ut({width:n.displayWidth,height:n.displayHeight},e.rotation))}#h(t){if(t.get(this.in.enabled)){if(!t.get(this.#t.frame)){this.#t.stalled.set(!0);return}this.#t.stalled.set(!1),t.timer(()=>{this.#t.stalled.set(!0)},Me)}}close(){this.#a(),this.#s.close()}static supported=ft},ke=class{sync;broadcast;track;config;catalog;stats;timestamp=new u(void 0);frame=new u(void 0);buffered=new u([]);#t=new u([]);#e=0;#i=new M;constructor(t){this.sync=t.sync,this.broadcast=t.broadcast,this.track=t.track,this.config=t.config,this.catalog=t.catalog,this.stats=t.stats,this.#i.run(this.#n.bind(this))}#n(t){let e=$(t,{broadcast:this.broadcast,track:this.track,priority:b.PRIORITY.video,maxAge:this.sync.out.maxAge});if(!e)return;let i=new VideoDecoder({output:async n=>{try{let s=this.#e,a=h.Milli.fromMicro(n.timestamp);if(a<(this.timestamp.peek()??0)||this.sync.out.reference.peek()===void 0||(this.frame.peek()===void 0&&this.frame.set(n.clone()),!await t.race(this.sync.wait(a).then(()=>!0)))||s!==this.#e||a<(this.timestamp.peek()??0))return;this.timestamp.set(a),this.#c(a),this.frame.update(r=>(r?.close(),n.clone()))}finally{n.close()}},error:n=>{console.error("video decoder error",n),t.close()}});t.cleanup(()=>{i.state!=="closed"&&i.close()}),this.config.container.kind==="cmaf"?this.#a(t,e,i):this.#s(t,e,i)}#s(t,e,i){let n=this.config.container.kind==="loc"?new y.Loc.Format("video"):new y.Legacy.Format(this.config),s=new y.Consumer(e,{format:n,maxAge:this.sync.out.maxAge});t.cleanup(()=>s.close()),t.run(o=>{let c=o.get(s.buffered),l=o.get(this.#t);this.buffered.update(()=>y.mergeBufferedRanges(c,l))}),i.configure({codec:this.config.codec,description:this.config.description?w.Hex.toBytes(this.config.description):void 0,displayAspectWidth:this.config.displayAspectWidth,displayAspectHeight:this.config.displayAspectHeight,optimizeForLatency:this.config.optimizeForLatency,flip:!1});let a,r;t.spawn(async()=>{for(;;){let o=await P(s);if(!o)break;this.#r(o.discontinuity)&&(a=void 0);let{frame:c}=o;if(!c)continue;let l=r!==void 0&&o.group<r;if(this.stats.update(p=>({frameCount:(p?.frameCount??0)+ +!l,bytesReceived:(p?.bytesReceived??0)+c.payload.byteLength})),l)continue;let d=h.Milli.fromMicro(c.timestamp);this.sync.received(d,"video");let f=new EncodedVideoChunk({type:c.keyframe?"key":"delta",data:c.payload,timestamp:c.timestamp});a!==void 0&&o.continuous&&this.#o(h.Milli.fromMicro(a),h.Milli.fromMicro(c.timestamp)),a=c.timestamp,r=o.group,i.decode(f)}})}#a(t,e,i){let n=this.config.container;if(n.kind!=="cmaf")return;let s=F(n.init),a=y.Cmaf.decodeInitSegment(s),r=this.config.description?w.Hex.toBytes(this.config.description):a.description,o=new y.Consumer(e,{format:new y.Cmaf.Format(a),maxAge:this.sync.out.maxAge});t.cleanup(()=>o.close()),t.run(d=>{let f=d.get(o.buffered),p=d.get(this.#t);this.buffered.update(()=>y.mergeBufferedRanges(f,p))}),i.configure({codec:this.config.codec,description:r,displayAspectWidth:this.config.displayAspectWidth,displayAspectHeight:this.config.displayAspectHeight,optimizeForLatency:this.config.optimizeForLatency,flip:!1});let c,l;t.spawn(async()=>{for(;;){let d=await P(o);if(!d)break;this.#r(d.discontinuity)&&(c=void 0);let{frame:f}=d;if(!f)continue;let p=l!==void 0&&d.group<l;if(this.stats.update(v=>({frameCount:(v?.frameCount??0)+ +!p,bytesReceived:(v?.bytesReceived??0)+f.payload.byteLength})),p)continue;let g=h.Milli.fromMicro(f.timestamp);if(this.sync.received(g,"video"),c!==void 0&&d.continuous&&this.#o(h.Milli.fromMicro(c),h.Milli.fromMicro(f.timestamp)),c=f.timestamp,i.state==="closed")break;l=d.group,i.decode(new EncodedVideoChunk({type:f.keyframe?"key":"delta",data:f.payload,timestamp:f.timestamp}))}})}#r(t){return t!==this.#e&&(this.#e=t,this.timestamp.set(void 0),this.#t.set([]),this.sync.reset(),!0)}#o(t,e){t>e||this.#t.mutate(i=>{for(let n of i)if(n.start<=e&&n.end>=t){n.start=h.Milli.min(n.start,t),n.end=h.Milli.max(n.end,e);return}i.push({start:t,end:e}),i.sort((n,s)=>n.start-s.start)})}#c(t){this.#t.mutate(e=>{for(;e.length>0;){if(e[0].end>=t){e[0].start=h.Milli.max(e[0].start,t);break}e.shift()}})}close(){this.#i.close(),this.frame.update(t=>{t?.close()})}};async function ft(t){if(!b.containerSupported(t.container)){let n=t.container.kind==="unknown"?t.container.raw.kind:t.container.kind;return console.warn(`video: ignoring rendition with unknown container: ${n}`),!1}let e;if(t.description)e=w.Hex.toBytes(t.description);else if(t.container.kind==="cmaf")try{e=y.Cmaf.decodeInitSegment(F(t.container.init)).description}catch(n){return console.warn(`video: malformed CMAF init segment for codec ${t.codec}`,n),!1}let{supported:i}=await VideoDecoder.isConfigSupported({codec:t.codec,description:e,displayAspectWidth:t.displayAspectWidth,displayAspectHeight:t.displayAspectHeight,optimizeForLatency:t.optimizeForLatency??!0});if(i)return!0;if(t.codec.startsWith("avc3.")){let n=`avc1.${t.codec.slice(5)}`;if((await VideoDecoder.isConfigSupported({codec:n,description:e,displayAspectWidth:t.displayAspectWidth,displayAspectHeight:t.displayAspectHeight,optimizeForLatency:t.optimizeForLatency??!0})).supported)return t.codec=n,!0}return!1}Object.assign(ft,{[lt]:me});var Z=.01,xe=class{decoder;in;#t={frame:new u(void 0),timestamp:new u(void 0),visible:new u(!1)};out=E(this.#t);#e=new u(void 0);#i=new M;constructor(t){this.decoder=t.decoder,this.in={canvas:m(t?.canvas),visible:m(t?.visible??"20%")},this.#i.run(e=>{let i=e.get(this.in.canvas);this.#e.set(i?.getContext("2d")??void 0)}),this.#i.run(this.#s.bind(this)),this.#i.run(this.#a.bind(this)),this.#i.run(this.#n.bind(this))}#n(t){let e=t.getAll([this.in.canvas,this.decoder.out.display]);if(!e)return;let[i,n]=e;(i.width!==n.width||i.height!==n.height)&&(i.width=n.width,i.height=n.height)}#s(t){let e=t.get(this.in.visible);if(e==="never"){this.#t.visible.set(!1);return}if(e==="always"){this.#t.visible.set(!0),t.cleanup(()=>this.#t.visible.set(!1));return}let i=t.get(this.in.canvas);if(!i){this.#t.visible.set(!1);return}let n=!1,s=()=>{this.#t.visible.set(n&&!document.hidden)},a=o=>{for(let c of o)n=c.isIntersecting,s()},r;try{r=new IntersectionObserver(a,{threshold:Z,rootMargin:e})}catch{console.warn(`moq-watch: invalid visible margin "${e}", using "0px"`),r=new IntersectionObserver(a,{threshold:Z})}s(),t.event(document,"visibilitychange",s),r.observe(i),t.cleanup(()=>r.disconnect()),t.cleanup(()=>this.#t.visible.set(!1))}#a(t){let e=t.get(this.#e);if(!e)return;let i=t.get(this.decoder.out.frame),n=t.get(this.decoder.source.out.catalog),s=requestAnimationFrame(()=>{this.#r(e,i,n),i?(this.#t.frame.update(a=>(a?.close(),i.clone())),this.#t.timestamp.set(h.Milli.fromMicro(i.timestamp))):(this.#t.frame.update(a=>{a?.close()}),this.#t.timestamp.set(void 0)),s=void 0});t.cleanup(()=>{s!==void 0&&cancelAnimationFrame(s)})}#r(t,e,i){if(!e){t.fillStyle="#000",t.fillRect(0,0,t.canvas.width,t.canvas.height);return}if(t.save(),t.fillStyle="#000",t.fillRect(0,0,t.canvas.width,t.canvas.height),!i?.rotation)i?.flip&&(t.scale(-1,1),t.translate(-t.canvas.width,0)),t.drawImage(e,0,0,t.canvas.width,t.canvas.height);else{let n=Ae(t.canvas,i);t.setTransform(...n.matrix),t.drawImage(e,0,0,n.source.width,n.source.height)}t.restore()}close(){this.#t.frame.update(t=>{t?.close()}),this.#t.timestamp.set(void 0),this.#i.close()}};function Re(t){return e=>{let i=[],n=[];for(let[s,a]of e)if(a.codedWidth&&a.codedHeight){let r=a.codedWidth*a.codedHeight;r<=t?i.push({name:s,size:r}):n.push({name:s,size:r})}return i.sort((s,a)=>a.size-s.size),i.length>0?i.map(s=>s.name):n.length>0?(n.sort((s,a)=>s.size-a.size),[n[0].name]):e.map(([s])=>s)}}function pt(t,e){return i=>{let n=[],s=[];for(let[a,r]of i){if(!r.codedWidth||!r.codedHeight)continue;let o=r.codedWidth*r.codedHeight,c=t==null||r.codedWidth<=t,l=e==null||r.codedHeight<=e;c&&l?n.push({name:a,size:o}):s.push({name:a,size:o})}return n.sort((a,r)=>r.size-a.size),n.length>0?n.map(a=>a.name):s.length>0?(s.sort((a,r)=>a.size-r.size),[s[0].name]):i.map(([a])=>a)}}function mt(t){return e=>{let i=[],n=[];for(let[s,a]of e)a.bitrate!=null&&a.bitrate<=t?i.push({name:s,bitrate:a.bitrate}):a.bitrate!=null&&n.push({name:s,bitrate:a.bitrate});return i.sort((s,a)=>a.bitrate-s.bitrate),i.length>0?i.map(s=>s.name):n.length>0?(n.sort((s,a)=>s.bitrate-a.bitrate),[n[0].name]):e.map(([s])=>s)}}function Ee(t){let e=t[0];for(let i of t){let[,n]=i,[,s]=e,a=(n.codedWidth??0)*(n.codedHeight??0),r=(s.codedWidth??0)*(s.codedHeight??0);if(a!==r){a>r&&(e=i);continue}(n.bitrate??0)>(s.bitrate??0)&&(e=i)}return e[0]}function Te(t){let e=Object.entries(t).filter(([,a])=>!a.stalled);if(e.length>0)return Object.fromEntries(e);let i=Object.entries(t);if(i.length===0)return{};let n=mt(0)(i),s=n.length===1?n[0]:pt(0,0)(i)[0];return{[s]:t[s]}}var Se=class{in;#t={catalog:new u(void 0),available:new u({}),error:new u(void 0),track:new u(void 0),config:new u(void 0)};out=E(this.#t);#e=new M;#i=new WeakMap;constructor(t){this.in={broadcast:m(t?.broadcast),target:m(t?.target),supported:m(t?.supported),probe:m(t?.probe)},this.#e.run(this.#n.bind(this)),this.#e.run(this.#s.bind(this)),this.#e.run(this.#a.bind(this))}#n(t){let e=t.get(this.in.broadcast);if(!e)return;let i=t.get(e.out.catalog)?.video;i&&t.set(this.#t.catalog,i)}#s(t){let e=t.get(this.in.supported);if(!e){this.#t.error.set(void 0);return}let i=t.get(this.#t.catalog)?.renditions??{};this.#t.error.set(void 0);let n=this.#i.get(e);n||(n=new Map,this.#i.set(e,n));let s=new Set(Object.keys(i));for(let a of n.keys())s.has(a)||n.delete(a);t.spawn(async()=>{let a={};for(let[o,c]of Object.entries(i)){let l=e[lt],d=l?l(c):JSON.stringify(c),f=n.get(o),p=!1;if(f?.key===d)p=f.supported;else{let g=!1;try{p=await t.race(e(c))}catch(v){g=!0,console.warn(`[Source] video rendition ${o} (${c.codec}) support probe failed; treating as unsupported`,v)}!g&&p!==void 0&&n.set(o,{key:l?l(c):JSON.stringify(c),supported:p})}if(t.abort.aborted)return;p&&(a[o]=c)}let r=Object.keys(a).length===0&&Object.keys(i).length>0?"unsupported":void 0;r==="unsupported"&&console.warn("[Source] No supported video renditions found:",i),this.#t.error.set(r),this.#t.available.set(a)})}#a(t){let e=t.get(this.#t.available),i=t.get(this.in.target);if(i?.name&&i.name in e){let o=e[i.name];t.set(this.#t.track,i.name),t.set(this.#t.config,o);return}let n=Te(e);if(Object.keys(n).length===0)return;let s=i;if(!i?.bitrate){let o=t.get(this.in.probe)?.estimatedRecvRate;if(o!=null){let c=Math.round(o*.8);s={...i,bitrate:c}}}let a=this.#r(n,s);if(!a)return;let r=n[a];t.set(this.#t.track,a),t.set(this.#t.config,r)}#r(t,e){let i=Object.entries(t);if(i.length===0)return;if(i.length===1)return i[0][0];let n=[];if(e?.pixels!=null&&n.push(Re(e.pixels)),(e?.width!=null||e?.height!=null)&&n.push(pt(e.width,e.height)),e?.bitrate!=null&&n.push(mt(e.bitrate)),n.length===0)return Ee(i);let s=n.map(r=>r(i)),a=s.map(r=>new Set(r));for(let r of s[0])if(a.every(o=>o.has(r)))return r;console.warn("conflicting rendition filters, no rendition satisfies all criteria")}close(){this.#e.close()}},Be=class{in;broadcast;sync;text;video;audio;renderer;emitter;textRenderer;#t=new u(!1);#e=new u(!1);#i=new u(!1);#n=new M;constructor(t={}){this.in=E({origin:m(t.origin),name:m(t.name??W.empty()),enabled:m(t.enabled??!0),announced:m(t.announced??!0),catalogFormat:m(t.catalogFormat),catalog:m(t.catalog),probe:m(t.probe),canvas:m(t.canvas),container:m(t.container),paused:m(t.paused??!1),volume:m(t.volume??.5),muted:m(t.muted??!1),visible:m(t.visible??"20%"),delay:m(t.delay??"auto"),buffer:m(t.buffer??h.Milli.zero),target:m(t.target),captions:m(t.captions)}),this.broadcast=new ee(this.in),this.#n.cleanup(()=>this.broadcast.close());let e=new Se({broadcast:this.broadcast,target:this.in.target,supported:Q.supported,probe:this.in.probe}),i=new qt({broadcast:this.broadcast,supported:U.supported});this.#n.cleanup(()=>{e.close(),i.close()}),this.text=new pe({broadcast:this.broadcast,target:this.in.captions}),this.#n.cleanup(()=>this.text.close()),this.sync=new ne({delay:this.in.delay,buffer:this.in.buffer,probe:this.in.probe}),this.#n.cleanup(()=>this.sync.close()),this.video=new Q({source:e,sync:this.sync,enabled:this.#t}),this.audio=new U({source:i,sync:this.sync,enabled:this.#e}),this.#n.cleanup(()=>{this.video.close(),this.audio.close()}),this.emitter=new Kt({source:this.audio,volume:this.in.volume,muted:this.in.muted,paused:this.in.paused}),this.renderer=new xe({decoder:this.video,canvas:this.in.canvas,visible:this.in.visible}),this.#n.cleanup(()=>{this.emitter.close(),this.renderer.close()}),this.textRenderer=new de({source:this.text,sync:this.sync,container:this.in.container,enabled:this.#i}),this.#n.cleanup(()=>this.textRenderer.close()),this.#n.run(n=>{this.#i.set(n.get(this.in.enabled)&&!n.get(this.in.paused))}),this.#n.run(n=>{this.#e.set(n.get(this.in.enabled)&&n.get(this.emitter.out.enabled))}),this.#n.run(n=>{let s=n.get(this.renderer.out.visible);n.get(this.in.enabled)?n.get(this.in.paused)?this.#t.set(s&&!n.get(this.renderer.out.frame)):this.#t.set(s):this.#t.set(!1)})}reset(){this.sync.reset(),this.audio.reset()}close(){this.#n.close()}};export{Kt as _,pe as a,he as c,le as d,J as f,qt as g,ze as h,Q as i,X as l,ee as m,Se as n,fe as o,ne as p,xe as r,de as s,Be as t,ce as u,U as v};
//# sourceMappingURL=player-DqpNnBDT.mjs.map