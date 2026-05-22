from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, make_response
from flask_login import login_required
from app.models import Voucher, VoucherItem, LedgerEntry, Ledger, StockItem, GSTRate, Company, HSNCode
from app import db
from datetime import date, datetime
from app.utils.invoice_pdf import generate_modern_invoice_pdf, generate_receipt_pdf

vouchers_bp = Blueprint('vouchers', __name__)

def get_cid():
    cid = session.get('company_id')
    if not cid:
        c = Company.query.filter_by(is_active=True).first()
        if c:
            session['company_id'] = c.id
            return c.id
    return cid or 1

def is_v_locked(company, vdate):
    if company and company.is_locked and company.lock_date:
        return vdate <= company.lock_date
    return False

def _auto_save_hsn(hsn_code, gst_rate, description=''):
    """Auto-learn HSN codes from voucher entries. If a new HSN code is used,
    save it to the HSN master with its GST rate for future auto-suggest."""
    hsn_code = (hsn_code or '').strip()
    if not hsn_code or len(hsn_code) < 4 or gst_rate is None:
        return
    try:
        existing = HSNCode.query.filter_by(code=hsn_code).first()
        if not existing:
            new_hsn = HSNCode(
                code=hsn_code,
                gst_rate=float(gst_rate),
                description=(description or 'Auto-learned from voucher')[:500]
            )
            db.session.add(new_hsn)
        elif existing.gst_rate != float(gst_rate):
            # Update rate if it changed
            existing.gst_rate = float(gst_rate)
    except Exception:
        pass  # Silent fail — don't break voucher save

def get_next_number(company_id, voucher_type):
    company = Company.query.get(company_id)
    prefixes = {
        'Sales': 'INV', 'Purchase': 'PUR', 'Credit Note': 'CN',
        'Debit Note': 'DN', 'Receipt': 'RCT', 'Payment': 'PMT',
        'Journal': 'JV', 'Contra': 'CON'
    }
    prefix = prefixes.get(voucher_type, 'VCH')

    if company and company.randomize_vouchers:
        import random
        fy = date.today().year
        for _ in range(20):
            rand_val = random.randint(1001, 99999)
            vnum = f"{prefix}/{fy}/{rand_val}"
            if not Voucher.query.filter_by(company_id=company_id, voucher_number=vnum).first():
                return vnum

    last = Voucher.query.filter_by(company_id=company_id, voucher_type=voucher_type)\
        .order_by(Voucher.id.desc()).first()
    fy = date.today().year
    if last and last.voucher_number and '/' in last.voucher_number:
        try:
            num = int(last.voucher_number.split('/')[-1]) + 1
        except:
            num = 1
    else:
        num = 1
    return f"{prefix}/{fy}/{num:04d}"

@vouchers_bp.route('/<vtype>')
@login_required
def list_vouchers(vtype):
    cid = get_cid()
    valid = ['Sales','Purchase','Credit Note','Debit Note','Receipt','Payment','Journal','Contra']
    if vtype not in valid:
        return redirect(url_for('dashboard.index'))
    
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    q = request.args.get('q', '')
    
    query = Voucher.query.filter_by(company_id=cid, voucher_type=vtype, is_trash=False)
    if q:
        query = query.join(Voucher.party, isouter=True).filter(
            (Voucher.voucher_number.ilike(f'%{q}%')) |
            (Voucher.narration.ilike(f'%{q}%')) |
            (Ledger.name.ilike(f'%{q}%'))
        )
        
    pagination = query.order_by(Voucher.date.desc(), Voucher.id.desc()).paginate(page=page, per_page=per_page, error_out=False)
        
    return render_template('vouchers/list.html', 
                           vouchers=pagination.items, 
                           pagination=pagination,
                           vtype=vtype,
                           per_page=per_page,
                           q=q)

@vouchers_bp.route('/create/<vtype>', methods=['GET','POST'])
@login_required
def create(vtype):
    cid = get_cid()
    company = Company.query.get(cid)
    ledgers = Ledger.query.filter_by(company_id=cid, is_active=True).order_by(Ledger.name).all()
    items = StockItem.query.filter_by(company_id=cid, is_active=True).all()
    gst_rates = GSTRate.query.all()
    
    if request.method == 'POST':
        data = request.json if request.is_json else request.form
        
        # Validation for empty voucher
        inventory_vtypes = ['Sales','Purchase','Credit Note','Debit Note']
        if vtype in inventory_vtypes:
            items_list = data.get('items') if request.is_json else None
            if not items_list and not request.is_json:
                import json
                try: items_list = json.loads(data.get('items_json', '[]'))
                except: items_list = []
            
            if not items_list or len(items_list) == 0:
                if request.is_json: return jsonify({'success': False, 'error': 'Voucher must have at least one item.'})
                flash('Cannot create voucher without items!', 'error')
                return redirect(request.referrer or url_for('vouchers.list_vouchers', vtype=vtype))
        else:
            entries = data.get('entries')
            if not entries or len(entries) == 0:
                if request.is_json: return jsonify({'success': False, 'error': 'Voucher must have at least one entry.'})
                flash('Cannot create voucher without entries!', 'error')
                return redirect(request.referrer or url_for('vouchers.list_vouchers', vtype=vtype))
        
        vdate = datetime.strptime(data.get('date', date.today().isoformat()), '%Y-%m-%d').date()
        if is_v_locked(company, vdate):
            flash(f'Cannot create voucher. Date {vdate} is locked!', 'error')
            return redirect(url_for('vouchers.list_vouchers', vtype=vtype))
            
        v = Voucher(
            company_id=cid,
            voucher_type=vtype,
            voucher_number=get_next_number(cid, vtype),
            date=vdate,
            ref_number=data.get('ref_number',''),
            party_ledger_id=data.get('party_ledger_id') or None,
            narration=data.get('narration',''),
            place_of_supply=data.get('place_of_supply', company.state if company else ''),
            is_igst=data.get('is_igst') in [True, 'true', '1', 'on'],
            reverse_charge=data.get('reverse_charge') in [True, 'true', '1', 'on'],
            payment_mode=data.get('payment_mode', 'Credit'),
            eway_bill_no=data.get('eway_bill_no'),
            vehicle_no=data.get('vehicle_no'),
            transporter_name=data.get('transporter_name'),
            tds_percent=float(data.get('tds_percent', 0)),
            payment_ledger_id=data.get('payment_ledger_id') or None,
            billing_address=data.get('billing_address'),
            billing_city=data.get('billing_city'),
            billing_state=data.get('billing_state'),
            billing_pincode=data.get('billing_pincode'),
            billing_gstin=data.get('billing_gstin'),
            shipping_address=data.get('shipping_address'),
            shipping_city=data.get('shipping_city'),
            shipping_state=data.get('shipping_state'),
            shipping_pincode=data.get('shipping_pincode'),
            shipping_gstin=data.get('shipping_gstin')
        )
        
        db.session.add(v)
        db.session.flush()
        
        # Parse items and totals using the unified helper
        _save_voucher_items_and_totals(v, data, request.is_json)
        
        # Double-entry bookkeeping
        if 'entries' in data and data['entries']:
            # Simple Voucher mode: Save provided entries
            total_dr = 0
            for row in data['entries']:
                lid = row.get('ledger_id')
                amt = float(row.get('amount', 0))
                type = row.get('dr_cr', 'Dr')
                if lid and amt > 0:
                    debit = amt if type == 'Dr' else 0
                    credit = amt if type == 'Cr' else 0
                    if debit > 0: total_dr += debit
                    db.session.add(LedgerEntry(
                        voucher_id=v.id, company_id=cid, ledger_id=lid,
                        date=v.date, debit=debit, credit=credit, narration=v.narration,
                        bank_tx_type=row.get('bank_tx_type'),
                        inst_no=row.get('inst_no'),
                        inst_date=datetime.strptime(row['inst_date'], '%Y-%m-%d').date() if row.get('inst_date') else None,
                        bank_name=row.get('bank_name')
                    ))
            v.total_amount = total_dr
        else:
            # Inventory Voucher mode: Generate entries from items
            create_ledger_entries(v, company)
            
            # Automatic Receipt/Payment for Cash transactions
            handle_automatic_payment(v, company)

        db.session.commit()
        flash(f'{vtype} {v.voucher_number} saved!', 'success')
        
        if request.is_json:
            return jsonify({'success': True, 'id': v.id, 'number': v.voucher_number})
        return redirect(url_for('vouchers.view', id=v.id))
    
    from app.routes.company import INDIAN_STATES
    from app.models import LedgerGroup
    groups = LedgerGroup.query.filter(LedgerGroup.name.in_(['Cash-in-Hand', 'Bank Accounts'])).all()
    group_ids = [g.id for g in groups]
    cash_bank_ledgers = Ledger.query.filter(
        Ledger.company_id == cid,
        Ledger.group_id.in_(group_ids),
        Ledger.is_active == True
    ).order_by(Ledger.name).all()
    
    inventory_vtypes = ['Sales','Purchase','Credit Note','Debit Note']
    mode = request.args.get('mode', 'standard')
    
    tmpl = 'vouchers/create.html' if vtype in inventory_vtypes else 'vouchers/create_simple.html'
    if mode == 'pos' and vtype == 'Sales': tmpl = 'vouchers/create_pos.html'
    elif mode == 'service' and vtype == 'Sales': tmpl = 'vouchers/create_service.html'

    from app.models import LedgerGroup
    categories = LedgerGroup.query.all() # For POS category filter

    return render_template(tmpl, vtype=vtype, company=company, voucher=None,
                           items=items, gst_rates=gst_rates,
                           states=INDIAN_STATES,
                           today=date.today().isoformat(),
                           next_number=get_next_number(cid, vtype),
                           cash_bank_ledgers=cash_bank_ledgers,
                           categories=categories)

@vouchers_bp.route('/duplicate/<int:id>')
@login_required
def duplicate(id):
    original = Voucher.query.get_or_404(id)
    cid = original.company_id
    company = Company.query.get(cid)
    
    new_v = Voucher(
        company_id=cid,
        voucher_type=original.voucher_type,
        voucher_number=get_next_number(cid, original.voucher_type),
        date=date.today(),
        ref_number=f"Copy of {original.voucher_number}",
        party_ledger_id=original.party_ledger_id,
        narration=original.narration,
        place_of_supply=original.place_of_supply,
        is_igst=original.is_igst,
        reverse_charge=original.reverse_charge,
        payment_mode=original.payment_mode,
        payment_ledger_id=original.payment_ledger_id,
        total_amount=original.total_amount,
        subtotal=original.subtotal,
        discount_amount=original.discount_amount,
        taxable_amount=original.taxable_amount,
        cgst_amount=original.cgst_amount,
        sgst_amount=original.sgst_amount,
        igst_amount=original.igst_amount,
        cess_amount=original.cess_amount,
        round_off=original.round_off
    )
    
    for item in original.items:
        new_item = VoucherItem(
            stock_item_id=item.stock_item_id,
            description=item.description,
            hsn_code=item.hsn_code,
            qty=item.qty,
            unit=item.unit,
            rate=item.rate,
            discount_pct=item.discount_pct,
            discount_amt=item.discount_amt,
            taxable_amount=item.taxable_amount,
            gst_rate=item.gst_rate,
            cgst_rate=item.cgst_rate,
            cgst_amount=item.cgst_amount,
            sgst_rate=item.sgst_rate,
            sgst_amount=item.sgst_amount,
            igst_rate=item.igst_rate,
            igst_amount=item.igst_amount,
            cess_rate=item.cess_rate,
            cess_amount=item.cess_amount,
            total_amount=item.total_amount
        )
        new_v.items.append(new_item)
    
    db.session.add(new_v)
    db.session.flush()
    create_ledger_entries(new_v, company)
    db.session.commit()
    
    flash(f'Voucher {original.voucher_number} duplicated to {new_v.voucher_number}', 'success')
    return redirect(url_for('vouchers.edit', id=new_v.id))

@vouchers_bp.route('/send-whatsapp/<int:id>')
@login_required
def send_whatsapp(id):
    import urllib.parse
    v = Voucher.query.get_or_404(id)
    company = Company.query.get(v.company_id)
    party = v.party
    phone = ""
    if party and party.phone:
        phone = ''.join(c for c in party.phone if c.isdigit())
        if len(phone) == 10: phone = '91' + phone
        
    vtype_name = "Invoice" if v.voucher_type == 'Sales' else v.voucher_type
    emoji = "🧾" if v.voucher_type == 'Sales' else "💸"
    
    msg = f"{emoji} *{vtype_name}* from *{company.name}*\n"
    msg += f"Doc No: *{v.voucher_number}*\n"
    msg += f"Date: {v.date.strftime('%d/%m/%Y')}\n"
    if v.voucher_type == 'Sales':
        msg += f"Thank you for your business! Items summary:\n"
        for item in v.items:
            msg += f"• {item.description}: {item.qty} {item.unit or 'Nos'} @ ₹{item.rate:,.2f}\n"
    elif v.voucher_type == 'Receipt':
        msg += f"We have successfully received your payment. Details:\n"
        for entry in v.ledger_entries:
            if entry.credit > 0:
                msg += f"• {entry.ledger.name}: ₹{entry.credit:,.2f}\n"
    else:
        # General details for other vouchers
        for entry in v.ledger_entries:
            side = "Dr" if entry.debit > 0 else "Cr"
            amt = entry.debit if entry.debit > 0 else entry.credit
            msg += f"• {entry.ledger.name}: ₹{amt:,.2f} {side}\n"

    msg += f"\nTotal Amount: *₹{v.total_amount:,.2f}*\n\n"
    msg += f"Please let us know if you have any questions. Thank you!"
    
    encoded = urllib.parse.quote(msg)
    link = f"https://wa.me/{phone}?text={encoded}"
    return redirect(link)

@vouchers_bp.route('/view_by_number')
@login_required
def view_by_number():
    num = request.args.get('num', '').strip()
    if not num:
        return redirect(url_for('dashboard.index'))
    
    cid = get_cid()
    v = Voucher.query.filter_by(company_id=cid, voucher_number=num).first()
    if v:
        return redirect(url_for('vouchers.view', id=v.id))
    
    flash(f'Voucher {num} not found.', 'error')
    return redirect(request.referrer or url_for('dashboard.index'))

@vouchers_bp.route('/view/<int:id>')
@login_required
def view(id):
    v = Voucher.query.get_or_404(id)
    company = Company.query.get(v.company_id)
    
    # Check for linked receipt to prevent duplicates
    linked_receipt = Voucher.query.filter_by(
        company_id=v.company_id,
        voucher_type='Receipt',
        ref_number=v.voucher_number,
        is_cancelled=False
    ).first()
    
    # Calculate HSN Summary for the view
    hsn_summary = {}
    for item in v.items:
        key = (item.hsn_code or '—', item.gst_rate)
        if key not in hsn_summary:
            hsn_summary[key] = {'taxable': 0, 'cgst': 0, 'sgst': 0, 'igst': 0, 'hsn': item.hsn_code or '—', 'rate': item.gst_rate}
        hsn_summary[key]['taxable'] += item.taxable_amount
        hsn_summary[key]['cgst'] += item.cgst_amount
        hsn_summary[key]['sgst'] += item.sgst_amount
        hsn_summary[key]['igst'] += item.igst_amount
    
    # Smart Party Detection for Receipt
    display_party = v.party.name if (v.party and v.party.name not in ['Cash', 'Bank Account', 'Bank']) else None
    if not display_party and v.voucher_type == 'Receipt':
        for entry in v.ledger_entries:
            if entry.credit > 0 and entry.ledger and entry.ledger.name not in ['Cash', 'Bank Account', 'Bank']:
                display_party = entry.ledger.name
                break
    
    # Select Template based on Performa
    # (Removed g.ui_mode override to prevent jumping themes; let the ThemeLoader use the user's UI mode)
    # Check for linked invoice if this is a receipt
    linked_invoice = None
    if v.ref_number:
        linked_invoice = Voucher.query.filter_by(
            company_id=v.company_id,
            voucher_number=v.ref_number,
            is_cancelled=False
        ).first()

    # Fetch available Cash and Bank accounts for quick payment/receipt selection
    from app.models import LedgerGroup
    groups = LedgerGroup.query.filter(LedgerGroup.name.in_(['Cash-in-Hand', 'Bank Accounts'])).all()
    group_ids = [g.id for g in groups]
    cash_bank_ledgers = Ledger.query.filter(
        Ledger.company_id == v.company_id,
        Ledger.group_id.in_(group_ids),
        Ledger.is_active == True
    ).all()

    return render_template('vouchers/view.html', voucher=v, company=company, 
                           linked_receipt=linked_receipt, 
                           linked_invoice=linked_invoice,
                           hsn_summary=sorted(hsn_summary.values(), key=lambda x: x['hsn']),
                           display_party=display_party,
                           cash_bank_ledgers=cash_bank_ledgers)

@vouchers_bp.route('/edit/<int:id>', methods=['GET','POST'])
@login_required
def edit(id):
    v = Voucher.query.get_or_404(id)
    cid = v.company_id
    company = Company.query.get(cid)
    ledgers = Ledger.query.filter_by(company_id=cid, is_active=True).order_by(Ledger.name).all()
    
    if request.method == 'POST':
        data = request.json if request.is_json else request.form
        
        # Validation for empty voucher
        inventory_vtypes = ['Sales','Purchase','Credit Note','Debit Note']
        if v.voucher_type in inventory_vtypes:
            items_list = data.get('items') if request.is_json else None
            if not items_list and not request.is_json:
                import json
                try: items_list = json.loads(data.get('items_json', '[]'))
                except: items_list = []
            
            if not items_list or len(items_list) == 0:
                if request.is_json: return jsonify({'success': False, 'error': 'Voucher must have at least one item.'})
                flash('Cannot update voucher to be empty!', 'error')
                return redirect(url_for('vouchers.edit', id=v.id))
        else:
            entries = data.get('entries')
            if not entries or len(entries) == 0:
                if request.is_json: return jsonify({'success': False, 'error': 'Voucher must have at least one entry.'})
                flash('Cannot update voucher to be empty!', 'error')
                return redirect(url_for('vouchers.edit', id=v.id))
        
        new_date = datetime.strptime(data.get('date', v.date.isoformat()), '%Y-%m-%d').date()
        if is_v_locked(company, v.date) or is_v_locked(company, new_date):
            flash('Cannot edit voucher. Original or new date is locked!', 'error')
            return redirect(url_for('vouchers.view', id=v.id))
            
        # Update voucher header
        v.date = new_date
        
        # Clear existing items and ledger entries for re-creation
        # Reset serial numbers before deleting items
        for item in v.items:
            for sn in list(item.serial_numbers):
                if v.voucher_type == 'Sales':
                    sn.status = 'Available'
                    sn.sale_voucher_id = None
                elif v.voucher_type == 'Purchase':
                    # If deleting a purchase item, we might want to delete the serial number
                    # or mark it as 'Not In Stock'. For now, let's just unlink it.
                    sn.purchase_voucher_id = None
                sn.voucher_item_id = None


        for item in v.items[:]:
            db.session.delete(item)
        v.items = []
        LedgerEntry.query.filter_by(voucher_id=v.id).delete()
        v.ref_number = data.get('ref_number','')
        v.party_ledger_id = data.get('party_ledger_id') or None
        v.narration = data.get('narration','')
        v.place_of_supply = data.get('place_of_supply', company.state if company else '')
        v.is_igst = data.get('is_igst') in [True, 'true', '1', 'on']
        v.reverse_charge = data.get('reverse_charge') in [True, 'true', '1', 'on']
        v.payment_mode = data.get('payment_mode', 'Credit')
        v.eway_bill_no = data.get('eway_bill_no')
        v.vehicle_no = data.get('vehicle_no')
        v.transporter_name = data.get('transporter_name')
        v.tds_percent = float(data.get('tds_percent', 0))
        v.payment_ledger_id = data.get('payment_ledger_id') or None
        v.billing_address = data.get('billing_address')
        v.billing_city = data.get('billing_city')
        v.billing_state = data.get('billing_state')
        v.billing_pincode = data.get('billing_pincode')
        v.billing_gstin = data.get('billing_gstin')
        v.shipping_address = data.get('shipping_address')
        v.shipping_city = data.get('shipping_city')
        v.shipping_state = data.get('shipping_state')
        v.shipping_pincode = data.get('shipping_pincode')
        v.shipping_gstin = data.get('shipping_gstin')
        
        # Reuse creation logic for items and totals
        _save_voucher_items_and_totals(v, data, request.is_json)
        
        # Re-create ledger entries
        if 'entries' in data and data['entries']:
            total_dr = 0
            for row in data['entries']:
                lid = row.get('ledger_id')
                amt = float(row.get('amount', 0))
                type = row.get('dr_cr', 'Dr')
                if lid and amt > 0:
                    debit = amt if type == 'Dr' else 0
                    credit = amt if type == 'Cr' else 0
                    if debit > 0: total_dr += debit
                    db.session.add(LedgerEntry(
                        voucher_id=v.id, company_id=cid, ledger_id=lid,
                        date=v.date, debit=debit, credit=credit, narration=v.narration,
                        bank_tx_type=row.get('bank_tx_type'),
                        inst_no=row.get('inst_no'),
                        inst_date=datetime.strptime(row['inst_date'], '%Y-%m-%d').date() if row.get('inst_date') else None,
                        bank_name=row.get('bank_name')
                    ))
            v.total_amount = total_dr
        else:
            create_ledger_entries(v, company)
            # Automatic Receipt/Payment if changed to Cash
            handle_automatic_payment(v, company, pay_date=date.today())
        
        db.session.commit()
        flash(f'Voucher {v.voucher_number} updated!', 'success')
        
        if request.is_json:
            return jsonify({'success': True, 'id': v.id})
        return redirect(url_for('vouchers.view', id=v.id))
        
    items = StockItem.query.filter_by(company_id=cid, is_active=True).all()
    gst_rates = GSTRate.query.all()
    
    from app.routes.company import INDIAN_STATES
    from app.models import LedgerGroup
    groups = LedgerGroup.query.filter(LedgerGroup.name.in_(['Cash-in-Hand', 'Bank Accounts'])).all()
    group_ids = [g.id for g in groups]
    cash_bank_ledgers = Ledger.query.filter(
        Ledger.company_id == cid,
        Ledger.group_id.in_(group_ids),
        Ledger.is_active == True
    ).order_by(Ledger.name).all()

    inventory_vtypes = ['Sales','Purchase','Credit Note','Debit Note']
    tmpl = 'vouchers/create.html' if v.voucher_type in inventory_vtypes else 'vouchers/create_simple.html'

    return render_template(tmpl, voucher=v, vtype=v.voucher_type,
                           company=company, ledgers=ledgers, items=items, gst_rates=gst_rates,
                           states=INDIAN_STATES,
                           today=v.date.isoformat(), edit=True,
                           cash_bank_ledgers=cash_bank_ledgers)

def _save_voucher_items_and_totals(v, data, is_json):
    # Parse items
    if is_json:
        invoice_items = data.get('items', [])
    else:
        import json
        invoice_items = json.loads(data.get('items_json', '[]'))
    
    subtotal = 0
    discount_total = 0
    taxable_total = 0
    cgst_total = 0
    sgst_total = 0
    igst_total = 0
    cess_total = 0
    
    for row in invoice_items:
        qty = float(row.get('qty', 0))
        rate = float(row.get('rate', 0))
        disc_pct = float(row.get('discount_pct', 0))
        
        # Check if GST is enabled for this company
        gst_rate = 0
        if v.company.enable_gst and v.company.gst_registration_type != 'Composition':
            gst_rate = float(row.get('gst_rate', 0))
        elif v.company.enable_gst and v.company.gst_registration_type == 'Composition' and v.voucher_type == 'Purchase':
            # Composition dealers pay GST on purchases but don't collect it on sales
            gst_rate = float(row.get('gst_rate', 0))
            
        is_igst = v.is_igst
        
        gross = qty * rate
        disc_amt = gross * disc_pct / 100
        taxable = gross - disc_amt
        
        if is_igst:
            igst_rate = gst_rate
            cgst_r = sgst_r = 0
        else:
            cgst_r = sgst_r = gst_rate / 2
            igst_rate = 0
        
        cess_rate = float(row.get('cess_rate', 0))
        cgst_amt = taxable * cgst_r / 100
        sgst_amt = taxable * sgst_r / 100
        igst_amt = taxable * igst_rate / 100
        cess_amt = taxable * cess_rate / 100
        total_amt = taxable + cgst_amt + sgst_amt + igst_amt + cess_amt
        
        item_id = row.get('stock_item_id') or None
        item_name = row.get('description', '').strip()
        
        # Resolve item_id if missing but matches an existing StockItem
        if not item_id and item_name:
            existing = StockItem.query.filter(StockItem.company_id == v.company_id, StockItem.name.ilike(item_name)).first()
            if existing:
                item_id = existing.id
            elif v.voucher_type == 'Purchase':
                new_item = StockItem(
                    company_id=v.company_id, name=item_name, hsn_code=row.get('hsn_code',''),
                    purchase_rate=rate, sale_rate=rate * 1.2,
                )
                u_sym = row.get('unit','').upper()
                if u_sym:
                    from app.models import Unit
                    u = Unit.query.filter_by(symbol=u_sym).first()
                    if u: new_item.unit_id = u.id
                db.session.add(new_item)
                db.session.flush()
                item_id = new_item.id

        # Update item master rates if it's a Purchase
        if item_id and v.voucher_type == 'Purchase':
            item = StockItem.query.get(item_id)
            if item:
                item.purchase_rate = rate
                new_sale_rate = float(row.get('sale_rate') or 0)
                if new_sale_rate > 0:
                    item.sale_rate = new_sale_rate
                if not item.hsn_code: item.hsn_code = row.get('hsn_code','')
        
        vi = VoucherItem(
            voucher_id=v.id,
            stock_item_id=item_id,
            description=item_name,
            hsn_code=row.get('hsn_code',''),
            qty=qty, unit=row.get('unit',''),
            rate=rate, discount_pct=disc_pct, discount_amt=disc_amt,
            taxable_amount=taxable, gst_rate=gst_rate,
            cgst_rate=cgst_r, cgst_amount=cgst_amt,
            sgst_rate=sgst_r, sgst_amount=sgst_amt,
            igst_rate=igst_rate, igst_amount=igst_amt,
            cess_rate=cess_rate, cess_amount=cess_amt,
            total_amount=total_amt
        )
        db.session.add(vi)
        db.session.flush()
        
        # Handle Serial Numbers
        if item_id:
            sns = row.get('serial_numbers', [])
            for sn_val in sns:
                from app.models import SerialNumber
                sn_obj = SerialNumber.query.filter_by(serial_number=sn_val, company_id=v.company_id).first()
                if not sn_obj:
                    sn_obj = SerialNumber(stock_item_id=item_id, company_id=v.company_id, serial_number=sn_val)
                    db.session.add(sn_obj)
                    db.session.flush()
                
                if sn_obj:
                    sn_obj.voucher_item_id = vi.id
                    if v.voucher_type == 'Purchase':
                        sn_obj.purchase_voucher_id = v.id
                        sn_obj.status = 'Available'
                    elif v.voucher_type in ['Sales', 'Delivery Note']:
                        sn_obj.sale_voucher_id = v.id
                        sn_obj.status = 'Sold'
                    elif v.voucher_type in ['Credit Note', 'Receipt Note']:
                        sn_obj.status = 'Available'
                    elif v.voucher_type == 'Debit Note':
                        sn_obj.status = 'Damaged'
        
        v.items.append(vi)

        # Auto-save HSN code to master if new
        _auto_save_hsn(row.get('hsn_code',''), gst_rate, item_name)
        
        subtotal += gross
        discount_total += disc_amt
        taxable_total += taxable
        cgst_total += cgst_amt
        sgst_total += sgst_amt
        igst_total += igst_amt
        cess_total += cess_amt
    
    v.subtotal = subtotal
    v.discount_amount = discount_total
    v.taxable_amount = taxable_total
    v.cgst_amount = cgst_total
    v.sgst_amount = sgst_total
    v.igst_amount = igst_total
    v.cess_amount = cess_total
    
    if v.reverse_charge:
        total_before_round = taxable_total
    else:
        total_before_round = taxable_total + cgst_total + sgst_total + igst_total + cess_total
    v.tds_amount = taxable_total * (v.tds_percent or 0) / 100
    total_before_round -= v.tds_amount
    rounded = round(total_before_round)
    v.round_off = rounded - total_before_round
    v.total_amount = rounded

@vouchers_bp.route('/cancel/<int:id>')
@login_required
def cancel(id):
    v = Voucher.query.get_or_404(id)
    company = Company.query.get(v.company_id)
    if is_v_locked(company, v.date):
        flash('Cannot delete voucher. Date is locked!', 'error')
        return redirect(url_for('vouchers.view', id=v.id))
    
    # Mark as both cancelled and trashed to remove from all reports
    v.is_cancelled = True
    v.is_trash = True
    
    # Reset serial numbers
    for item in v.items:
        for sn in list(item.serial_numbers):
            if v.voucher_type == 'Sales':
                sn.status = 'Available'
                sn.sale_voucher_id = None
            elif v.voucher_type == 'Purchase':
                sn.purchase_voucher_id = None
            sn.voucher_item_id = None

    # Zero out ledger entries to ensure no "ghost" impact even if trash filter is bypassed
    for e in v.ledger_entries:
        e.debit, e.credit = 0, 0

    # Automatically handle linked Receipt/Payment vouchers
    linked = Voucher.query.filter_by(
        company_id=v.company_id,
        ref_number=v.voucher_number,
        is_trash=False
    ).all()
    
    for lv in linked:
        lv.is_trash = True
        lv.is_cancelled = True
        for le in lv.ledger_entries:
            le.debit, le.credit = 0, 0
        flash(f'Linked voucher {lv.voucher_number} also deleted.', 'info')

    db.session.commit()
    flash(f'Voucher {v.voucher_number} has been deleted.', 'warning')
    return redirect(url_for('vouchers.list_vouchers', vtype=v.voucher_type))

@vouchers_bp.route('/pdf/<int:id>')
@login_required
def pdf(id):
    v = Voucher.query.get_or_404(id)
    company = Company.query.get(v.company_id)
    if v.voucher_type in ['Receipt', 'Payment']:
        pdf_bytes = generate_receipt_pdf(v, company)
    else:
        pdf_bytes = generate_modern_invoice_pdf(v, company)
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename="{v.voucher_number}.pdf"'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    
    # Save a copy to the structured library if enabled
    if company.auto_save_invoices:
        try:
            import os
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            party_name = v.party.name if v.party else 'Unknown'
            month_str = v.date.strftime('%Y-%m')
            library_dir = os.path.join(base_dir, 'exports', 'invoices', party_name, month_str)
            os.makedirs(library_dir, exist_ok=True)
            filename = f"{v.voucher_number.replace('/', '_')}.pdf"
            filepath = os.path.join(library_dir, filename)
            with open(filepath, 'wb') as f:
                f.write(pdf_bytes)
        except Exception:
            pass
        
    return response

@vouchers_bp.route('/trash')
@login_required
def trash():
    cid = get_cid()
    page = request.args.get('page', 1, type=int)
    vouchers = Voucher.query.filter_by(company_id=cid, is_trash=True).order_by(Voucher.date.desc()).paginate(page=page, per_page=50)
    return render_template('vouchers/trash.html', vouchers=vouchers)

# Deprecated move_to_trash, redirect to cancel
@vouchers_bp.route('/move-to-trash/<int:id>')
@login_required
def move_to_trash(id):
    return redirect(url_for('vouchers.cancel', id=id))

@vouchers_bp.route('/restore/<int:id>')
@login_required
def restore(id):
    v = Voucher.query.get_or_404(id)
    v.is_trash = False
    db.session.commit()
    flash(f'Voucher {v.voucher_number} restored.', 'success')
    return redirect(url_for('vouchers.trash'))

@vouchers_bp.route('/delete-permanent/<int:id>')
@login_required
def delete_permanent(id):
    v = Voucher.query.get_or_404(id)
    if not v.is_trash:
        flash('Only trashed items can be permanently deleted.', 'error')
        return redirect(url_for('vouchers.trash'))
    db.session.delete(v)
    db.session.commit()
    flash('Voucher permanently deleted.', 'success')
    return redirect(url_for('vouchers.trash'))

@vouchers_bp.route('/library')
@login_required
def library():
    import os
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    export_dir = os.path.join(base_dir, 'exports', 'invoices')
    os.makedirs(export_dir, exist_ok=True)
    
    clients = []
    if os.path.exists(export_dir):
        clients = [d for d in os.listdir(export_dir) if os.path.isdir(os.path.join(export_dir, d))]
    
    selected_client = request.args.get('client')
    selected_month = request.args.get('month')
    
    files = []
    if selected_client:
        client_dir = os.path.join(export_dir, selected_client)
        if selected_month:
            target_dir = os.path.join(client_dir, selected_month)
            if os.path.exists(target_dir):
                files = [f for f in os.listdir(target_dir) if f.endswith('.pdf')]
        else:
            # List all months for this client
            months = [d for d in os.listdir(client_dir) if os.path.isdir(os.path.join(client_dir, d))]
            return render_template('vouchers/library_months.html', client=selected_client, months=months)

    return render_template('vouchers/library.html', clients=clients, selected_client=selected_client, files=files, month=selected_month)

@vouchers_bp.route('/pdf/view-saved/<client>/<month>/<filename>')
@login_required
def view_saved_pdf(client, month, filename):
    import os
    from flask import send_from_directory
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    target_dir = os.path.join(base_dir, 'exports', 'invoices', client, month)
    return send_from_directory(target_dir, filename)

@vouchers_bp.route('/pdf/download/<int:id>')
@login_required
def pdf_download(id):
    v = Voucher.query.get_or_404(id)
    company = Company.query.get(v.company_id)
    if v.voucher_type in ['Receipt', 'Payment']:
        pdf_bytes = generate_receipt_pdf(v, company)
    else:
        pdf_bytes = generate_modern_invoice_pdf(v, company)
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename="{v.voucher_number}.pdf"'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@vouchers_bp.route('/quick-receipt/<int:id>')
@login_required
def quick_receipt(id):
    v = Voucher.query.get_or_404(id)
    cid = v.company_id
    
    # Check if a receipt already exists for this bill to prevent duplicates
    existing = Voucher.query.filter_by(
        company_id=cid,
        voucher_type='Receipt',
        ref_number=v.voucher_number,
        is_cancelled=False
    ).first()
    
    if existing:
        flash(f'A receipt ({existing.voucher_number}) already exists for this bill.', 'warning')
        return redirect(url_for('vouchers.view', id=v.id))

    # Use ledger_id from request if provided
    selected_lid = request.args.get('ledger_id', type=int)
    cash_ledger = None
    if selected_lid:
        cash_ledger = Ledger.query.get(selected_lid)
    
    if not cash_ledger:
        def find_ledger(name):
            return Ledger.query.filter_by(company_id=cid, name=name).first()
        
        cash_ledger = find_ledger('Cash')
        if not cash_ledger:
            from app.models import LedgerGroup
            groups = LedgerGroup.query.filter(LedgerGroup.name.in_(['Cash-in-Hand', 'Bank Accounts'])).all()
            group_ids = [g.id for g in groups]
            cash_ledger = Ledger.query.filter(Ledger.company_id == cid, Ledger.group_id.in_(group_ids)).first()

    # Determine payment mode based on ledger group
    pay_mode = 'Cash'
    if cash_ledger and cash_ledger.group and cash_ledger.group.name == 'Bank Accounts':
        pay_mode = 'Bank'

    # Create the receipt voucher
    receipt_v = Voucher(
        company_id=cid,
        voucher_type='Receipt',
        voucher_number=get_next_number(cid, 'Receipt'),
        date=date.today(),
        ref_number=v.voucher_number,
        party_ledger_id=v.party_ledger_id,
        narration=f"Payment received against {v.voucher_number}",
        total_amount=v.total_amount,
        payment_mode=pay_mode
    )
    db.session.add(receipt_v)
    db.session.flush()
    
    if cash_ledger and v.party_ledger_id:
        # Dr Cash
        db.session.add(LedgerEntry(
            voucher_id=receipt_v.id, company_id=cid, ledger_id=cash_ledger.id,
            date=receipt_v.date, debit=v.total_amount, credit=0, narration=receipt_v.narration
        ))
        # Cr Party
        db.session.add(LedgerEntry(
            voucher_id=receipt_v.id, company_id=cid, ledger_id=v.party_ledger_id,
            date=receipt_v.date, debit=0, credit=v.total_amount, narration=receipt_v.narration
        ))
    
    db.session.commit()
    flash(f'Receipt {receipt_v.voucher_number} generated for bill {v.voucher_number}', 'success')
    return redirect(url_for('vouchers.view', id=receipt_v.id))

@vouchers_bp.route('/quick-payment/<int:id>')
@login_required
def quick_payment(id):
    v = Voucher.query.get_or_404(id)
    cid = v.company_id
    
    # Check if a payment already exists for this bill
    existing = Voucher.query.filter_by(
        company_id=cid,
        voucher_type='Payment',
        ref_number=v.voucher_number,
        is_trash=False
    ).first()
    
    if existing:
        flash(f'A payment ({existing.voucher_number}) already exists for this bill.', 'warning')
        return redirect(url_for('vouchers.view', id=v.id))

    # Use ledger_id from request if provided
    selected_lid = request.args.get('ledger_id', type=int)
    cash_ledger = None
    if selected_lid:
        cash_ledger = Ledger.query.get(selected_lid)
        
    if not cash_ledger:
        def find_ledger(name):
            return Ledger.query.filter_by(company_id=cid, name=name).first()
        
        cash_ledger = find_ledger('Cash')
        if not cash_ledger:
            from app.models import LedgerGroup
            groups = LedgerGroup.query.filter(LedgerGroup.name.in_(['Cash-in-Hand', 'Bank Accounts'])).all()
            group_ids = [g.id for g in groups]
            cash_ledger = Ledger.query.filter(Ledger.company_id == cid, Ledger.group_id.in_(group_ids)).first()

    # Determine payment mode based on ledger group
    pay_mode = 'Cash'
    if cash_ledger and cash_ledger.group and cash_ledger.group.name == 'Bank Accounts':
        pay_mode = 'Bank'

    pay_v = Voucher(
        company_id=cid,
        voucher_type='Payment',
        voucher_number=get_next_number(cid, 'Payment'),
        date=date.today(),
        ref_number=v.voucher_number,
        party_ledger_id=v.party_ledger_id,
        narration=f"Payment made against {v.voucher_number}",
        total_amount=v.total_amount,
        payment_mode=pay_mode
    )
    db.session.add(pay_v)
    db.session.flush()
    
    if cash_ledger and v.party_ledger_id:
        # Dr Party, Cr Cash
        db.session.add(LedgerEntry(voucher_id=pay_v.id, company_id=cid, ledger_id=v.party_ledger_id, date=pay_v.date, debit=v.total_amount, credit=0, narration=pay_v.narration))
        db.session.add(LedgerEntry(voucher_id=pay_v.id, company_id=cid, ledger_id=cash_ledger.id, date=pay_v.date, debit=0, credit=v.total_amount, narration=pay_v.narration))
    
    db.session.commit()
    flash(f'Payment {pay_v.voucher_number} generated for bill {v.voucher_number}', 'success')
    return redirect(url_for('vouchers.view', id=pay_v.id))

def recalculate_voucher_totals(v):
    subtotal = 0
    discount_total = 0
    taxable_total = 0
    cgst_total = 0
    sgst_total = 0
    igst_total = 0
    cess_total = 0
    
    for vi in v.items:
        gross = vi.qty * vi.rate
        disc_amt = gross * vi.discount_pct / 100
        taxable = gross - disc_amt
        
        if v.is_igst:
            igst_rate = vi.gst_rate
            cgst_r = sgst_r = 0
        else:
            cgst_r = sgst_r = vi.gst_rate / 2
            igst_rate = 0
        
        cess_rate = vi.cess_rate or 0
        cgst_amt = taxable * cgst_r / 100
        sgst_amt = taxable * sgst_r / 100
        igst_amt = taxable * igst_rate / 100
        cess_amt = taxable * cess_rate / 100
        
        vi.taxable_amount = taxable
        vi.cgst_amount = cgst_amt
        vi.sgst_amount = sgst_amt
        vi.igst_amount = igst_amt
        vi.total_amount = taxable + cgst_amt + sgst_amt + igst_amt + cess_amt
        
        subtotal += gross
        discount_total += disc_amt
        taxable_total += taxable
        cgst_total += cgst_amt
        sgst_total += sgst_amt
        igst_total += igst_amt
        cess_total += cess_amt
        
    v.subtotal = subtotal
    v.discount_amount = discount_total
    v.taxable_amount = taxable_total
    v.cgst_amount = cgst_total
    v.sgst_amount = sgst_total
    v.igst_amount = igst_total
    v.cess_amount = cess_total
    
    if v.reverse_charge:
        total_before_round = taxable_total
    else:
        total_before_round = taxable_total + cgst_total + sgst_total + igst_total + cess_total
        
    rounded = round(total_before_round)
    v.round_off = rounded - total_before_round
    v.total_amount = rounded

def create_ledger_entries(voucher, company):
    cid = company.id
    
    def find_ledger(name):
        return Ledger.query.filter_by(company_id=cid, name=name).first()
    
    def add_entry(ledger_id, debit=0, credit=0):
        if ledger_id and (debit > 0 or credit > 0):
            e = LedgerEntry(
                voucher_id=voucher.id,
                company_id=cid,
                ledger_id=ledger_id,
                date=voucher.date,
                debit=round(debit, 2),
                credit=round(credit, 2),
                narration=voucher.narration
            )
            db.session.add(e)
    
    vtype = voucher.voucher_type
    party_id = voucher.party_ledger_id
    
    if vtype == 'Sales':
        sales = find_ledger('Sales')
        round_ledger = find_ledger('Round Off')
        
        # Party gets the final rounded total
        add_entry(party_id, debit=voucher.total_amount)
        add_entry(sales.id if sales else None, credit=voucher.taxable_amount)
        
        if company.enable_gst and company.gst_registration_type != 'Composition':
            if not voucher.is_igst:
                cgst = find_ledger('CGST Payable')
                sgst = find_ledger('SGST Payable')
                add_entry(cgst.id if cgst else None, credit=voucher.cgst_amount)
                add_entry(sgst.id if sgst else None, credit=voucher.sgst_amount)
            else:
                igst = find_ledger('IGST Payable')
                add_entry(igst.id if igst else None, credit=voucher.igst_amount)
            
            if voucher.cess_amount:
                cess = find_ledger('Cess Payable')
                add_entry(cess.id if cess else None, credit=voucher.cess_amount)
            
        # Post Round Off
        if voucher.round_off:
            if voucher.round_off > 0:
                add_entry(round_ledger.id if round_ledger else None, credit=abs(voucher.round_off))
            else:
                add_entry(round_ledger.id if round_ledger else None, debit=abs(voucher.round_off))
    
    elif vtype == 'Purchase':
        purchase = find_ledger('Purchase')
        round_ledger = find_ledger('Round Off')
        if company.gst_registration_type == 'Composition':
            # GST is part of cost for composition dealers
            add_entry(purchase.id if purchase else None, debit=voucher.taxable_amount + voucher.cgst_amount + voucher.sgst_amount + voucher.igst_amount + voucher.cess_amount)
        else:
            add_entry(purchase.id if purchase else None, debit=voucher.taxable_amount)
        
        if voucher.reverse_charge:
            # RCM: Party only gets taxable amount
            add_entry(party_id, credit=voucher.taxable_amount + (voucher.round_off or 0))
            
            if company.enable_gst:
                # RCM Tax accounting: Debit Input (RCM), Credit Liability (RCM)
                if not voucher.is_igst:
                    cgst_in = find_ledger('CGST Input')
                    sgst_in = find_ledger('SGST Input')
                    cgst_pay = find_ledger('CGST Payable')
                    sgst_pay = find_ledger('SGST Payable')
                    
                    add_entry(cgst_in.id if cgst_in else None, debit=voucher.cgst_amount)
                    add_entry(sgst_in.id if sgst_in else None, debit=voucher.sgst_amount)
                    add_entry(cgst_pay.id if cgst_pay else None, credit=voucher.cgst_amount)
                    add_entry(sgst_pay.id if sgst_pay else None, credit=voucher.cgst_amount)
                else:
                    igst_in = find_ledger('IGST Input')
                    igst_pay = find_ledger('IGST Payable')
                    add_entry(igst_in.id if igst_in else None, debit=voucher.igst_amount)
                    add_entry(igst_pay.id if igst_pay else None, credit=voucher.igst_amount)
        else:
            # Normal Purchase: Party gets full total
            add_entry(party_id, credit=voucher.total_amount)
            
            if company.enable_gst and company.gst_registration_type != 'Composition':
                if not voucher.is_igst:
                    cgst = find_ledger('CGST Input')
                    sgst = find_ledger('SGST Input')
                    add_entry(cgst.id if cgst else None, debit=voucher.cgst_amount)
                    add_entry(sgst.id if sgst else None, debit=voucher.sgst_amount)
                else:
                    igst = find_ledger('IGST Input')
                    add_entry(igst.id if igst else None, debit=voucher.igst_amount)

        if company.enable_gst and company.gst_registration_type != 'Composition' and voucher.cess_amount:
            cess = find_ledger('Cess Input')
            add_entry(cess.id if cess else None, debit=voucher.cess_amount)

        # Post Round Off
        if voucher.round_off:
            if voucher.round_off > 0:
                add_entry(round_ledger.id if round_ledger else None, debit=abs(voucher.round_off))
            else:
                add_entry(round_ledger.id if round_ledger else None, credit=abs(voucher.round_off))

def handle_automatic_payment(v, company, pay_date=None):
    cid = company.id
    vtype = v.voucher_type
    
    if v.payment_mode in ['Cash', 'Bank', 'UPI']:
        # Find appropriate ledger (Cash or Bank)
        target_ledger = None
        if v.payment_ledger_id:
            target_ledger = Ledger.query.get(v.payment_ledger_id)
            if target_ledger and target_ledger.group:
                if target_ledger.group.name == 'Bank Accounts':
                    v.payment_mode = 'Bank'
                elif target_ledger.group.name == 'Cash-in-Hand':
                    v.payment_mode = 'Cash'
            
        if not target_ledger:
            if v.payment_mode == 'Cash':
                target_ledger = Ledger.query.filter(Ledger.company_id == cid, Ledger.name.ilike('Cash'), Ledger.is_active == True).first()
                search_group = 'Cash-in-Hand'
            else:
                target_ledger = Ledger.query.filter(Ledger.company_id == cid, Ledger.name.ilike('%Bank%'), Ledger.is_active == True).first()
                search_group = 'Bank Accounts'

        if not target_ledger:
            from app.models import LedgerGroup
            target_ledger = Ledger.query.join(LedgerGroup).filter(
                Ledger.company_id == cid,
                Ledger.is_active == True,
                LedgerGroup.name.ilike(search_group)
            ).first()

        if v.party_ledger_id and target_ledger and v.party_ledger_id != target_ledger.id:
            target_vtype = 'Receipt' if vtype == 'Sales' else 'Payment'
            actual_date = pay_date if pay_date else v.date
            existing = Voucher.query.filter_by(company_id=cid, voucher_type=target_vtype, ref_number=v.voucher_number, is_trash=False).first()
            
            if existing:
                existing.total_amount = v.total_amount
                existing.date = actual_date
                existing.party_ledger_id = v.party_ledger_id
                existing.payment_mode = 'Bank' if v.payment_mode == 'UPI' else v.payment_mode
                existing.narration = f"UPI-{v.voucher_number}" if v.payment_mode == 'UPI' else f"{v.payment_mode} {target_vtype.lower()} against {v.voucher_number}"
                LedgerEntry.query.filter_by(voucher_id=existing.id).delete()
                pay_v = existing
            else:
                pay_v = Voucher(
                    company_id=cid, voucher_type=target_vtype, voucher_number=get_next_number(cid, target_vtype),
                    date=actual_date, ref_number=v.voucher_number, party_ledger_id=v.party_ledger_id,
                    narration=f"UPI-{v.voucher_number}" if v.payment_mode == 'UPI' else f"{v.payment_mode} {target_vtype.lower()} against {v.voucher_number}",
                    total_amount=v.total_amount, payment_mode='Bank' if v.payment_mode == 'UPI' else v.payment_mode
                )
                db.session.add(pay_v)
                db.session.flush()

            if vtype == 'Sales':
                # Dr Cash/Bank, Cr Party
                db.session.add(LedgerEntry(voucher_id=pay_v.id, company_id=cid, ledger_id=target_ledger.id, date=actual_date, debit=v.total_amount, credit=0, narration=pay_v.narration))
                db.session.add(LedgerEntry(voucher_id=pay_v.id, company_id=cid, ledger_id=v.party_ledger_id, date=actual_date, debit=0, credit=v.total_amount, narration=pay_v.narration))
            elif vtype == 'Purchase':
                # Dr Party, Cr Cash/Bank
                db.session.add(LedgerEntry(voucher_id=pay_v.id, company_id=cid, ledger_id=v.party_ledger_id, date=actual_date, debit=v.total_amount, credit=0, narration=pay_v.narration))
                db.session.add(LedgerEntry(voucher_id=pay_v.id, company_id=cid, ledger_id=target_ledger.id, date=actual_date, debit=0, credit=v.total_amount, narration=pay_v.narration))
    else:
        # If changed to Credit/Other, get rid of any existing auto-linked vouchers
        auto_linked = Voucher.query.filter(
            Voucher.company_id == cid,
            Voucher.voucher_type.in_(['Receipt', 'Payment']),
            Voucher.ref_number == v.voucher_number,
            Voucher.is_trash == False
        ).all()
        for lv in auto_linked:
            lv.is_trash = True
            lv.is_cancelled = True
            for le in lv.ledger_entries:
                le.debit, le.credit = 0, 0
            flash(f"Automatically removed linked {lv.voucher_type} (ghost entry cleanup)", "info")

# ─── QR Code endpoints ───────────────────────────────────
@vouchers_bp.route('/qr/invoice/<int:id>')
@login_required
def qr_invoice(id):
    import qrcode, io, json
    v = Voucher.query.get_or_404(id)
    c = Company.query.get(v.company_id)
    data = json.dumps({
        'SellerGSTIN': c.gstin or '',
        'BuyerGSTIN': (v.party.gstin if v.party else '') or '',
        'DocNo': v.voucher_number,
        'DocDt': v.date.strftime('%d/%m/%Y'),
        'TotInvVal': str(round(v.total_amount, 2)),
    }, separators=(',',':'))
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=4, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    from flask import send_file
    return send_file(buf, mimetype='image/png')

@vouchers_bp.route('/qr/upi/<int:id>')
@login_required
def qr_upi(id):
    import qrcode, io
    v = Voucher.query.get_or_404(id)
    c = Company.query.get(v.company_id)
    upi_id = getattr(c, 'upi_id', '') or ''
    if not upi_id:
        # Return empty 1x1 transparent PNG
        import base64
        from flask import Response
        empty = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')
        return Response(empty, mimetype='image/png')
    name = (c.name or '').replace(' ','%20')
    upi_str = f"upi://pay?pa={upi_id}&pn={name}&am={v.total_amount:.2f}&cu=INR"
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=4, border=2)
    qr.add_data(upi_str)
    qr.make(fit=True)
    img = qr.make_image(fill_color='#075e54', back_color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    from flask import send_file
    return send_file(buf, mimetype='image/png')
