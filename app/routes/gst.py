from flask import Blueprint, render_template, request, session, jsonify, make_response, flash, redirect, url_for
from flask_login import login_required
from app.models import Voucher, VoucherItem, Company, HSNCode, GSTRate
import io, csv
from app import db
from sqlalchemy import func
from datetime import date
import calendar
import json
import re
from lxml import html

gst_bp = Blueprint('gst', __name__)

@gst_bp.before_request
@login_required
def check_gst_enabled():
    cid = session.get('company_id')
    if not cid: return
    company = Company.query.get(cid)
    if company and not company.enable_gst:
        flash('GST features are disabled for this company.', 'warning')
        return redirect(url_for('dashboard.index'))

def get_cid():
    return session.get('company_id', 1)

def _company():
    return Company.query.get(get_cid())

def _is_composition(company):
    return (company.gst_registration_type or '').lower() == 'composition'

def _month_period(month=None):
    month = month or date.today().strftime('%Y-%m')
    try:
        year, mon = map(int, month.split('-'))
        from_date = date(year, mon, 1)
    except Exception:
        month = date.today().strftime('%Y-%m')
        year, mon = map(int, month.split('-'))
        from_date = date(year, mon, 1)
    to_date = date(year, mon, calendar.monthrange(year, mon)[1])
    return month, year, mon, from_date, to_date

def _fp(mon, year):
    return f"{mon:02d}{year}"

def _money(value):
    return round(float(value or 0), 2)

def _voucher_period_query(cid, vtypes, from_date, to_date):
    if isinstance(vtypes, str):
        vtypes = [vtypes]
    return Voucher.query.filter(
        Voucher.company_id == cid,
        Voucher.is_cancelled == False,
        Voucher.is_trash == False,
        Voucher.voucher_type.in_(vtypes),
        Voucher.date >= from_date,
        Voucher.date <= to_date,
    )

def _sum_vouchers(vouchers):
    return {
        'taxable': _money(sum(v.taxable_amount or 0 for v in vouchers)),
        'igst': _money(sum(v.igst_amount or 0 for v in vouchers)),
        'cgst': _money(sum(v.cgst_amount or 0 for v in vouchers)),
        'sgst': _money(sum(v.sgst_amount or 0 for v in vouchers)),
        'cess': _money(sum(v.cess_amount or 0 for v in vouchers)),
        'total': _money(sum(v.total_amount or 0 for v in vouchers)),
    }

def _json_download(payload, filename):
    response = make_response(json.dumps(payload, indent=2, ensure_ascii=False))
    response.headers['Content-Type'] = 'application/json'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

def _csv_download(text, filename):
    response = make_response(text)
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

def _require_scheme(company, scheme):
    wants_composition = scheme == 'composition'
    if _is_composition(company) != wants_composition:
        flash(
            'This return is available for Composition companies only.' if wants_composition
            else 'This return is available for Regular GST companies only.',
            'warning'
        )
        return redirect(url_for('gst.index'))
    return None

@gst_bp.route('/')
@login_required
def index():
    cid = get_cid()
    company = Company.query.get(cid)
    return render_template('gst/index.html', company=company)

@gst_bp.route('/gstr4')
@login_required
def gstr4():
    cid = get_cid()
    company = _company()
    guard = _require_scheme(company, 'composition')
    if guard: return guard
    month, year, mon, from_date, to_date = _month_period(request.args.get('month'))
    
    # Inward supplies from registered dealers (B2B Purchases)
    purchases = _voucher_period_query(cid, 'Purchase', from_date, to_date).all()
    
    b2b_purchases = [v for v in purchases if v.party and v.party.gstin]
    
    # Outward supplies (Sales) - Total Turnover
    sales_vouchers = _voucher_period_query(cid, 'Sales', from_date, to_date).all()
    
    total_turnover = sum(v.taxable_amount or v.total_amount or 0 for v in sales_vouchers)
    flat_tax_rate = company.composition_rate or 0
    flat_tax_amount = (total_turnover * flat_tax_rate) / 100
    
    return render_template('gst/gstr4.html', company=company, month=month,
        b2b_purchases=b2b_purchases, total_turnover=total_turnover,
        flat_tax_rate=flat_tax_rate, flat_tax_amount=flat_tax_amount,
        from_date=from_date, to_date=to_date)

@gst_bp.route('/gstr4/json')
@login_required
def gstr4_json():
    cid = get_cid()
    company = _company()
    guard = _require_scheme(company, 'composition')
    if guard: return guard
    month, year, mon, from_date, to_date = _month_period(request.args.get('month'))
    
    # Inward supplies from registered dealers (B2B Purchases)
    purchases = _voucher_period_query(cid, 'Purchase', from_date, to_date).all()
    
    b2b_purchases = [v for v in purchases if v.party and v.party.gstin]
    
    # Outward supplies (Sales) - Total Turnover
    sales_vouchers = _voucher_period_query(cid, 'Sales', from_date, to_date).all()
    
    total_turnover = sum(v.taxable_amount or v.total_amount or 0 for v in sales_vouchers)
    flat_tax_rate = company.composition_rate or 0
    flat_tax_amount = (total_turnover * flat_tax_rate) / 100
    
    b2b_map = {}
    for v in b2b_purchases:
        gstin = v.party.gstin.upper()
        if gstin not in b2b_map:
            b2b_map[gstin] = {'ctin': gstin, 'inv': []}
            
        items_list = []
        for item in v.items:
            items_list.append({
                'num': len(items_list) + 1,
                'itm_det': {
                    'txval': round(item.taxable_amount, 2),
                    'rt': item.gst_rate,
                    'iamt': round(item.igst_amount, 2),
                    'camt': round(item.cgst_amount, 2),
                    'samt': round(item.sgst_amount, 2),
                    'csamt': round(item.cess_amount, 2),
                }
            })
            
        b2b_map[gstin]['inv'].append({
            'inum': v.ref_number or v.voucher_number,
            'idt': v.date.strftime('%d-%m-%Y'),
            'val': round(v.total_amount, 2),
            'pos': (v.place_of_supply or company.state_code or '')[:2],
            'rchrg': 'Y' if v.reverse_charge else 'N',
            'inv_typ': 'R',
            'itms': items_list,
        })
        
    txos_data = []
    if total_turnover > 0:
        cgst_amt = flat_tax_amount / 2
        sgst_amt = flat_tax_amount / 2
        txos_data.append({
            'rt': flat_tax_rate,
            'txval': round(total_turnover, 2),
            'camt': round(cgst_amt, 2),
            'samt': round(sgst_amt, 2),
            'iamt': 0.0,
            'csamt': 0.0
        })
        
    gstr4_data = {
        'gstin': company.gstin or '',
        'fp': _fp(mon, year),
        'version': 'GST4.0.0',
        'hash': 'hash',
        'b2b': list(b2b_map.values()),
        'txos': txos_data
    }
    
    return _json_download(gstr4_data, f'GSTR4_{month}_GSTN.json')

@gst_bp.route('/gstr4/export-csv')
@login_required
def gstr4_export_csv():
    cid = get_cid()
    company = _company()
    guard = _require_scheme(company, 'composition')
    if guard: return guard
    month, year, mon, from_date, to_date = _month_period(request.args.get('month'))

    purchases = _voucher_period_query(cid, 'Purchase', from_date, to_date).all()
    b2b_purchases = [v for v in purchases if v.party and v.party.gstin]
    sales_vouchers = _voucher_period_query(cid, 'Sales', from_date, to_date).all()
    total_turnover = sum(v.taxable_amount or v.total_amount or 0 for v in sales_vouchers)
    flat_tax_rate = company.composition_rate or 0
    flat_tax_amount = (total_turnover * flat_tax_rate) / 100

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Company', company.name, 'GSTIN', company.gstin or '', 'Period', month])
    writer.writerow([])
    writer.writerow(['Summary', 'Amount'])
    writer.writerow(['Taxable Turnover', _money(total_turnover)])
    writer.writerow(['Composition Rate %', flat_tax_rate])
    writer.writerow(['Tax Payable', _money(flat_tax_amount)])
    writer.writerow(['B2B Purchases', _money(sum(v.total_amount or 0 for v in b2b_purchases))])
    writer.writerow([])
    writer.writerow(['Date', 'Voucher/Ref', 'Supplier', 'GSTIN', 'Taxable', 'GST Paid', 'Total'])
    for v in b2b_purchases:
        writer.writerow([
            v.date.strftime('%d/%m/%Y') if v.date else '',
            v.ref_number or v.voucher_number,
            v.party.name if v.party else '',
            v.party.gstin if v.party else '',
            _money(v.taxable_amount),
            _money((v.igst_amount or 0) + (v.cgst_amount or 0) + (v.sgst_amount or 0)),
            _money(v.total_amount),
        ])
    return _csv_download(output.getvalue(), f'GSTR4_{month}.csv')

@gst_bp.route('/cmp08/json')
@login_required
def cmp08_json():
    cid = get_cid()
    company = _company()
    guard = _require_scheme(company, 'composition')
    if guard: return guard
    month, year, mon, from_date, to_date = _month_period(request.args.get('month'))
    
    rc_purchases = _voucher_period_query(cid, 'Purchase', from_date, to_date)\
        .filter(Voucher.reverse_charge == True).all()
        
    sales_vouchers = _voucher_period_query(cid, 'Sales', from_date, to_date).all()
        
    total_outward = sum(v.taxable_amount or v.total_amount or 0 for v in sales_vouchers)
    flat_tax_rate = company.composition_rate or 0
    tax_on_outward = (total_outward * flat_tax_rate) / 100
    
    total_rc_taxable = sum(v.taxable_amount for v in rc_purchases)
    total_rc_cgst = sum(v.cgst_amount for v in rc_purchases)
    total_rc_sgst = sum(v.sgst_amount for v in rc_purchases)
    total_rc_igst = sum(v.igst_amount for v in rc_purchases)
    
    cmp08_data = {
        'gstin': company.gstin or '',
        'fp': _fp(mon, year),
        'summary': {
            'outward_supplies': {
                'taxable_value': round(total_outward, 2),
                'cgst': round(tax_on_outward / 2, 2) if flat_tax_rate > 0 else 0.0,
                'sgst': round(tax_on_outward / 2, 2) if flat_tax_rate > 0 else 0.0,
                'igst': 0.0,
                'cess': 0.0,
                'tax_payable': round(tax_on_outward, 2)
            },
            'rc_inward_supplies': {
                'taxable_value': round(total_rc_taxable, 2),
                'cgst': round(total_rc_cgst, 2),
                'sgst': round(total_rc_sgst, 2),
                'igst': round(total_rc_igst, 2),
                'cess': 0.0,
                'tax_payable': round(total_rc_cgst + total_rc_sgst + total_rc_igst, 2)
            },
            'total_tax_payable': round(tax_on_outward + total_rc_cgst + total_rc_sgst + total_rc_igst, 2)
        }
    }
    
    return _json_download(cmp08_data, f'CMP08_{month}.json')

@gst_bp.route('/gstr1')
@login_required
def gstr1():
    cid = get_cid()
    company = _company()
    guard = _require_scheme(company, 'regular')
    if guard: return guard
    month, year, mon, from_date, to_date = _month_period(request.args.get('month'))
    
    vouchers = _voucher_period_query(cid, ['Sales', 'Debit Note', 'Credit Note'], from_date, to_date).all()
    outward_vouchers = [v for v in vouchers if v.voucher_type in ['Sales', 'Debit Note']]
    credit_notes = [v for v in vouchers if v.voucher_type == 'Credit Note']
    
    # B2B invoices (party with GSTIN)
    b2b = [v for v in outward_vouchers if v.party and v.party.gstin]
    # B2C invoices
    b2c = [v for v in outward_vouchers if not (v.party and v.party.gstin)]
    
    # HSN summary
    hsn_summary = {}
    for v in outward_vouchers:
        for item in v.items:
            hsn = item.hsn_code or 'UNKNOWN'
            if hsn not in hsn_summary:
                hsn_summary[hsn] = {'qty': 0, 'taxable': 0, 'cgst': 0, 'sgst': 0, 'igst': 0, 'total': 0}
            hsn_summary[hsn]['qty'] += item.qty
            hsn_summary[hsn]['taxable'] += item.taxable_amount
            hsn_summary[hsn]['cgst'] += item.cgst_amount
            hsn_summary[hsn]['sgst'] += item.sgst_amount
            hsn_summary[hsn]['igst'] += item.igst_amount
            hsn_summary[hsn]['total'] += item.total_amount
    
    totals = {
        'taxable': sum(v.taxable_amount or 0 for v in outward_vouchers) - sum(v.taxable_amount or 0 for v in credit_notes),
        'cgst': sum(v.cgst_amount or 0 for v in outward_vouchers) - sum(v.cgst_amount or 0 for v in credit_notes),
        'sgst': sum(v.sgst_amount or 0 for v in outward_vouchers) - sum(v.sgst_amount or 0 for v in credit_notes),
        'igst': sum(v.igst_amount or 0 for v in outward_vouchers) - sum(v.igst_amount or 0 for v in credit_notes),
        'total': sum(v.total_amount or 0 for v in outward_vouchers) - sum(v.total_amount or 0 for v in credit_notes),
    }
    
    return render_template('gst/gstr1.html', company=company, month=month,
        b2b=b2b, b2c=b2c, credit_notes=credit_notes,
        hsn_summary=hsn_summary, totals=totals,
        from_date=from_date, to_date=to_date)

@gst_bp.route('/gstr3b')
@login_required
def gstr3b():
    cid = get_cid()
    company = _company()
    guard = _require_scheme(company, 'regular')
    if guard: return guard
    month, year, mon, from_date, to_date = _month_period(request.args.get('month'))
    
    def get_totals(vtype):
        vs = _voucher_period_query(cid, vtype, from_date, to_date).all()
        return _sum_vouchers(vs)
    
    sales = get_totals('Sales')
    purchases = get_totals('Purchase')
    cn = get_totals('Credit Note')
    dn = get_totals('Debit Note')
    
    net_outward = {
        k: _money((sales.get(k, 0) + dn.get(k, 0)) - cn.get(k, 0))
        for k in ['taxable', 'igst', 'cgst', 'sgst', 'cess', 'total']
    }
    net_gst_liability = net_outward['igst'] + net_outward['cgst'] + net_outward['sgst'] + net_outward['cess']
    itc_available = purchases['igst'] + purchases['cgst'] + purchases['sgst'] + purchases['cess']
    net_payable = net_gst_liability - itc_available
    
    return render_template('gst/gstr3b.html', company=company, month=month,
        sales=sales, purchases=purchases, cn=cn, dn=dn,
        net_outward=net_outward,
        net_gst_liability=net_gst_liability,
        itc_available=itc_available, net_payable=net_payable,
        from_date=from_date, to_date=to_date)

@gst_bp.route('/gstr1/json')
@login_required
def gstr1_json():
    cid = get_cid()
    company = _company()
    guard = _require_scheme(company, 'regular')
    if guard: return guard
    month, year, mon, from_date, to_date = _month_period(request.args.get('month'))
    
    vouchers = _voucher_period_query(cid, ['Sales', 'Debit Note', 'Credit Note'], from_date, to_date).all()
    
    b2b_data = []
    for v in vouchers:
        if v.party and v.party.gstin:
            b2b_data.append({
                'gstin': v.party.gstin,
                'invoice_number': v.voucher_number,
                'invoice_date': v.date.strftime('%d-%m-%Y'),
                'invoice_value': round(v.total_amount, 2),
                'place_of_supply': v.place_of_supply or '',
                'taxable_value': round(v.taxable_amount, 2),
                'igst': round(v.igst_amount, 2),
                'cgst': round(v.cgst_amount, 2),
                'sgst': round(v.sgst_amount, 2),
            })
    
    gstr1_data = {
        'gstin': company.gstin,
        'fp': month.replace('-', ''),
        'b2b': b2b_data,
    }
    
    return _json_download(gstr1_data, f'GSTR1_{month}.json')

@gst_bp.route('/gstr1/export-csv')
@login_required
def gstr1_export_csv():
    cid = get_cid()
    company = _company()
    guard = _require_scheme(company, 'regular')
    if guard: return guard
    month, year, mon, from_date, to_date = _month_period(request.args.get('month'))
    vouchers = _voucher_period_query(cid, ['Sales', 'Debit Note', 'Credit Note'], from_date, to_date)\
        .order_by(Voucher.date, Voucher.voucher_number).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Company', company.name, 'GSTIN', company.gstin or '', 'Period', month])
    writer.writerow([])
    writer.writerow(['Type', 'Date', 'Voucher No', 'Party', 'GSTIN', 'Taxable', 'CGST', 'SGST', 'IGST', 'Cess', 'Total'])
    for v in vouchers:
        sign = -1 if v.voucher_type == 'Credit Note' else 1
        writer.writerow([
            v.voucher_type,
            v.date.strftime('%d/%m/%Y') if v.date else '',
            v.voucher_number,
            v.party.name if v.party else 'Unregistered',
            v.party.gstin if v.party and v.party.gstin else 'URP',
            _money(sign * (v.taxable_amount or 0)),
            _money(sign * (v.cgst_amount or 0)),
            _money(sign * (v.sgst_amount or 0)),
            _money(sign * (v.igst_amount or 0)),
            _money(sign * (v.cess_amount or 0)),
            _money(sign * (v.total_amount or 0)),
        ])
    return _csv_download(output.getvalue(), f'GSTR1_{month}.csv')

@gst_bp.route('/gstr3b/export-csv')
@login_required
def gstr3b_export_csv():
    cid = get_cid()
    company = _company()
    guard = _require_scheme(company, 'regular')
    if guard: return guard
    month, year, mon, from_date, to_date = _month_period(request.args.get('month'))

    sales = _sum_vouchers(_voucher_period_query(cid, 'Sales', from_date, to_date).all())
    purchases = _sum_vouchers(_voucher_period_query(cid, 'Purchase', from_date, to_date).all())
    cn = _sum_vouchers(_voucher_period_query(cid, 'Credit Note', from_date, to_date).all())
    dn = _sum_vouchers(_voucher_period_query(cid, 'Debit Note', from_date, to_date).all())
    net_outward = {k: _money((sales.get(k, 0) + dn.get(k, 0)) - cn.get(k, 0)) for k in ['taxable', 'igst', 'cgst', 'sgst', 'cess', 'total']}
    itc = _money(purchases['igst'] + purchases['cgst'] + purchases['sgst'] + purchases['cess'])
    liability = _money(net_outward['igst'] + net_outward['cgst'] + net_outward['sgst'] + net_outward['cess'])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Company', company.name, 'GSTIN', company.gstin or '', 'Period', month])
    writer.writerow([])
    writer.writerow(['Section', 'Taxable', 'IGST', 'CGST', 'SGST', 'Cess', 'Total'])
    writer.writerow(['3.1 Outward supplies (net)', net_outward['taxable'], net_outward['igst'], net_outward['cgst'], net_outward['sgst'], net_outward['cess'], net_outward['total']])
    writer.writerow(['4.0 ITC available', purchases['taxable'], purchases['igst'], purchases['cgst'], purchases['sgst'], purchases['cess'], purchases['total']])
    writer.writerow([])
    writer.writerow(['Net GST Liability', liability])
    writer.writerow(['Eligible ITC', itc])
    writer.writerow(['Net Payable / Credit', _money(liability - itc)])
    return _csv_download(output.getvalue(), f'GSTR3B_{month}.csv')

@gst_bp.route('/filing-assistant')
@login_required
def filing_assistant():
    cid = get_cid()
    company = Company.query.get(cid)
    return render_template('gst/filing_guide.html', company=company)


# ─── HSN Rate Management ──────────────────────────────────
@gst_bp.route('/hsn-rates', methods=['GET', 'POST'])
@login_required
def hsn_rates():
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        rate = float(request.form.get('rate') or 0)
        desc = request.form.get('description', '')
        
        if not code:
            flash('HSN Code is required', 'error')
        else:
            hsn = HSNCode.query.filter_by(code=code).first()
            if hsn:
                hsn.gst_rate = rate
                hsn.description = desc
                flash(f'Updated HSN {code}', 'success')
            else:
                hsn = HSNCode(code=code, gst_rate=rate, description=desc)
                db.session.add(hsn)
                flash(f'Added HSN {code}', 'success')
            db.session.commit()
        return redirect(url_for('gst.hsn_rates'))

    page = request.args.get('page', 1, type=int)
    q = request.args.get('q', '')
    query = HSNCode.query
    if q:
        query = query.filter(
            (HSNCode.code.ilike(f'%{q}%')) | 
            (HSNCode.description.ilike(f'%{q}%'))
        )
    
    pagination = query.order_by(HSNCode.code).paginate(page=page, per_page=50)
    return render_template('gst/hsn_rates.html', pagination=pagination, q=q)

@gst_bp.route('/api/hsn/<string:code>')
@login_required
def api_hsn_lookup(code):
    hsn = HSNCode.query.filter_by(code=code).first()
    if hsn:
        # Find the matching GSTRate ID if possible
        gst_rate = GSTRate.query.filter(GSTRate.rate == hsn.gst_rate).first()
        return jsonify({
            'success': True,
            'code': hsn.code,
            'rate': hsn.gst_rate,
            'gst_rate_id': gst_rate.id if gst_rate else None,
            'description': hsn.description
        })
    return jsonify({'success': False, 'message': 'HSN not found'})

@gst_bp.route('/import/hsn', methods=['POST'])
@login_required
def import_hsn():
    if 'file' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(url_for('gst.hsn_rates'))
    
    file = request.files['file']
    if not file.filename:
        flash('No file selected', 'error')
        return redirect(url_for('gst.hsn_rates'))

    ext = file.filename.split('.')[-1].lower()

    try:
        raw_data = file.read()
        try:
            content = raw_data.decode('utf-8-sig')
        except UnicodeDecodeError:
            content = raw_data.decode('latin-1')

        count = 0
        if ext in ['html', 'mhtml']:
            # Robust HTML/MHTML parsing for unpredictable government table structures
            tree = html.fromstring(content)
            for tr in tree.xpath('//tr'):
                tds = tr.xpath('.//td')
                if not tds: continue
                
                # Extract all text from columns
                cols = [" ".join(td.xpath('.//text()')).strip() for td in tds]
                row_text = " ".join(cols)
                
                # 1. Identify HSN Code
                # Look for 4, 6, or 8 digit patterns. Sometimes they have dots like 84.71
                hsn_match = re.search(r'\b(\d{2,4}\.?\d{0,4})\b', row_text)
                hsn_code = hsn_match.group(1).replace('.', '') if hsn_match else None
                
                if not hsn_code or len(hsn_code) < 2: 
                    # Try another way: check specific columns for pure digits
                    for c in cols[:3]:
                        clean = re.sub(r'[^0-9]', '', c)
                        if 2 <= len(clean) <= 8:
                            hsn_code = clean
                            break
                
                if not hsn_code: continue

                # 2. Identify GST Rate
                # Look for common GST rates: 0, 5, 12, 18, 28
                # We prioritize the highest number found in the row (usually IGST)
                rates_found = []
                for text in cols:
                    # Find numbers followed by % or standalone numbers 0-40
                    matches = re.findall(r'(\d+\.?\d*)\s*%?', text)
                    for m in matches:
                        try:
                            val = float(m)
                            if val in [0, 0.1, 0.25, 1, 1.5, 3, 5, 6, 12, 14, 18, 28]:
                                rates_found.append(val)
                            elif 0 <= val <= 40 and '.' in m: # Catch decimals like 12.5
                                rates_found.append(val)
                        except: pass
                
                total_rate = max(rates_found) if rates_found else None
                if total_rate is None: continue

                # 3. Extract Description
                # Use the column with the most words that isn't the HSN
                desc_candidates = [c for c in cols if len(c) > 5 and not c.replace('.', '').isdigit()]
                description = max(desc_candidates, key=len) if desc_candidates else "Imported HSN"

                # 4. Save/Update
                hsn = HSNCode.query.filter_by(code=hsn_code).first()
                if hsn:
                    hsn.gst_rate = total_rate
                    hsn.description = description[:500]
                else:
                    hsn = HSNCode(code=hsn_code, gst_rate=total_rate, description=description[:500])
                    db.session.add(hsn)
                count += 1
            
            db.session.commit()
            flash(f'Successfully processed {count} potential HSN/SAC records!', 'success')
        else:
            # Handle CSV (More flexible column detection)
            import csv
            f = io.StringIO(content)
            reader = csv.reader(f)
            header = [h.lower().strip() for h in next(reader, [])]
            
            # Map columns
            idx_code = -1
            idx_rate = -1
            idx_desc = -1
            
            for i, h in enumerate(header):
                if any(k in h for k in ['code', 'hsn', 'sac']): idx_code = i
                if any(k in h for k in ['rate', 'gst', 'tax']): idx_rate = i
                if any(k in h for k in ['desc', 'item', 'name']): idx_desc = i
            
            for row in reader:
                if not row: continue
                code = row[idx_code].strip().replace('.', '') if idx_code != -1 else ""
                if not code: continue
                
                rate_str = re.sub(r'[^0-9.]', '', row[idx_rate]) if idx_rate != -1 else "0"
                rate = float(rate_str or 0)
                desc = row[idx_desc].strip() if idx_desc != -1 else "Imported"
                
                hsn = HSNCode.query.filter_by(code=code).first()
                if hsn:
                    hsn.gst_rate = rate
                    hsn.description = desc[:500]
                else:
                    hsn = HSNCode(code=code, gst_rate=rate, description=desc[:500])
                    db.session.add(hsn)
                count += 1
            db.session.commit()
            flash(f'Successfully imported {count} items from CSV!', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Import failed: {str(e)}', 'error')
        
    return redirect(url_for('gst.hsn_rates'))

@gst_bp.route('/hsn/seed-defaults')
@login_required
def seed_hsn_defaults():
    # Common HSN codes and rates
    defaults = [
        ('8471', 18, 'Computers, Peripherals and storage devices'),
        ('8517', 18, 'Mobile phones and communication equipment'),
        ('8528', 18, 'Monitors and Projectors'),
        ('8443', 18, 'Printers, Fax machines'),
        ('4802', 12, 'Paper and stationery'),
        ('9403', 18, 'Furniture and parts'),
        ('3926', 18, 'Plastic articles'),
        ('7308', 18, 'Iron or steel structures'),
        ('9018', 12, 'Medical instruments'),
        ('9983', 18, 'Professional and technical services (SAC)'),
        ('9987', 18, 'Maintenance and repair services (SAC)'),
    ]
    
    count = 0
    for code, rate, desc in defaults:
        hsn = HSNCode.query.filter_by(code=code).first()
        if not hsn:
            hsn = HSNCode(code=code, gst_rate=rate, description=desc)
            db.session.add(hsn)
            count += 1
    
    db.session.commit()
    flash(f'Seeded {count} common HSN/SAC codes!', 'success')
    return redirect(url_for('gst.hsn_rates'))

@gst_bp.route('/hsn/clear', methods=['POST'])
@login_required
def clear_hsn_data():
    try:
        num = HSNCode.query.delete()
        db.session.commit()
        flash(f'Successfully cleared {num} HSN records!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to clear data: {str(e)}', 'error')
    return redirect(url_for('gst.hsn_rates'))


# ═══════════════════════════════════════════════════════════
# GSTR-2B RECONCILIATION
# ═══════════════════════════════════════════════════════════

@gst_bp.route('/gstr2b', methods=['GET', 'POST'])
@login_required
def gstr2b():
    cid = get_cid()
    company = Company.query.get(cid)
    results = None
    summary = None
    month = request.args.get('month', date.today().strftime('%Y-%m'))

    if request.method == 'POST':
        month = request.form.get('month', month)
        year, mon = map(int, month.split('-'))
        from_date = date(year, mon, 1)
        import calendar
        last_day = calendar.monthrange(year, mon)[1]
        to_date = date(year, mon, last_day)

        file = request.files.get('gstr2b_file')
        if not file or not file.filename:
            flash('Please upload the GSTR-2B JSON file.', 'error')
            return redirect(url_for('gst.gstr2b', month=month))

        try:
            raw = file.read()
            try:
                data = json.loads(raw.decode('utf-8-sig'))
            except:
                data = json.loads(raw.decode('latin-1'))

            # Parse GSTR-2B structure
            gstr2b_entries = _parse_gstr2b_json(data)

            # Get purchase vouchers for the period
            purchases = Voucher.query.filter_by(
                company_id=cid, voucher_type='Purchase', is_cancelled=False
            ).filter(Voucher.date >= from_date, Voucher.date <= to_date).all()

            results = _reconcile_2b(gstr2b_entries, purchases)
            summary = {
                'matched': len([r for r in results if r['status'] == 'Matched']),
                'amount_mismatch': len([r for r in results if r['status'] == 'Amount Mismatch']),
                'books_only': len([r for r in results if r['status'] == 'Books Only']),
                'twob_only': len([r for r in results if r['status'] == '2B Only']),
                'total': len(results),
            }

            # Store in session for CSV export
            session['gstr2b_results'] = results
            session['gstr2b_month'] = month

        except Exception as e:
            flash(f'Error processing file: {str(e)}', 'error')

    return render_template('gst/gstr2b.html', company=company, month=month,
                           results=results, summary=summary)


def _parse_gstr2b_json(data):
    """Parse GSTR-2B JSON from GST portal into flat entries."""
    entries = []

    # Standard GSTR-2B structure: data.docdata.b2b
    doc_data = data.get('data', data).get('docdata', data.get('docdata', data))

    b2b_list = doc_data.get('b2b', [])
    for supplier in b2b_list:
        gstin = supplier.get('ctin', supplier.get('gstin', ''))
        trade_name = supplier.get('trdnm', supplier.get('trade_name', ''))
        for inv in supplier.get('inv', supplier.get('invoices', [])):
            inv_no = inv.get('inum', inv.get('invoice_number', ''))
            inv_date = inv.get('dt', inv.get('invoice_date', ''))
            inv_val = float(inv.get('val', inv.get('invoice_value', 0)))

            taxable = 0
            igst = 0
            cgst = 0
            sgst = 0
            for item in inv.get('items', inv.get('itms', [])):
                det = item.get('itm_det', item)
                taxable += float(det.get('txval', det.get('taxable_value', 0)))
                igst += float(det.get('iamt', det.get('igst', 0)))
                cgst += float(det.get('camt', det.get('cgst', 0)))
                sgst += float(det.get('samt', det.get('sgst', 0)))

            entries.append({
                'gstin': gstin,
                'trade_name': trade_name,
                'inv_no': inv_no.strip().upper(),
                'inv_date': inv_date,
                'inv_value': inv_val,
                'taxable': taxable,
                'igst': igst,
                'cgst': cgst,
                'sgst': sgst,
            })
    return entries


def _reconcile_2b(gstr2b_entries, purchases):
    """Match 2B entries against purchase books."""
    results = []
    matched_voucher_ids = set()
    matched_2b_indices = set()

    for idx, entry in enumerate(gstr2b_entries):
        best_match = None
        best_score = 0

        for v in purchases:
            if v.id in matched_voucher_ids:
                continue
            score = 0
            # GSTIN match
            if v.party and v.party.gstin and v.party.gstin.upper() == entry['gstin'].upper():
                score += 50
            # Invoice number match (fuzzy)
            v_num = (v.ref_number or v.voucher_number or '').strip().upper()
            if v_num and v_num == entry['inv_no']:
                score += 40
            elif v_num and (v_num in entry['inv_no'] or entry['inv_no'] in v_num):
                score += 25
            # Amount match (within tolerance)
            if abs(v.total_amount - entry['inv_value']) < 2:
                score += 10

            if score > best_score and score >= 50:
                best_score = score
                best_match = v

        if best_match:
            matched_voucher_ids.add(best_match.id)
            matched_2b_indices.add(idx)

            amt_diff = abs(best_match.total_amount - entry['inv_value'])
            status = 'Matched' if amt_diff < 2 else 'Amount Mismatch'

            results.append({
                'status': status,
                'gstin': entry['gstin'],
                'party_name': entry['trade_name'] or (best_match.party.name if best_match.party else ''),
                'inv_no_2b': entry['inv_no'],
                'inv_no_books': best_match.ref_number or best_match.voucher_number,
                'inv_date_2b': entry['inv_date'],
                'inv_date_books': best_match.date.strftime('%d-%m-%Y') if best_match.date else '',
                'amount_2b': entry['inv_value'],
                'amount_books': best_match.total_amount,
                'tax_2b': entry['igst'] + entry['cgst'] + entry['sgst'],
                'tax_books': best_match.igst_amount + best_match.cgst_amount + best_match.sgst_amount,
                'diff': round(best_match.total_amount - entry['inv_value'], 2),
            })
        else:
            results.append({
                'status': '2B Only',
                'gstin': entry['gstin'],
                'party_name': entry['trade_name'],
                'inv_no_2b': entry['inv_no'],
                'inv_no_books': '',
                'inv_date_2b': entry['inv_date'],
                'inv_date_books': '',
                'amount_2b': entry['inv_value'],
                'amount_books': 0,
                'tax_2b': entry['igst'] + entry['cgst'] + entry['sgst'],
                'tax_books': 0,
                'diff': -entry['inv_value'],
            })

    # Books-only entries
    for v in purchases:
        if v.id not in matched_voucher_ids:
            results.append({
                'status': 'Books Only',
                'gstin': v.party.gstin if v.party else '',
                'party_name': v.party.name if v.party else '',
                'inv_no_2b': '',
                'inv_no_books': v.ref_number or v.voucher_number,
                'inv_date_2b': '',
                'inv_date_books': v.date.strftime('%d-%m-%Y') if v.date else '',
                'amount_2b': 0,
                'amount_books': v.total_amount,
                'tax_2b': 0,
                'tax_books': v.igst_amount + v.cgst_amount + v.sgst_amount,
                'diff': v.total_amount,
            })

    return results


@gst_bp.route('/gstr2b/export-csv')
@login_required
def gstr2b_export_csv():
    results = session.get('gstr2b_results', [])
    month = session.get('gstr2b_month', '')

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Status', 'GSTIN', 'Party', 'Inv No (2B)', 'Inv No (Books)',
                      'Date (2B)', 'Date (Books)', 'Amount (2B)', 'Amount (Books)',
                      'Tax (2B)', 'Tax (Books)', 'Difference'])
    for r in results:
        writer.writerow([r['status'], r['gstin'], r['party_name'],
                         r['inv_no_2b'], r['inv_no_books'],
                         r['inv_date_2b'], r['inv_date_books'],
                         r['amount_2b'], r['amount_books'],
                         r['tax_2b'], r['tax_books'], r['diff']])

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename="GSTR2B_Recon_{month}.csv"'
    return response


# ═══════════════════════════════════════════════════════════
# GSTN-COMPATIBLE JSON EXPORTS
# ═══════════════════════════════════════════════════════════

@gst_bp.route('/gstr1/gstn-json')
@login_required
def gstr1_gstn_json():
    """Generate GSTN Offline Tool compatible GSTR-1 JSON."""
    cid = get_cid()
    company = _company()
    guard = _require_scheme(company, 'regular')
    if guard: return guard
    month, year, mon, from_date, to_date = _month_period(request.args.get('month'))
    fp = _fp(mon, year)

    vouchers = _voucher_period_query(cid, ['Sales', 'Debit Note', 'Credit Note'], from_date, to_date).all()
    outward_vouchers = [v for v in vouchers if v.voucher_type in ['Sales', 'Debit Note']]
    credit_notes = [v for v in vouchers if v.voucher_type == 'Credit Note']

    # B2B
    b2b_map = {}
    for v in outward_vouchers:
        if not (v.party and v.party.gstin):
            continue
        gstin = v.party.gstin.upper()
        if gstin not in b2b_map:
            b2b_map[gstin] = {'ctin': gstin, 'inv': []}

        items_list = []
        for idx, item in enumerate(v.items, 1):
            items_list.append({
                'num': idx,
                'itm_det': {
                    'txval': round(item.taxable_amount, 2),
                    'rt': item.gst_rate,
                    'iamt': round(item.igst_amount, 2),
                    'camt': round(item.cgst_amount, 2),
                    'samt': round(item.sgst_amount, 2),
                    'csamt': round(item.cess_amount, 2),
                }
            })

        b2b_map[gstin]['inv'].append({
            'inum': v.voucher_number,
            'idt': v.date.strftime('%d-%m-%Y'),
            'val': round(v.total_amount, 2),
            'pos': (v.place_of_supply or company.state_code or '')[:2],
            'rchrg': 'Y' if v.reverse_charge else 'N',
            'inv_typ': 'R',
            'itms': items_list,
        })

    # B2CS (Unregistered, small invoices)
    b2cs_map = {}
    for v in outward_vouchers:
        if v.party and v.party.gstin:
            continue
        pos = (v.place_of_supply or company.state_code or '')[:2]
        for item in v.items:
            key = (pos, item.gst_rate)
            if key not in b2cs_map:
                b2cs_map[key] = {'sply_ty': 'INTRA' if pos == (company.state_code or '')[:2] else 'INTER',
                                 'pos': pos, 'rt': item.gst_rate,
                                 'txval': 0, 'iamt': 0, 'camt': 0, 'samt': 0, 'csamt': 0}
            b2cs_map[key]['txval'] += round(item.taxable_amount, 2)
            b2cs_map[key]['iamt'] += round(item.igst_amount, 2)
            b2cs_map[key]['camt'] += round(item.cgst_amount, 2)
            b2cs_map[key]['samt'] += round(item.sgst_amount, 2)
            b2cs_map[key]['csamt'] += round(item.cess_amount, 2)

    # HSN Summary
    hsn_map = {}
    for v in outward_vouchers:
        for item in v.items:
            hsn = item.hsn_code or '0'
            if hsn not in hsn_map:
                hsn_map[hsn] = {'num': 1, 'hsn_sc': hsn, 'desc': item.description or '',
                                'uqc': item.unit or 'NOS', 'qty': 0, 'txval': 0,
                                'iamt': 0, 'camt': 0, 'samt': 0, 'csamt': 0, 'rt': item.gst_rate}
            hsn_map[hsn]['qty'] += item.qty
            hsn_map[hsn]['txval'] += round(item.taxable_amount, 2)
            hsn_map[hsn]['iamt'] += round(item.igst_amount, 2)
            hsn_map[hsn]['camt'] += round(item.cgst_amount, 2)
            hsn_map[hsn]['samt'] += round(item.sgst_amount, 2)
            hsn_map[hsn]['csamt'] += round(item.cess_amount, 2)

    # Credit/debit note details for registered parties.
    cdnr_map = {}
    for v in credit_notes:
        if not (v.party and v.party.gstin):
            continue
        gstin = v.party.gstin.upper()
        if gstin not in cdnr_map:
            cdnr_map[gstin] = {'ctin': gstin, 'nt': []}
        items_list = []
        for idx, item in enumerate(v.items, 1):
            items_list.append({
                'num': idx,
                'itm_det': {
                    'txval': round(item.taxable_amount or 0, 2),
                    'rt': item.gst_rate or 0,
                    'iamt': round(item.igst_amount or 0, 2),
                    'camt': round(item.cgst_amount or 0, 2),
                    'samt': round(item.sgst_amount or 0, 2),
                    'csamt': round(item.cess_amount or 0, 2),
                }
            })
        cdnr_map[gstin]['nt'].append({
            'ntty': 'C',
            'nt_num': v.voucher_number or '',
            'nt_dt': v.date.strftime('%d-%m-%Y') if v.date else '',
            'p_gst': 'N',
            'val': round(v.total_amount or 0, 2),
            'itms': items_list,
        })

    gstr1 = {
        'gstin': company.gstin or '',
        'fp': fp,
        'version': 'GST3.0.4',
        'hash': 'hash',
        'b2b': list(b2b_map.values()),
        'b2cs': list(b2cs_map.values()),
        'cdnr': list(cdnr_map.values()),
        'hsn': {'data': list(hsn_map.values())},
    }

    return _json_download(gstr1, f'GSTR1_{month}_GSTN.json')


@gst_bp.route('/gstr3b/gstn-json')
@login_required
def gstr3b_gstn_json():
    """Generate GSTN Offline Tool compatible GSTR-3B JSON."""
    cid = get_cid()
    company = _company()
    guard = _require_scheme(company, 'regular')
    if guard: return guard
    month, year, mon, from_date, to_date = _month_period(request.args.get('month'))
    ret_period = _fp(mon, year)

    def totals(vtype):
        vs = _voucher_period_query(cid, vtype, from_date, to_date).all()
        summed = _sum_vouchers(vs)
        return {
            'txval': summed['taxable'],
            'iamt': summed['igst'],
            'camt': summed['cgst'],
            'samt': summed['sgst'],
            'csamt': summed['cess'],
        }

    sales = totals('Sales')
    purchases = totals('Purchase')
    cn = totals('Credit Note')
    dn = totals('Debit Note')
    net_sales = {
        key: _money(sales[key] + dn[key] - cn[key])
        for key in ['txval', 'iamt', 'camt', 'samt', 'csamt']
    }

    gstr3b = {
        'gstin': company.gstin or '',
        'ret_period': ret_period,
        'sup_details': {
            'osup_det': {  # 3.1(a) Outward taxable supplies
                'txval': net_sales['txval'],
                'iamt': net_sales['iamt'],
                'camt': net_sales['camt'],
                'samt': net_sales['samt'],
                'csamt': net_sales['csamt'],
            },
            'osup_zero': {'txval': 0, 'iamt': 0, 'camt': 0, 'samt': 0, 'csamt': 0},
            'osup_nil_exmp': {'txval': 0},
            'isup_rev': {'txval': 0, 'iamt': 0, 'camt': 0, 'samt': 0, 'csamt': 0},
            'osup_nongst': {'txval': 0},
        },
        'itc_elg': {
            'itc_avl': [{
                'ty': 'ISRC',
                'iamt': purchases['iamt'],
                'camt': purchases['camt'],
                'samt': purchases['samt'],
                'csamt': purchases['csamt'],
            }],
            'itc_net': {
                'iamt': purchases['iamt'],
                'camt': purchases['camt'],
                'samt': purchases['samt'],
                'csamt': purchases['csamt'],
            },
        },
        'intr_ltfee': {
            'intr_details': {'iamt': 0, 'camt': 0, 'samt': 0, 'csamt': 0},
            'ltfee_details': {'iamt': 0, 'camt': 0, 'samt': 0, 'csamt': 0},
        }
    }

    return _json_download(gstr3b, f'GSTR3B_{month}_GSTN.json')


# ═══════════════════════════════════════════════════════════
# E-WAY BILL MANAGEMENT & JSON EXPORT
# ═══════════════════════════════════════════════════════════

# State code → name map for e-Way Bill
EWAY_STATE_MAP = {
    '01': 'JAMMU AND KASHMIR', '02': 'HIMACHAL PRADESH', '03': 'PUNJAB',
    '04': 'CHANDIGARH', '05': 'UTTARAKHAND', '06': 'HARYANA',
    '07': 'DELHI', '08': 'RAJASTHAN', '09': 'UTTAR PRADESH',
    '10': 'BIHAR', '11': 'SIKKIM', '12': 'ARUNACHAL PRADESH',
    '13': 'NAGALAND', '14': 'MANIPUR', '15': 'MIZORAM',
    '16': 'TRIPURA', '17': 'MEGHALAYA', '18': 'ASSAM',
    '19': 'WEST BENGAL', '20': 'JHARKHAND', '21': 'ODISHA',
    '22': 'CHHATTISGARH', '23': 'MADHYA PRADESH', '24': 'GUJARAT',
    '25': 'DAMAN AND DIU', '26': 'DADRA AND NAGAR HAVELI', '27': 'MAHARASHTRA',
    '28': 'ANDHRA PRADESH', '29': 'KARNATAKA', '30': 'GOA',
    '31': 'LAKSHADWEEP', '32': 'KERALA', '33': 'TAMIL NADU',
    '34': 'PUDUCHERRY', '35': 'ANDAMAN AND NICOBAR ISLANDS',
    '36': 'TELANGANA', '37': 'ANDHRA PRADESH', '38': 'LADAKH',
    '97': 'OTHER TERRITORY',
}

# NIC Unit Quantity Code mapping
UQC_MAP = {
    'NOS': 'NOS', 'PCS': 'PCS', 'KG': 'KGS', 'KGS': 'KGS',
    'GMS': 'GMS', 'LTR': 'LTR', 'MTR': 'MTR', 'SQM': 'SQM',
    'BOX': 'BOX', 'PCK': 'PAC', 'HRS': 'OTH', 'DYS': 'OTH',
    'MNT': 'OTH', 'TON': 'TON', 'QTL': 'QTL', 'BAG': 'BAG',
    'BTL': 'BTL', 'BDL': 'BDL', 'CMS': 'CMS',
}


def _get_state_code(state_name):
    """Resolve a state name to its 2-digit code."""
    if not state_name:
        return ''
    # Already a code?
    if state_name.strip().isdigit() and len(state_name.strip()) == 2:
        return state_name.strip()
    # Match by name (case-insensitive)
    for code, name in EWAY_STATE_MAP.items():
        if name.lower() == state_name.strip().lower():
            return code
    # Fuzzy: check if the state name starts with the value
    for code, name in EWAY_STATE_MAP.items():
        if state_name.strip().lower() in name.lower() or name.lower() in state_name.strip().lower():
            return code
    return ''


def _build_eway_json(voucher, company):
    """Build a single NIC-compatible e-Way Bill JSON object for a voucher."""
    from app.models import Ledger

    # Supply type: O (Outward) for Sales, I (Inward) for Purchase
    if voucher.voucher_type in ['Sales', 'Credit Note', 'Debit Note']:
        supply_type = 'O'
    else:
        supply_type = 'I'

    # Sub-supply type
    sub_supply_map = {
        'Sales': 1,       # Supply
        'Purchase': 1,    # Supply
        'Credit Note': 7, # Sales Return
        'Debit Note': 8,  # Others
    }
    sub_supply_type = sub_supply_map.get(voucher.voucher_type, 1)

    is_comp = (company.gst_registration_type or '').lower() == 'composition'

    # Document type
    doc_type_map = {
        'Sales': 'BIL' if is_comp else 'INV',
        'Purchase': 'INV',
        'Credit Note': 'CNT',
        'Debit Note': 'BIL' if is_comp else 'INV',
    }
    doc_type = doc_type_map.get(voucher.voucher_type, 'INV')

    # Transaction type: 1=Regular, 2=Bill To-Ship To, 3=Bill From-Dispatch From, 4=Combo
    transaction_type = 1

    # From / To details
    from_gstin = company.gstin or 'URP'
    from_name = company.legal_name or company.name or ''
    from_addr = company.address or ''
    from_place = company.city or ''
    from_pincode = int(company.pincode) if company.pincode and company.pincode.isdigit() else 0
    from_state_code = int(company.state_code) if company.state_code and company.state_code.isdigit() else 0

    party = voucher.party
    to_gstin = (party.gstin or 'URP') if party else 'URP'
    to_name = (party.name or '') if party else ''
    to_addr = (party.address or '') if party else ''
    to_place = (party.city or '') if party else ''
    to_pincode = int(party.pincode) if party and party.pincode and party.pincode.isdigit() else 0
    to_state_code = int(party.state_code) if party and party.state_code and party.state_code.isdigit() else 0

    # For purchases, swap from/to
    if voucher.voucher_type in ['Purchase']:
        from_gstin, to_gstin = to_gstin, from_gstin
        from_name, to_name = to_name, from_name
        from_addr, to_addr = to_addr, from_addr
        from_place, to_place = to_place, from_place
        from_pincode, to_pincode = to_pincode, from_pincode
        from_state_code, to_state_code = to_state_code, from_state_code

    # If to_state_code is 0, try to derive from place_of_supply
    if to_state_code == 0 and voucher.place_of_supply:
        sc = _get_state_code(voucher.place_of_supply)
        if sc:
            to_state_code = int(sc)

    # Item list
    item_list = []
    for idx, item in enumerate(voucher.items, 1):
        unit_raw = (item.unit or 'NOS').upper().strip()
        uqc = UQC_MAP.get(unit_raw, 'OTH')

        cgst_rate = 0.0 if (is_comp and supply_type == 'O') else (item.cgst_rate or 0.0)
        sgst_rate = 0.0 if (is_comp and supply_type == 'O') else (item.sgst_rate or 0.0)
        igst_rate = 0.0 if (is_comp and supply_type == 'O') else (item.igst_rate or 0.0)
        cess_rate = 0.0 if (is_comp and supply_type == 'O') else (item.cess_rate or 0.0)

        item_list.append({
            'productName': item.description or (item.stock_item.name if item.stock_item else f'Item {idx}'),
            'productDesc': item.description or '',
            'hsnCode': int(item.hsn_code) if item.hsn_code and item.hsn_code.isdigit() else 0,
            'quantity': round(item.qty, 2),
            'qtyUnit': uqc,
            'taxableAmount': round(item.taxable_amount, 2),
            'cgstRate': round(cgst_rate, 2),
            'sgstRate': round(sgst_rate, 2),
            'igstRate': round(igst_rate, 2),
            'cessRate': round(cess_rate, 2),
        })

    # Transport mode: 1=Road, 2=Rail, 3=Air, 4=Ship
    trans_mode = 1  # Default to Road

    cgst_val = 0.0 if (is_comp and supply_type == 'O') else (voucher.cgst_amount or 0.0)
    sgst_val = 0.0 if (is_comp and supply_type == 'O') else (voucher.sgst_amount or 0.0)
    igst_val = 0.0 if (is_comp and supply_type == 'O') else (voucher.igst_amount or 0.0)
    cess_val = 0.0 if (is_comp and supply_type == 'O') else (voucher.cess_amount or 0.0)
    tot_inv_val = (voucher.taxable_amount or voucher.total_amount or 0.0) if (is_comp and supply_type == 'O') else (voucher.total_amount or 0.0)

    eway_obj = {
        'supplyType': supply_type,
        'subSupplyType': sub_supply_type,
        'docType': doc_type,
        'docNo': voucher.voucher_number or '',
        'docDate': voucher.date.strftime('%d/%m/%Y') if voucher.date else '',
        'fromGstin': from_gstin,
        'fromTrdName': from_name,
        'fromAddr1': from_addr[:120] if from_addr else '',
        'fromAddr2': '',
        'fromPlace': from_place,
        'fromPincode': from_pincode,
        'fromStateCode': from_state_code,
        'toGstin': to_gstin,
        'toTrdName': to_name,
        'toAddr1': to_addr[:120] if to_addr else '',
        'toAddr2': '',
        'toPlace': to_place,
        'toPincode': to_pincode,
        'toStateCode': to_state_code,
        'transactionType': transaction_type,
        'totalValue': round(voucher.taxable_amount or 0, 2),
        'cgstValue': round(cgst_val, 2),
        'sgstValue': round(sgst_val, 2),
        'igstValue': round(igst_val, 2),
        'cessValue': round(cess_val, 2),
        'totInvValue': round(tot_inv_val, 2),
        'transporterId': '',
        'transporterName': voucher.transporter_name or '',
        'transDocNo': '',
        'transDocDate': '',
        'transMode': str(trans_mode),
        'transDistance': str(voucher.distance or 0),
        'vehicleNo': (voucher.vehicle_no or '').replace(' ', '').replace('-', '').upper(),
        'vehicleType': 'R',  # R=Regular, O=Over Dimensional Cargo
        'itemList': item_list,
    }

    return eway_obj


@gst_bp.route('/eway-bill')
@login_required
def eway_bill():
    """e-Way Bill management page — lists all vouchers eligible for e-Way Bill (value > ₹50,000)."""
    cid = get_cid()
    company = Company.query.get(cid)

    from_date_str = request.args.get('from_date', '')
    to_date_str = request.args.get('to_date', '')
    threshold = float(request.args.get('threshold', 50000))
    vtype_filter = request.args.get('vtype', '')

    # Default to current month
    if not from_date_str:
        from_date = date(date.today().year, date.today().month, 1)
    else:
        from_date = date.fromisoformat(from_date_str)

    if not to_date_str:
        import calendar
        last_day = calendar.monthrange(from_date.year, from_date.month)[1]
        to_date = date(from_date.year, from_date.month, last_day)
    else:
        to_date = date.fromisoformat(to_date_str)

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('size', 50, type=int)

    query = Voucher.query.filter_by(company_id=cid, is_cancelled=False, is_trash=False)\
        .filter(Voucher.voucher_type.in_(['Sales', 'Purchase', 'Credit Note', 'Debit Note']))\
        .filter(Voucher.date >= from_date, Voucher.date <= to_date)\
        .filter(Voucher.total_amount >= threshold)

    if vtype_filter:
        query = query.filter(Voucher.voucher_type == vtype_filter)

    pagination = query.order_by(Voucher.date.desc()).paginate(page=page, per_page=per_page)
    vouchers = pagination.items

    # Classify
    with_eway = [v for v in vouchers if v.eway_bill_no]
    without_eway = [v for v in vouchers if not v.eway_bill_no]

    summary = {
        'total': pagination.total,
        'with_eway': len(with_eway),
        'without_eway': len(without_eway),
        'total_value': sum(v.total_amount for v in vouchers),
    }

    return render_template('gst/eway_bill.html', company=company,
                           vouchers=vouchers, with_eway=with_eway,
                           without_eway=without_eway, summary=summary,
                           from_date=from_date.isoformat(), to_date=to_date.isoformat(),
                           threshold=threshold, vtype_filter=vtype_filter,
                           pagination=pagination)


@gst_bp.route('/eway-bill/json/<int:voucher_id>')
@login_required
def eway_bill_json_single(voucher_id):
    """Export a single voucher as NIC-compatible e-Way Bill JSON."""
    v = Voucher.query.filter_by(id=voucher_id, company_id=get_cid()).first_or_404()
    company = Company.query.get(v.company_id)

    eway_data = _build_eway_json(v, company)

    response = make_response(json.dumps(eway_data, indent=2, ensure_ascii=False))
    response.headers['Content-Type'] = 'application/json'
    safe_num = (v.voucher_number or 'EWB').replace('/', '_')
    response.headers['Content-Disposition'] = f'attachment; filename="EWayBill_{safe_num}.json"'
    return response


@gst_bp.route('/eway-bill/bulk-json')
@login_required
def eway_bill_json_bulk():
    """Export multiple vouchers as NIC Bulk e-Way Bill JSON (array format)."""
    cid = get_cid()
    company = Company.query.get(cid)

    from_date_str = request.args.get('from_date', '')
    to_date_str = request.args.get('to_date', '')
    threshold = float(request.args.get('threshold', 50000))
    vtype_filter = request.args.get('vtype', '')
    ids = request.args.get('ids', '')  # Comma-separated voucher IDs

    if ids:
        # Export specific vouchers by ID
        id_list = [int(x.strip()) for x in ids.split(',') if x.strip().isdigit()]
        vouchers = Voucher.query.filter(
            Voucher.id.in_(id_list),
            Voucher.company_id == cid,
            Voucher.is_cancelled == False,
            Voucher.is_trash == False
        ).all()
    else:
        # Export by date range
        if not from_date_str:
            from_date = date(date.today().year, date.today().month, 1)
        else:
            from_date = date.fromisoformat(from_date_str)

        if not to_date_str:
            import calendar
            last_day = calendar.monthrange(from_date.year, from_date.month)[1]
            to_date = date(from_date.year, from_date.month, last_day)
        else:
            to_date = date.fromisoformat(to_date_str)

        query = Voucher.query.filter_by(company_id=cid, is_cancelled=False, is_trash=False)\
            .filter(Voucher.voucher_type.in_(['Sales', 'Purchase', 'Credit Note', 'Debit Note']))\
            .filter(Voucher.date >= from_date, Voucher.date <= to_date)\
            .filter(Voucher.total_amount >= threshold)

        if vtype_filter:
            query = query.filter(Voucher.voucher_type == vtype_filter)

        vouchers = query.order_by(Voucher.date).all()

    bill_list = []
    for v in vouchers:
        bill_list.append(_build_eway_json(v, company))

    export_data = {
        'version': '1.0.0921',
        'billLists': bill_list,
    }

    month_str = date.today().strftime('%Y-%m')
    response = make_response(json.dumps(export_data, indent=2, ensure_ascii=False))
    response.headers['Content-Type'] = 'application/json'
    response.headers['Content-Disposition'] = f'attachment; filename="EWayBill_Bulk_{month_str}.json"'
    return response


@gst_bp.route('/eway-bill/update-number', methods=['POST'])
@login_required
def update_eway_number():
    """Quickly update the e-Way Bill number for a voucher."""
    data = request.json
    voucher_id = data.get('voucher_id')
    eway_bill_no = data.get('eway_bill_no', '').strip()

    if not voucher_id or not eway_bill_no:
        return jsonify({'success': False, 'error': 'Voucher ID and EWB Number are required'})

    v = Voucher.query.filter_by(id=voucher_id, company_id=get_cid()).first_or_404()
    v.eway_bill_no = eway_bill_no
    db.session.commit()

    return jsonify({'success': True})


# ═══════════════════════════════════════════════════════════
# TDS / TCS MANAGEMENT
# ═══════════════════════════════════════════════════════════

TDS_SECTIONS = {
    '194C':  {'name': 'Contractor Payments', 'ind_rate': 1.0, 'comp_rate': 2.0, 'threshold': 30000, 'agg_threshold': 100000},
    '194J':  {'name': 'Professional / Technical Fees', 'ind_rate': 10.0, 'comp_rate': 10.0, 'threshold': 30000, 'agg_threshold': 30000},
    '194Ja': {'name': 'Technical Fees (Special)', 'ind_rate': 2.0, 'comp_rate': 2.0, 'threshold': 30000, 'agg_threshold': 30000},
    '194I(a)': {'name': 'Rent - Plant & Machinery', 'ind_rate': 2.0, 'comp_rate': 2.0, 'threshold': 240000, 'agg_threshold': 240000},
    '194I(b)': {'name': 'Rent - Land & Building', 'ind_rate': 10.0, 'comp_rate': 10.0, 'threshold': 240000, 'agg_threshold': 240000},
    '194H':  {'name': 'Commission / Brokerage', 'ind_rate': 5.0, 'comp_rate': 5.0, 'threshold': 15000, 'agg_threshold': 15000},
    '194Q':  {'name': 'Purchase of Goods (>50L)', 'ind_rate': 0.1, 'comp_rate': 0.1, 'threshold': 5000000, 'agg_threshold': 5000000},
    '194O':  {'name': 'E-commerce Operator', 'ind_rate': 1.0, 'comp_rate': 1.0, 'threshold': 500000, 'agg_threshold': 500000},
    '195':   {'name': 'Non-Resident Payments', 'ind_rate': 20.0, 'comp_rate': 20.0, 'threshold': 0, 'agg_threshold': 0},
}

TCS_SECTIONS = {
    '206C(1H)': {'name': 'Sale of Goods (>50L)', 'rate': 0.1, 'threshold': 5000000},
    '52':       {'name': 'E-commerce TCS', 'rate': 1.0, 'threshold': 0},
}


@gst_bp.route('/tds-tcs')
@login_required
def tds_tcs():
    cid = get_cid()
    company = Company.query.get(cid)

    # Get quarter from query string
    fy = request.args.get('fy', '')
    quarter = request.args.get('quarter', 'Q1')
    if not fy:
        today = date.today()
        yr = today.year if today.month >= 4 else today.year - 1
        fy = f"{yr}-{str(yr+1)[2:]}"

    fy_start_year = int(fy.split('-')[0])
    q_ranges = {
        'Q1': (date(fy_start_year, 4, 1), date(fy_start_year, 6, 30)),
        'Q2': (date(fy_start_year, 7, 1), date(fy_start_year, 9, 30)),
        'Q3': (date(fy_start_year, 10, 1), date(fy_start_year, 12, 31)),
        'Q4': (date(fy_start_year + 1, 1, 1), date(fy_start_year + 1, 3, 31)),
    }
    from_date, to_date = q_ranges.get(quarter, q_ranges['Q1'])

    # Get vouchers with TDS
    tds_vouchers = Voucher.query.filter_by(company_id=cid, is_cancelled=False)\
        .filter(Voucher.tds_amount > 0, Voucher.date >= from_date, Voucher.date <= to_date).all()

    tds_entries = []
    for v in tds_vouchers:
        tds_entries.append({
            'date': v.date.strftime('%d-%m-%Y'),
            'voucher_number': v.voucher_number,
            'voucher_type': v.voucher_type,
            'party_name': v.party.name if v.party else '',
            'pan': v.party.pan if v.party else '',
            'amount': v.total_amount,
            'tds_rate': v.tds_percent,
            'tds_amount': v.tds_amount,
            'section': _guess_tds_section(v),
        })

    tds_total = sum(e['tds_amount'] for e in tds_entries)

    return render_template('gst/tds_tcs.html', company=company,
                           fy=fy, quarter=quarter,
                           tds_entries=tds_entries, tds_total=tds_total,
                           tds_sections=TDS_SECTIONS, tcs_sections=TCS_SECTIONS,
                           from_date=from_date, to_date=to_date)


def _guess_tds_section(voucher):
    """Best-effort guess of TDS section from rate."""
    rate = voucher.tds_percent or 0
    if rate == 0:
        return '—'
    if rate <= 0.1:
        return '194Q'
    if rate == 1:
        return '194C (Ind)'
    if rate == 2:
        return '194C (Co) / 194Ja / 194I(a)'
    if rate == 5:
        return '194H'
    if rate == 10:
        return '194J / 194I(b)'
    if rate == 20:
        return '195'
    return f'Custom ({rate}%)'


@gst_bp.route('/tds-tcs/export-26q')
@login_required
def export_26q():
    """Export Form 26Q-ready CSV for TDS."""
    cid = get_cid()
    company = Company.query.get(cid)
    fy = request.args.get('fy', '')
    quarter = request.args.get('quarter', 'Q1')

    if not fy:
        today = date.today()
        yr = today.year if today.month >= 4 else today.year - 1
        fy = f"{yr}-{str(yr+1)[2:]}"

    fy_start_year = int(fy.split('-')[0])
    q_ranges = {
        'Q1': (date(fy_start_year, 4, 1), date(fy_start_year, 6, 30)),
        'Q2': (date(fy_start_year, 7, 1), date(fy_start_year, 9, 30)),
        'Q3': (date(fy_start_year, 10, 1), date(fy_start_year, 12, 31)),
        'Q4': (date(fy_start_year + 1, 1, 1), date(fy_start_year + 1, 3, 31)),
    }
    from_date, to_date = q_ranges.get(quarter, q_ranges['Q1'])

    tds_vouchers = Voucher.query.filter_by(company_id=cid, is_cancelled=False)\
        .filter(Voucher.tds_amount > 0, Voucher.date >= from_date, Voucher.date <= to_date)\
        .order_by(Voucher.date).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Sr No', 'Section', 'PAN of Deductee', 'Name of Deductee',
                      'Date of Payment/Credit', 'Amount Paid/Credited',
                      'TDS Rate (%)', 'TDS Amount Deducted',
                      'Voucher Type', 'Voucher No', 'Deductor TAN'])

    for i, v in enumerate(tds_vouchers, 1):
        writer.writerow([
            i,
            _guess_tds_section(v),
            v.party.pan if v.party else '',
            v.party.name if v.party else '',
            v.date.strftime('%d/%m/%Y'),
            round(v.total_amount, 2),
            v.tds_percent,
            round(v.tds_amount, 2),
            v.voucher_type,
            v.voucher_number,
            company.pan or '',
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename="Form26Q_{fy}_{quarter}.csv"'
    return response

import requests
import base64
import random

@gst_bp.route('/api/official/captcha')
@login_required
def get_official_captcha():
    try:
        # We need a session to keep cookies consistent
        import random
        rnd = random.random()
        url = f"https://services.gst.gov.in/services/captcha?rnd={rnd}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Referer': 'https://services.gst.gov.in/services/searchtp'
        }
        res = requests.get(url, headers=headers, timeout=10)
        
        # Capture the CaptchaCookie
        captcha_cookie = res.cookies.get('CaptchaCookie')
        if not captcha_cookie:
            # Fallback check headers
            set_cookie = res.headers.get('Set-Cookie', '')
            if 'CaptchaCookie=' in set_cookie:
                # Extract cookie value
                match = re.search(r'CaptchaCookie=([^;]+)', set_cookie)
                if match: captcha_cookie = match.group(1)
        
        if not captcha_cookie:
            return jsonify({'success': False, 'error': 'Government portal rejected the request. Please try again.'})
            
        session['gst_captcha_cookie'] = captcha_cookie
        img_base64 = base64.b64encode(res.content).decode('utf-8')
        return jsonify({'success': True, 'captcha_img': img_base64})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@gst_bp.route('/api/search-gst/<string:gstin>')
@login_required
def api_search_gst(gstin):
    """
    Deprecated: Redirects or acts as a placeholder for the official lookup.
    Actually, let's keep a simplified mock version as fallback or just use the official one.
    User specifically asked for Official Lookup.
    """
    return jsonify({'success': False, 'error': 'Use Official Lookup with Captcha'})

@gst_bp.route('/api/official/search', methods=['POST'])
@login_required
def official_search():
    try:
        data = request.json
        gstin = data.get('gstin', '').upper().strip()
        captcha = data.get('captcha', '').strip()
        cookie_val = session.get('gst_captcha_cookie')
        
        if not cookie_val:
            return jsonify({'success': False, 'error': 'Session expired. Please refresh Captcha.'})
        if not captcha:
            return jsonify({'success': False, 'error': 'Captcha text is required.'})
            
        url = "https://services.gst.gov.in/services/api/search/taxpayerDetails"
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Referer': 'https://services.gst.gov.in/services/searchtp',
            'Cookie': f'CaptchaCookie={cookie_val}'
        }
        payload = {
            "gstin": gstin,
            "captcha": captcha
        }
        
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        if res.status_code != 200:
             return jsonify({'success': False, 'error': f'Portal error ({res.status_code})'})
             
        try:
            result = res.json()
        except:
            return jsonify({'success': False, 'error': f'Invalid JSON response. Raw: {res.text[:50]}'})
        
        # If result is not a dict, it's likely an error message string
        if not isinstance(result, dict):
             return jsonify({'success': False, 'error': f'Portal Message: {result}'})

        if 'err' in result:
             return jsonify({'success': False, 'error': result.get('err', 'Invalid Captcha or GSTIN')})
             
        # Helper for nested access
        def get_val(obj, path, default=''):
            current = obj
            for key in path.split('.'):
                if isinstance(current, dict):
                    current = current.get(key)
                else:
                    return default
            return current if current is not None else default

        # State mapping
        state_map = {
            '01': 'Jammu & Kashmir', '02': 'Himachal Pradesh', '03': 'Punjab', '04': 'Chandigarh',
            '05': 'Uttarakhand', '06': 'Haryana', '07': 'Delhi', '08': 'Rajasthan',
            '09': 'Uttar Pradesh', '10': 'Bihar', '11': 'Sikkim', '12': 'Arunachal Pradesh',
            '13': 'Nagaland', '14': 'Manipur', '15': 'Mizoram', '16': 'Tripura',
            '17': 'Meghalaya', '18': 'Assam', '19': 'West Bengal', '20': 'Jharkhand',
            '21': 'Odisha', '22': 'Chhattisgarh', '23': 'Madhya Pradesh', '24': 'Gujarat',
            '27': 'Maharashtra', '28': 'Andhra Pradesh', '29': 'Karnataka', '30': 'Goa',
            '31': 'Lakshadweep', '32': 'Kerala', '33': 'Tamil Nadu', '34': 'Puducherry',
            '35': 'Andaman & Nicobar Islands', '36': 'Telangana', '37': 'Andhra Pradesh',
            '38': 'Ladakh'
        }
        
        # Extract fields safely
        lgnm = get_val(result, 'lgnm')
        tradeNam = get_val(result, 'tradeNam') or lgnm
        
        # 1. Get Principal Place of Business object
        pradr = get_val(result, 'pradr')
        if isinstance(pradr, list) and len(pradr) > 0:
            pradr = pradr[0]
        
        # 2. Get address details (try various structures)
        addr_data = {}
        full_addr_str = ""
        
        if isinstance(pradr, dict):
            # Try nested 'addr' or 'adr'
            addr_data = pradr.get('addr') or pradr.get('adr')
            if not isinstance(addr_data, dict):
                # Check if pradr itself has the fields
                if 'bnm' in pradr or 'st' in pradr:
                    addr_data = pradr
                elif isinstance(addr_data, str):
                    full_addr_str = addr_data
                    addr_data = {}
        elif isinstance(pradr, str):
            full_addr_str = pradr
            
        # Fallback to adadr if pradr failed
        if not addr_data and not full_addr_str:
            adadr = get_val(result, 'adadr')
            if isinstance(adadr, list) and len(adadr) > 0:
                first_ad = adadr[0]
                addr_data = first_ad.get('addr') or first_ad.get('adr') or first_ad
        
        if not isinstance(addr_data, dict): addr_data = {}

        # Extract sub-fields from whichever object we found
        bnm = str(addr_data.get('bnm') or '')
        st = str(addr_data.get('st') or '')
        loc = str(addr_data.get('loc') or '')
        bno = str(addr_data.get('bno') or '')
        flno = str(addr_data.get('flno') or '')
        stcd = str(addr_data.get('stcd') or '')
        dst = str(addr_data.get('dst') or addr_data.get('city') or '')
        pncd = str(addr_data.get('pncd') or addr_data.get('pincode') or '')
        
        # Build address string if we didn't get a flat one
        if not full_addr_str:
            addr_parts = [bno, flno, bnm, st, loc, dst]
            full_addr_str = ", ".join([p for p in addr_parts if p and p.strip()]).strip(", ")
        
        # Fallback: Extract Pincode and City from full_addr_str if missing
        import re
        if not pncd and full_addr_str:
            match = re.search(r'\b\d{6}\b', full_addr_str)
            if match: pncd = match.group(0)
            
        if not dst and not loc and full_addr_str:
            # Try to guess city from comma-separated parts
            parts = [p.strip() for p in full_addr_str.split(',') if p.strip()]
            if len(parts) >= 2:
                # If last part is pincode, city is usually 2 steps back
                if re.match(r'^\d{6}$', parts[-1]):
                    if len(parts) >= 3: dst = parts[-3]
                else:
                    # City is usually the part before the state (which is usually the last part)
                    dst = parts[-2]

        # State and Nature
        state = state_map.get(gstin[:2], stcd or "Maharashtra")

        # CLEANUP: Remove redundant city, state, pincode from address string
        if full_addr_str:
            # Strip multiple times to handle cases like "City, State, Pincode"
            for _ in range(5):
                prev = full_addr_str
                full_addr_str = full_addr_str.strip(", ")
                
                # Strip pincode
                if pncd and full_addr_str.endswith(pncd):
                    full_addr_str = full_addr_str[:-len(pncd)].strip(", ")
                
                # Strip state name
                if state and full_addr_str.lower().endswith(state.lower()):
                    full_addr_str = full_addr_str[:-len(state)].strip(", ")
                
                # Strip city (dst or loc)
                for c_val in [dst, loc]:
                    if c_val and len(c_val) > 2 and full_addr_str.lower().endswith(c_val.lower()):
                        full_addr_str = full_addr_str[:-len(c_val)].strip(", ")
                
                if full_addr_str == prev: break

        # ntr can be in pradr or root nba
        ntr = ""
        if isinstance(pradr, dict): ntr = pradr.get('ntr', '')
        if not ntr:
            nba = result.get('nba', [])
            if isinstance(nba, list) and nba: ntr = nba[0]
            elif isinstance(nba, str): ntr = nba

        mapped_data = {
            'gstin': gstin,
            'legal_name': lgnm,
            'trade_name': tradeNam,
            'state': state,
            'address': full_addr_str,
            'city': dst or loc,
            'pincode': pncd,
            'nature': str(ntr),
            'status': get_val(result, 'sts'),
            'type': get_val(result, 'ctb')
        }
        
        return jsonify({'success': True, 'data': mapped_data})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Lookup failed: {str(e)}'})
