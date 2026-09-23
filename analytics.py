"""Explicit public-demo rules. Monetary values are integer cents; rates basis points."""
from decimal import Decimal, ROUND_HALF_UP
import pandas as pd

START='2025-01-01'
END='2026-12-31'
AS_OF='2026-09-23'
METRICS=('paid_cents','expected_bonus','realized_bonus','pending_bonus','expected_cn','realized_cn','pending_cn','realized_noi','pending_noi','total_benefits','unvalued_bonus_qty')

def cents(value):
    return int(Decimal(str(value)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))

def normalize_supplier(value, suppliers):
    key=' '.join(str(value).split()).casefold()
    for row in suppliers.to_dict('records'):
        if key in (row['supplier_id'].casefold(),row['name'].casefold()):return row['supplier_id']
    raise ValueError('Unknown supplier')

def analyze(data,start=START,end=AS_OF,supplier='',item=''):
    agreements=data['agreements'].to_dict('records')
    suppliers={r['supplier_id']:r['name'] for r in data['suppliers'].to_dict('records')}
    items={r['item_id']:r for r in data['items'].to_dict('records')}
    def term(s,i,d):
        found=[a for a in agreements if a['supplier_id']==s and a['item_id']==i and a['start']<=d<a['end']]
        if len(found)>1:raise ValueError('Ambiguous synthetic agreement')
        return found[0] if found else None
    def key(s,i,a):return (s,i,a['agreement_id'] if a else 'UNMATCHED')
    grn=[r for r in data['grn'].to_dict('records') if not r['excluded'] and START<=r['date']<=AS_OF]
    cost_basis={}
    # Fixed as-of term cost keeps split-month/range valuations additive.
    for r in grn:
        k=key(r['supplier_id'],r['item_id'],term(r['supplier_id'],r['item_id'],r['date']))
        units=r['quantity']*(items[r['item_id']]['pack_size'] if r['uom']=='BOX' else 1)
        if r['unit_cents']>0:
            value,qty=cost_basis.get(k,(0,0))
            cost_basis[k]=(value+r['quantity']*r['unit_cents'],qty+units)
    rows={};events=[]
    def row_for(s,i,a):
        k=key(s,i,a)
        if k not in rows:
            rows[k]={m:0 for m in METRICS}
            rows[k].update(supplier_id=s,supplier=suppliers[s],item_id=i,description=items[i]['description'] if i in items else 'Other benefits',manufacturer=items[i]['manufacturer'] if i in items else 'Not item-specific',agreement=k[2],period=(a['start']+' to '+a['end']+' (end exclusive)') if a else 'No matching agreement',bonus_rate=a['bonus_bps']/100 if a else 0,cn_rate=a['cn_bps']/100 if a else 0)
        return rows[k]
    def add(s,i,d,a,**values):
        if not(start<=d<=min(end,AS_OF)) or (supplier and s!=supplier) or (item and i!=item):return
        row=row_for(s,i,a)
        for k,v in values.items():row[k]+=v
        events.append(dict(supplier_id=s,item_id=i,date=d,**values))
    for r in grn:
        s,i,d=r['supplier_id'],r['item_id'],r['date'];a=term(s,i,d)
        if r['unit_cents']>0:
            paid=r['quantity']*r['unit_cents']
            add(s,i,d,a,paid_cents=paid,expected_bonus=cents(Decimal(paid)*(a['bonus_bps'] if a else 0)/10000),expected_cn=cents(Decimal(paid)*(a['cn_bps'] if a else 0)/10000))
        else:
            value,qty=cost_basis.get(key(s,i,a),(0,0));units=r['quantity']*(items[i]['pack_size'] if r['uom']=='BOX' else 1)
            add(s,i,d,a,realized_bonus=cents(Decimal(units)*value/qty) if qty else 0,unvalued_bonus_qty=units if not qty else 0)
    headers={r['receipt_id']:r for r in data['cn_headers'].to_dict('records')}
    for detail in data['cn_details'].to_dict('records'):
        h=headers[detail['receipt_id']]
        if h['purchasing_confirmed'] and h['finance_confirmed']:
            s,i,d=h['supplier_id'],detail['item_id'],h['date']
            add(s,i,d,term(s,i,d),realized_cn=detail['amount_cents'])
    for r in data['noi'].to_dict('records'):
        realized=r['purchasing_confirmed'] and r['finance_confirmed']
        add(r['supplier_id'],'NOI',r['date'],None,**{'realized_noi' if realized else 'pending_noi':r['amount_cents']})
    def derived(r):
        r['pending_bonus']=r['expected_bonus']-r['realized_bonus']
        r['pending_cn']=r['expected_cn']-r['realized_cn']
        r['total_benefits']=r['realized_bonus']+r['realized_cn']+r['realized_noi']
        return r
    def status(target,actual,unvalued=0):
        if unvalued:return 'Unvalued quantity'
        if target==0:return 'No target' if actual else 'Zero target'
        return 'Over target' if actual>target else ('Realized' if actual==target else 'Pending reconciliation')
    result=[]
    for r in rows.values():
        derived(r);r['bonus_status']=status(r['expected_bonus'],r['realized_bonus'],r['unvalued_bonus_qty']);r['cn_status']=status(r['expected_cn'],r['realized_cn']);result.append(r)
    # Pandas aggregation of the same item-period ledger feeds every page/export.
    df=pd.DataFrame(result,columns=list(METRICS)+['supplier_id','supplier','item_id','description','manufacturer','agreement','period','bonus_rate','cn_rate','bonus_status','cn_status'])
    vendor=[]
    if not df.empty:
        vendor=df.groupby(['supplier_id','supplier'],sort=True)[list(METRICS)].sum().reset_index().to_dict('records')
    total={m:sum(int(r[m]) for r in vendor) for m in METRICS}
    monthly=[]
    for month in pd.period_range(start=start,end=end,freq='M'):
        label=str(month);r={m:0 for m in METRICS};r['month']=label
        for event in events:
            if event['date'][:7]==label:
                for m in METRICS:r[m]+=event.get(m,0)
        monthly.append(derived(r))
    return dict(rows=sorted(result,key=lambda r:(r['supplier_id'],r['item_id'],r['agreement'])),suppliers=sorted(vendor,key=lambda r:(-r['total_benefits'],r['supplier_id'])),totals=total,monthly=monthly)
