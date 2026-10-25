import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import run_technical_fix_review as m
from test_technical_fix_review import fixture
class CliTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  for name,value in [(m.INPUT,{'teams':[{'id':t} for t in m.TEAMS]}),(m.FIXTURE,fixture())]:
   p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value))
  self.out=self.root/'review.json'
 def test_actual_local_cli_function(self):
  before=(self.root/m.INPUT).read_bytes()
  with patch('socket.create_connection',side_effect=AssertionError('network')):r=m.run(self.root,self.out)
  self.assertFalse(r['team_delivery_verified']);self.assertEqual(before,(self.root/m.INPUT).read_bytes())
  self.assertEqual(len(json.loads(self.out.read_text())['technical_review_handoff']['incidents']),4)
 def test_no_overwrite(self):
  self.out.write_text('keep')
  with self.assertRaises(ValueError):m.run(self.root,self.out)
  self.assertEqual(self.out.read_text(),'keep')
 def test_output_outside_root(self):
  with self.assertRaises(ValueError):m.run(self.root,self.root.parent/'forbidden.json')
 def test_symlink_input(self):
  p=self.root/m.INPUT;p.unlink();p.symlink_to(self.root/m.FIXTURE)
  with self.assertRaises(ValueError):m.run(self.root,self.out)
  self.assertFalse(self.out.exists())
 def test_unknown_missing_team(self):
  (self.root/m.INPUT).write_text('{"teams":[]}')
  with self.assertRaises(ValueError):m.run(self.root,self.out)
 def test_duplicate_keys(self):
  (self.root/m.INPUT).write_text('{"teams":[],"teams":[]}')
  with self.assertRaises(ValueError):m.run(self.root,self.out)
if __name__=='__main__':unittest.main()
