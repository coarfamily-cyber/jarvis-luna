import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
import unittest
from scripts import gosi_observation_history as history

NOW=datetime(2026,10,25,4,tzinfo=timezone.utc)
def event(provider='daiso',code=403,category='auth',hours=24):
 return {'provider':provider,'code':code,'category':category,'stopped_at':(NOW-timedelta(hours=hours)).isoformat()}
class ProviderReportingTests(unittest.TestCase):
 def evaluate(self,doc,provider='daiso'):
  before=copy.deepcopy(doc)
  r=history.provider_stop_report(doc,provider,now=NOW)
  self.assertEqual(doc,before)
  self.assertFalse(r['request_authorized']);self.assertFalse(r['continuity_verified'])
  return r
 def test_exact_boundary(self):
  for hours,state in [(23.999,'known_stop_active'),(24,'known_cooldown_elapsed'),(25,'known_cooldown_elapsed')]:
   with self.subTest(hours=hours):self.assertEqual(self.evaluate({'provider_stops':[event(hours=hours)]})['state'],state)
 def test_auth_quota_distinct(self):
  for code,category in [(403,'auth'),(429,'quota')]:
   r=self.evaluate({'provider_stops':[event(code=code,category=category)]})
   self.assertEqual(r['events'][0]['code'],code);self.assertEqual(r['events'][0]['category'],category)
 def test_missing_invalid_future_clock(self):
  for stamp in [None,'', 'bad','2026-10-24T01:00:00', (NOW+timedelta(seconds=1)).isoformat()]:
   e=event();e['stopped_at']=stamp
   self.assertEqual(self.evaluate({'provider_stops':[e]})['state'],'unknown_history')
 def test_provider_separation(self):
  r=self.evaluate({'provider_stops':[event(provider='gemini',code=429,category='quota',hours=1)]})
  self.assertEqual(r['state'],'unknown_history');self.assertEqual(r['events'],[])
 def test_history_is_not_current_access(self):
  r=self.evaluate({'provider_stops':[],'provider_stop_history':[dict(event(hours=100),expired_at=NOW.isoformat())]})
  self.assertEqual(r['state'],'known_cooldown_elapsed');self.assertEqual(r['history_completeness'],'not_established')
 def test_unknown_and_active_preserved(self):
  r=self.evaluate({'provider_stops':[event(hours=1),dict(event(),stopped_at=None)]})
  self.assertEqual(r['state'],'known_stop_active');self.assertTrue(r['unknown_evidence'])
 def test_malformed_or_category_mismatch(self):
  for doc in [None,{}, {'provider_stops':'bad'}, {'provider_stops':[None]}, {'provider_stops':[dict(event(),category='quota')]}, {'provider_stops':[dict(event(),code=True)]}]:
   self.assertEqual(self.evaluate(doc)['state'],'unknown_history')
 def test_invalid_evaluation_clock_and_unknown_category(self):
  for clock in [NOW.replace(tzinfo=None), "2026-10-25"]:
   r=history.provider_stop_report({"provider_stops":[event()]},"daiso",now=clock)
   self.assertEqual(r["state"],"unknown_history")
   self.assertFalse(r["request_authorized"])
  self.assertEqual(self.evaluate({"provider_stops":[dict(event(),category="other")]} )["state"],"unknown_history")
 def test_offsets_and_no_input_alias(self):
  e=event();e['stopped_at']='2026-10-24T13:00:00+09:00';d={'provider_stops':[e]}
  r=self.evaluate(d);self.assertEqual(r['state'],'known_cooldown_elapsed')
  r['events'][0]['code']=999;self.assertEqual(e['code'],403)
class ReportIntegrationTests(unittest.TestCase):
 def test_actual_report_uses_diagnostics_without_source_mutation(self):
  from scripts import build_error_report as report
  with tempfile.TemporaryDirectory() as tmp:
   data=Path(tmp); source=data/'gosi.json'
   source.write_text(json.dumps({'provider_stops':[event(provider='gemini',code=429,category='quota')], 'vision_deferred':['1068721']}))
   before=source.read_bytes()
   with patch.object(report,'DATA',data),patch.object(report,'OUT',data/'error_report.json'),patch('socket.socket',side_effect=AssertionError('network forbidden')):
    self.assertEqual(report.main(),0)
   self.assertEqual(source.read_bytes(),before)
   result=json.loads((data/'error_report.json').read_text())
   states=result['provider_stop_diagnostics']
   self.assertEqual(states['daiso']['state'],'unknown_history')
   self.assertEqual(states['daiso']['events'],[])
   self.assertFalse(states['gemini']['request_authorized'])
   self.assertFalse(states['gemini']['continuity_verified'])
   self.assertNotIn('daiso HTTP 429',json.dumps(result,ensure_ascii=False))
if __name__=='__main__':unittest.main()
