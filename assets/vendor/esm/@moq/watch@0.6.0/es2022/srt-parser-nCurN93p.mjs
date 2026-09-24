/* esm.sh - @moq/watch@0.6.0/srt-parser-nCurN93p */
import{_ as a,g as h,h as e}from"./player-DiUmUis6.mjs";var n=/,/g,r="-->",l=class extends a{parse(s,i){if(s==="")this.a&&=(this.j.push(this.a),this.f.onCue?.(this.a),null),this.c=e.None;else if(this.c===e.Cue)this.a.text+=(this.a.text?`
`:"")+s;else if(s.includes(r)){let t=this.o(s,i);t&&(this.a=new h(t[0],t[1],t[2].join(" ")),this.a.id=this.l,this.c=e.Cue)}this.l=s}o(s,i){return super.o(s.replace(n,"."),i)}};function u(){return new l}export{u as default};
//# sourceMappingURL=srt-parser-nCurN93p.mjs.map