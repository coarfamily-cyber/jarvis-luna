/* Public read-only observer. No credentials, mutations, sales authority or auto retry. */
(function(root){
'use strict';
const REPO='coarfamily-cyber/jarvis-luna';
const API='https://api.github.com/repos/'+REPO;
const SHA=/^[a-f0-9]{40}$/;
function integer(x){return Number.isSafeInteger(x)&&x>0;}
function run(x){
 if(!x||!integer(x.id)||!integer(x.run_number)||!integer(x.run_attempt)||!SHA.test(x.head_sha)||!['queued','in_progress','completed','waiting','requested','pending'].includes(x.status)) throw Error('실행 형식 미확인');
 if(x.repository?.full_name!==REPO) throw Error('저장소 불일치');
 if(!Number.isFinite(Date.parse(x.updated_at))) throw Error('실행 시각 미확인');
 return {id:x.id,number:x.run_number,attempt:x.run_attempt,status:x.status,conclusion:x.conclusion||'unknown',updatedAt:x.updated_at,sha:x.head_sha,url:'https://github.com/'+REPO+'/actions/runs/'+x.id};
}
function summarize(producerRaw,publisherRaw,state,branch,checkedAt){
 const producer=run(producerRaw),publisher=run(publisherRaw);
 if(!Number.isFinite(Date.parse(checkedAt))||Date.parse(producer.updatedAt)>Date.parse(checkedAt)+60000||Date.parse(publisher.updatedAt)>Date.parse(checkedAt)+60000)throw Error('시각 근거 불일치');
 if(!state||state.schema!=='jarvis-owned-durable-ledger-v1'||!integer(state.last_run_id)||!integer(state.last_run_number)||!integer(state.event_count)||!state.checkpoint||!integer(state.checkpoint.run_id)||!Number.isSafeInteger(state.checkpoint.sequence)||state.checkpoint.sequence<0||!SHA.test(branch?.commit?.sha)) throw Error('원장 형식 미확인');
 if(state.holds?.full_core_recovery!==false||state.checkpoint.result?.full_core_recovery!==false) throw Error('기존 제한 상태와 다름: 별도 검증 필요');
 const expectedHolds={ai_requests:'disabled',full_core_recovery:false,legacy_budget_reset:'disabled',legacy_claim_replay:'disabled',legacy_continuity:'unresolved_gap',legacy_stop_clearance:'disabled',shopify_writes:'disabled',source_requests:'disabled'};
 for(const [key,value] of Object.entries(expectedHolds))if(state.holds?.[key]!==value||state.checkpoint.holds?.[key]!==value)throw Error('제한 상태 변경: 별도 검증 필요');
 const signature=branch.commit.commit?.verification?.verified===true&&branch.commit.commit.verification.reason==='valid';
 const sameRun=producer.id===state.last_run_id && producer.number===state.last_run_number;
 const numbersMatch=sameRun&&producer.status==='completed'&&signature&&publisher.status==='completed'&&publisher.conclusion==='success';
 return {checkedAt,producer,publisher,ledger:{commit:branch.commit.sha,lastRun:state.last_run_id,lastNumber:state.last_run_number,sequence:state.checkpoint.sequence,checkpointRun:state.checkpoint.run_id,events:state.event_count,signature,numbersMatch,url:'https://github.com/'+REPO+'/commit/'+branch.commit.sha},notice:numbersMatch?'실행 번호와 원장 번호 일치 · 재시도/성공 검증은 별도':'실행 번호와 원장 번호 일치 확인 안 됨',business:'Core 전체 복구·상품 등록·매출 성과는 이 결과로 증명되지 않습니다.'};
}
async function readJson(url){
 const c=new AbortController(),t=setTimeout(()=>c.abort(),15000);
 try{const r=await fetch(url,{method:'GET',credentials:'omit',cache:'no-store',redirect:'error',signal:c.signal,headers:{Accept:'application/json'}}); if(!r.ok)throw Error('공개 조회 실패 HTTP '+r.status); const s=await r.text(); if(s.length>1500000)throw Error('응답 크기 초과'); return JSON.parse(s);}finally{clearTimeout(t);}
}
async function observe(){
 const [p,w,b]=await Promise.all([readJson(API+'/actions/workflows/owned-core-local.yml/runs?per_page=1'),readJson(API+'/actions/workflows/owned-core-ledger-publisher.yml/runs?per_page=1'),readJson(API+'/branches/jarvis-owned-state')]);
 if(!SHA.test(b?.commit?.sha))throw Error('원장 커밋 미확인');
 const s=await readJson('https://raw.githubusercontent.com/'+REPO+'/'+b.commit.sha+'/.jarvis-owned-state.json');
 const [p2,w2,b2]=await Promise.all([readJson(API+'/actions/workflows/owned-core-local.yml/runs?per_page=1'),readJson(API+'/actions/workflows/owned-core-ledger-publisher.yml/runs?per_page=1'),readJson(API+'/branches/jarvis-owned-state')]);
 const identity=x=>JSON.stringify(run(x));
 if(b2?.commit?.sha!==b.commit.sha||identity(p2.workflow_runs?.[0])!==identity(p.workflow_runs?.[0])||identity(w2.workflow_runs?.[0])!==identity(w.workflow_runs?.[0]))throw Error('조회 중 실행 또는 원장이 변경됨. 다시 조회하세요.');
 return summarize(p.workflow_runs?.[0],w.workflow_runs?.[0],s,b,new Date().toISOString());
}
function boot(){
 let expiry=null;
 const status=document.getElementById('status'),body=document.getElementById('results'),button=document.getElementById('refresh');
 function line(label,value,url){let p=document.createElement('p');p.append(document.createTextNode(label+': '));let n=document.createElement(url?'a':'span'); n.textContent=String(value);if(url)n.href=url;p.append(n);body.append(p);}
 async function refresh(){clearTimeout(expiry);button.disabled=true;status.textContent='공개 GitHub 근거를 조회 중입니다.';body.replaceChildren();try{const s=await observe();status.textContent=s.notice;expiry=setTimeout(()=>{status.textContent='조회 후 5분 경과 · 현재 상태 다시 확인 필요';},300000);line('조회 완료 (KST)',new Date(s.checkedAt).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}));line('생산 실행',`#${s.producer.number} · ${s.producer.status} / ${s.producer.conclusion} · 시도 ${s.producer.attempt}`,s.producer.url);line('생산 실행 마지막 변경',s.producer.updatedAt);line('실행 기록 경과',Math.max(0,Math.floor((Date.now()-Date.parse(s.producer.updatedAt))/60000))+'분 · 조회 성공이 새 실행을 의미하지 않습니다.');line('원장 게시 실행',s.publisher.status+' / '+s.publisher.conclusion,s.publisher.url);line('원장',`마지막 실행 #${s.ledger.lastNumber} · checkpoint ${s.ledger.sequence} · 사건 ${s.ledger.events}`,s.ledger.url);line('API 원장에 보존된 checkpoint 실행',s.ledger.checkpointRun,'https://github.com/'+REPO+'/actions/runs/'+s.ledger.checkpointRun);line('GitHub 보고 커밋 서명',s.ledger.signature?'검증됨':'미확인');line('범위',s.business);line('검증 한계','이 화면은 API 기록 대조이며 실행 attempt의 원장 봉인·artifact·전체 이력 체인의 독립 재검증은 아닙니다. 조회 후 변화는 다시 조회해야 합니다.');}catch(e){status.textContent='현재 상태 미확인';line('조회 오류',e.message);line('판정','접근 제한·호출 한도·네트워크 오류는 정상 또는 0으로 바꾸지 않습니다. 아래 직접 실행 링크에서 확인하세요.');}finally{button.disabled=false;}}
 button.addEventListener('click',refresh);refresh();
}
if(typeof module!=='undefined')module.exports={summarize,run,observe,readJson};else{root.JarvisAudit={summarize,run};boot();}
})(typeof globalThis!=='undefined'?globalThis:this);
