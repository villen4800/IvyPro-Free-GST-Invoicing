from app import db, login_manager
from flask_login import UserMixin
from datetime import datetime, date
from sqlalchemy import func
import json

# ─── Auth ───────────────────────────────────────────────
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(120))
    role = db.Column(db.String(20), default='admin')  # admin, staff
    photo_path = db.Column(db.String(300))
    permissions = db.Column(db.Text)
    can_edit = db.Column(db.Boolean, default=True)
    can_delete = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    allowed_companies = db.Column(db.Text) # JSON list of company IDs
    theme = db.Column(db.String(20), default='dark')
    accent_color = db.Column(db.String(20), default='#ff7429')
    keyboard_layout = db.Column(db.String(20), default='Standard') # Standard or KeyboardOnly
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def permission_set(self):
        if self.role == 'admin':
            return set(PERMISSION_KEYS)
        try:
            return set(json.loads(self.permissions or '[]'))
        except Exception:
            return set()

    def can_access(self, feature):
        return self.role == 'admin' or feature in self.permission_set()

    def allowed_company_ids(self):
        if self.role == 'admin': return None # None means access all
        try:
            return json.loads(self.allowed_companies or '[]')
        except Exception:
            return []

    def can_access_company(self, company_id):
        if self.role == 'admin': return True
        ids = self.allowed_company_ids()
        if ids is None: return True
        return int(company_id) in [int(x) for x in ids]

class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    username = db.Column(db.String(80))
    action = db.Column(db.String(80), nullable=False)
    feature = db.Column(db.String(50))
    detail = db.Column(db.Text)
    ip_address = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='activity_logs')

PERMISSION_KEYS = [
    'vouchers', 'ledger', 'inventory', 'reports', 'gst',
    'import_export', 'company', 'settings', 'users', 'service_job', 'attendance', 'tally_sync'
]

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ─── Company ─────────────────────────────────────────────
class Company(db.Model):
    __tablename__ = 'companies'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    legal_name = db.Column(db.String(200))
    gstin = db.Column(db.String(15))
    pan = db.Column(db.String(10))
    address = db.Column(db.Text)
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    state_code = db.Column(db.String(5))
    pincode = db.Column(db.String(10))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    website = db.Column(db.String(100))
    bank_name = db.Column(db.String(100))
    bank_account = db.Column(db.String(20))
    bank_ifsc = db.Column(db.String(20))
    bank_branch = db.Column(db.String(100))
    financial_year_start = db.Column(db.String(5), default='04-01')
    upi_id = db.Column(db.String(100))  # UPI ID for QR payment
    currency = db.Column(db.String(5), default='INR')
    enable_gst = db.Column(db.Boolean, default=True)  # False = Non-GST / composition firm
    invoice_prefix = db.Column(db.String(10), default='INV')
    invoice_start_number = db.Column(db.Integer, default=1)
    logo_path = db.Column(db.String(300))
    signature_path = db.Column(db.String(300))
    show_gst_summary = db.Column(db.Boolean, default=True)
    show_invoice_qr = db.Column(db.Boolean, default=False)
    show_upi_qr = db.Column(db.Boolean, default=True)
    terms = db.Column(db.Text)
    is_locked = db.Column(db.Boolean, default=False)
    lock_date = db.Column(db.Date)
    current_fy = db.Column(db.String(20)) # Manual FY override (e.g. "2024-25")
    randomize_vouchers = db.Column(db.Boolean, default=False) # Privacy: INV-8231 instead of INV-0001
    print_layout = db.Column(db.String(20), default='A4') # A4 or Thermal
    invoice_copies = db.Column(db.Integer, default=1) # 1=Original, 2=Duplicate, 3=Triplicate
    auto_save_invoices = db.Column(db.Boolean, default=False)
    gst_registration_type = db.Column(db.String(20), default='Regular') # Regular, Composition, Unregistered
    composition_rate = db.Column(db.Float, default=0) # Flat tax rate for composition scheme (e.g. 1% or 5%)
    
    # Advanced Invoice Customization
    voucher_performa = db.Column(db.String(50), default='modern') # modern, classic, tally
    custom_header_text = db.Column(db.String(200)) # Custom text above/below company name
    custom_footer_text = db.Column(db.String(200)) # Custom greeting/footer text
    header_alignment = db.Column(db.String(20), default='LEFT') # LEFT, CENTER, RIGHT
    logo_placement = db.Column(db.String(20), default='LEFT') # LEFT, RIGHT, TOP_CENTER
    watermark_path = db.Column(db.String(300)) # Background watermark image
    table_header_bg = db.Column(db.String(20), default='#1a1a2e') # Table header background hex
    table_header_text_color = db.Column(db.String(20), default='#ffffff')
    primary_color = db.Column(db.String(20), default='#e94560') # Accent color for lines/borders
    
    # Format-specific configuration
    a4_font_size = db.Column(db.Float, default=9.5)
    a5_font_size = db.Column(db.Float, default=8.0)
    thermal_font_size = db.Column(db.Float, default=7.5)
    margin_top = db.Column(db.Float, default=10.0) # mm
    margin_bottom = db.Column(db.Float, default=10.0) # mm
    margin_left = db.Column(db.Float, default=10.0) # mm
    margin_right = db.Column(db.Float, default=10.0) # mm
    qr_placement = db.Column(db.String(20), default='BOTTOM_CENTER') # BOTTOM_LEFT, BOTTOM_CENTER, BOTTOM_RIGHT, TOP_RIGHT
    block_order = db.Column(db.String(200), default='header,hr,addresses,items,totals,gst,footer') # Order of invoice sections
    thermal_width = db.Column(db.Float, default=80.0)
    custom_width = db.Column(db.Float, default=210.0)
    custom_height = db.Column(db.Float, default=297.0)
    paper_type = db.Column(db.String(20), default='Plain') # Plain, Letterhead, Pre-printed
    
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


    def get_fy(self, dt=None):
        if not dt: dt = date.today()
        if isinstance(dt, str):
            try:
                # Handle YYYY-MM-DD or YYYY-MM-DD HH:MM:SS
                dt = date.fromisoformat(dt.split(' ')[0])
            except:
                dt = date.today()
        
        year = dt.year
        if dt.month < 4: # Jan, Feb, Mar
            return f"{year-1}-{str(year)[2:]}"
        else: # Apr - Dec
            return f"{year}-{str(year+1)[2:]}"

    @property
    def display_fy(self):
        if self.current_fy:
            return self.current_fy
        return self.get_fy()

# ─── GST Rates ────────────────────────────────────────────
class GSTRate(db.Model):
    __tablename__ = 'gst_rates'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    rate = db.Column(db.Float, default=0)  # Total GST %
    cgst = db.Column(db.Float, default=0)
    sgst = db.Column(db.Float, default=0)
    igst = db.Column(db.Float, default=0)
    cess = db.Column(db.Float, default=0)

# ─── HSN/SAC ─────────────────────────────────────────────
class HSNCode(db.Model):
    __tablename__ = 'hsn_codes'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True)
    description = db.Column(db.Text)
    gst_rate = db.Column(db.Float, default=0)
    code_type = db.Column(db.String(5), default='HSN')  # HSN or SAC

# ─── Ledger Groups (Tally-style) ─────────────────────────
class LedgerGroup(db.Model):
    __tablename__ = 'ledger_groups'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('ledger_groups.id'), nullable=True)
    nature = db.Column(db.String(20))  # Assets, Liabilities, Income, Expense
    is_system = db.Column(db.Boolean, default=False)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'))
    children = db.relationship('LedgerGroup', backref=db.backref('parent', remote_side=[id]))

# ─── Ledger / Account ─────────────────────────────────────
class Ledger(db.Model):
    __tablename__ = 'ledgers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    alias = db.Column(db.String(100))
    group_id = db.Column(db.Integer, db.ForeignKey('ledger_groups.id'))
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    opening_balance = db.Column(db.Float, default=0)
    opening_type = db.Column(db.String(2), default='Dr')  # Dr or Cr
    gstin = db.Column(db.String(15))
    pan = db.Column(db.String(10))
    address = db.Column(db.Text)
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    state_code = db.Column(db.String(5))
    pincode = db.Column(db.String(10))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    credit_limit = db.Column(db.Float, default=0)
    credit_days = db.Column(db.Integer, default=30)
    is_active = db.Column(db.Boolean, default=True)
    registration_type = db.Column(db.String(20), default='Regular') # Regular, Composition, Unregistered, Consumer
    is_exported_to_tally = db.Column(db.Boolean, default=False)
    
    # Loan specifics
    is_loan = db.Column(db.Boolean, default=False)
    loan_principal = db.Column(db.Float, default=0)
    loan_interest_rate = db.Column(db.Float, default=0)
    loan_emi = db.Column(db.Float, default=0)
    loan_tenure = db.Column(db.Integer, default=12) # Months
    loan_interest_type = db.Column(db.String(20), default='Reducing') # Reducing or Flat
    loan_is_compounding = db.Column(db.Boolean, default=False)
    interest_ledger_id = db.Column(db.Integer, db.ForeignKey('ledgers.id'))
    loan_start_date = db.Column(db.Date)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    group = db.relationship('LedgerGroup', backref='ledgers')
    addresses = db.relationship('PartyAddress', backref='ledger', cascade='all, delete-orphan')

# ─── Party Address (Multi-Address Tracking) ───────────────
class PartyAddress(db.Model):
    __tablename__ = 'party_addresses'
    id = db.Column(db.Integer, primary_key=True)
    ledger_id = db.Column(db.Integer, db.ForeignKey('ledgers.id'), nullable=False)
    address_type = db.Column(db.String(50), default='Billing') # e.g. Billing, Shipping, Branch, Warehouse
    address = db.Column(db.Text)
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    pincode = db.Column(db.String(10))
    gstin = db.Column(db.String(15)) # Optional branch GSTIN
    is_default = db.Column(db.Boolean, default=False)

# ─── Stock Group ──────────────────────────────────────────
class StockGroup(db.Model):
    __tablename__ = 'stock_groups'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('stock_groups.id'), nullable=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'))
    children = db.relationship('StockGroup', backref=db.backref('parent', remote_side=[id]))

# ─── Unit of Measurement ──────────────────────────────────
class Unit(db.Model):
    __tablename__ = 'units'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    symbol = db.Column(db.String(10))

# ─── Stock Item (Product/Service) ─────────────────────────
class StockItem(db.Model):
    __tablename__ = 'stock_items'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    alias = db.Column(db.String(100))
    group_id = db.Column(db.Integer, db.ForeignKey('stock_groups.id'))
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id'))
    hsn_code = db.Column(db.String(10))
    gst_rate_id = db.Column(db.Integer, db.ForeignKey('gst_rates.id'))
    purchase_rate = db.Column(db.Float, default=0)
    sale_rate = db.Column(db.Float, default=0)
    mrp = db.Column(db.Float, default=0)
    opening_qty = db.Column(db.Float, default=0)
    opening_value = db.Column(db.Float, default=0)
    reorder_level = db.Column(db.Float, default=0)
    is_service = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    description = db.Column(db.Text)
    barcode = db.Column(db.String(100)) # Product-level barcode
    group = db.relationship('StockGroup', backref='items')
    unit = db.relationship('Unit')
    gst_rate = db.relationship('GSTRate')

# ─── Serial Numbers Tracking ──────────────────────────────
class SerialNumber(db.Model):
    __tablename__ = 'serial_numbers'
    id = db.Column(db.Integer, primary_key=True)
    stock_item_id = db.Column(db.Integer, db.ForeignKey('stock_items.id'), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    serial_number = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='Available') # Available, Sold, Damaged, Transferred
    
    # Tracking links
    purchase_voucher_id = db.Column(db.Integer, db.ForeignKey('vouchers.id'))
    sale_voucher_id = db.Column(db.Integer, db.ForeignKey('vouchers.id'))
    voucher_item_id = db.Column(db.Integer, db.ForeignKey('voucher_items.id')) # Link to specific row
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    stock_item = db.relationship('StockItem', backref='serial_numbers')
    purchase_voucher = db.relationship('Voucher', foreign_keys=[purchase_voucher_id])
    sale_voucher = db.relationship('Voucher', foreign_keys=[sale_voucher_id])

# ─── Voucher Types ────────────────────────────────────────
VOUCHER_TYPES = [
    'Sales', 'Purchase', 'Credit Note', 'Debit Note',
    'Receipt', 'Payment', 'Journal', 'Contra',
    'Stock Journal', 'Delivery Note', 'Receipt Note'
]

# ─── Voucher (Master) ─────────────────────────────────────
class Voucher(db.Model):
    __tablename__ = 'vouchers'
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    voucher_type = db.Column(db.String(30), nullable=False)
    voucher_number = db.Column(db.String(50))
    date = db.Column(db.Date, nullable=False, default=date.today)
    ref_number = db.Column(db.String(50))
    party_ledger_id = db.Column(db.Integer, db.ForeignKey('ledgers.id'))
    narration = db.Column(db.Text)
    
    # Billing Address Snapshot
    billing_address = db.Column(db.Text)
    billing_city = db.Column(db.String(100))
    billing_state = db.Column(db.String(100))
    billing_pincode = db.Column(db.String(10))
    billing_gstin = db.Column(db.String(15))

    # Shipping Address Snapshot (Consignee)
    shipping_address = db.Column(db.Text)
    shipping_city = db.Column(db.String(100))
    shipping_state = db.Column(db.String(100))
    shipping_pincode = db.Column(db.String(10))
    shipping_gstin = db.Column(db.String(15))
    
    # GST fields
    place_of_supply = db.Column(db.String(100))
    is_igst = db.Column(db.Boolean, default=False)
    reverse_charge = db.Column(db.Boolean, default=False)
    e_invoice_irn = db.Column(db.String(100))
    
    # Totals
    subtotal = db.Column(db.Float, default=0)
    discount_amount = db.Column(db.Float, default=0)
    taxable_amount = db.Column(db.Float, default=0)
    cgst_amount = db.Column(db.Float, default=0)
    sgst_amount = db.Column(db.Float, default=0)
    igst_amount = db.Column(db.Float, default=0)
    cess_amount = db.Column(db.Float, default=0)
    total_amount = db.Column(db.Float, default=0)
    round_off = db.Column(db.Float, default=0)
    
    payment_mode = db.Column(db.String(20), default='Cash')  # Cash or Credit
    payment_ledger_id = db.Column(db.Integer, db.ForeignKey('ledgers.id'))
    is_cancelled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    party = db.relationship('Ledger', foreign_keys=[party_ledger_id], backref='vouchers')
    payment_ledger = db.relationship('Ledger', foreign_keys=[payment_ledger_id])
    is_trash = db.Column(db.Boolean, default=False)
    is_exported_to_tally = db.Column(db.Boolean, default=False)
    
    # Compliance: e-Way Bill
    eway_bill_no = db.Column(db.String(20))
    transporter_name = db.Column(db.String(100))
    vehicle_no = db.Column(db.String(20))
    distance = db.Column(db.Integer)
    
    # Compliance: TDS / TCS
    tds_amount = db.Column(db.Float, default=0)
    tds_percent = db.Column(db.Float, default=0)
    
    party = db.relationship('Ledger', foreign_keys=[party_ledger_id])
    company = db.relationship('Company', backref='vouchers')
    items = db.relationship('VoucherItem', backref='voucher', cascade='all, delete-orphan')
    ledger_entries = db.relationship('LedgerEntry', backref='voucher', cascade='all, delete-orphan')

# ─── Voucher Items (Invoice Lines) ────────────────────────
class VoucherItem(db.Model):
    __tablename__ = 'voucher_items'
    id = db.Column(db.Integer, primary_key=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey('vouchers.id'), nullable=False)
    stock_item_id = db.Column(db.Integer, db.ForeignKey('stock_items.id'))
    description = db.Column(db.String(300))
    hsn_code = db.Column(db.String(10))
    qty = db.Column(db.Float, default=0)
    unit = db.Column(db.String(20))
    rate = db.Column(db.Float, default=0)
    discount_pct = db.Column(db.Float, default=0)
    discount_amt = db.Column(db.Float, default=0)
    taxable_amount = db.Column(db.Float, default=0)
    gst_rate = db.Column(db.Float, default=0)
    cgst_rate = db.Column(db.Float, default=0)
    cgst_amount = db.Column(db.Float, default=0)
    sgst_rate = db.Column(db.Float, default=0)
    sgst_amount = db.Column(db.Float, default=0)
    igst_rate = db.Column(db.Float, default=0)
    igst_amount = db.Column(db.Float, default=0)
    cess_rate = db.Column(db.Float, default=0)
    cess_amount = db.Column(db.Float, default=0)
    total_amount = db.Column(db.Float, default=0)
    stock_item = db.relationship('StockItem')
    # Link to serial numbers assigned to this specific line
    serial_numbers = db.relationship('SerialNumber', foreign_keys=[SerialNumber.voucher_item_id], backref='assigned_item')

# ─── Ledger Entry (Double Entry) ─────────────────────────
class LedgerEntry(db.Model):
    __tablename__ = 'ledger_entries'
    id = db.Column(db.Integer, primary_key=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey('vouchers.id'), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'))
    ledger_id = db.Column(db.Integer, db.ForeignKey('ledgers.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    debit = db.Column(db.Float, default=0)
    credit = db.Column(db.Float, default=0)
    narration = db.Column(db.Text)
    
    # Bank Details (for Tally-style credited/bank entries)
    bank_tx_type = db.Column(db.String(30))  # Cheque, NEFT, UPI, etc.
    inst_no = db.Column(db.String(50))      # Instrument Number
    inst_date = db.Column(db.Date)          # Instrument Date
    bank_name = db.Column(db.String(100))   # Bank Name
    
    ledger = db.relationship('Ledger')

# ─── Payment Tracking ────────────────────────────────────
class Payment(db.Model):
    __tablename__ = 'payments'
    id = db.Column(db.Integer, primary_key=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey('vouchers.id'))
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'))
    amount = db.Column(db.Float, default=0)
    date = db.Column(db.Date, default=date.today)
    mode = db.Column(db.String(30))  # Cash, Bank, UPI, Cheque
    reference = db.Column(db.String(100))
    notes = db.Column(db.Text)

# ─── Seed / Defaults ─────────────────────────────────────
def seed_data():
    if not GSTRate.query.first():
        rates = [
            GSTRate(name='GST 0%',  rate=0,  cgst=0,   sgst=0,   igst=0,  cess=0),
            GSTRate(name='GST 0.25%', rate=0.25, cgst=0.125, sgst=0.125, igst=0.25, cess=0),
            GSTRate(name='GST 3%',  rate=3,  cgst=1.5, sgst=1.5, igst=3,  cess=0),
            GSTRate(name='GST 5%',  rate=5,  cgst=2.5, sgst=2.5, igst=5,  cess=0),
            GSTRate(name='GST 12%', rate=12, cgst=6,   sgst=6,   igst=12, cess=0),
            GSTRate(name='GST 18%', rate=18, cgst=9,   sgst=9,   igst=18, cess=0),
            GSTRate(name='GST 28%', rate=28, cgst=14,  sgst=14,  igst=28, cess=0),
        ]
        db.session.add_all(rates)
    
    if not Unit.query.first():
        units = [
            Unit(name='Numbers', symbol='NOS'),
            Unit(name='Kilograms', symbol='KG'),
            Unit(name='Grams', symbol='GMS'),
            Unit(name='Litres', symbol='LTR'),
            Unit(name='Metres', symbol='MTR'),
            Unit(name='Square Metres', symbol='SQM'),
            Unit(name='Pieces', symbol='PCS'),
            Unit(name='Box', symbol='BOX'),
            Unit(name='Pack', symbol='PCK'),
            Unit(name='Hours', symbol='HRS'),
            Unit(name='Days', symbol='DYS'),
            Unit(name='Months', symbol='MNT'),
        ]
        db.session.add_all(units)
    
    if not LedgerGroup.query.first():
        groups = [
            # Asset groups
            LedgerGroup(name='Capital Account', nature='Liabilities', is_system=True),
            LedgerGroup(name='Loans (Liability)', nature='Liabilities', is_system=True),
            LedgerGroup(name='Current Liabilities', nature='Liabilities', is_system=True),
            LedgerGroup(name='Sundry Creditors', nature='Liabilities', is_system=True),
            LedgerGroup(name='Duties & Taxes', nature='Liabilities', is_system=True),
            LedgerGroup(name='Fixed Assets', nature='Assets', is_system=True),
            LedgerGroup(name='Current Assets', nature='Assets', is_system=True),
            LedgerGroup(name='Cash-in-Hand', nature='Assets', is_system=True),
            LedgerGroup(name='Bank Accounts', nature='Assets', is_system=True),
            LedgerGroup(name='Sundry Debtors', nature='Assets', is_system=True),
            LedgerGroup(name='Stock-in-Hand', nature='Assets', is_system=True),
            LedgerGroup(name='Sales Accounts', nature='Income', is_system=True),
            LedgerGroup(name='Purchase Accounts', nature='Expense', is_system=True),
            LedgerGroup(name='Direct Income', nature='Income', is_system=True),
            LedgerGroup(name='Indirect Income', nature='Income', is_system=True),
            LedgerGroup(name='Direct Expenses', nature='Expense', is_system=True),
            LedgerGroup(name='Indirect Expenses', nature='Expense', is_system=True),
        ]
        db.session.add_all(groups)
    
    db.session.commit()


# ─── End of Models ──────────────────────────────────────
