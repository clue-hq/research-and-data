import unittest
import assets


class AssetTests(unittest.TestCase):
    def test_palette_png_transparency_is_not_misread_as_an_opaque_matte(self):
        import io,tempfile
        from PIL import Image
        from core import Store
        im=Image.new('P',(4,4));im.putpalette([0,0,0,255,255,255]+[0]*762)
        out=io.BytesIO();im.save(out,format='PNG',transparency=0)
        class P:
            def download(self,url):return out.getvalue(),'image/png',url
        with tempfile.TemporaryDirectory() as d:
            a=assets.AssetPipeline(Store(d),P()).ingest('https://example.com/logo.png',{'collection':'website'})
            self.assertFalse(a['dimensions']['has_alpha_channel'])
            self.assertTrue(a['dimensions']['has_transparency'])

    def test_website_identity_icons_survive_generic_navigation_filter(self):
        import tempfile
        from unittest.mock import patch
        from core import Store
        with tempfile.TemporaryDirectory() as d:
            s=Store(d);s.write('sources.json',{'s':{'id':'s','url':'https://www.conduit.ai/','images':[{'url':'https://www.conduit.ai/icon.png'},{'url':'https://www.conduit.ai/apple-icon.png'},{'url':'https://www.conduit.ai/social-twitter.svg'}]}})
            found=[]
            def ingest(_,url,origin):found.append(url);return {'id':url}
            with patch.object(assets.AssetPipeline,'ingest',ingest):assets.AssetPipeline(s,object()).website()
            self.assertEqual(set(found),{'https://www.conduit.ai/icon.png','https://www.conduit.ai/apple-icon.png'})

    def test_optimizer_source_decodes_to_original_and_preserves_external_host(self):
        self.assertEqual(assets.original_url('https://www.conduit.ai/_next/image?url=%2Fhero%2Fbg.png&w=3840&q=75'), 'https://www.conduit.ai/hero/bg.png')
        self.assertEqual(assets.original_url('https://www.conduit.ai/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fasset.jpg&w=100'), 'https://cdn.sanity.io/asset.jpg')

    def test_thought_leader_and_wrong_advertiser_not_silently_mixed(self):
        ads = [{'ad_id': '1', 'advertiser': {'name': 'Conduit', 'promoted': True}, 'type': 'image', 'image': {'url': 'https://example.org/a.png'}},
               {'ad_id': '2', 'advertiser': {'name': 'Someone else', 'promoted': True}, 'type': 'image', 'image': {'url': 'https://example.org/b.png'}}]
        kept, rejected = assets.select_ads(ads, {'conduit'})
        self.assertEqual([a['ad_id'] for a in kept], ['1'])
        self.assertEqual(rejected[0]['reason'], 'advertiser_mismatch')

    def test_carousel_is_not_mislabeled_as_single_image(self):
        ad = {'type': 'image', 'carousel': {'cards': [{'image': {'url': 'https://example.org/a.png'}}, {'image': {'url': 'https://example.org/b.png'}}]}}
        self.assertEqual(assets.media_entries(ad)[0]['format'], 'carousel')
        self.assertEqual(len(assets.media_entries(ad)), 2)

    def test_custom_date_window_ends_yesterday(self):
        from datetime import date
        self.assertEqual(assets.ad_window(date(2026,9,19), 90), {'startdate': '2026-06-21', 'enddate': '2026-09-18'})

if __name__ == '__main__': unittest.main()

class IdentityAndCoverageTests(unittest.TestCase):
    def test_linkedin_identity_requires_reciprocal_domain_and_unique_page_id(self):
        sources={'web': {'id':'web','url':'https://conduit.ai/', 'links':['https://www.linkedin.com/company/useconduitai/']},
                 'li': {'id':'li','url':'https://www.linkedin.com/company/useconduitai/', 'text':'Website https://conduit.ai', 'links':['https://www.linkedin.com/jobs/search?f_C=96574094']}}
        self.assertEqual(assets.linkedin_identity(sources)['page_id'], '96574094')
        sources['li']['text']='Website https://anotherconduit.com'
        with self.assertRaises(ValueError): assets.linkedin_identity(sources)

    def test_carousel_slides_do_not_count_as_separate_ads_and_repeated_media_deduped(self):
        entries=[{'asset_ids':['a','b','c']},{'asset_ids':['a','b','c']},{'asset_ids':['d']}]
        self.assertEqual(assets.distinct_creative_count(entries),2)

class RequestContractTests(unittest.TestCase):
 def test_ad_api_receives_string_page_identifier(self):
  import tempfile
  from pathlib import Path
  from core import Store
  class P:
   env={'ADYNTEL_API_KEY':'test','ADYNTEL_EMAIL':'test@example.com'}
   calls=[]
   def paid(self,*args,**kwargs):
    self.calls.append(args[3]); return {'page_id':'96574094','ads':[],'is_last_page':True}
  with tempfile.TemporaryDirectory() as d:
   s=Store(Path(d));s.write('sources.json',{'web':{'id':'web','url':'https://conduit.ai/','links':['https://www.linkedin.com/company/useconduitai/']},'li':{'id':'li','url':'https://www.linkedin.com/company/useconduitai/','text':'https://conduit.ai','links':['https://www.linkedin.com/jobs/search?f_C=96574094']}})
   p=P();assets.AssetPipeline(s,p).ads()
   self.assertIsInstance(p.calls[0]['linkedin_page_id'],str)

class CompleteCreativeCoverageTests(unittest.TestCase):
 def test_video_covers_do_not_satisfy_original_creative_target(self):
  self.assertEqual(assets.distinct_creative_count([{'asset_ids':['poster'],'media_status':'cover_only'},{'asset_ids':['ad'],'media_status':'saved'}]),1)

class SponsorTests(unittest.TestCase):
 def test_author_name_is_not_advertiser_identity(self):
  from ad_details import verified_sponsor
  source={'text':'Punn Kam\nPromoted by Conduit\nAdvertiser\nConduit\nPaid for by HostAI Labs, Inc.','links':['https://www.linkedin.com/company/96574094?trk=about']}
  self.assertTrue(verified_sponsor(source,'96574094'))
  self.assertFalse(verified_sponsor(source,'123'))
  source['text']='Punn Kam. Works at Conduit.'
  self.assertFalse(verified_sponsor(source,'96574094'))

class ClassifierIdentityTests(unittest.TestCase):
 def test_alias_ids_cannot_silently_mark_a_batch_complete(self):
  import json,tempfile
  from pathlib import Path
  from unittest.mock import patch
  from core import Store
  class P:
   model='test'
   def chat(self,*args,**kwargs):
    return {'choices':[{'message':{'content':json.dumps({'assets':[{'id':'invented-alias'}]})}}]}
  with tempfile.TemporaryDirectory() as d:
   s=Store(Path(d));s.write('assets.json',{'asset_real':{'id':'asset_real','mime':'image/png','origins':[]}})
   p=s.path('previews/asset_real.png');p.parent.mkdir();p.write_bytes(b'preview-test')
   with patch.object(assets.AssetPipeline,'previews'):
    with self.assertRaisesRegex(ValueError,'identifiers differ'): assets.AssetPipeline(s,P()).classify()
   self.assertNotEqual(s.read('assets.json')['asset_real'].get('analysis_status'),'completed')
