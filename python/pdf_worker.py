"""Isolated PDF operations. Coordinates are recovered from original text-layer glyphs."""
import base64, gzip, hashlib, json, math, struct, sys
from pathlib import Path
import pymupdf as fitz
REC = struct.Struct('<II8d')
def require(ok, code):
    if not ok: raise ValueError(code)
def digest(data): return hashlib.sha256(data).hexdigest()
def character_quad(line, span, char, inverse):
    """Equivalent horizontal recover_char_quad geometry without allocating a Quad.

    Point transforms deliberately remain PyMuPDF operations (float semantics
    match its annotation API). Other writing directions use the library itself.
    """
    try:
        if tuple(line['dir']) == (1, 0):
            x0,y0,x1,y1=char['bbox']
            height=(1 if fitz.TOOLS.set_small_glyph_heights() else span['ascender']-span['descender'])*span['size']
            if not (x1>x0 and height>0): return None
            points=((x0,y1),(x1,y0+height),(x1,y0),(x0,y1-height))
            # A malformed font can produce a crossed quadrilateral.
            if y0+height<=y0 or y1<=y1-height:return None
            pts=[fitz.Point(*p)*inverse for p in points]
        else:
            q=fitz.recover_char_quad(line['dir'],span,char)
            if not q.is_convex:return None
            pts=[p*inverse for p in (q.ll,q.lr,q.ur,q.ul)]
        quad=[v for p in pts for v in (p.x,p.y)]
        return quad if all(math.isfinite(v) for v in quad) else None
    except (ValueError,ZeroDivisionError): return None

def extract(data):
    require(data.startswith(b'%PDF-'), 'INVALID_PDF')
    pages=[]; total=0
    with fitz.open(stream=data,filetype='pdf') as doc:
        require(not doc.needs_pass,'ENCRYPTED_PDF');require(len(doc)<=1000,'PDF_PAGE_LIMIT')
        for page in doc:
            rotation=page.rotation;page.set_rotation(0);inv=~page.transformation_matrix
            parts=[]; packed=bytearray();blocks=[];position=0
            for block in page.get_text('rawdict',sort=False,flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks']:
                start=position
                for line in block.get('lines',[]):
                    for span in line['spans']:
                        for char in span['chars']:
                            c=char['c'];end=position+len(c);quad=None
                            quad=character_quad(line,span,char,inv)
                            packed.extend(REC.pack(position,end,*(quad or [math.nan]*8)))
                            parts.append(c);position=end
                    parts.append('\n');position+=1
                if position>start:blocks.append([start,position])
            total+=position;require(total<=2000000,'PDF_TEXT_LIMIT')
            pages.append({'number':page.number+1,'rotation':rotation,'text':''.join(parts),'blocks':blocks,'chars':base64.b64encode(packed).decode()})
    return {'hash':digest(data),'offsetEncoding':'unicode-code-points','pages':pages,'characters':total}
def geometry(page,start,end):
    raw=base64.b64decode(page['chars'],validate=True); result=[]
    require(len(raw)%REC.size==0,'SOURCE_INTEGRITY')
    lo,hi=0,len(raw)//REC.size
    while lo<hi:
        mid=(lo+hi)//2
        if REC.unpack_from(raw,mid*REC.size)[1]<=start:lo=mid+1
        else:hi=mid
    for i in range(lo*REC.size,len(raw),REC.size):
        a,b,*q=REC.unpack_from(raw,i)
        if a>=end:break
        if b>start:result.append({'index':i//REC.size,'start':a,'end':b,'quad':q if all(math.isfinite(v) for v in q) else None})
    return result
def make_hit(doc,page,start,end):
    blocks=[x for x in page['blocks'] if x[0]<=start<x[1]]
    a,b=blocks[0] if blocks else (start,end)
    if b-a>3000:
        a=max(a,page['text'].rfind('\n',0,start)+1); n=page['text'].find('\n',end);b=min(b,n if n>=0 else b)
    b=max(b,end)
    return {'id':f'{page["number"]}:{start}:{end}','page':page['number'],'start':start,'end':end,'sourceStart':a,'sourceEnd':b,'quote':page['text'][a:b],'matchedText':page['text'][start:end],'segments':geometry(page,start,end),'documentHash':doc['hash'],'offsetEncoding':'unicode-code-points'}
_ALL_PAGES = object()
def search(doc,terms,pages=_ALL_PAGES):
    # Omitted scope searches the whole document; explicit [] searches nothing.
    selected=doc['pages']
    if pages is not _ALL_PAGES:
        require(type(pages) is list and len(pages)<=20,'INVALID_PAGES')
        require(all(type(n) is int and 1<=n<=len(doc['pages']) for n in pages),'INVALID_PAGES')
        require(len(set(pages))==len(pages),'INVALID_PAGES')
        scope=set(pages)
        selected=[page for page in doc['pages'] if page['number'] in scope]
    hits=[];seen=set();truncated=False
    for term in terms:
        require(isinstance(term,str) and 0<len(term)<=120,'INVALID_TERM')
        count=0;capped=False
        for page in selected:
            pos=0
            while (pos:=page['text'].find(term,pos))>=0:
                hit=make_hit(doc,page,pos,pos+len(term));pos+=len(term)
                if hit['id'] in seen:continue
                if count>=40 or len(hits)>=160:truncated=True;capped=True;break
                seen.add(hit['id']);hits.append(hit);count+=1
            if capped:break
    return {'hits':hits,'truncated':truncated}
def context(doc, page, start, end=None, before=0, after=3, nextPage=False):
    """Return bounded neighboring source blocks, never model-authored text."""
    require(type(page) is int and 1<=page<=len(doc['pages']),'INVALID_CONTEXT')
    require(type(before) is int and 0<=before<=2 and type(after) is int and 0<=after<=4,'INVALID_CONTEXT')
    require(type(nextPage) is bool,'INVALID_CONTEXT')
    p=doc['pages'][page-1]
    end=start+1 if end is None else end
    require(type(start) is int and type(end) is int and 0<=start<end<=len(p['text']),'INVALID_CONTEXT')
    indices=[i for i,(a,b) in enumerate(p['blocks']) if a<end and b>start]
    require(bool(indices),'INVALID_CONTEXT')
    selected=[(p,a,b) for a,b in p['blocks'][max(0,indices[0]-before):indices[-1]+after+1]]
    if nextPage and page<len(doc['pages']):
        following=doc['pages'][page]
        selected.extend((following,a,b) for a,b in following['blocks'][:2])
    hits=[];characters=0;truncated=False
    for source,a,b in selected:
        if len(hits)>=8 or characters+b-a>12000:
            truncated=True;break
        hits.append(make_hit(doc,source,a,b));characters+=b-a
    return {'hits':hits,'truncated':truncated}

def verify(doc,hit):
    require(type(hit.get('page')) is int and 1<=hit['page']<=len(doc['pages']),'SOURCE_INTEGRITY')
    p=doc['pages'][hit['page']-1]
    require(type(hit.get('start')) is int and type(hit.get('end')) is int and 0<=hit['start']<hit['end']<=len(p['text']),'SOURCE_INTEGRITY')
    require(hit==make_hit(doc,p,hit['start'],hit['end']),'SOURCE_INTEGRITY')
def annotate(data,doc,hits):
    require(digest(data)==doc['hash'],'SOURCE_INTEGRITY');count=0;skipped=0;seen=set()
    with fitz.open(stream=data,filetype='pdf') as pdf:
        for hit in hits:
            verify(doc,hit)
            if hit['id'] in seen:continue
            seen.add(hit['id']);page=pdf[hit['page']-1];rotation=page.rotation;page.set_rotation(0);quads=[]
            for s in hit['segments']:
                if s['quad'] is None:skipped+=1;continue
                q=s['quad'];ll,lr,ur,ul=[fitz.Point(q[i],q[i+1])*page.transformation_matrix for i in range(0,8,2)]
                quads.append(fitz.Quad(ul,ur,ll,lr))
            if quads:
                a=page.add_highlight_annot(quads);a.set_colors(stroke=(1,.82,.12));a.set_opacity(.3)
                a.set_info(title='InsureLens',content=hit['quote']);a.update();count+=1
            page.set_rotation(rotation)
        return pdf.tobytes(garbage=3,deflate=True),count,skipped

def main(p):
    op=p['op'];data=Path(p['pdf']).read_bytes();require(len(data)<=20*1024*1024,'PDF_SIZE_LIMIT')
    if op=='index':
        doc=extract(data)
        with gzip.open(p['index'],'wt',encoding='utf8',compresslevel=1) as f:json.dump(doc,f,ensure_ascii=False,separators=(',',':'))
        return {'hash':doc['hash'],'pages':len(doc['pages']),'characters':doc['characters'],'textPages':sum(bool(x['text'].strip()) for x in doc['pages'])}
    if op=='render':
        with fitz.open(stream=data,filetype='pdf') as d:
            require(len(d)<=8,'PRESCRIPTION_PAGE_LIMIT')
            images=[]
            for page in d:
                require(page.rect.width>0 and page.rect.height>0,'INVALID_PDF_PAGE')
                scale=min(1.5,2400/max(page.rect.width,page.rect.height))
                pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
                images.append(base64.b64encode(pix.tobytes('png')).decode())
            return {'images':images}
    with gzip.open(p['index'],'rt',encoding='utf8') as f:doc=json.load(f)
    require(doc['hash']==digest(data),'SOURCE_INTEGRITY')
    if op=='text':return {'text':'\n'.join(x['text'] for x in doc['pages'])[:50000]}
    if op=='search':return search(doc,p['terms'],**({'pages':p['pages']} if 'pages' in p else {}))
    if op=='context':return context(doc,p['page'],p['start'],p.get('end'),p.get('before',0),p.get('after',3),p.get('nextPage',False))
    if op=='annotate':
        # Re-extract from the original PDF so a modified index cannot forge coordinates.
        fresh=extract(data);output,count,skipped=annotate(data,fresh,p['hits']);Path(p['output']).write_bytes(output)
        return {'count':count,'skipped':skipped}
    raise ValueError('UNKNOWN_OPERATION')
if __name__=='__main__':
    try:result={'value':main(json.loads(sys.stdin.read(8*1024*1024)))}
    except Exception as e:result={'error':str(e) if isinstance(e,ValueError) else 'PDF_PROCESSING_FAILED'}
    print(json.dumps(result,ensure_ascii=False,separators=(',',':')))
