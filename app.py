"""Anonymous read-only Flask analytics; run via Gunicorn, never a debug launcher."""
from datetime import date, datetime
from io import BytesIO
import re
from zipfile import ZipFile
from xml.dom.minidom import parseString
from flask import Flask, abort, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException
from openpyxl import Workbook
import db
from analytics import START, END, AS_OF, analyze, normalize_supplier

app=Flask(__name__)
app.config.update(DEBUG=False,TESTING=False,MAX_CONTENT_LENGTH=0,MAX_FORM_MEMORY_SIZE=0)
TITLE='Supplier Benefits & Procurement Reconciliation Analytics'
BONUS_COLUMNS=('supplier','item_id','description','manufacturer','agreement','period','paid_cents','bonus_rate','expected_bonus','realized_bonus','pending_bonus','bonus_status','unvalued_bonus_qty')
CN_COLUMNS=('supplier','item_id','description','manufacturer','agreement','period','paid_cents','cn_rate','expected_cn','realized_cn','pending_cn','cn_status')
RECORD_COLUMNS=('record_id','supplier','date','benefit_type','payment_type','amount_cents','confirmation')
LABELS={'supplier':'Supplier','supplier_id':'Supplier ID','item_id':'Item','description':'Description','manufacturer':'Manufacturer','agreement':'Agreement','period':'Agreement period','paid_cents':'Paid value (AED)','bonus_rate':'Negotiated bonus (%)','cn_rate':'Negotiated CN (%)','expected_bonus':'Expected bonus (AED)','realized_bonus':'Realized bonus (AED)','pending_bonus':'Pending bonus (AED)','expected_cn':'Expected CN (AED)','realized_cn':'Realized CN (AED)','pending_cn':'Pending CN (AED)','bonus_status':'Status','cn_status':'Status','unvalued_bonus_qty':'Unvalued base units','record_id':'Record','date':'Date','benefit_type':'Benefit type','payment_type':'Payment type','amount_cents':'Value (AED)','confirmation':'Confirmation','start':'Effective from','end':'Effective to (exclusive)','bonus_bps':'Bonus (%)','cn_bps':'CN (%)','total_benefits':'Total benefits (AED)'}
MONEY={'paid_cents','expected_bonus','realized_bonus','pending_bonus','expected_cn','realized_cn','pending_cn','realized_noi','pending_noi','total_benefits','amount_cents'}

@app.template_filter('display')
def display(value,key):
    if key in MONEY:return f'{value/100:,.2f}'
    if key in ('bonus_bps','cn_bps'):return f'{value/100:.2f}'
    return value

@app.before_request
def boundary():
    if request.method not in ('GET','HEAD'):abort(405)
    if request.content_length or request.headers.get('Transfer-Encoding'):abort(400)
    if len(request.query_string)>1024:abort(400)
    if request.path.startswith('/static/') and request.query_string:abort(400)

@app.after_request
def headers(response):
    response.headers.update({'Content-Security-Policy':"default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'",'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY','Permissions-Policy':'camera=(), microphone=(), geolocation=()','Cache-Control':'no-store'})
    return response

@app.errorhandler(Exception)
def error(exc):
    if isinstance(exc,HTTPException):code=exc.code
    else:
        code=503
        # Type only: don't log values, paths, SQL, filters or exception messages.
        app.logger.error('Analytics request failed; exception_type=%s',type(exc).__name__)
    return render_template('error.html',title=TITLE,code=code),code

def filters(data,extra=()):
    allowed={'start_date','end_date','supplier','item','q',*extra}
    if set(request.args)-allowed:abort(400)
    if any(len(request.args.getlist(k))!=1 or len(v)>80 for k,v in request.args.items()):abort(400)
    start=request.args.get('start_date') or START;end=request.args.get('end_date') or AS_OF
    for value in (start,end):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):abort(400)
        try:date.fromisoformat(value)
        except ValueError:abort(400)
        if not START<=value<=END:abort(400)
    start,end=sorted((start,end))
    supplier=request.args.get('supplier','');item=request.args.get('item','')
    if supplier:
        try:supplier=normalize_supplier(supplier,data['suppliers'])
        except ValueError:abort(400)
    if item and (not re.fullmatch(r'ITEM-\d{3}',item) or item not in set(data['items']['item_id'])):abort(400)
    q=request.args.get('q','').strip()
    if any(ord(c)<32 for c in q):abort(400)
    return dict(start_date=start,end_date=end,supplier=supplier,item=item,q=q)

def search(rows,q):
    return [r for r in rows if not q or q.casefold() in ' '.join(str(v) for v in r.values()).casefold()]

def records(data,f):
    names=dict(zip(data['suppliers'].supplier_id,data['suppliers'].name));out=[]
    for r in data['noi'].to_dict('records'):
        if f['item']:continue # not item-allocated
        out.append(dict(record_id=r['record_id'],supplier_id=r['supplier_id'],supplier=names[r['supplier_id']],date=r['date'],benefit_type=r['benefit_type'],payment_type=r['payment_type'],amount_cents=r['amount_cents'],confirmation='Dual confirmed' if r['purchasing_confirmed'] and r['finance_confirmed'] else 'Partially / not confirmed'))
    # In item-filter view CN records use that item's allocated amount, not whole header.
    details=data['cn_details'].to_dict('records')
    for r in data['cn_headers'].to_dict('records'):
        amount=r['amount_cents']
        if f['item']:
            matching=[d for d in details if d['receipt_id']==r['receipt_id'] and d['item_id']==f['item']]
            if not matching:continue
            amount=sum(d['amount_cents'] for d in matching)
        out.append(dict(record_id=r['receipt_id'],supplier_id=r['supplier_id'],supplier=names[r['supplier_id']],date=r['date'],benefit_type='Credit note / rebate',payment_type='Credit note',amount_cents=amount,confirmation='Dual confirmed' if r['purchasing_confirmed'] and r['finance_confirmed'] else 'Partially / not confirmed'))
    return [r for r in out if f['start_date']<=r['date']<=min(f['end_date'],AS_OF) and (not f['supplier'] or r['supplier_id']==f['supplier'])]

def context():
    data=db.load();f=filters(data);a=analyze(data,f['start_date'],f['end_date'],f['supplier'],f['item'])
    return data,f,a

def page(kind):
    data,f,a=context();columns=();rows=[]
    if kind=='Bonus Tracking':columns=BONUS_COLUMNS;rows=[r for r in a['rows'] if r['item_id']!='NOI']
    elif kind=='CN / Rebate Tracking':columns=CN_COLUMNS;rows=[r for r in a['rows'] if r['item_id']!='NOI']
    elif kind=='Benefits / NOI Records':columns=RECORD_COLUMNS;rows=records(data,f)
    elif kind=='Agreements':
        columns=('agreement_id','supplier','item_id','start','end','bonus_bps','cn_bps')
        names=dict(zip(data['suppliers'].supplier_id,data['suppliers'].name))
        rows=[dict(r,supplier=names[r['supplier_id']]) for r in data['agreements'].to_dict('records') if r['start']<=f['end_date'] and r['end']>f['start_date'] and (not f['supplier'] or f['supplier']==r['supplier_id']) and (not f['item'] or f['item']==r['item_id'])]
    if kind=='Dashboard':
        columns=('supplier','paid_cents','realized_bonus','realized_cn','realized_noi','total_benefits');rows=a['suppliers']
    maximum=max((r['total_benefits'] for r in a['monthly']),default=1) or 1
    chart=[dict(r,height=round(125*r['total_benefits']/maximum,2),x=22+i*27) for i,r in enumerate(a['monthly'])]
    download={'Bonus Tracking':'download_summary','CN / Rebate Tracking':'download_cn_tracking','Benefits / NOI Records':'export_noi_management'}.get(kind)
    return render_template('page.html',title=TITLE,kind=kind,f=f,a=a,rows=search(rows,f['q']),columns=columns,labels=LABELS,suppliers=data['suppliers'].to_dict('records'),items=data['items'].to_dict('records'),chart=chart,chart_width=max(320,len(chart)*27+44),download=download,as_of=AS_OF,targets=data['targets'].to_dict('records'))

@app.get('/')
def index():return page('Dashboard')
@app.get('/summary')
def summary_dashboard():return page('Bonus Tracking')
@app.get('/cn-rebates')
def cn_rebates():return page('CN / Rebate Tracking')
@app.get('/agreements')
def agreements():return page('Agreements')
@app.get('/noi-management')
def noi_management():return page('Benefits / NOI Records')

@app.get('/api/item-lookup')
def item_lookup():
    if set(request.args)!={'item_code'} or len(request.args.getlist('item_code'))!=1:abort(400)
    code=request.args['item_code']
    if not re.fullmatch(r'ITEM-\d{3}',code):abort(400)
    data=db.load();rows=data['items'][data['items'].item_id==code]
    if rows.empty:abort(404)
    return jsonify(item=rows.to_dict('records')[0])

@app.get('/health')
def health():
    if request.query_string:abort(400)
    conn=db.connect()
    try:conn.execute('SELECT 1 FROM metadata LIMIT 1').fetchone()
    finally:conn.close()
    return jsonify(status='ok')

def safe_cell(value):
    if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')):return "'"+value
    return value

def workbook(rows,columns):
    if len(rows)>5000:raise ValueError('Export limit')
    wb=Workbook();ws=wb.active;ws.title='Synthetic analysis'
    wb.properties.creator='Portfolio Demo';wb.properties.lastModifiedBy='Portfolio Demo'
    wb.properties.created=wb.properties.modified=datetime(2026,9,23)
    ws.append([LABELS.get(c,c.replace('_',' ').title()) for c in columns])
    for row in rows:
        ws.append([safe_cell(row[c]/100 if c in MONEY else row.get(c,'')) for c in columns])
    ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
    raw=BytesIO();wb.save(raw)
    # openpyxl overwrites modified on save. Normalize final OOXML properties
    # and ZIP timestamps locally; preserve every other package member's bytes.
    out=BytesIO()
    with ZipFile(raw) as source, ZipFile(out,'w') as target:
        for entry in source.infolist():
            content=source.read(entry.filename)
            if entry.filename=='docProps/core.xml':
                core=parseString(content)
                for name in ('created','modified'):
                    nodes=core.getElementsByTagNameNS('http://purl.org/dc/terms/',name)
                    if len(nodes)!=1:raise ValueError('Export metadata structure')
                    nodes[0].firstChild.nodeValue='2026-09-23T00:00:00Z'
                content=core.toxml(encoding='utf-8')
                core.unlink()
            entry.date_time=(2026,9,23,0,0,0)
            target.writestr(entry,content)
    out.seek(0)
    if out.getbuffer().nbytes>5_000_000:raise ValueError('Export size limit')
    return out

def export(kind):
    data,f,a=context()
    if kind=='bonus':columns=BONUS_COLUMNS;rows=[r for r in a['rows'] if r['item_id']!='NOI']
    elif kind=='cn':columns=CN_COLUMNS;rows=[r for r in a['rows'] if r['item_id']!='NOI']
    else:columns=RECORD_COLUMNS;rows=records(data,f)
    return send_file(workbook(search(rows,f['q']),columns),as_attachment=True,download_name=f'synthetic-{kind}-analysis.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
@app.get('/download_summary')
def download_summary():return export('bonus')
@app.get('/cn-rebates/download')
def download_cn_tracking():return export('cn')
@app.get('/noi-management/export')
def export_noi_management():return export('benefits')
