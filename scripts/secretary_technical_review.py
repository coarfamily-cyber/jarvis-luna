"""Explicit local-copy rehearsal using the existing secretary and executor.

No CLI, workflow, external API, repair, provider, new queue or canonical reset.
Only the single pinned artifact and two existing review roles are admitted.
"""
import copy
from pathlib import Path
import jarvis_operations as core
import jarvis_execution as execution
import jarvis_audit as audit
import run_jarvis_operations as runner
import technical_review_binding as binding
GOAL='Technical artifact read review / '+binding.ZIP_SHA

def payload(code):
 return {'purpose':binding.PURPOSE,'teams':[binding.ROUTES[code]],'technical_error_code':code,
  'technical_artifact_sha256':binding.ZIP_SHA,'technical_run_id':binding.RUN_ID}

def run(root,*,now=None,actor='secretary'):
 if actor!='secretary':raise ValueError('only_secretary_controller')
 root=Path(root).absolute()
 # Existing complete checkpoint is mandatory; never bootstrap/reset a new store.
 for path in (runner.STATE,execution.ExecutionStore.filename):
  if not (root/path).is_file():raise ValueError('existing_checkpoint_required')
 if (root/'data/operations/.restore-pending.json').exists():raise ValueError('restore_pending')
 binding.read(root)
 with runner.transaction(root):
  state=runner.read(root,runner.STATE);runner.validate_state(root,state)
  old={k:core.digest(v) for k,v in state['tasks'].items() if v.get('goal')!=GOAL}
  before_claims=len(runner.read(root,execution.ExecutionStore.filename)['claims'])
  def persist():runner.atomic(root,runner.STATE,state)
  def complete(t):
   tid=t['task_id'];task=state['tasks'][tid]
   if task['state']=='COMPLETED':
    r=state['receipts'][task['receipt_id']]
    if not execution.validate_receipt(root,r):raise ValueError('prior_receipt_invalid_no_replay')
    return
   # Interrupted transitions require reconciliation, never implicit redispatch.
   if task['state']!='CREATED':raise ValueError('interrupted_task_no_replay')
   persist()
   for phase in ('ROUTED','IN_PROGRESS','VERIFYING'):
    core.transition(state,tid,phase);persist()
   preparation=audit.prepare(state,tid,now=now);persist()
   core.transition(state,tid,'EXECUTING');persist()
   receipt=execution.execute(root,state['tasks'][tid],execution.ExecutionStore(root),now=now)
   outcome=audit.outcome(state,preparation,root=root,receipt=receipt,now=now);persist()
   if not outcome['result']['output_verified'] or not execution.validate_receipt(root,receipt):
    core.transition(state,tid,'BLOCKED',reason='technical_review_receipt_validation_failed');persist()
    raise ValueError('technical_review_receipt_validation_failed')
   state['receipts'][receipt['receipt_id']]=receipt
   action=receipt['action'];state.setdefault('actions',{})[action['action_id']]={**action,'status':'VERIFIED','receipt_id':receipt['receipt_id']}
   state['decisions'][preparation['decision_id']].update(status='LOCAL_OUTPUT_VERIFIED',action_id=action['action_id'],receipt_id=receipt['receipt_id'])
   core.transition(state,tid,'COMPLETED',receipt=receipt);persist()
  first=core.create_task(state,goal=GOAL,team='sourcing',kind='snapshot_report',payload=payload('vt-source-webp'),evidence={'artifact_sha256':binding.ZIP_SHA,'scope':'local_technical_snapshot_review_not_repair'})
  complete(first)
  proposal=core.propose_handoff(state,first['task_id'],'pricing','Secretary routes verified artifact review to existing pricing role',kind='snapshot_report',payload=payload('fx-timestamp-schema'))
  if state['handoffs'][proposal['proposal_id']]['status']=='PROPOSED':
   second=core.accept_handoff(state,proposal['proposal_id'],actor=actor);persist()
  else:second=state['tasks'][state['handoffs'][proposal['proposal_id']]['child_id']]
  complete(second)
  runner.validate_state(root,state)
  if any(k not in state['tasks'] or core.digest(state['tasks'][k])!=v for k,v in old.items()):raise ValueError('old_goals_changed')
  after_claims=len(runner.read(root,execution.ExecutionStore.filename)['claims'])
  return {'scope':'isolated_copy_existing_secretary_readonly_review','goal':GOAL,
    'task_ids':[first['task_id'],second['task_id']],'task_states':[state['tasks'][t]['state'] for t in (first['task_id'],second['task_id'])],
    'handoff_status':state['handoffs'][proposal['proposal_id']]['status'],'new_claims':after_claims-before_claims,
    'old_goal_tasks_unchanged':len(old),'manual_blocked_codes':['pages-workflow-inventory','core-empty-job-metadata'],
    'engineering_fix_completed':False,'external_team_delivery_verified':False,'remote_changes':0}
