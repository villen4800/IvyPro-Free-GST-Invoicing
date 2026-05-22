from flask import Blueprint, render_template, request, session
from flask_login import login_required
from app.models import Voucher, LedgerEntry, Ledger, LedgerGroup, StockItem, VoucherItem, Company
from app import db
from sqlalchemy import func, or_
from datetime import date

reports_bp = Blueprint('reports', __name__)

def get_cid():
    return session.get('company_id', 1)


def _ledger_opening(ledger):
    return (ledger.opening_balance or 0) if ledger.opening_type == 'Dr' else -(ledger.opening_balance or 0)


def _ledger_movement(ledger_id, from_date=None, to_date=None):
    query = db.session.query(
        func.coalesce(func.sum(LedgerEntry.debit), 0),
        func.coalesce(func.sum(LedgerEntry.credit), 0)
    ).join(Voucher).filter(LedgerEntry.ledger_id == ledger_id, Voucher.is_trash == False)
    if from_date is not None:
        query = query.filter(LedgerEntry.date >= from_date)
    if to_date is not None:
        query = query.filter(LedgerEntry.date <= to_date)
    dr, cr = query.first()
    return float(dr or 0), float(cr or 0)


def _ledger_balance(ledger, as_on):
    dr, cr = _ledger_movement(ledger.id, to_date=as_on)
    return _ledger_opening(ledger) + dr - cr


def _descendant_group_ids(group):
    ids = [group.id]
    for child in group.children:
        ids.extend(_descendant_group_ids(child))
    return ids


def _group_ledgers(group, company_id):
    return Ledger.query.filter(
        Ledger.company_id == company_id,
        Ledger.is_active == True,
        Ledger.group_id.in_(_descendant_group_ids(group))
    ).order_by(Ledger.name).all()


def _stock_value(company_id, as_on=None):
    if as_on is None: as_on = date.today()
    total = 0
    items = StockItem.query.filter_by(company_id=company_id, is_active=True, is_service=False).all()
    
    # Batch query movements for all items up to the specified date
    q = db.session.query(
        VoucherItem.stock_item_id,
        Voucher.voucher_type,
        func.sum(VoucherItem.qty)
    ).join(Voucher).filter(
        Voucher.company_id == company_id,
        Voucher.is_cancelled == False,
        Voucher.is_trash == False,
        Voucher.date <= as_on
    ).group_by(VoucherItem.stock_item_id, Voucher.voucher_type).all()
    
    m_map = {}
    for iid, vtype, qty in q:
        if iid not in m_map: m_map[iid] = {'in': 0, 'out': 0}
        if vtype in ('Purchase','Receipt Note','Credit Note'): m_map[iid]['in'] += qty
        elif vtype in ('Sales','Delivery Note','Debit Note'): m_map[iid]['out'] += qty
        
    for item in items:
        m = m_map.get(item.id, {'in': 0, 'out': 0})
        qty = (item.opening_qty or 0) + m['in'] - m['out']
        if qty > 0:
            # Value at purchase rate (simple valuation)
            total += qty * (item.purchase_rate or 0)
    return total

@reports_bp.route('/')
@login_required
def index():
    return render_template('reports/index.html')

@reports_bp.route('/trial-balance')
@login_required
def trial_balance():
    cid = get_cid()
    company = Company.query.get(cid)
    
    # Standardize dates
    fdate_str = request.args.get('from_date', date.today().replace(month=4, day=1).isoformat())
    tdate_str = request.args.get('to_date', date.today().isoformat())
    try:
        from_date = date.fromisoformat(fdate_str)
        to_date = date.fromisoformat(tdate_str)
    except (ValueError, TypeError):
        from_date = date.today().replace(month=4, day=1)
        to_date = date.today()
    
    ledgers = Ledger.query.filter_by(company_id=cid, is_active=True).all()
    result = []
    total_dr = 0
    total_cr = 0
    
    for l in ledgers:
        period_dr, period_cr = _ledger_movement(l.id, from_date, to_date)
        
        # Calculate Opening Balance up to the day before from_date
        prev_dr = db.session.query(func.sum(LedgerEntry.debit)).join(Voucher).filter(
            LedgerEntry.ledger_id == l.id,
            Voucher.is_trash == False,
            LedgerEntry.date < from_date
        ).scalar() or 0
        prev_cr = db.session.query(func.sum(LedgerEntry.credit)).join(Voucher).filter(
            LedgerEntry.ledger_id == l.id,
            Voucher.is_trash == False,
            LedgerEntry.date < from_date
        ).scalar() or 0
        
        initial_ob = _ledger_opening(l)
        report_opening = initial_ob + prev_dr - prev_cr
        
        # Final net balance as on to_date
        net = report_opening + period_dr - period_cr
        closing_dr = max(net, 0)
        closing_cr = abs(min(net, 0))
        
        if abs(net) > 0.01 or abs(report_opening) > 0.01 or abs(period_dr) > 0.01 or abs(period_cr) > 0.01:
            row_data = {
                'ledger': l,
                'name': l.name,
                'group': l.group.name if l.group else '—',
                'opening': report_opening,
                'period_debit': period_dr,
                'period_credit': period_cr,
                'debit': closing_dr,
                'credit': closing_cr,
                'net_balance': net,
                'closing_dr': closing_dr,
                'closing_cr': closing_cr
            }
            result.append(row_data)
            total_dr += closing_dr
            total_cr += closing_cr
    
    # We pass both sets of variable names to satisfy both Modern and Classic templates
    return render_template('reports/trial_balance.html', 
                           result=result, trial_balance=result,
                           total_dr=total_dr, total_debit=total_dr,
                           total_cr=total_cr, total_credit=total_cr,
                           from_date=from_date.isoformat(), to_date=to_date.isoformat(), 
                           company=company)

@reports_bp.route('/profit-loss')
@login_required
def profit_loss():
    cid = get_cid()
    company = Company.query.get(cid)
    
    fdate_str = request.args.get('from_date', date.today().replace(month=4, day=1).isoformat())
    tdate_str = request.args.get('to_date', date.today().isoformat())
    try:
        from_date = date.fromisoformat(fdate_str)
        to_date = date.fromisoformat(tdate_str)
    except:
        from_date = date.today().replace(month=4, day=1)
        to_date = date.today()
    
    def find_all_groups(name_variants):
        """Find ALL ledger groups matching any of the name variants (handles duplicates from Tally imports)."""
        groups = []
        seen_ids = set()
        for name in name_variants:
            matches = LedgerGroup.query.filter(
                LedgerGroup.name.ilike(name),
                or_(LedgerGroup.company_id == cid, LedgerGroup.company_id == None)
            ).all()
            for g in matches:
                if g.id not in seen_ids:
                    groups.append(g)
                    seen_ids.add(g.id)
        return groups

    def _all_group_ledgers(groups):
        """Get all ledgers from multiple groups, deduplicated."""
        seen = set()
        result = []
        for group in groups:
            for l in _group_ledgers(group, cid):
                if l.id not in seen:
                    result.append(l)
                    seen.add(l.id)
        return result

    def get_income_total(name_variants, date_from, date_to):
        """For income groups: net = Credits - Debits (positive means income)."""
        groups = find_all_groups(name_variants)
        if not groups:
            return 0, []
        items = []
        total = 0
        for l in _all_group_ledgers(groups):
            dr, cr = _ledger_movement(l.id, date_from, date_to)
            net = cr - dr  # Income accounts are credited
            if abs(net) > 0.01:
                items.append({'name': l.name, 'amount': abs(net)})
                total += net
        return abs(total), items

    def get_expense_total(name_variants, date_from, date_to):
        """For expense groups: net = Debits - Credits (positive means expense)."""
        groups = find_all_groups(name_variants)
        if not groups:
            return 0, []
        items = []
        total = 0
        for l in _all_group_ledgers(groups):
            dr, cr = _ledger_movement(l.id, date_from, date_to)
            net = dr - cr  # Expense accounts are debited
            if abs(net) > 0.01:
                items.append({'name': l.name, 'amount': abs(net)})
                total += net
        return abs(total), items


    # Stock Calculation for P&L
    # Opening Stock is value as of day before from_date
    from_date_minus_1 = from_date.replace(day=from_date.day-1) if from_date.day > 1 else from_date # simplified
    # Better: just use from_date if it's 1st April, else calculate. 
    # For simplicity, we'll calculate stock value at the start and end of the period.
    import datetime
    opening_stock_val = _stock_value(cid, from_date - datetime.timedelta(days=1))
    closing_stock_val = _stock_value(cid, to_date)

    # Income side — try multiple name variants from Tally / manual creation
    sales, sales_items = get_income_total(
        ['Sales Accounts', 'Sales Account', 'Sales', 'Revenue'], from_date, to_date)
    direct_income, di_items = get_income_total(
        ['Direct Income', 'Direct Incomes'], from_date, to_date)
    indirect_income, ii_items = get_income_total(
        ['Indirect Income', 'Indirect Incomes'], from_date, to_date)
    
    # Expense side
    purchases, pur_items = get_expense_total(
        ['Purchase Accounts', 'Purchase Account', 'Purchases'], from_date, to_date)
    direct_exp, de_items = get_expense_total(
        ['Direct Expenses', 'Direct Expense'], from_date, to_date)
    indirect_exp, ie_items = get_expense_total(
        ['Indirect Expenses', 'Indirect Expense'], from_date, to_date)
    
    total_income = sales + direct_income + indirect_income + closing_stock_val
    total_expense = purchases + direct_exp + indirect_exp + opening_stock_val
    net_profit = total_income - total_expense
    
    return render_template('reports/profit_loss.html',
        company=company, from_date=from_date.isoformat(), to_date=to_date.isoformat(),
        sales=sales, sales_items=sales_items,
        direct_income=direct_income, di_items=di_items,
        indirect_income=indirect_income, ii_items=ii_items,
        purchases=purchases, pur_items=pur_items,
        direct_exp=direct_exp, de_items=de_items,
        indirect_exp=indirect_exp, ie_items=ie_items,
        opening_stock=opening_stock_val, closing_stock=closing_stock_val,
        total_income=total_income, total_expense=total_expense,
        net_profit=net_profit
    )


@reports_bp.route('/day-book')
@login_required
def day_book():
    cid = get_cid()
    company = Company.query.get(cid)
    d_str = request.args.get('date', date.today().isoformat())
    try:
        selected_date = date.fromisoformat(d_str)
    except:
        selected_date = date.today()
        
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    
    query = Voucher.query.filter_by(company_id=cid, is_cancelled=False, is_trash=False)\
        .filter(Voucher.date == selected_date)
    
    pagination = query.order_by(Voucher.id).paginate(page=page, per_page=per_page, error_out=False)
    
    # Calculate day totals (Debit and Credit separately)
    vouchers_all = query.all()
    total_dr = 0
    total_cr = 0
    
    # Logic: 
    # Sales, Payment, Debit Note -> Normally Debit the party
    # Purchase, Receipt, Credit Note -> Normally Credit the party
    # Contra/Journal -> Depends, but we'll use a best-effort approach
    for v in vouchers_all:
        if v.voucher_type in ['Sales', 'Payment', 'Debit Note']:
            total_dr += v.total_amount
            v.is_dr = True
        elif v.voucher_type in ['Purchase', 'Receipt', 'Credit Note']:
            total_cr += v.total_amount
            v.is_dr = False
        else:
            # Journal/Contra: default to Debit for total volume calculation
            total_dr += v.total_amount
            v.is_dr = True
            
    return render_template('reports/day_book.html', 
                           vouchers=pagination.items,
                           pagination=pagination,
                           selected_date=selected_date.isoformat(), 
                           total_dr=total_dr, total_cr=total_cr,
                           company=company, per_page=per_page)

@reports_bp.route('/sales-register')
@login_required
def sales_register():
    cid = get_cid()
    company = Company.query.get(cid)
    f_str = request.args.get('from_date', date.today().replace(month=4, day=1).isoformat())
    t_str = request.args.get('to_date', date.today().isoformat())
    try:
        from_date = date.fromisoformat(f_str)
        to_date = date.fromisoformat(t_str)
    except:
        from_date = date.today().replace(month=4, day=1)
        to_date = date.today()
    
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    
    query = Voucher.query.filter_by(company_id=cid, voucher_type='Sales', is_cancelled=False, is_trash=False)\
        .filter(Voucher.date >= from_date, Voucher.date <= to_date)
    
    pagination = query.order_by(Voucher.date.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    # Calculate totals for the entire filtered period (not just current page)
    totals_query = db.session.query(
        func.sum(Voucher.taxable_amount),
        func.sum(Voucher.cgst_amount),
        func.sum(Voucher.sgst_amount),
        func.sum(Voucher.igst_amount),
        func.sum(Voucher.total_amount)
    ).filter_by(company_id=cid, voucher_type='Sales', is_cancelled=False, is_trash=False)\
     .filter(Voucher.date >= from_date, Voucher.date <= to_date).first()
    
    totals = {
        'taxable': totals_query[0] or 0,
        'cgst': totals_query[1] or 0,
        'sgst': totals_query[2] or 0,
        'igst': totals_query[3] or 0,
        'total': totals_query[4] or 0,
    }
    
    return render_template('reports/sales_register.html', 
                           vouchers=pagination.items, 
                           pagination=pagination,
                           from_date=from_date.isoformat(), to_date=to_date.isoformat(), 
                           totals=totals, company=company, per_page=per_page)

@reports_bp.route('/purchase-register')
@login_required
def purchase_register():
    cid = get_cid()
    company = Company.query.get(cid)
    f_str = request.args.get('from_date', date.today().replace(month=4, day=1).isoformat())
    t_str = request.args.get('to_date', date.today().isoformat())
    try:
        from_date = date.fromisoformat(f_str)
        to_date = date.fromisoformat(t_str)
    except:
        from_date = date.today().replace(month=4, day=1)
        to_date = date.today()
        
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    
    query = Voucher.query.filter_by(company_id=cid, voucher_type='Purchase', is_cancelled=False, is_trash=False)\
        .filter(Voucher.date >= from_date, Voucher.date <= to_date)
    
    pagination = query.order_by(Voucher.date.desc()).paginate(page=page, per_page=per_page, error_out=False)

    # Calculate totals for the entire filtered period
    totals_query = db.session.query(
        func.sum(Voucher.taxable_amount),
        func.sum(Voucher.cgst_amount),
        func.sum(Voucher.sgst_amount),
        func.sum(Voucher.igst_amount),
        func.sum(Voucher.total_amount)
    ).filter_by(company_id=cid, voucher_type='Purchase', is_cancelled=False, is_trash=False)\
     .filter(Voucher.date >= from_date, Voucher.date <= to_date).first()
    
    totals = {
        'taxable': totals_query[0] or 0,
        'cgst': totals_query[1] or 0,
        'sgst': totals_query[2] or 0,
        'igst': totals_query[3] or 0,
        'total': totals_query[4] or 0,
    }
    
    return render_template('reports/purchase_register.html', 
                           vouchers=pagination.items, 
                           pagination=pagination,
                           from_date=from_date.isoformat(), to_date=to_date.isoformat(), 
                           totals=totals, company=company, per_page=per_page)

@reports_bp.route('/outstanding')
@login_required
def outstanding():
    cid = get_cid()
    company = Company.query.get(cid)
    # Normalize type to match what template expects (receivables/payables)
    rtype = request.args.get('type', 'receivable')
    if not rtype.endswith('s'): rtype += 's' 
    
    if rtype == 'receivables':
        group = LedgerGroup.query.filter_by(name='Sundry Debtors').first()
    else:
        group = LedgerGroup.query.filter_by(name='Sundry Creditors').first()
    
    ledgers = Ledger.query.filter_by(company_id=cid, group_id=group.id if group else None).all() if group else []
    result = []
    for l in ledgers:
        dr = db.session.query(func.sum(LedgerEntry.debit)).join(Voucher).filter(LedgerEntry.ledger_id==l.id, Voucher.is_trash==False).scalar() or 0
        cr = db.session.query(func.sum(LedgerEntry.credit)).join(Voucher).filter(LedgerEntry.ledger_id==l.id, Voucher.is_trash==False).scalar() or 0
        ob = l.opening_balance if l.opening_type == 'Dr' else -l.opening_balance
        balance = ob + dr - cr
        if abs(balance) > 0.01:
            # Add fields for Modern template
            result.append({
                'ledger': l, # for classic
                'id': l.id,
                'name': l.name,
                'gstin': l.gstin,
                'amount': balance, # for modern
                'balance': balance, # for classic
                'type': 'Dr' if balance > 0 else 'Cr',
                'days_due': (date.today() - l.created_at.date()).days if l.created_at else 0
            })
    
    return render_template('reports/outstanding.html', 
                           result=result, outstanding=result,
                           report_type=rtype, type=rtype, company=company)

@reports_bp.route('/balance-sheet')
@login_required
def balance_sheet():
    cid = get_cid()
    company = Company.query.get(cid)
    d_str = request.args.get('date', date.today().isoformat())
    try:
        as_on = date.fromisoformat(d_str)
    except:
        as_on = date.today()
    
    # Financial year start
    fy_start = date(as_on.year if as_on.month >= 4 else as_on.year - 1, 4, 1)

    def group_balance_details(group_names, side):
        if isinstance(group_names, str): group_names = [group_names]
        total = 0
        details = []
        groups = LedgerGroup.query.filter(
            LedgerGroup.name.in_(group_names),
            or_(LedgerGroup.company_id == cid, LedgerGroup.company_id == None)
        ).all()
        
        for g in groups:
            for l in _group_ledgers(g, cid):
                net = _ledger_balance(l, as_on)
                amount = net if side == 'assets' else -net
                if abs(amount) > 0.01:
                    details.append({'name': l.name, 'amount': amount})
                    total += amount
        return total, details

    # --- LIABILITIES SIDE ---
    liab_sections = []
    
    # 1. Capital Account (Includes Reserves & Surplus)
    val, items = group_balance_details(['Capital Account', 'Reserves & Surplus'], 'liabilities')
    if abs(val) > 0.01: liab_sections.append({'name': 'Capital Account', 'amount': val, 'ledgers': items})
    
    # 2. Loans (Liability)
    val, items = group_balance_details(['Loans (Liability)', 'Bank OD A/c', 'Secured Loans', 'Unsecured Loans'], 'liabilities')
    if abs(val) > 0.01: liab_sections.append({'name': 'Loans (Liability)', 'amount': val, 'ledgers': items})
    
    # 3. Current Liabilities
    val, items = group_balance_details(['Current Liabilities', 'Duties & Taxes', 'Provisions', 'Sundry Creditors'], 'liabilities')
    if abs(val) > 0.01: liab_sections.append({'name': 'Current Liabilities', 'amount': val, 'ledgers': items})
    
    # 4. Suspense A/c
    val, items = group_balance_details('Suspense A/c', 'liabilities')
    if abs(val) > 0.01: liab_sections.append({'name': 'Suspense A/c', 'amount': val, 'ledgers': items})

    # 5. Branch / Divisions
    val, items = group_balance_details('Branch / Divisions', 'liabilities')
    if abs(val) > 0.01: liab_sections.append({'name': 'Branch / Divisions', 'amount': val, 'ledgers': items})

    # --- ASSETS SIDE ---
    asset_sections = []
    
    # 1. Fixed Assets
    val, items = group_balance_details('Fixed Assets', 'assets')
    if abs(val) > 0.01: asset_sections.append({'name': 'Fixed Assets', 'amount': val, 'ledgers': items})
    
    # 2. Investments
    val, items = group_balance_details('Investments', 'assets')
    if abs(val) > 0.01: asset_sections.append({'name': 'Investments', 'amount': val, 'ledgers': items})
    
    # 3. Current Assets
    # Includes Cash, Bank, Debtors, Stock, Loans & Adv, Deposits
    val, items = group_balance_details(['Current Assets', 'Bank Accounts', 'Cash-in-hand', 'Sundry Debtors', 
                                        'Loans & Advances (Asset)', 'Deposits (Asset)', 'Stock-in-hand'], 'assets')
    stock_val = _stock_value(cid, as_on)
    if stock_val > 0.01:
        items.append({'name': 'Closing Stock', 'amount': stock_val})
        val += stock_val
    if abs(val) > 0.01: asset_sections.append({'name': 'Current Assets', 'amount': val, 'ledgers': items})

    # 4. Misc. Expenses (Asset)
    val, items = group_balance_details('Misc. Expenses (Asset)', 'assets')
    if abs(val) > 0.01: asset_sections.append({'name': 'Misc. Expenses (Asset)', 'amount': val, 'ledgers': items})

    # --- PROFIT & LOSS CALCULATION ---
    income_opening = 0
    expense_opening = 0
    income_current = 0
    expense_current = 0
    
    pnl_groups = LedgerGroup.query.filter(
        LedgerGroup.nature.in_(['Income', 'Expense']),
        or_(LedgerGroup.company_id == cid, LedgerGroup.company_id == None)
    ).all()
    
    processed_ledger_ids = set()
    for g in pnl_groups:
        for l in _group_ledgers(g, cid):
            if l.id in processed_ledger_ids: continue
            processed_ledger_ids.add(l.id)
            
            # Opening (everything before this FY)
            prev_dr, prev_cr = _ledger_movement(l.id, to_date=fy_start.replace(day=fy_start.day-1) if fy_start.day > 1 else fy_start)
            net_pre = _ledger_opening(l) + prev_dr - prev_cr
            
            # Current (Movement in this FY)
            dr_curr, cr_curr = _ledger_movement(l.id, from_date=fy_start, to_date=as_on)
            net_curr = dr_curr - cr_curr
            
            if g.nature == 'Income':
                income_opening += -net_pre
                income_current += -net_curr
            else:
                expense_opening += net_pre
                expense_current += net_curr
                
    import datetime
    opening_stock_fy = _stock_value(cid, fy_start - datetime.timedelta(days=1))
    closing_stock_as_on = _stock_value(cid, as_on)

    pnl_opening = income_opening - expense_opening
    pnl_current = (income_current + closing_stock_as_on) - (expense_current + opening_stock_fy)
    pnl_total = pnl_opening + pnl_current
    
    pnl_data = {
        'opening': pnl_opening,
        'current': pnl_current,
        'total': pnl_total
    }
    
    if pnl_total > 0:
        liab_sections.append({'name': 'Profit & Loss A/c', 'amount': pnl_total, 'details': pnl_data})
    elif pnl_total < 0:
        asset_sections.append({'name': 'Profit & Loss A/c', 'amount': abs(pnl_total), 'details': pnl_data})

    # --- BALANCING ---
    total_liab = sum(s['amount'] for s in liab_sections)
    total_asset = sum(s['amount'] for s in asset_sections)
    
    diff = total_liab - total_asset
    if diff > 0.01:
        asset_sections.append({'name': 'Difference in opening balances', 'amount': diff})
        total_asset += diff
    elif diff < -0.01:
        liab_sections.append({'name': 'Difference in opening balances', 'amount': abs(diff)})
        total_liab += abs(diff)

    return render_template('reports/balance_sheet.html',
        company=company, as_on=as_on,
        liabilities=liab_sections, assets=asset_sections,
        total_liabilities=total_liab, total_assets=total_asset
    )
