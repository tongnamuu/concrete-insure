import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path
import pymupdf as fitz

spec=importlib.util.spec_from_file_location('pdf_worker',Path(__file__).parents[1]/'python/pdf_worker.py')
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)

def document(rotation=0,crop=False):
    d=fitz.open();p=d.new_page(width=400,height=500)
    p.insert_text((70,100),'독감 항바이러스제 오셀타미비르',fontname='korea',fontsize=14)
    p.insert_text((70,140),'Tamiflu exact source',fontsize=12)
    p.insert_text((300,280),'Vertical',rotate=90,fontsize=12)
    if crop:p.set_cropbox(fitz.Rect(30,30,370,470))
    p.set_rotation(rotation)
    return d.tobytes()

class PDFTests(unittest.TestCase):
    def test_korean_source_and_annotation_roundtrip(self):
        for rotation in (0,90,180,270):
            for crop in (False,True):
                with self.subTest(rotation=rotation,crop=crop):
                    data=document(rotation,crop);doc=w.extract(data)
                    hits=w.search(doc,['독감','오셀타미비르','Vertical'])['hits']
                    self.assertEqual(len(hits),3)
                    for h in hits:
                        p=doc['pages'][h['page']-1]
                        self.assertEqual(h['quote'],p['text'][h['sourceStart']:h['sourceEnd']])
                    output,count,skipped=w.annotate(data,doc,hits)
                    self.assertEqual((count,skipped),(3,0))
                    d=fitz.open(stream=output,filetype='pdf');p=d[0]
                    self.assertEqual(p.rotation,rotation)
                    self.assertEqual(p.get_text(),fitz.open(stream=data,filetype='pdf')[0].get_text())
                    for a,h in zip(p.annots(),hits):
                        self.assertEqual(a.type[0],fitz.PDF_ANNOT_HIGHLIGHT)
                        self.assertEqual(a.info['content'],h['quote'])
                        self.assertEqual(d.xref_get_key(a.xref,'AP')[0],'dict')
                    # Ensure appearance streams affect actual rendered pixels.
                    self.assertNotEqual(p.get_pixmap(annots=True).samples,p.get_pixmap(annots=False).samples)

    def test_fast_geometry_equals_library(self):
        d=fitz.open(stream=document(90,True),filetype='pdf');p=d[0];p.set_rotation(0);inv=~p.transformation_matrix
        for block in p.get_text('rawdict')['blocks']:
            for line in block.get('lines',[]):
                for span in line['spans']:
                    for char in span['chars']:
                        q=fitz.recover_char_quad(line['dir'],span,char)
                        pts=[x*inv for x in (q.ll,q.lr,q.ur,q.ul)]
                        expected=[v for x in pts for v in (x.x,x.y)]
                        self.assertEqual(w.character_quad(line,span,char,inv),expected)

    def test_tampered_quote_coordinates_hash_rejected(self):
        data=document();doc=w.extract(data);hit=w.search(doc,['독감'])['hits'][0]
        for key,value in [('quote','fabricated'),('documentHash','x'),('sourceStart',1),('offsetEncoding','utf16')]:
            bad=copy.deepcopy(hit);bad[key]=value
            with self.assertRaisesRegex(ValueError,'SOURCE_INTEGRITY'):w.annotate(data,doc,[bad])
        bad=copy.deepcopy(hit);bad['segments'][0]['quad'][0]+=1
        with self.assertRaisesRegex(ValueError,'SOURCE_INTEGRITY'):w.annotate(data,doc,[bad])
        with self.assertRaisesRegex(ValueError,'SOURCE_INTEGRITY'):w.annotate(data+b'changed',doc,[hit])

    def test_unicode_codepoints_and_newline_gaps(self):
        text='A😀독감\n끝'
        records=b''.join(w.REC.pack(i,i+1,*([1.0]*8)) for i in (0,1,2,3,5))
        page={'number':1,'text':text,'blocks':[[0,len(text)]],'chars':w.base64.b64encode(records).decode()}
        doc={'hash':'x','pages':[page]}
        h=w.search(doc,['독감'])['hits'][0]
        self.assertEqual((h['start'],h['end']),(2,4))
        self.assertEqual([s['start'] for s in h['segments']],[2,3])
        self.assertEqual(w.geometry(page,4,5),[])

    def test_limits_and_truncation(self):
        d=fitz.open()
        for _ in range(412):d.new_page()
        self.assertEqual(len(w.extract(d.tobytes())['pages']),412)
        p={'number':1,'text':'x '*41,'blocks':[[0,82]],'chars':''}
        result=w.search({'hash':'x','pages':[p]},['x'])
        self.assertEqual(len(result['hits']),40);self.assertTrue(result['truncated'])
        p['text']='x '*40
        self.assertFalse(w.search({'hash':'x','pages':[p]},['x'])['truncated'])
        with self.assertRaisesRegex(ValueError,'INVALID_PDF'):w.extract(b'not pdf')

    def test_search_page_scope_preserves_source_and_annotations(self):
        d=fitz.open()
        for _ in range(3):d.new_page().insert_text((70,70),'Exact match')
        data=d.tobytes();doc=w.extract(data)
        all_hits=w.search(doc,['match'])['hits']
        self.assertEqual([h['page'] for h in all_hits],[1,2,3])
        scoped=w.search(doc,['match'],pages=[3,1])
        self.assertEqual(scoped,{'hits':[all_hits[0],all_hits[2]],'truncated':False})
        self.assertEqual(w.search(doc,['match'],pages=[]),{'hits':[],'truncated':False})
        for hit in scoped['hits']:w.verify(doc,hit)
        output,count,skipped=w.annotate(data,doc,scoped['hits'])
        self.assertEqual((count,skipped),(2,0))
        marked=fitz.open(stream=output,filetype='pdf')
        self.assertEqual([len(list(page.annots())) for page in marked],[1,0,1])
        with tempfile.TemporaryDirectory() as folder:
            pdf=Path(folder)/'source.pdf';pdf.write_bytes(data)
            payload={'pdf':str(pdf),'index':str(Path(folder)/'index.gz')}
            w.main(dict(payload,op='index'))
            self.assertEqual(w.main(dict(payload,op='search',terms=['match'],pages=[2]))['hits'],[all_hits[1]])
            self.assertEqual(w.main(dict(payload,op='search',terms=['match'],pages=[]))['hits'],[])
            self.assertEqual(w.main(dict(payload,op='search',terms=['match']))['hits'],all_hits)

    def test_search_rejects_invalid_page_scopes(self):
        doc=w.extract(document())
        for scope in (None,1,'1',{},[0],[-1],[2],[True],[1.0],['1'],[1,1],list(range(1,22))):
            with self.subTest(scope=scope):
                with self.assertRaisesRegex(ValueError,'INVALID_PAGES'):
                    w.search(doc,['독감'],pages=scope)

    def test_context_returns_exact_neighbors_and_next_page(self):
        d=fitz.open();p=d.new_page()
        for y,text in [(70,'Heading'),(140,'Payment reasons'),(220,'Ingredient list')]:p.insert_text((70,y),text)
        p=d.new_page();p.insert_text((70,70),'Continuation')
        data=d.tobytes();doc=w.extract(data);hit=w.search(doc,['Heading'])['hits'][0]
        result=w.context(doc,1,hit['start'],hit['end'],after=2,nextPage=True)
        self.assertEqual(len(result['hits']),4)
        self.assertTrue(any('Payment reasons' in h['quote'] for h in result['hits']))
        self.assertEqual(result['hits'][-1]['page'],2)
        for h in result['hits']:
            w.verify(doc,h)
            self.assertEqual(h['quote'],h['matchedText'])
        _,count,skipped=w.annotate(data,doc,result['hits'])
        self.assertEqual((count,skipped),(4,0))
        with self.assertRaisesRegex(ValueError,'INVALID_CONTEXT'):w.context(doc,1,-1)

    def test_worker_reextracts_before_annotation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);pdf=root/'x.pdf';idx=root/'x.json.gz';pdf.write_bytes(document())
            w.main({'op':'index','pdf':str(pdf),'index':str(idx)})
            with w.gzip.open(idx,'rt') as f:doc=w.json.load(f)
            doc['pages'][0]['text']=doc['pages'][0]['text'].replace('독감','변조')
            with w.gzip.open(idx,'wt') as f:w.json.dump(doc,f)
            hits=w.search(doc,['변조'])['hits']
            with self.assertRaisesRegex(ValueError,'SOURCE_INTEGRITY'):
                w.main({'op':'annotate','pdf':str(pdf),'index':str(idx),'hits':hits,'output':str(root/'out.pdf')})

if __name__=='__main__':unittest.main()
