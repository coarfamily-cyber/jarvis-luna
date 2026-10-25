"""Offline real-incident regressions; quotations are supplier facts, not approval."""
import copy
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from daiso.collect_gosi_alt import clean_maker, clean_net_contents
import supplier_notice_disclosures as disclosure

class DisclosureTests(unittest.TestCase):
    def test_medipeel_age_boundary_not_lost(self):
        source={'warnings':'만 3세 이하 영유아에게는 사용하지 말 것'}
        result=disclosure.inspect('1053482','Toner',source)
        self.assertIn(source['warnings'],result['rows'][0][1])
        self.assertFalse(result['human_approved'])
        self.assertFalse(result['publication_allowed'])
    def test_bon_source_directions_preserved_without_translation(self):
        source={'usage':'세럼 단계에서 적당량을 피부결에 따라 펴 바른 후 가볍게 두드려 흡수시켜 줍니다.'}
        before=copy.deepcopy(source)
        result=disclosure.inspect('1055167','Serum 30 ml',source)
        self.assertEqual(result['rows'][0][1], source['usage'])
        self.assertEqual(source,before)
        self.assertIn('warnings_source_missing',result['reasons'])
    def test_organist_role_fragment_and_quantity_conflict(self):
        self.assertEqual(clean_maker('및 판매원'),'')
        result=disclosure.inspect('1025282','Body wash 200 ml',{'volume':'190 ml (200g)'})
        self.assertTrue(result['volume_hold'])
        self.assertIn('supplier_title_notice_volume_conflict',result['reasons'])
    def test_vt_known_unresolved_stock_cannot_be_cleared_by_flags(self):
        result=disclosure.inspect('1067498','Cream',{'ingredients':'Water','human_approved':True,'formula_verified':True})
        self.assertTrue(result['formula_hold'])
        self.assertFalse(result['physical_label_verified'])
    def test_generic_new_old_formulas_never_selected(self):
        result=disclosure.inspect('999','Cream',{'ingredients':'신형: 정제수, 구형: 글리세린'})
        self.assertTrue(result['formula_hold'])
    def test_manufacturer_heading_prefix_only(self):
        self.assertEqual(clean_maker('화장품 Manufacturer: 나우코스케이'),'Manufacturer: 나우코스케이')
        self.assertEqual(clean_maker('화장품나라 주식회사'),'화장품나라 주식회사')
        for raw in (True,{},[],None):self.assertEqual(clean_maker(raw),'')
    def test_future_quantity_not_proof(self):
        for raw in ('30 ml will be confirmed later','30 ml 제공 예정','30 ml 추후 확인'):
            self.assertEqual(clean_net_contents(raw),'')
        self.assertEqual(clean_net_contents('30 ml'),'30 ml')
    def test_visible_color_not_ingredients_or_safety(self):
        result=disclosure.inspect('1074979','Brightener',{'color':'01 Pale White'})
        self.assertIn(('Color (supplier source text; unverified)','01 Pale White'),result['rows'])
        self.assertFalse(result['physical_label_verified'])
    def test_renderer_preserves_and_escapes_warning(self):
        import daiso_daily_beauty_to_shopify as daily
        resolver=Mock();resolver.to_inci.return_value=('Water',[],[],[])
        source={'ingredients':'정제수','volume':'200 ml','maker':'Maker','origin':'대한민국',
                'warnings':'만 3세 이하 영유아에게는 사용하지 말 것 <script>bad</script>'}
        with patch.object(daily,'_inci_resolver',return_value=(resolver,Mock())):
            result=daily.build_us_label('1053482','Toner',source)
        self.assertIn('만 3세 이하',result['html']);self.assertNotIn('<script>',result['html'])
        self.assertFalse(result['supplier_disclosure']['publication_allowed'])
    def test_formula_hold_suppresses_even_dictionary_resolved_inci(self):
        import daiso_daily_beauty_to_shopify as daily
        resolver=Mock();resolver.to_inci.return_value=('Water',[],[],[])
        with patch.object(daily,'_inci_resolver',return_value=(resolver,Mock())):
            result=daily.build_us_label('1067498','Cream',{'ingredients':'정제수'})
        self.assertNotIn('Ingredients (INCI)',result['html'])
    def test_generator_cannot_stringify_fake_maker_or_quantity(self):
        import daiso_daily_beauty_to_shopify as daily
        resolver=Mock();resolver.to_inci.return_value=('Water',[],[],[])
        with patch.object(daily,'_inci_resolver',return_value=(resolver,Mock())):
            result=daily.build_us_label('999','Cream',{'maker':{'company':'Fake'},'volume':{'amount':'30 ml'}})
        self.assertNotIn('Fake',result['html'])
        self.assertIn('maker_missing',result['reasons'])
        self.assertIn('net_contents_missing_or_invalid',result['reasons'])
    def test_existing_supplier_transcription_is_used_without_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'data/manual').mkdir(parents=True)
            row={'sources':[{'url':'https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo=1055167'}],
                 'directions_ko':'피부결을 따라 펴 바릅니다.', 'human_approved':True}
            (root/'data/manual/official_label_text.json').write_text(json.dumps({'items':{'1055167':row}}))
            source={};filled=disclosure.with_retained_supplier_text(root,'1055167',source)
            self.assertEqual(filled['usage'],row['directions_ko']);self.assertEqual(source,{})
            self.assertNotIn('human_approved',filled)
            conflicting=disclosure.with_retained_supplier_text(root,'1055167',{'usage':'다른 원문'})
            self.assertEqual(conflicting['usage'],'다른 원문')
            self.assertIn('supplier_disclosure_versions_conflict',disclosure.inspect('1055167','',conflicting)['reasons'])
            row['sources'][0]['url']='https://example.org/wrong'
            (root/'data/manual/official_label_text.json').write_text(json.dumps({'items':{'1055167':row}}))
            self.assertEqual(disclosure.with_retained_supplier_text(root,'1055167',{'_retained_disclosure_sha256':'forged'}),{})
    def test_unknown_inci_still_held(self):
        import daiso_daily_beauty_to_shopify as daily
        resolver=Mock();resolver.to_inci.return_value=('Water',['unknown'],[],[])
        with patch.object(daily,'_inci_resolver',return_value=(resolver,Mock())):
            result=daily.build_us_label('999','Cream',{'ingredients':'unknown'})
        self.assertNotIn('Ingredients (INCI)',result['html'])
        self.assertIn('inci_unresolved:1',result['reasons'])

    def test_recorded_quantity_conflicts_survive_self_declared_approval(self):
        for pd, name, volume in [('1084687', 'Dr.CPU cream 60g', '60ml'),
                                 ('1076498', 'Blistex Lip Balm 4.25g', '4.25g')]:
            with self.subTest(pd=pd):
                notice = {'volume': volume, 'origin': '한국', 'human_approved': True,
                          'physical_label_verified': True, 'volume_hold': False,
                          'origin_hold': False, 'publication_allowed': True}
                before = copy.deepcopy(notice)
                result = disclosure.inspect(pd, name, notice)
                self.assertTrue(result['volume_hold'])
                self.assertIn('supplier_net_contents_conflict_unresolved', result['reasons'])
                self.assertFalse(result['physical_label_verified'])
                self.assertFalse(result['human_approved'])
                self.assertFalse(result['publication_allowed'])
                self.assertEqual(notice, before)

    def test_blistex_origin_conflict_cannot_choose_either_supplier_version(self):
        import daiso_daily_beauty_to_shopify as daily
        resolver = Mock(); resolver.to_inci.return_value = ('Water', [], [], [])
        for origin, volume in [('한국', '4.25g'), ('미국', '4.5g')]:
            with self.subTest(origin=origin), patch.object(daily, '_inci_resolver', return_value=(resolver, Mock())):
                source = {'ingredients': '정제수', 'volume': volume, 'origin': origin, 'maker': 'Blistex'}
                before = copy.deepcopy(source)
                result = daily.build_us_label('1076498', 'Blistex Lip Balm', source)
                self.assertNotIn('origin', result['label'])
                self.assertNotIn('net_contents', result['label'])
                self.assertNotIn('<strong>Country of origin:</strong>', result['html'])
                self.assertIn('Source verification pending.', result['html'])
                self.assertIn('supplier_origin_conflict_unresolved', result['reasons'])
                self.assertIn('supplier_net_contents_conflict_unresolved', result['reasons'])
                self.assertEqual(source, before)

    def test_dr_cpu_mass_volume_conflict_cannot_be_reintroduced_by_renderer(self):
        import daiso_daily_beauty_to_shopify as daily
        resolver = Mock(); resolver.to_inci.return_value = ('Water', [], [], [])
        for volume in ('60g', '60ml'):
            with self.subTest(volume=volume), patch.object(daily, '_inci_resolver', return_value=(resolver, Mock())):
                result = daily.build_us_label('1084687', 'Dr.CPU cream', {'volume': volume})
                self.assertNotIn('net_contents', result['label'])
                self.assertIn('Source verification pending.', result['html'])
                self.assertTrue(result['supplier_disclosure']['volume_hold'])

    def test_unaffected_source_origin_stays_source_value_without_sales_authority(self):
        import daiso_daily_beauty_to_shopify as daily
        resolver = Mock(); resolver.to_inci.return_value = ('Water', [], [], [])
        with patch.object(daily, '_inci_resolver', return_value=(resolver, Mock())):
            result = daily.build_us_label('999', 'Cream 30ml', {'volume': '30ml', 'origin': '한국'})
        self.assertEqual(result['label']['origin'], 'Korea')
        self.assertIn('30ml', result['label']['net_contents'])
        self.assertFalse(result['supplier_disclosure']['origin_hold'])
        self.assertFalse(result['supplier_disclosure']['publication_allowed'])

    def test_quantity_copy_guard_is_exact_text_only_and_idempotent(self):
        for pd, amount in [('1084687', '60 ml'), ('1076498', '4.25 g')]:
            with self.subTest(pd=pd):
                source = {'title': 'PDRN 300 50% Cream ' + amount,
                          'description_html': '<p>Cream ' + amount + '; PDRN 300; 50%; 160g; pack 2.</p>'
                            '<a href="https://example.invalid/4.25g/60ml">source</a>'
                            '<img src="/4.25g.png" alt="60ml source photo">',
                          'ingredients': 'Water 50%', 'price': 21.99,
                          'origin': 'supplier Korea', 'images': ['4.25g.png']}
                before = copy.deepcopy(source)
                guarded = disclosure.hold_conflicting_quantity_copy(pd, source)
                self.assertEqual(source, before)
                self.assertNotIn(amount, guarded['title'])
                self.assertIn('(net contents unverified)', guarded['title'])
                self.assertIn('<p>Cream net contents unverified;', guarded['description_html'])
                for kept in ('PDRN 300', '50%', '160g', 'pack 2',
                             'https://example.invalid/4.25g/60ml', 'alt="60ml source photo"'):
                    self.assertIn(kept, guarded['description_html'])
                for field in ('ingredients', 'price', 'origin', 'images'):
                    self.assertEqual(guarded[field], before[field])
                self.assertEqual(disclosure.hold_conflicting_quantity_copy(pd, guarded), guarded)
                self.assertEqual(disclosure.hold_conflicting_quantity_copy('999', source), source)

    def test_quantity_guard_handles_conversion_entities_and_emphasis_not_attributes(self):
        cases = [('1084687', '60 mL (2.03 fl oz)'), ('1084687', '60 mL (2.02 fl oz)'),
                 ('1076498', '4.25g (0.15 oz)'), ('1076498', '4.5g (0.16 oz)')]
        for pd, amount in cases:
            with self.subTest(pd=pd, amount=amount):
                body = '<p>' + amount.replace(' ', '&nbsp;').replace('g', '<strong>g</strong>') + '</p>'
                source = {'title': 'Cream ' + amount, 'description_html': body +
                          '<a href="https://example.invalid/?x=>60ml">source</a>'}
                result = disclosure.hold_conflicting_quantity_copy(pd, source)
                self.assertNotIn('oz', result['title'])
                self.assertNotIn('oz', result['description_html'])
                self.assertIn('net contents unverified', result['description_html'])
                self.assertIn('<a href="https://example.invalid/?x=>60ml">source</a>', result['description_html'])
                if '<strong>' in body:
                    self.assertIn('<strong></strong>', result['description_html'])
                self.assertEqual(disclosure.hold_conflicting_quantity_copy(pd, result), result)

if __name__=='__main__':unittest.main()
