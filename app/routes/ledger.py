from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_required
from app.models import Ledger, LedgerGroup, LedgerEntry, Voucher
from app import db
from sqlalchemy import func
from datetime import date
from app.routes.vouchers import get_next_number

ledger_bp = Blueprint('ledger', __name__)

def get_cid():
    return session.get('company_id', 1)

@ledger_bp.route('/')
@login_required
def index():
    cid = get_cid()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    q = request.args.get('q', '')
    
    status = request.args.get('status', 'all')
    
    query = Ledger.query.filter_by(company_id=cid)
    if status == 'active':
        query = query.filter_by(is_active=True)
    elif status == 'inactive':
        query = query.filter_by(is_active=False)
        
    if q:
        query = query.filter(Ledger.name.ilike(f'%{q}%') | Ledger.alias.ilike(f'%{q}%'))
        
    pagination = query.order_by(Ledger.is_active.desc(), Ledger.name).paginate(page=page, per_page=per_page, error_out=False)
        
    # Calculate current balances for ledgers in the current page
    ledger_ids = [l.id for l in pagination.items]
    balances = {}
    if ledger_ids:
        sums = db.session.query(
            LedgerEntry.ledger_id,
            func.sum(LedgerEntry.debit).label('dr'),
            func.sum(LedgerEntry.credit).label('cr')
        ).join(Voucher).filter(LedgerEntry.ledger_id.in_(ledger_ids), Voucher.is_trash == False)\
         .group_by(LedgerEntry.ledger_id).all()
        
        sums_map = {s.ledger_id: (s.dr or 0, s.cr or 0) for s in sums}
        
        for l in pagination.items:
            dr, cr = sums_map.get(l.id, (0, 0))
            ob = l.opening_balance if l.opening_type == 'Dr' else -l.opening_balance
            net = ob + dr - cr
            balances[l.id] = {
                'value': abs(net),
                'type': 'Dr' if net >= 0 else 'Cr'
            }
    
    groups = LedgerGroup.query.all()
    return render_template('ledger/index.html', 
                           ledgers=pagination.items, 
                           pagination=pagination,
                           groups=groups,
                           per_page=per_page,
                           balances=balances,
                           q=q)

@ledger_bp.route('/create', methods=['GET','POST'])
@login_required
def create():
    cid = get_cid()
    groups = LedgerGroup.query.order_by(LedgerGroup.name).all()
    from app.routes.company import INDIAN_STATES
    if request.method == 'POST':
        l = Ledger(
            company_id=cid,
            name=request.form['name'],
            alias=request.form.get('alias'),
            group_id=request.form.get('group_id') or None,
            gstin=request.form.get('gstin','').upper(),
            pan=request.form.get('pan','').upper(),
            address=request.form.get('address'),
            city=request.form.get('city'),
            state=request.form.get('state'),
            state_code=request.form.get('state_code'),
            pincode=request.form.get('pincode'),
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            opening_balance=float(request.form.get('opening_balance') or 0),
            opening_type=request.form.get('opening_type','Dr'),
            registration_type=request.form.get('registration_type', 'Regular'),
            credit_limit=float(request.form.get('credit_limit') or 0),
            credit_days=int(request.form.get('credit_days') or 30),
            is_loan='is_loan' in request.form,
            loan_principal=float(request.form.get('loan_principal') or 0),
            loan_interest_rate=float(request.form.get('loan_interest_rate') or 0),
            loan_emi=float(request.form.get('loan_emi') or 0),
            loan_tenure=int(request.form.get('loan_tenure') or 12),
            loan_interest_type=request.form.get('loan_interest_type', 'Reducing'),
            loan_is_compounding='loan_is_compounding' in request.form,
            interest_ledger_id=int(request.form.get('interest_ledger_id') or 0) or None,
            is_active='is_active' in request.form if 'is_active' in request.form else True
        )
        if request.form.get('loan_start_date'):
            try: l.loan_start_date = date.fromisoformat(request.form.get('loan_start_date'))
            except: pass

        db.session.add(l)
        db.session.commit()
        flash('Ledger created!', 'success')
        return redirect(url_for('ledger.index'))
    all_ledgers = Ledger.query.filter_by(company_id=cid, is_active=True).order_by(Ledger.name).all()
    return render_template('ledger/form.html', groups=groups, ledger=None, all_ledgers=all_ledgers, states=INDIAN_STATES)

@ledger_bp.route('/edit/<int:id>', methods=['GET','POST'])
@login_required
def edit(id):
    cid = get_cid()
    l = Ledger.query.get_or_404(id)
    groups = LedgerGroup.query.order_by(LedgerGroup.name).all()
    all_ledgers = Ledger.query.filter_by(company_id=cid, is_active=True).order_by(Ledger.name).all()
    from app.routes.company import INDIAN_STATES
    if request.method == 'POST':
        l.name = request.form['name']
        l.alias = request.form.get('alias')
        l.group_id = request.form.get('group_id') or None
        l.gstin = request.form.get('gstin','').upper()
        l.pan = request.form.get('pan','').upper()
        l.address = request.form.get('address')
        l.city = request.form.get('city')
        l.state = request.form.get('state')
        l.state_code = request.form.get('state_code')
        l.pincode = request.form.get('pincode')
        l.phone = request.form.get('phone')
        l.email = request.form.get('email')
        l.opening_balance = float(request.form.get('opening_balance') or 0)
        l.opening_type = request.form.get('opening_type','Dr')
        l.registration_type = request.form.get('registration_type', 'Regular')
        l.credit_limit = float(request.form.get('credit_limit') or 0)
        l.credit_days = int(request.form.get('credit_days') or 30)
        
        l.is_loan = 'is_loan' in request.form
        l.loan_principal = float(request.form.get('loan_principal') or 0)
        l.loan_interest_rate = float(request.form.get('loan_interest_rate') or 0)
        l.loan_emi = float(request.form.get('loan_emi') or 0)
        l.loan_tenure = int(request.form.get('loan_tenure') or 12)
        l.loan_interest_type = request.form.get('loan_interest_type', 'Reducing')
        l.loan_is_compounding = 'loan_is_compounding' in request.form
        l.interest_ledger_id = int(request.form.get('interest_ledger_id') or 0) or None
        if request.form.get('loan_start_date'):
            try: l.loan_start_date = date.fromisoformat(request.form.get('loan_start_date'))
            except: pass
        else:
            l.loan_start_date = None
            
        l.is_active = 'is_active' in request.form
            
        db.session.commit()
        flash('Ledger updated!', 'success')
        return redirect(url_for('ledger.index'))
    return render_template('ledger/form.html', ledger=l, groups=groups, all_ledgers=all_ledgers, states=INDIAN_STATES, edit=True)

@ledger_bp.route('/delete/<int:id>')
@login_required
def delete(id):
    l = Ledger.query.get_or_404(id)
    l.is_active = False
    db.session.commit()
    flash('Ledger deleted', 'success')
    return redirect(url_for('ledger.index'))

@ledger_bp.route('/statement/<int:id>')
@login_required
def statement(id):
    l = Ledger.query.get_or_404(id)
    cid = get_cid()
    today = date.today()
    fy_start = today.replace(month=4, day=1) if today.month >= 4 else today.replace(year=today.year-1, month=4, day=1)
    from_date = request.args.get('from_date', fy_start.isoformat())
    to_date   = request.args.get('to_date',   today.isoformat())
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    try:
        fd = date.fromisoformat(from_date)
        td = date.fromisoformat(to_date)
    except:
        fd, td = fy_start, today

    # Calculate Opening Balance on 'fd'
    dr_before = db.session.query(func.sum(LedgerEntry.debit)).join(Voucher).filter(LedgerEntry.ledger_id == id, Voucher.is_trash == False, LedgerEntry.date < fd).scalar() or 0
    cr_before = db.session.query(func.sum(LedgerEntry.credit)).join(Voucher).filter(LedgerEntry.ledger_id == id, Voucher.is_trash == False, LedgerEntry.date < fd).scalar() or 0
    ob_val = l.opening_balance if l.opening_type == 'Dr' else -l.opening_balance
    opening_on_fd = ob_val + dr_before - cr_before

    # Paginate entries in range
    pagination = LedgerEntry.query.join(Voucher).filter(
        LedgerEntry.ledger_id == id,
        Voucher.is_trash == False,
        LedgerEntry.date >= fd,
        LedgerEntry.date <= td
    ).order_by(LedgerEntry.date, LedgerEntry.id).paginate(page=page, per_page=per_page, error_out=False)

    # Calculate balance at start of current page
    offset = (page - 1) * per_page
    if offset > 0:
        dr_page_start = db.session.query(func.sum(LedgerEntry.debit)).filter(
            LedgerEntry.ledger_id == id, LedgerEntry.date >= fd, LedgerEntry.date <= td
        ).order_by(LedgerEntry.date, LedgerEntry.id).limit(offset).subquery()
        # This is hard in SQL. Simpler: Sum first N entries.
        # Actually, let's just sum manually for the offset.
        prev_page_entries = LedgerEntry.query.join(Voucher).filter(
            LedgerEntry.ledger_id == id, Voucher.is_trash == False, LedgerEntry.date >= fd, LedgerEntry.date <= td
        ).order_by(LedgerEntry.date, LedgerEntry.id).limit(offset).all()
        page_start_balance = opening_on_fd + sum(e.debit or 0 for e in prev_page_entries) - sum(e.credit or 0 for e in prev_page_entries)
    else:
        page_start_balance = opening_on_fd

    rows = []
    balance = page_start_balance
    for e in pagination.items:
        dr = e.debit or 0.0
        cr = e.credit or 0.0
        balance += dr - cr
        particulars = e.narration or ''
        v = e.voucher
        if v:
            other = next((oe.ledger.name for oe in (v.ledger_entries or []) if oe.ledger_id != id and oe.ledger), v.party.name if v.party else (v.voucher_type or ''))
            particulars = other or particulars
        rows.append({
            'date': e.date, 'particulars': particulars, 'narration': e.narration,
            'voucher_number': v.voucher_number if v else '', 'voucher_type': v.voucher_type if v else '',
            'voucher_id': e.voucher_id, 'debit': dr, 'credit': cr, 'balance': balance,
        })

    # Period totals
    totals = db.session.query(func.sum(LedgerEntry.debit), func.sum(LedgerEntry.credit)).join(Voucher).filter(
        LedgerEntry.ledger_id == id, Voucher.is_trash == False, LedgerEntry.date >= fd, LedgerEntry.date <= td
    ).first()
    
    total_debit = totals[0] or 0
    total_credit = totals[1] or 0
    closing_balance = opening_on_fd + total_debit - total_credit

    from app.models import Company
    company = Company.query.get(get_cid())
    
    # Quick Actions Setup
    quick_ledgers = []
    quick_action_type = None
    
    if l.group:
        if l.group.name == 'Cash-in-Hand':
            quick_action_type = 'deposit'
            quick_ledgers = Ledger.query.join(LedgerGroup).filter(
                LedgerGroup.name == 'Bank Accounts',
                Ledger.company_id == cid, Ledger.is_active == True
            ).all()
        elif l.group.name == 'Bank Accounts':
            quick_action_type = 'withdraw'
            quick_ledgers = Ledger.query.join(LedgerGroup).filter(
                LedgerGroup.name == 'Cash-in-Hand',
                Ledger.company_id == cid, Ledger.is_active == True
            ).all()
        elif l.group.name == 'Sundry Debtors':
            quick_action_type = 'receipt'
            quick_ledgers = Ledger.query.join(LedgerGroup).filter(
                LedgerGroup.name.in_(['Cash-in-Hand', 'Bank Accounts']),
                Ledger.company_id == cid, Ledger.is_active == True
            ).all()
        elif l.group.name == 'Sundry Creditors':
            quick_action_type = 'payment'
            quick_ledgers = Ledger.query.join(LedgerGroup).filter(
                LedgerGroup.name.in_(['Cash-in-Hand', 'Bank Accounts']),
                Ledger.company_id == cid, Ledger.is_active == True
            ).all()

    bank_ledgers = Ledger.query.join(LedgerGroup).filter(
        LedgerGroup.name.in_(['Cash-in-Hand', 'Bank Accounts']),
        Ledger.company_id == cid, Ledger.is_active == True
    ).all()

    return render_template('ledger/statement.html',
        ledger=l, entries=rows, pagination=pagination,
        total_debit=total_debit, total_credit=total_credit,
        opening_on_fd=opening_on_fd,
        closing_balance=closing_balance,
        from_date=from_date, to_date=to_date,
        per_page=per_page, company=company,
        quick_ledgers=quick_ledgers,
        quick_action_type=quick_action_type,
        bank_ledgers=bank_ledgers,
        today_iso=date.today().isoformat())

@ledger_bp.route('/quick-transaction', methods=['POST'])
@login_required
def quick_transaction():
    cid = get_cid()
    data = request.json
    action = data.get('action') # 'deposit', 'withdraw', 'receipt', 'payment', 'manual'
    main_id = data.get('main_id') # The ledger we are looking at
    other_id = data.get('other_id') # The other ledger
    amount = float(data.get('amount', 0))
    narration = data.get('narration', '')
    vtype = data.get('vtype', 'Journal')
    entry_side = data.get('entry_side', 'Dr') # Side for main_id
    
    if amount <= 0: return jsonify({'success':False, 'error':'Invalid amount'})
    if not other_id: return jsonify({'success':False, 'error':'Please select an opposite ledger'})
    
    main_ledger = Ledger.query.get_or_404(main_id)
    other_ledger = Ledger.query.get_or_404(other_id)
    
    if action == 'deposit' or action == 'withdraw': vtype = 'Contra'
    elif action == 'receipt': vtype = 'Receipt'
    elif action == 'payment': vtype = 'Payment'
    
    v = Voucher(
        company_id=cid,
        voucher_type=vtype,
        voucher_number=get_next_number(cid, vtype),
        date=date.today(),
        narration=narration or f"Quick {action} via ledger dashboard",
        total_amount=amount,
        party_ledger_id=main_id if vtype in ('Receipt', 'Payment') else None
    )
    db.session.add(v)
    db.session.flush()
    
    # Entries logic
    if action == 'deposit': # Cash (main) -> Bank (other)
        e1 = LedgerEntry(voucher_id=v.id, ledger_id=other_id, debit=amount, credit=0, company_id=cid, date=v.date, narration=v.narration)
        e2 = LedgerEntry(voucher_id=v.id, ledger_id=main_id, debit=0, credit=amount, company_id=cid, date=v.date, narration=v.narration)
    elif action == 'withdraw': # Bank (main) -> Cash (other)
        e1 = LedgerEntry(voucher_id=v.id, ledger_id=other_id, debit=amount, credit=0, company_id=cid, date=v.date, narration=v.narration)
        e2 = LedgerEntry(voucher_id=v.id, ledger_id=main_id, debit=0, credit=amount, company_id=cid, date=v.date, narration=v.narration)
    elif action == 'receipt': # Customer (main) -> Cash/Bank (other)
        e1 = LedgerEntry(voucher_id=v.id, ledger_id=other_id, debit=amount, credit=0, company_id=cid, date=v.date, narration=v.narration)
        e2 = LedgerEntry(voucher_id=v.id, ledger_id=main_id, debit=0, credit=amount, company_id=cid, date=v.date, narration=v.narration)
    elif action == 'payment': # Supplier (main) -> Cash/Bank (other)
        e1 = LedgerEntry(voucher_id=v.id, ledger_id=main_id, debit=amount, credit=0, company_id=cid, date=v.date, narration=v.narration)
        e2 = LedgerEntry(voucher_id=v.id, ledger_id=other_id, debit=0, credit=amount, company_id=cid, date=v.date, narration=v.narration)
    elif action == 'manual':
        if entry_side == 'Dr':
            e1 = LedgerEntry(voucher_id=v.id, ledger_id=main_id, debit=amount, credit=0, company_id=cid, date=v.date, narration=v.narration)
            e2 = LedgerEntry(voucher_id=v.id, ledger_id=other_id, debit=0, credit=amount, company_id=cid, date=v.date, narration=v.narration)
        else:
            e1 = LedgerEntry(voucher_id=v.id, ledger_id=main_id, debit=0, credit=amount, company_id=cid, date=v.date, narration=v.narration)
            e2 = LedgerEntry(voucher_id=v.id, ledger_id=other_id, debit=amount, credit=0, company_id=cid, date=v.date, narration=v.narration)

    db.session.add(e1); db.session.add(e2)
    db.session.commit()
    return jsonify({'success':True})

@ledger_bp.route('/api/search')
@login_required
def api_search():
    cid = get_cid()
    q = request.args.get('q','')
    groups_filter = request.args.get('groups', '').split(',') if request.args.get('groups') else []
    
    from app.models import Company
    company = Company.query.get(cid)
    
    query = Ledger.query.filter(
        Ledger.company_id == cid,
        Ledger.is_active == True,
        Ledger.name.ilike(f'%{q}%')
    )
    
    if groups_filter:
        query = query.join(LedgerGroup).filter(LedgerGroup.name.in_(groups_filter))
    
    if company and not company.enable_gst:
        # Exclude common GST ledgers
        query = query.filter(
            ~Ledger.name.ilike('CGST%'),
            ~Ledger.name.ilike('SGST%'),
            ~Ledger.name.ilike('IGST%'),
            ~Ledger.name.ilike('% GST%')
        )
        
    ledgers = query.limit(20).all()
    return jsonify([{'id': l.id, 'name': l.name, 'group': l.group.name if l.group else '', 'gstin': l.gstin or '', 'state': l.state or '', 'phone': l.phone or ''} for l in ledgers])

@ledger_bp.route('/api/details/<int:id>')
@login_required
def api_details(id):
    l = Ledger.query.get_or_404(id)
    addresses = [{
        'id': a.id,
        'address_type': a.address_type,
        'address': a.address or '',
        'city': a.city or '',
        'state': a.state or '',
        'pincode': a.pincode or '',
        'gstin': a.gstin or '',
        'is_default': a.is_default
    } for a in l.addresses]
    
    return jsonify({
        'id': l.id, 'name': l.name, 'gstin': l.gstin or '',
        'address': l.address or '', 'city': l.city or '',
        'state': l.state or '', 'state_code': l.state_code or '',
        'pincode': l.pincode or '', 'phone': l.phone or '',
        'email': l.email or '', 'addresses': addresses
    })

@ledger_bp.route('/api/addresses/save', methods=['POST'])
@login_required
def api_save_address():
    from app.models import PartyAddress
    data = request.json
    ledger_id = data.get('ledger_id')
    if not ledger_id:
        return jsonify({'success': False, 'error': 'Ledger ID required'})
    
    addr = PartyAddress(
        ledger_id=ledger_id,
        address_type=data.get('address_type', 'Additional'),
        address=data.get('address', ''),
        city=data.get('city', ''),
        state=data.get('state', ''),
        pincode=data.get('pincode', ''),
        gstin=data.get('gstin', '').upper(),
        is_default=bool(data.get('is_default', False))
    )
    db.session.add(addr)
    db.session.commit()
    return jsonify({'success': True, 'id': addr.id})

@ledger_bp.route('/api/quick-edit', methods=['POST'])
@login_required
def api_quick_edit():
    data = request.json
    l = Ledger.query.get_or_404(data['id'])
    l.address = data.get('address')
    l.city = data.get('city')
    l.state = data.get('state')
    l.state_code = data.get('state_code')
    l.pincode = data.get('pincode')
    l.gstin = data.get('gstin','').upper()
    db.session.commit()
    return jsonify({'success': True})

@ledger_bp.route('/api/create', methods=['POST'])
@login_required
def api_create():
    cid = get_cid()
    data = request.json
    name = data.get('name')
    if not name:
        return jsonify({'success': False, 'error': 'Name is required'})
        
    # Check if exists
    existing = Ledger.query.filter_by(company_id=cid, name=name).first()
    
    # Get Sundry Debtors/Creditors group based on VTYPE or default
    vtype = data.get('vtype')
    group_name = 'Sundry Creditors' if vtype == 'Purchase' else 'Sundry Debtors'
    group = LedgerGroup.query.filter_by(name=group_name).first()

    if existing:
        if existing.is_active:
            return jsonify({'success': False, 'error': 'Ledger with this name already exists'})
        else:
            # Reactivate and update
            l = existing
            l.is_active = True
            l.group_id = group.id if group else l.group_id
    else:
        l = Ledger(company_id=cid, name=name, group_id=group.id if group else None)
        db.session.add(l)

    # Update common fields
    l.gstin = data.get('gstin', '').upper()
    l.address = data.get('address')
    l.city = data.get('city')
    l.state = data.get('state')
    l.state_code = data.get('state_code')
    l.pincode = data.get('pincode')
    l.phone = data.get('phone')
    l.email = data.get('email')
    l.registration_type = data.get('registration_type', 'Regular')
    
    db.session.commit()
    return jsonify({
        'success': True, 
        'id': l.id, 
        'name': l.name, 
        'state': l.state, 
        'gstin': l.gstin
    })

@ledger_bp.route('/groups')
@login_required
def groups():
    all_groups = LedgerGroup.query.order_by(LedgerGroup.name).all()
    return render_template('ledger/groups.html', groups=all_groups)

@ledger_bp.route('/groups/create', methods=['POST'])
@login_required
def create_group():
    cid = get_cid()
    g = LedgerGroup(
        name=request.form['name'],
        nature=request.form.get('nature','Assets'),
        parent_id=request.form.get('parent_id') or None,
        company_id=cid
    )
    db.session.add(g)
    db.session.commit()
    flash('Group created!', 'success')
    return redirect(url_for('ledger.groups'))
@ledger_bp.route('/whatsapp/<int:id>')
@login_required
def whatsapp_ledger(id):
    import urllib.parse
    l = Ledger.query.get_or_404(id)
    cid = get_cid()
    from app.models import Company, Voucher
    company = Company.query.get(cid)

    # Correctly filter entries by joining with Voucher and checking is_trash
    res = db.session.query(
        func.sum(LedgerEntry.debit),
        func.sum(LedgerEntry.credit)
    ).join(Voucher).filter(
        LedgerEntry.ledger_id == l.id,
        Voucher.is_trash == False
    ).first()
    
    dr = res[0] or 0
    cr = res[1] or 0
    ob = l.opening_balance if l.opening_type == 'Dr' else -l.opening_balance
    net = ob + dr - cr
    
    phone = ""
    if l.phone:
        phone = ''.join(c for c in l.phone if c.isdigit())
        if len(phone) == 10: phone = '91' + phone

    # Get last 10 entries for history
    entries = LedgerEntry.query.join(Voucher).filter(
        LedgerEntry.ledger_id == l.id,
        Voucher.is_trash == False
    ).order_by(LedgerEntry.date.desc()).limit(10).all()
    entries.reverse()

    msg = f"📊 *Statement Summary* from *{company.name}*\n"
    msg += f"Party: *{l.name}*\n"
    msg += f"Balance: *₹{abs(net):,.2f} {'Dr' if net>=0 else 'Cr'}*\n\n"
    msg += "Recent Transactions:\n"
    msg += "--------------------------------\n"
    for e in entries:
        dt = e.date.strftime('%d/%m/%y')
        amt = e.debit if e.debit > 0 else e.credit
        side = "Dr" if e.debit > 0 else "Cr"
        msg += f"{dt} | ₹{amt:,.2f} {side}\n"
    msg += "--------------------------------\n"
    msg += "Please verify the statement. Thank you!"

    encoded = urllib.parse.quote(msg)
    link = f"https://wa.me/{phone}?text={encoded}"
    return redirect(link)

@ledger_bp.route('/whatsapp-statement/<int:id>')
@login_required
def whatsapp_statement(id):
    # This is an alias for the more detailed version or the same logic
    return whatsapp_ledger(id)

@ledger_bp.route('/whatsapp-due/<int:id>')
@login_required
def whatsapp_due(id):
    import urllib.parse
    l = Ledger.query.get_or_404(id)
    cid = get_cid()
    from app.models import Company, Voucher
    company = Company.query.get(cid)

    # Correctly filter entries by joining with Voucher and checking is_trash
    res = db.session.query(
        func.sum(LedgerEntry.debit),
        func.sum(LedgerEntry.credit)
    ).join(Voucher).filter(
        LedgerEntry.ledger_id == l.id,
        Voucher.is_trash == False
    ).first()
    
    dr = res[0] or 0
    cr = res[1] or 0
    ob = l.opening_balance if l.opening_type == 'Dr' else -l.opening_balance
    net = ob + dr - cr
    
    if abs(net) < 0.01:
        flash('Account has zero balance.', 'info')
        return redirect(url_for('ledger.statement', id=id))

    phone = ""
    if l.phone:
        phone = ''.join(c for c in l.phone if c.isdigit())
        if len(phone) == 10: phone = '91' + phone

    if net > 0:
        msg = f"🔔 *Payment Reminder* from *{company.name}*\n"
        msg += f"Dear *{l.name}*,\n\n"
        msg += f"This is a friendly reminder that there is an outstanding balance of *₹{abs(net):,.2f}* in your account.\n\n"
        msg += f"We request you to kindly settle the dues at the earliest. If already paid, please ignore this message.\n\n"
        msg += f"Thank you!"
    else:
        msg = f"💰 *Account Credit Update* from *{company.name}*\n"
        msg += f"Dear *{l.name}*,\n\n"
        msg += f"You have a credit balance of *₹{abs(net):,.2f}* in your account.\n\n"
        msg += f"Thank you for your continued business!"

    encoded = urllib.parse.quote(msg)
    link = f"https://wa.me/{phone}?text={encoded}"
    return redirect(link)
