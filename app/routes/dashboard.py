from flask import Blueprint, render_template, session, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import Company, Voucher
from app import db
from datetime import datetime, date, timedelta
from sqlalchemy import func

dashboard_bp = Blueprint('dashboard', __name__)

def get_company():
    if not current_user or not current_user.is_authenticated:
        return None
    cid = session.get('company_id')
    if cid:
        c = Company.query.get(cid)
        if c and current_user.can_access_company(c.id):
            return c
    # Find first allowed company
    companies = Company.query.filter_by(is_active=True).all()
    for c in companies:
        if current_user.can_access_company(c.id):
            session['company_id'] = c.id
            return c
    return None

@dashboard_bp.app_context_processor
def inject_globals():
    company = None
    companies = []
    if current_user and current_user.is_authenticated:
        company = get_company()
        all_cos = Company.query.filter_by(is_active=True).all()
        companies = [c for c in all_cos if current_user.can_access_company(c.id)]
    return dict(company=company, companies=companies, now=datetime.now())

@dashboard_bp.route('/dashboard')
@login_required
def index():
    company = get_company()
    if not company:
        return redirect(url_for('company.setup'))
    
    today = date.today()
    month_start = today.replace(day=1)
    
    # Monthly Stats
    sales_month = db.session.query(func.sum(Voucher.total_amount)).filter(
        Voucher.company_id == company.id, Voucher.voucher_type == 'Sales',
        Voucher.date >= month_start, Voucher.is_cancelled == False
    ).scalar() or 0
    
    purchases_month = db.session.query(func.sum(Voucher.total_amount)).filter(
        Voucher.company_id == company.id, Voucher.voucher_type == 'Purchase',
        Voucher.date >= month_start, Voucher.is_cancelled == False
    ).scalar() or 0
    
    # Sales Comparison (Growth Calculation)
    if today.month == 1:
        prev_month_start = today.replace(year=today.year - 1, month=12, day=1)
    else:
        prev_month_start = today.replace(month=today.month - 1, day=1)
    prev_month_end = month_start - timedelta(days=1)
    
    sales_prev_month = db.session.query(func.sum(Voucher.total_amount)).filter(
        Voucher.company_id == company.id, Voucher.voucher_type == 'Sales',
        Voucher.date >= prev_month_start, Voucher.date <= prev_month_end,
        Voucher.is_cancelled == False
    ).scalar() or 0
    
    # Dynamic Growth Logic
    sales_growth = 0
    if sales_prev_month > 0:
        sales_growth = ((sales_month - sales_prev_month) / sales_prev_month) * 100
    elif sales_month > 0:
        sales_growth = 100
        
    recent = Voucher.query.filter_by(company_id=company.id, is_cancelled=False, is_trash=False)\
        .order_by(Voucher.date.desc(), Voucher.id.desc()).limit(10).all()
    
    all_cos = Company.query.filter_by(is_active=True).all()
    companies = [c for c in all_cos if current_user.can_access_company(c.id)]
    
    return render_template('dashboard/index.html',
        company=company, companies=companies,
        sales_month=sales_month, purchases_month=purchases_month,
        sales_growth=sales_growth,
        recent=recent, today=today)

@dashboard_bp.route('/switch-company/<int:company_id>')
@login_required
def switch_company(company_id):
    if not current_user.can_access_company(company_id):
        flash('You do not have access to this company.', 'error')
        return redirect(url_for('dashboard.index'))
    c = Company.query.get_or_404(company_id)
    session['company_id'] = company_id
    flash(f'Switched to {c.name}', 'success')
    return redirect(url_for('dashboard.index'))

@dashboard_bp.route('/settings')
@login_required
def settings():
    company = get_company()
    return render_template('dashboard/settings.html', company=company)

@dashboard_bp.route('/reconcile')
@login_required
def reconcile():
    company = get_company()
    if not company: return redirect(url_for('dashboard.index'))
    cid = company.id
    
    from app.models import Voucher, LedgerEntry, StockItem, VoucherItem
    from app.routes.vouchers import recalculate_voucher_totals, create_ledger_entries
    
    # 1. Reconcile Vouchers and Ledger Entries
    vouchers = Voucher.query.filter_by(company_id=cid).all()
    count = 0
    for v in vouchers:
        if v.is_cancelled: continue
        # Only for inventory vouchers (Sales/Purchase/etc)
        if v.voucher_type in ['Sales','Purchase','Credit Note','Debit Note']:
            recalculate_voucher_totals(v)
            # Re-generate ledger entries to ensure sync
            LedgerEntry.query.filter_by(voucher_id=v.id).delete()
            create_ledger_entries(v, company)
            count += 1
            
    # 2. Re-sync Stock Item master rates from latest transactions
    items = StockItem.query.filter_by(company_id=cid).all()
    for item in items:
        last_p = VoucherItem.query.join(Voucher).filter(
            VoucherItem.stock_item_id == item.id,
            Voucher.voucher_type == 'Purchase',
            Voucher.is_cancelled == False
        ).order_by(Voucher.date.desc()).first()
        if last_p: item.purchase_rate = last_p.rate
        
        last_s = VoucherItem.query.join(Voucher).filter(
            VoucherItem.stock_item_id == item.id,
            Voucher.voucher_type == 'Sales',
            Voucher.is_cancelled == False
        ).order_by(Voucher.date.desc()).first()
        if last_s: item.sale_rate = last_s.rate

    db.session.commit()
    flash(f'Reconciliation complete! Audited {count} vouchers and updated item rates.', 'success')
    return redirect(url_for('dashboard.index'))
