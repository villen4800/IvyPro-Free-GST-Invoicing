from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_required
from app.models import (StockItem, StockGroup, Unit, GSTRate, VoucherItem, Voucher, SerialNumber)
from app import db
from sqlalchemy import func
from datetime import date

inventory_bp = Blueprint('inventory', __name__)

def get_cid():
    return session.get('company_id', 1)

# ─── Helpers ─────────────────────────────────────────────
def calc_stock(item_id, company_id, godown_id=None):
    item = StockItem.query.get(item_id)
    base = item.opening_qty if item else 0

    q = db.session.query(
        func.sum(VoucherItem.qty),
        Voucher.voucher_type
    ).join(Voucher).filter(
        VoucherItem.stock_item_id == item_id,
        Voucher.company_id == company_id,
        Voucher.is_cancelled == False,
        Voucher.is_trash == False
    ).group_by(Voucher.voucher_type).all()

    purchased = sum(qty for qty, vt in q if vt in ('Purchase','Receipt Note','Credit Note'))
    sold      = sum(qty for qty, vt in q if vt in ('Sales','Delivery Note','Debit Note'))
    return base + purchased - sold

# ─── Stock Items ─────────────────────────────────────────
@inventory_bp.route('/')
@login_required
def index():
    cid = get_cid()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    q = request.args.get('q', '')
    group_id = request.args.get('group_id', type=int)
    
    query = StockItem.query.filter_by(company_id=cid, is_active=True)
    if group_id:
        query = query.filter(StockItem.group_id == group_id)
        
    if q:
        query = query.filter(
            (StockItem.name.ilike(f'%{q}%')) | 
            (StockItem.alias.ilike(f'%{q}%')) | 
            (StockItem.barcode.ilike(f'%{q}%')) |
            (StockItem.hsn_code.ilike(f'%{q}%'))
        )
        
    pagination = query.order_by(StockItem.name).paginate(page=page, per_page=per_page, error_out=False)
    
    # Calculate current stock for the items on this page
    for item in pagination.items:
        item.current_stock = calc_stock(item.id, cid)
        
    groups = StockGroup.query.filter_by(company_id=cid).order_by(StockGroup.name).all()
    
    return render_template('inventory/index.html', 
                           items=pagination.items, 
                           pagination=pagination,
                           per_page=per_page,
                           q=q,
                           groups=groups)

@inventory_bp.route('/create', methods=['GET','POST'])
@login_required
def create():
    cid = get_cid()
    groups = StockGroup.query.filter_by(company_id=cid).all()
    units = Unit.query.all()
    gst_rates = GSTRate.query.all()
    if request.method == 'POST':
        item = StockItem(
            company_id=cid,
            name=request.form['name'],
            alias=request.form.get('alias'),
            group_id=request.form.get('group_id') or None,
            unit_id=request.form.get('unit_id') or None,
            hsn_code=request.form.get('hsn_code',''),
            gst_rate_id=request.form.get('gst_rate_id') or None,
            purchase_rate=float(request.form.get('purchase_rate') or 0),
            sale_rate=float(request.form.get('sale_rate') or 0),
            mrp=float(request.form.get('mrp') or 0),
            opening_qty=float(request.form.get('opening_qty') or request.form.get('opening_stock') or 0),
            opening_value=float(request.form.get('opening_value') or 0),
            reorder_level=float(request.form.get('reorder_level') or 0),
            is_service=request.form.get('is_service') in ['1', 'true', 'on'],
            description=request.form.get('description'),
            barcode=request.form.get('barcode'),
        )
        db.session.add(item)
        db.session.flush()
        db.session.commit()

        # Handle Serial Numbers
        sns_text = request.form.get('serial_numbers', '')
        if sns_text:
            for line in sns_text.split('\n'):
                sn = line.strip()
                if sn:
                    exists = SerialNumber.query.filter_by(serial_number=sn, company_id=cid).first()
                    if not exists:
                        db.session.add(SerialNumber(stock_item_id=item.id, company_id=cid, serial_number=sn))
            db.session.commit()

        flash('Item created!', 'success')
        return redirect(url_for('inventory.index'))
    return render_template('inventory/form.html', groups=groups, units=units, gst_rates=gst_rates)

@inventory_bp.route('/edit/<int:id>', methods=['GET','POST'])
@login_required
def edit(id):
    cid = get_cid()
    item = StockItem.query.get_or_404(id)
    groups = StockGroup.query.filter_by(company_id=cid).all()
    units = Unit.query.all()
    gst_rates = GSTRate.query.all()
    if request.method == 'POST':
        item.name         = request.form['name']
        item.alias        = request.form.get('alias')
        item.group_id     = request.form.get('group_id') or None
        item.unit_id      = request.form.get('unit_id') or None
        item.hsn_code     = request.form.get('hsn_code','')
        item.gst_rate_id  = request.form.get('gst_rate_id') or None
        item.purchase_rate= float(request.form.get('purchase_rate') or 0)
        item.sale_rate    = float(request.form.get('sale_rate') or 0)
        item.mrp          = float(request.form.get('mrp') or 0)
        item.opening_qty  = float(request.form.get('opening_qty') or request.form.get('opening_stock') or 0)
        item.reorder_level= float(request.form.get('reorder_level') or 0)
        item.is_service   = request.form.get('is_service') in ['1', 'true', 'on']
        item.description  = request.form.get('description')
        item.barcode      = request.form.get('barcode')
        
            
        db.session.commit()
        
        # Handle Serial Numbers
        sns_text = request.form.get('serial_numbers', '')
        if sns_text:
            for line in sns_text.split('\n'):
                sn = line.strip()
                if sn:
                    exists = SerialNumber.query.filter_by(serial_number=sn, company_id=cid).first()
                    if not exists:
                        db.session.add(SerialNumber(stock_item_id=item.id, company_id=cid, serial_number=sn))
            db.session.commit()

        flash('Item updated!', 'success')
        return redirect(url_for('inventory.index'))
    return render_template('inventory/form.html', item=item, groups=groups, units=units, gst_rates=gst_rates, edit=True)

@inventory_bp.route('/delete/<int:id>')
@login_required
def delete(id):
    item = StockItem.query.get_or_404(id)
    item.is_active = False
    db.session.commit()
    flash('Item deleted', 'success')
    return redirect(url_for('inventory.index'))

# ─── Stock Summary (Tally-style) ─────────────────────────
@inventory_bp.route('/stock-summary')
@login_required
def stock_summary():
    cid = get_cid()
    group_id = request.args.get('group_id', type=int)
    q = request.args.get('q', '')
    
    current_group = StockGroup.query.get(group_id) if group_id else None
    
    # 1. Get Sub-groups
    subgroups = StockGroup.query.filter_by(company_id=cid, parent_id=group_id).order_by(StockGroup.name).all()
    
    # 2. Get Items in this group
    items_query = StockItem.query.filter_by(company_id=cid, is_active=True, group_id=group_id)
    if q:
        items_query = items_query.filter(StockItem.name.ilike(f'%{q}%'))
    items = items_query.order_by(StockItem.name).all()
    
    # 3. Calculate movements for all relevant items in one batch
    # We need to know which items are under which subgroup to sum them up.
    all_items_in_cid = StockItem.query.filter_by(company_id=cid, is_active=True).all()
    
    # Pre-calculate item balances
    movements = db.session.query(
        VoucherItem.stock_item_id,
        Voucher.voucher_type,
        func.sum(VoucherItem.qty)
    ).join(Voucher).filter(
        Voucher.company_id == cid,
        Voucher.is_cancelled == False,
        Voucher.is_trash == False
    ).group_by(VoucherItem.stock_item_id, Voucher.voucher_type).all()

    m_map = {}
    for iid, vtype, qty in movements:
        if iid not in m_map: m_map[iid] = {'in': 0, 'out': 0}
        if vtype in ('Purchase','Receipt Note','Credit Note'): m_map[iid]['in'] += qty
        elif vtype in ('Sales','Delivery Note','Debit Note'): m_map[iid]['out'] += qty
        
    item_stats = {}
    for item in all_items_in_cid:
        m = m_map.get(item.id, {'in': 0, 'out': 0})
        closing = item.opening_qty + m['in'] - m['out']
        item_stats[item.id] = {
            'opening': item.opening_qty,
            'inward': m['in'],
            'outward': m['out'],
            'closing': closing,
            'value': closing * (item.purchase_rate or 0)
        }
        
    # Helper to get recursive totals
    def get_recursive_stats(gid):
        # Find all subgroups under gid
        total = {'opening': 0, 'inward': 0, 'outward': 0, 'closing': 0, 'value': 0}
        
        # Items directly in this group
        group_items = [i for i in all_items_in_cid if i.group_id == gid]
        for i in group_items:
            stats = item_stats.get(i.id, {'opening': 0, 'inward': 0, 'outward': 0, 'closing': 0, 'value': 0})
            for k in total: total[k] += stats[k]
            
        # Recurse for sub-groups
        child_groups = [g for g in all_groups if g.parent_id == gid]
        for cg in child_groups:
            cstats = get_recursive_stats(cg.id)
            for k in total: total[k] += cstats[k]
            
        return total

    all_groups = StockGroup.query.filter_by(company_id=cid).all()
    
    result = []
    # Add subgroups to result
    for sg in subgroups:
        stats = get_recursive_stats(sg.id)
        result.append({
            'type': 'group',
            'id': sg.id,
            'name': sg.name,
            'stats': stats
        })
        
    # Add items to result
    for item in items:
        stats = item_stats.get(item.id)
        result.append({
            'type': 'item',
            'id': item.id,
            'name': item.name,
            'item': item, # For template details
            'stats': stats
        })

    # Calculate Grand Total for the current view
    total_value = sum(r['stats']['value'] for r in result)
    
    return render_template('inventory/stock_summary.html',
                           result=result, 
                           current_group=current_group,
                           total_value=total_value,
                           q=q)

# ─── Stock Ledger (item-wise movement) ───────────────────
@inventory_bp.route('/stock-ledger/<int:item_id>')
@login_required
def stock_ledger(item_id):
    cid = get_cid()
    item = StockItem.query.get_or_404(item_id)
    
    # Standardize dates
    f_str = request.args.get('from_date', date.today().replace(month=4,day=1).isoformat())
    t_str = request.args.get('to_date', date.today().isoformat())
    try:
        from_date = date.fromisoformat(f_str)
        to_date = date.fromisoformat(t_str)
    except:
        from_date = date.today().replace(month=4,day=1)
        to_date = date.today()

    movements = db.session.query(VoucherItem, Voucher).join(Voucher).filter(
        VoucherItem.stock_item_id == item_id,
        Voucher.company_id == cid,
        Voucher.is_cancelled == False,
        Voucher.is_trash == False,
        Voucher.date >= from_date,
        Voucher.date <= to_date,
    ).order_by(Voucher.date).all()

    running = item.opening_qty
    rows = []
    for vi, v in movements:
        in_qty = out_qty = 0
        if v.voucher_type in ('Purchase','Receipt Note','Credit Note'):
            in_qty = vi.qty
        else:
            out_qty = vi.qty
        running += in_qty - out_qty
        rows.append({'voucher': v, 'item': vi, 'in_qty': in_qty,
                     'out_qty': out_qty, 'balance': running})

    return render_template('inventory/stock_ledger.html',
        item=item, rows=rows, from_date=from_date.isoformat(), to_date=to_date.isoformat(),
        opening=item.opening_qty)


# ─── Groups ──────────────────────────────────────────────
@inventory_bp.route('/groups')
@login_required
def groups():
    cid = get_cid()
    groups = StockGroup.query.filter_by(company_id=cid).all()
    return render_template('inventory/groups.html', groups=groups)

@inventory_bp.route('/groups/create', methods=['POST'])
@login_required
def create_group():
    cid = get_cid()
    g = StockGroup(name=request.form['name'], company_id=cid,
                   parent_id=request.form.get('parent_id') or None)
    db.session.add(g)
    db.session.commit()
    flash('Stock group created!', 'success')
    return redirect(url_for('inventory.groups'))

# ─── API search (for invoice form) ──────────────────────
@inventory_bp.route('/api/search')
@login_required
def api_search():
    cid = get_cid()
    q = request.args.get('q','')
    items = StockItem.query.filter(
        StockItem.company_id == cid,
        StockItem.is_active == True,
        (StockItem.name.ilike(f'%{q}%') | StockItem.barcode.ilike(f'%{q}%'))
    ).limit(20).all()
    result = []
    for item in items:
        current_stock = calc_stock(item.id, cid)
        result.append({
            'id': item.id, 'name': item.name,
            'rate': float(item.sale_rate or 0), 
            'sale_rate': float(item.sale_rate or 0),
            'purchase_rate': float(item.purchase_rate or 0),
            'hsn': item.hsn_code or '',
            'unit': item.unit.symbol if item.unit else '',
            'gst_rate': item.gst_rate.rate if item.gst_rate else 0,
            'cgst': item.gst_rate.cgst if item.gst_rate else 0,
            'sgst': item.gst_rate.sgst if item.gst_rate else 0,
            'igst': item.gst_rate.igst if item.gst_rate else 0,
            'current_stock': round(current_stock, 3),
            'mrp': float(item.mrp or 0),
        })
    return jsonify(result)

@inventory_bp.route('/api/check-serial/<string:sn>')
@login_required
def check_serial(sn):
    cid = get_cid()
    serial = SerialNumber.query.filter_by(serial_number=sn, company_id=cid, status='Available').first()
    if serial:
        item = serial.stock_item
        current_stock = calc_stock(item.id, cid)
        return jsonify({
            'success': True,
            'id': item.id,
            'name': item.name,
            'rate': float(item.sale_rate or 0),
            'sale_rate': float(item.sale_rate or 0),
            'purchase_rate': float(item.purchase_rate or 0),
            'hsn': item.hsn_code or '',
            'unit': item.unit.symbol if item.unit else '',
            'gst_rate': item.gst_rate.rate if item.gst_rate else 0,
            'cgst': item.gst_rate.cgst if item.gst_rate else 0,
            'sgst': item.gst_rate.sgst if item.gst_rate else 0,
            'igst': item.gst_rate.igst if item.gst_rate else 0,
            'current_stock': round(current_stock, 3),
            'mrp': float(item.mrp or 0),
            'serial_number': serial.serial_number
        })
    return jsonify({'success': False})

@inventory_bp.route('/api/stock-item-serials/<int:item_id>')
@login_required
def get_stock_item_serials(item_id):
    cid = get_cid()
    serials = SerialNumber.query.filter_by(stock_item_id=item_id, company_id=cid, status='Available').all()
    return jsonify([s.serial_number for s in serials])
