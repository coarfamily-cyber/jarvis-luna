// Public API field fixtures captured 2026-10-24; negative variants below are synthetic.
const assert=require('node:assert/strict');
const {summarize,run,observe,readJson}=require('../audit.js');
const p={"id":40131237089,"run_number":9,"run_attempt":1,"head_sha":"90bcdaf29f9951cb83eb9d741e1f49170a8b763b","status":"completed","conclusion":"failure","updated_at":"2026-10-24T20:46:21Z","repository":{"full_name":"coarfamily-cyber/jarvis-luna"}};
const w={"id":40131283669,"run_number":7,"run_attempt":1,"head_sha":"90bcdaf29f9951cb83eb9d741e1f49170a8b763b","status":"completed","conclusion":"success","updated_at":"2026-10-24T20:47:33Z","repository":{"full_name":"coarfamily-cyber/jarvis-luna"}};
const b={"commit":{"sha":"4dde6d0984c6bc287dfed1cfc7e02f998f630809","commit":{"verification":{"verified":true,"reason":"valid"}}}};
const s={"schema":"jarvis-owned-durable-ledger-v1","last_run_id":40131237089,"last_run_number":9,"event_count":6,"holds":{"ai_requests":"disabled","full_core_recovery":false,"legacy_budget_reset":"disabled","legacy_claim_replay":"disabled","legacy_continuity":"unresolved_gap","legacy_stop_clearance":"disabled","shopify_writes":"disabled","source_requests":"disabled"},"checkpoint":{"run_id":40116062999,"sequence":6,"holds":{"ai_requests":"disabled","full_core_recovery":false,"legacy_budget_reset":"disabled","legacy_claim_replay":"disabled","legacy_continuity":"unresolved_gap","legacy_stop_clearance":"disabled","shopify_writes":"disabled","source_requests":"disabled"},"result":{"full_core_recovery":false}}};
const now='2026-10-24T21:50:00Z';
let n=0;function test(f){f();n++;}function clone(x){return structuredClone(x)}
test(()=>assert.equal(summarize(p,w,s,b,now).ledger.numbersMatch,true));
test(()=>assert.equal(summarize(p,w,s,b,now).producer.conclusion,'failure'));
test(()=>assert.equal(summarize(p,w,s,b,now).ledger.checkpointRun,40116062999));
test(()=>{let x=clone(s);x.last_run_id--;assert.equal(summarize(p,w,x,b,now).ledger.numbersMatch,false)});
test(()=>{let x=clone(b);x.commit.commit.verification.verified=false;assert.equal(summarize(p,w,s,x,now).ledger.numbersMatch,false)});
test(()=>{let x=clone(w);x.conclusion='failure';assert.equal(summarize(p,x,s,b,now).ledger.numbersMatch,false)});
test(()=>{let x=clone(p);x.repository.full_name='coar0000-wq/jarvis-luna';assert.throws(()=>run(x))});
test(()=>{let x=clone(p);x.id='evil';assert.throws(()=>run(x))});
test(()=>{let x=clone(p);x.head_sha='javascript:alert(1)';assert.throws(()=>run(x))});
test(()=>{let x=clone(p);x.html_url='https://evil.example/';assert.ok(run(x).url.startsWith('https://github.com/coarfamily-cyber/'))});
test(()=>{let x=clone(s);x.holds.full_core_recovery=true;assert.throws(()=>summarize(p,w,x,b,now))});
test(()=>assert.throws(()=>summarize(null,w,s,b,now)));
test(()=>{let x=clone(s);x.checkpoint.sequence=-1;assert.throws(()=>summarize(p,w,x,b,now))});
test(()=>{let x=clone(p);x.status='in_progress';x.conclusion=null;assert.equal(summarize(x,w,s,b,now).producer.conclusion,'unknown')});
test(()=>{let x=clone(p);x.status='in_progress';x.conclusion=null;assert.equal(summarize(x,w,s,b,now).ledger.numbersMatch,false)});

(async()=>{let count=0;async function check(f){await f();count++}
function network(change){let calls=0;global.fetch=async(url,o)=>{assert.equal(o.method,'GET');assert.equal(o.credentials,'omit');assert.equal(o.cache,'no-store');assert.equal(o.redirect,'error');assert.ok(!('Authorization' in o.headers));assert.ok(url.startsWith('https://api.github.com/repos/coarfamily-cyber/jarvis-luna/')||url.startsWith('https://raw.githubusercontent.com/coarfamily-cyber/jarvis-luna/'));calls++;let v=url.includes('owned-core-local')?{workflow_runs:[p]}:url.includes('owned-core-ledger')?{workflow_runs:[w]}:url.includes('branches')?b:s;v=structuredClone(v);if(change)v=change(v,calls);return{ok:true,text:async()=>JSON.stringify(v)}};return()=>calls;}
await check(async()=>{let c=network();assert.equal((await observe()).ledger.numbersMatch,true);assert.equal(c(),7)});
await check(async()=>{network((v,n)=>{if(n===7)v.commit.sha='a'.repeat(40);return v});await assert.rejects(observe,/변경됨/)});
await check(async()=>{network((v,n)=>{if(n===5)v.workflow_runs[0].run_attempt=2;return v});await assert.rejects(observe,/변경됨/)});
await check(async()=>{network((v,n)=>{if(n===6)v.workflow_runs[0].conclusion='failure';return v});await assert.rejects(observe,/변경됨/)});
for(const status of [403,429,404,500])await check(async()=>{global.fetch=async()=>({ok:false,status});await assert.rejects(()=>readJson('https://example.invalid'),new RegExp(String(status)))});
await check(async()=>{global.fetch=async()=>{throw Error('network down')};await assert.rejects(observe,/network down/)});
await check(async()=>{network((v,n)=>n===1?{workflow_runs:[]}:v);await assert.rejects(observe)});
console.log(n+' model tests + '+count+' network tests passed');})();

// Home integration must reuse the existing observer, styles and historical sections.
const fs=require('node:fs'),path=require('node:path');
const home=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
for(const id of ['owner-audit','owner-audit-title','status','refresh','results'])assert.equal((home.match(new RegExp('id="'+id+'"','g'))||[]).length,1);
assert.equal((home.match(/<script src="audit\.js" defer><\/script>/g)||[]).length,1);
assert.ok(home.includes('class="dashboard-card" id="owner-audit"')&&home.includes('class="btn btn-secondary" id="refresh"'));
for(const id of ['daily-pipeline','teams','daiso','operations-system','knowledge-graph'])assert.ok(home.includes('id="'+id+'"'));
console.log('4 home integration groups passed');
