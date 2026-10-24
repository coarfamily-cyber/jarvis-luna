"""Offline synthetic approval-metadata regressions; no real evidence or approval."""
from copy import deepcopy
from datetime import datetime, timezone
import unittest
import check_legal_products as legal

PAST='2020-01-01T00:00:00Z'
FUTURE='9999-01-01T00:00:00Z'
PROMISES=('will be provided','We will obtain the report later','shall be confirmed',
          'planned to obtain','to be supplied','not yet received','awaiting assessment',
          '확인 후 제공 예정','검토할 예정','추후 제출','안전성 자료 확보 계획',
          'ｗｉｌｌ ｂｅ ｐｒｏｖｉｄｅｄ','will&nbsp;be provided','wi\u200bll be provided')

def proof(kind='actual_packaging'):
    return {'human_approved':True,'product_id':'101','source_type':kind,
            'evidence_ref':'fixture-report-1','reviewed_by':'Fixture reviewer','reviewed_at':PAST}

def label():
    return {'ingredients_inci':'Water','net_contents':'30 ml','manufacturer':'Fixture Manufacturer',
            'country_of_origin':'Korea','product_name_en':'Fixture Lotion',
            'directions_en':'Apply gently.','warnings_en':'For external use only.',
            'actual_label_evidence':proof(),
            'responsible_person':{'name':'Fixture RP','address':'123 Fixture Road'},
            'responsible_person_evidence':proof('responsible_person_confirmation'),
            'product_safety_evidence':dict(proof('manufacturer_product_safety'),
                manufacturer='Fixture Manufacturer',product_specific_basis='Fixture report section 2')}

class LegalEvidenceMetadataTests(unittest.TestCase):
    def check(self,value):return legal.human_evidence(value,'101',('actual_packaging',))
    def test_existing_metadata_shape_remains_compatible_without_mutation(self):
        value=proof();before=deepcopy(value)
        self.assertTrue(self.check(value));self.assertEqual(value,before)
        self.assertTrue(all(row['ok'] for row in legal.us_requirements(label(),'101').values()))
    def test_false_and_truthy_nonbool_approval_never_accepted(self):
        for flag in (False,0,1,'true','false',[],{}):
            with self.subTest(flag=flag):self.assertFalse(self.check(dict(proof(),human_approved=flag)))
    def test_future_or_malformed_review_timestamp_rejected(self):
        for date in (FUTURE,'tomorrow','review complete','',None,True,{},'2020-19-01','2020-01-01T25:00:00Z'):
            with self.subTest(date=date):self.assertFalse(self.check(dict(proof(),reviewed_at=date)))
    def test_promised_reference_and_reviewer_rejected(self):
        for key in ('evidence_ref','reviewed_by'):
            for value in PROMISES:
                with self.subTest(key=key,value=value):self.assertFalse(self.check(dict(proof(),**{key:value})))
    def test_boolean_container_evidence_text_rejected(self):
        for value in (True,False,1,[],{},None):
            self.assertFalse(legal.evidence_text(value))
    def test_ordinary_name_with_will_and_completed_review_not_false_positive(self):
        for text in ('Will Smith','William Laboratories','Review completed; report retained.','검토 완료 문서 1'):
            with self.subTest(text=text):self.assertTrue(legal.evidence_text(text))
    def test_timezone_dates_compared_as_instants(self):
        clock=datetime(2024,1,1,tzinfo=timezone.utc)
        self.assertTrue(legal.review_date('2024-01-01T01:00:00+01:00',clock=clock))
        self.assertFalse(legal.review_date('2023-12-31T23:30:00-01:00',clock=clock))
        self.assertFalse(legal.review_date(PAST,clock=datetime(2024,1,1)))
    def test_legacy_naive_iso_dates_keep_utc_interpretation(self):
        clock=datetime(2024,1,1,tzinfo=timezone.utc)
        for date in ('2020-01-01','2020-01-01T12:00:00'):
            with self.subTest(date=date):self.assertTrue(legal.review_date(date,clock=clock))
    def test_source_type_and_product_binding_remain_required(self):
        for delta in ({'product_id':'102'},{'source_type':'model'},{'source_type':'alt_parser'}):
            self.assertFalse(self.check(dict(proof(),**delta)))
    def test_promised_responsible_person_details_rejected(self):
        for key in ('name','address'):
            value=label();value['responsible_person'][key]='will be provided'
            self.assertFalse(legal.us_requirements(value,'101')['responsible_person']['ok'])
    def test_promised_safety_basis_or_manufacturer_rejected(self):
        for key in ('manufacturer','product_specific_basis'):
            value=label();value['product_safety_evidence'][key]='will be provided'
            if key=='manufacturer':value['manufacturer']='will be provided'
            self.assertFalse(legal.us_requirements(value,'101')['manufacturer_product_safety']['ok'])
    def test_all_human_evidence_types_reject_future_reviews(self):
        for field,check in (('actual_label_evidence','actual_label_review'),
                            ('responsible_person_evidence','responsible_person'),
                            ('product_safety_evidence','manufacturer_product_safety')):
            value=label();value[field]['reviewed_at']=FUTURE
            self.assertFalse(legal.us_requirements(value,'101')[check]['ok'])
    def test_retained_legal_pass_cannot_use_future_review_or_promised_reviewer(self):
        value={'status':'pass','reviewer':'Fixture reviewer','reviewed_at':PAST,'signature':'retain'}
        self.assertTrue(legal.human_legal_approval(value))
        for delta in ({'reviewed_at':FUTURE},{'reviewed_at':'not a timestamp'},
                      {'reviewer':'will be provided'},{'status':'auto_checked'}):
            changed=dict(value,**delta);before=deepcopy(changed)
            self.assertFalse(legal.human_legal_approval(changed));self.assertEqual(changed,before)
    def test_main_preserves_future_signed_row_but_effective_pass_is_false(self):
        from test_us_label_provenance import run_legal
        signed={'status':'pass','reviewer':'Fixture reviewer','reviewed_at':FUTURE,'signature':'keep'}
        result=run_legal({'101':label()},{'items':{'101':signed}})['items']['101']
        for key,value in signed.items():self.assertEqual(result[key],value)
        self.assertFalse(result['effective_legal_pass'])
        self.assertIn('human_legal_approval',result['auto_blockers'])

if __name__=='__main__':unittest.main()
