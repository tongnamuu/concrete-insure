"""Local-only PDF verification; never copies supplied PDFs into the project."""
import importlib.util,json,sys,tempfile,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('worker',Path(__file__).parents[1]/'python/pdf_worker.py');w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
for name in sys.argv[1:]:
    pdf=Path(name).resolve()
    with tempfile.TemporaryDirectory() as folder:
        p={'pdf':str(pdf),'index':str(Path(folder)/'index.gz')}
        start=time.monotonic();meta=w.main(dict(p,op='index'));index_seconds=time.monotonic()-start
        start=time.monotonic();found=w.main(dict(p,op='search',terms=['독감','보험']));search_seconds=time.monotonic()-start
        start=time.monotonic();out=Path(folder)/'annotated.pdf';annot=w.main(dict(p,op='annotate',hits=found['hits'][:3],output=str(out)));annotate_seconds=time.monotonic()-start
        original=w.fitz.open(pdf);marked=w.fitz.open(out)
        assert len(original)==len(marked)
        assert all(a.get_text()==b.get_text() for a,b in zip(original,marked))
        print(json.dumps({'file':pdf.name,'bytes':pdf.stat().st_size,**meta,'indexSeconds':round(index_seconds,3),'searchSeconds':round(search_seconds,3),'annotateSeconds':round(annotate_seconds,3),'indexBytes':Path(p['index']).stat().st_size,'hits':len(found['hits']),**annot,'textUnchanged':True}),flush=True)
