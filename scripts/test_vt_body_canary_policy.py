import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest
import vt_body_canary_policy as p


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)  # Synthetic, never approval.
        self.slot = p.ReviewedSlot(17, 8, 'a'*40, self.now, self.now+timedelta(hours=1), 'b'*64, 42, 'c'*64)
        self.run = dict(repository_id=1431541717, workflow_id=17, run_number=8,
                        run_attempt=1, head_sha='a'*40, head_branch='main',
                        event='workflow_dispatch', status='in_progress', id=99)
        self.artifact = dict(id=42, expired=False, digest='sha256:'+'c'*64,
                             workflow_run={'id':99,'head_sha':'a'*40})
        self.journal = dict(operation_id=p.operation_id(), run_id='99', run_attempt='1',
                            code_sha='a'*40, before_projection_sha256='b'*64,
                            state='prepared', write_attempts=0)

    def validate(self, **kw):
        return p.validate_slot(kw.get('slot',self.slot), kw.get('run',self.run),
            kw.get('checkpoint',self.artifact), kw.get('original_journal',self.journal), now=kw.get('now',self.now))

    def test_valid_model_never_authorizes_execution(self):
        self.assertFalse(self.validate()['execution_authorized'])

    def test_run_binding_new_dispatch_rerun_deleted_workflow(self):
        for key, value in dict(repository_id=1, workflow_id=18, run_number=9,
            run_attempt=2, head_sha='d'*40, head_branch='other', event='schedule',
            status='completed', id=100).items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(run=dict(self.run, **{key:value}))

    def test_missing_deleted_expired_checkpoint_no_bootstrap(self):
        for artifact in [None, {}, dict(self.artifact,id=43), dict(self.artifact,expired=True),
                         dict(self.artifact,digest='sha256:'+'d'*64), dict(self.artifact,workflow_run={})]:
            with self.subTest(artifact=artifact), self.assertRaises(ValueError):
                self.validate(checkpoint=artifact)

    def test_consumed_missing_or_other_original_intent(self):
        for key, value in dict(operation_id='new-ticket', run_id='100', run_attempt='2',
            code_sha='d'*40, before_projection_sha256='e'*64, state='write_unknown', write_attempts=1).items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(original_journal=dict(self.journal, **{key:value}))
        with self.assertRaises(ValueError):
            self.validate(original_journal=None)

    def test_expiry_and_no_future_or_naive_grant(self):
        for now in [self.now-timedelta(seconds=1), self.slot.expires_at, self.now.replace(tzinfo=None)]:
            with self.subTest(now=now), self.assertRaises(ValueError):
                self.validate(now=now)
        with self.assertRaises(ValueError):
            self.validate(slot=replace(self.slot, expires_at=self.now+timedelta(hours=25)))

    def test_unknown_outcome_always_stop(self):
        self.assertFalse(p.reconcile_unknown({}, {})['retry_allowed'])
        self.assertEqual(p.reconcile_unknown({}, {})['state'], 'unknown_write_stop')

    def test_all_nonbody_fields_protected(self):
        original = dict(id=p.PRODUCT,status='ACTIVE',descriptionHtml='before',title='fixed',
                        prices=['18.99'],images=['image'],ingredients=['unknown'],publications=['copilot'])
        for field in ('title','prices','images','ingredients','publications','status'):
            actual=copy.deepcopy(original);actual[field]='CHANGED'
            with self.subTest(field=field), self.assertRaises(ValueError):
                p.verify_readback(original,actual)

    def test_unknown_source_and_body_fail_closed(self):
        with self.assertRaises(ValueError):
            p.proposed_body(p.OLD,b'not verified supplier pixels')

    def test_stable_operation_id_no_ticket_argument(self):
        self.assertEqual(p.operation_id(),p.operation_id())
        with self.assertRaises(TypeError):
            p.operation_id('new-ticket')


if __name__ == '__main__':
    unittest.main()
