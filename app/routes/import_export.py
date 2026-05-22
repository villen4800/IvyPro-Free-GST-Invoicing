from flask import Blueprint, render_template, request, redirect, url_for, flash, session, send_file, make_response
from flask_login import login_required
from app.models import Voucher, Ledger, StockItem, Company, VoucherItem, LedgerGroup, StockGroup, Unit
from app import db
import io, csv, json
from datetime import date
import zipfile
from sqlalchemy import or_

import_export_bp = Blueprint('import_export', __name__)

def get_cid():
    return session.get('company_id', 1)

@import_export_bp.route('/')
@login_required
def index():
    return render_template('import_export/index.html')

# ─── Export CSV ──────────────────────────────────────────
@import_export_bp.route('/export/sales-csv')
@login_required
def export_sales_csv():
    cid = get_cid()
    from_date = request.args.get('from_date', date.today().replace(month=4, day=1).isoformat())
    to_date = request.args.get('to_date', date.today().isoformat())
    
    vouchers = Voucher.query.filter_by(company_id=cid, voucher_type='Sales', is_cancelled=False)\
        .filter(Voucher.date >= from_date, Voucher.date <= to_date).order_by(Voucher.date).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date','Invoice No','Party','GSTIN','Taxable','CGST','SGST','IGST','Total'])
    for v in vouchers:
        writer.writerow([
            v.date.strftime('%d/%m/%Y'), v.voucher_number,
            v.party.name if v.party else '', v.party.gstin if v.party else '',
            round(v.taxable_amount,2), round(v.cgst_amount,2),
            round(v.sgst_amount,2), round(v.igst_amount,2), round(v.total_amount,2)
        ])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename="Sales_{from_date}_to_{to_date}.csv"'
    return response

@import_export_bp.route('/export/purchase-csv')
@login_required
def export_purchase_csv():
    cid = get_cid()
    from_date = request.args.get('from_date', date.today().replace(month=4, day=1).isoformat())
    to_date = request.args.get('to_date', date.today().isoformat())
    
    vouchers = Voucher.query.filter_by(company_id=cid, voucher_type='Purchase', is_cancelled=False)\
        .filter(Voucher.date >= from_date, Voucher.date <= to_date).order_by(Voucher.date).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date','Bill No','Supplier','GSTIN','Taxable','CGST','SGST','IGST','Total'])
    for v in vouchers:
        writer.writerow([
            v.date.strftime('%d/%m/%Y'), v.ref_number or v.voucher_number,
            v.party.name if v.party else '', v.party.gstin if v.party else '',
            round(v.taxable_amount,2), round(v.cgst_amount,2),
            round(v.sgst_amount,2), round(v.igst_amount,2), round(v.total_amount,2)
        ])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename="Purchase_{from_date}_to_{to_date}.csv"'
    return response

@import_export_bp.route('/export/ledgers-csv')
@login_required
def export_ledgers_csv():
    cid = get_cid()
    ledgers = Ledger.query.filter_by(company_id=cid, is_active=True).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Name','Alias','Group','GSTIN','PAN','City','State','Phone','Email','Opening Balance','Type'])
    for l in ledgers:
        writer.writerow([
            l.name, l.alias or '', l.group.name if l.group else '',
            l.gstin or '', l.pan or '', l.city or '', l.state or '',
            l.phone or '', l.email or '', l.opening_balance, l.opening_type
        ])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = 'attachment; filename="Ledgers.csv"'
    return response

@import_export_bp.route('/export/items-csv')
@login_required
def export_items_csv():
    cid = get_cid()
    items = StockItem.query.filter_by(company_id=cid, is_active=True).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Name','Alias','HSN Code','Unit','GST Rate','Purchase Rate','Sale Rate','MRP','Opening Qty','Opening Value'])
    for item in items:
        writer.writerow([
            item.name, item.alias or '', item.hsn_code or '',
            item.unit.symbol if item.unit else '', 
            item.gst_rate.rate if item.gst_rate else 0,
            item.purchase_rate, item.sale_rate, item.mrp,
            item.opening_qty, item.opening_value
        ])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = 'attachment; filename="StockItems.csv"'
    return response

# CSV Import logic follows...

# ─── Import CSV ──────────────────────────────────────────
@import_export_bp.route('/import/ledgers', methods=['POST'])
@login_required
def import_ledgers():
    cid = get_cid()
    if 'file' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(url_for('import_export.index'))
    
    file = request.files['file']
    from app.models import LedgerGroup
    
    content = file.read().decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(content))
    
    count = 0
    for row in reader:
        name = row.get('Name','').strip()
        if not name:
            continue
        existing = Ledger.query.filter_by(company_id=cid, name=name).first()
        if existing:
            continue
        group_name = row.get('Group','').strip()
        group = LedgerGroup.query.filter_by(name=group_name).first() if group_name else None
        l = Ledger(
            company_id=cid, name=name,
            alias=row.get('Alias','').strip() or None,
            group_id=group.id if group else None,
            gstin=row.get('GSTIN','').strip().upper() or None,
            pan=row.get('PAN','').strip().upper() or None,
            city=row.get('City','').strip() or None,
            state=row.get('State','').strip() or None,
            phone=row.get('Phone','').strip() or None,
            email=row.get('Email','').strip() or None,
            opening_balance=float(row.get('Opening Balance',0) or 0),
            opening_type=row.get('Type','Dr').strip() or 'Dr',
        )
        db.session.add(l)
        count += 1
    
    db.session.commit()
    flash(f'{count} ledgers imported successfully!', 'success')
    return redirect(url_for('import_export.index'))

@import_export_bp.route('/import/items', methods=['POST'])
@login_required
def import_items():
    cid = get_cid()
    if 'file' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(url_for('import_export.index'))
    
    file = request.files['file']
    from app.models import Unit, GSTRate
    
    content = file.read().decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(content))
    
    count = 0
    for row in reader:
        name = row.get('Name','').strip()
        if not name:
            continue
        existing = StockItem.query.filter_by(company_id=cid, name=name).first()
        if existing:
            continue
        
        unit_sym = row.get('Unit','').strip()
        unit = Unit.query.filter_by(symbol=unit_sym).first() if unit_sym else None
        
        gst_r = float(row.get('GST Rate',18) or 18)
        gst_rate_obj = GSTRate.query.filter_by(rate=gst_r).first()
        
        item = StockItem(
            company_id=cid, name=name,
            alias=row.get('Alias','').strip() or None,
            hsn_code=row.get('HSN Code','').strip() or None,
            unit_id=unit.id if unit else None,
            gst_rate_id=gst_rate_obj.id if gst_rate_obj else None,
            purchase_rate=float(row.get('Purchase Rate',0) or 0),
            sale_rate=float(row.get('Sale Rate',0) or 0),
            mrp=float(row.get('MRP',0) or 0),
            opening_qty=float(row.get('Opening Qty',0) or 0),
            opening_value=float(row.get('Opening Value',0) or 0),
        )
        db.session.add(item)
        count += 1
    
    db.session.commit()
    flash(f'{count} items imported successfully!', 'success')
    return redirect(url_for('import_export.index'))

# ─── Backup ──────────────────────────────────────────────
# Backup logic follows...

@import_export_bp.route('/backup')
@login_required
def backup():
    import os, shutil
    from flask import current_app; base_dir = current_app.config.get('BASE_DIR', os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    db_path = os.path.join(base_dir, 'data', 'gst_billing.db')
    backup_name = f'backup_{date.today().isoformat()}.db'
    backup_path = os.path.join(base_dir, 'backups', backup_name)
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    shutil.copy2(db_path, backup_path)
    return send_file(backup_path, as_attachment=True, download_name=backup_name)
