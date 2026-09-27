"""Isolated PDF operations. Coordinates are recovered from original text-layer glyphs."""
import base64, gzip, hashlib, json, math, re, struct, sys, unicodedata
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
        if not visible_text(source['text'][a:b]):continue
        if len(hits)>=8 or characters+b-a>12000:
            truncated=True;break
        hits.append(make_hit(doc,source,a,b));characters+=b-a
    return {'hits':hits,'truncated':truncated}

def visible_text(text):
    # Detection only. Never trim, normalize or rewrite a returned source span.
    return any(not ch.isspace() and not unicodedata.category(ch).startswith('C') for ch in text)

def heading_text(text):
    return ''.join(ch for ch in text if not ch.isspace() and not unicodedata.category(ch).startswith('C'))

def section_title(text):
    t=heading_text(text)
    return bool(re.match(r'^\d+(?:[-.]\d+)+',t) and ('특별약관' in t or '특약' in t) and len(t)<240 and not re.search(r'\.{3,}|…{2,}',t))

def article_kind(text):
    t=heading_text(text)
    if not re.match(r'^제\d+조(?:의\d+)?[（(]',t):return None
    # Clause headings may contain nested disease-name parentheses.
    canonical=t.replace('（','(').replace('）',')');begin=canonical.find('(');depth=0;finish=len(canonical)
    for i in range(begin,len(canonical)):
        if canonical[i]=='(':depth+=1
        elif canonical[i]==')':
            depth-=1
            if depth==0:finish=i+1;break
    title=canonical[:finish]
    if re.search(r'보험금(?:의)?지급사유|보험금을지급하는사유|보상하는손해',title):return 'payment'
    if re.search(r'보험금을지급하지않는사유|보장하지않는손해|보상하지않는손해',title):return 'exclusion'
    if '정의' in title or '진단확정' in title:return 'definition'
    if re.search(r'보험금(?:의)?청구',title):return 'claim'
    return 'other'

def policy_sections(doc,anchors):
    """Bounded source-only rider/article grouping. Unsupported layouts remain unresolved."""
    require(type(anchors) is list and len(anchors)<=12,'INVALID_SECTION_ANCHORS')
    for anchor in anchors:verify(doc,anchor)
    flat=[(p,a,b) for p in doc['pages'] for a,b in p['blocks'] if visible_text(p['text'][a:b])]
    titles=[i for i,(p,a,b) in enumerate(flat) if section_title(p['text'][a:b])]
    selected=[]
    for anchor in anchors:
        pos=next((i for i,(p,a,b) in enumerate(flat) if p['number']==anchor['page'] and a<=anchor['start']<b),None)
        candidates=[i for i in titles if pos is not None and i<=pos]
        if not candidates:continue
        owner=candidates[-1]
        if anchor['page']-flat[owner][0]['number']>6:continue
        if owner not in selected:selected.append(owner)
    sections=[];truncated=len(selected)>4;characters=0
    for owner in selected[:4]:
        p,a,b=flat[owner];title=make_hit(doc,p,a,b)
        end=next((i for i in titles if i>owner),len(flat))
        articles=[];current=None;partial=False;used=0
        for source,start,stop in flat[owner+1:end]:
            if source['number']-p['number']>6 or used+stop-start>10000 or characters+stop-start>20000:
                partial=True;truncated=True;break
            kind=article_kind(source['text'][start:stop])
            if kind is not None:
                current={'kind':kind,'heading':make_hit(doc,source,start,stop),'hits':[]}
                articles.append(current)
            if current is not None and current['kind']!='other':
                # Exclude recurring page furniture only; the extraction remains immutable.
                text=source['text'][start:stop]
                if re.match(r'^\d+\s*\n무배당',text):continue
                h=make_hit(doc,source,start,stop);current['hits'].append(h)
                used+=stop-start;characters+=stop-start
        clauses=[x for x in articles if x['kind']!='other' and x['hits']]
        # Keep each article contiguous within a page, including original whitespace.
        # This avoids presenting table cells and sentence fragments as separate cards.
        for clause in clauses:
            merged=[]
            for hit in clause['hits']:
                if merged and merged[-1]['page']==hit['page']:
                    prior=merged.pop();source=doc['pages'][hit['page']-1]
                    merged.append(make_hit(doc,source,prior['start'],hit['end']))
                else:merged.append(hit)
            clause['hits']=merged;clause['heading']=merged[0]
        if clauses:sections.append({'id':title['id'],'title':title,'clauses':clauses,'truncated':partial})
    return {'sections':sections,'truncated':truncated}

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
    if op=='sections':return policy_sections(doc,p['anchors'])
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
