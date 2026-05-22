from flask import Flask, request, redirect, url_for, flash, g, session
import jinja2
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import os

db = SQLAlchemy()
login_manager = LoginManager()

def create_app(db_path=None):
    app = Flask(__name__, static_folder='static')
    
    app.jinja_loader = jinja2.ChoiceLoader([
        jinja2.FileSystemLoader(os.path.join(app.root_path, '../templates_modern')),
        app.jinja_loader
    ])
    app.jinja_options = app.jinja_options.copy()
    app.jinja_options['cache_size'] = 0

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)

    if db_path is None:
        db_path = os.path.join(data_dir, 'gst_billing.db')

    app.config['SECRET_KEY'] = 'gst-billing-secret-key-india-2024'
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['BASE_DIR'] = base_dir

    db.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'
    # Use 303 so unauthenticated POSTs redirect as GET
    login_manager.refresh_view = 'auth.login'

    from app.routes import register_blueprints
    register_blueprints(app)


    @app.context_processor
    def inject_globals():
        from app.utils.formatters import num_to_words
        from app.plugin_manager import plugin_manager
        from flask import g
        return dict(
            num_to_words=num_to_words, 
            plugin_manager=plugin_manager,
            current_company=getattr(g, 'current_company', None)
        )

    @app.before_request
    def enforce_permissions():
        from flask_login import current_user
        from app.models import User, ActivityLog, Company

        if current_user and current_user.is_authenticated:
            cid = session.get('company_id')
            company = None
            if cid:
                company = db.session.get(Company, cid)
            
            if not company:
                company = Company.query.filter_by(is_active=True).first()
                if company:
                    session['company_id'] = company.id
            
            g.current_company = company

        endpoint = request.endpoint or ''
        if endpoint.startswith('static'):
            return None

        if endpoint not in ('auth.first_setup', 'auth.login') and not User.query.first():
            return redirect(url_for('auth.first_setup'))

        if not current_user.is_authenticated:
            return None
        if endpoint != 'auth.logout' and not getattr(current_user, 'is_active', True):
            return redirect(url_for('auth.logout'))

        # Exemptions
        if not endpoint or endpoint.endswith('.settings') or endpoint == 'auth.logout':
            return None

        feature = _feature_for_endpoint(endpoint)
        if feature and not current_user.can_access(feature):
            db.session.add(ActivityLog(
                user_id=current_user.id,
                username=current_user.username,
                action='blocked_access',
                feature=feature,
                detail=endpoint,
                ip_address=request.remote_addr
            ))
            db.session.commit()
            flash('You do not have permission to access that feature.', 'error')
            return redirect(url_for('dashboard.settings'))

        if endpoint.endswith('.delete') or endpoint in ('vouchers.cancel',):
            if current_user.role != 'admin' and not current_user.can_delete:
                flash('You do not have delete/cancel permission.', 'error')
                return redirect(request.referrer or url_for('dashboard.index'))

        if request.method in ('POST', 'PUT', 'PATCH') or '.edit' in endpoint or '.create' in endpoint:
            if feature and current_user.role != 'admin' and not current_user.can_edit:
                flash('You do not have add/edit permission.', 'error')
                return redirect(request.referrer or url_for('dashboard.index'))

    @app.after_request
    def log_mutations(response):
        from flask_login import current_user
        from app.models import ActivityLog
        if current_user.is_authenticated and response.status_code < 400:
            endpoint = request.endpoint or ''
            if request.method in ('POST', 'PUT', 'PATCH') or endpoint.endswith('.delete') or endpoint in ('vouchers.cancel',):
                feature = _feature_for_endpoint(endpoint)
                if feature:
                    db.session.add(ActivityLog(
                        user_id=current_user.id,
                        username=current_user.username,
                        action=request.method.lower(),
                        feature=feature,
                        detail=endpoint,
                        ip_address=request.remote_addr
                    ))
                    db.session.commit()
        return response

    with app.app_context():
        db.create_all()
        _upgrade_sqlite_schema()
        from app.models import seed_data
        seed_data()
        
        # Load plugins AFTER DB is ready
        from app.plugin_manager import plugin_manager
        plugin_manager.init_app(app)

    return app

def _feature_for_endpoint(endpoint):
    if not endpoint or endpoint.endswith('.settings') or endpoint == 'auth.logout':
        return None  # Everyone can access settings/profile and logout
    if endpoint.startswith('auth.users') or endpoint.startswith('auth.create_user') or endpoint.startswith('auth.update_user') or endpoint.startswith('auth.delete_user'):
        return 'users'
    prefix = endpoint.split('.')[0] if endpoint else ''
    return {
        'dashboard': 'dashboard',
        'vouchers': 'vouchers',
        'ledger': 'ledger',
        'inventory': 'inventory',
        'reports': 'reports',
        'gst': 'gst',
        'import_export': 'import_export',
        'company': 'company',
        'settings': 'settings',
        'service_job': 'service_job',
        'attendance': 'attendance',
        'tally_sync': 'tally_sync',
        'plugins': 'plugins',
    }.get(prefix)

def _upgrade_sqlite_schema():
    from sqlalchemy import text
    engine = db.engine

    def columns(table):
        try:
            rows = db.session.execute(text(f"PRAGMA table_info({table})")).fetchall()
            return {row[1] for row in rows}
        except Exception:
            return set()

    # ── companies table migrations ────────────────────────
    co_cols = columns('companies')
    co_additions = {
        'enable_gst':           "ALTER TABLE companies ADD COLUMN enable_gst BOOLEAN DEFAULT 1",
        'invoice_prefix':       "ALTER TABLE companies ADD COLUMN invoice_prefix VARCHAR(10) DEFAULT 'INV'",
        'invoice_start_number': "ALTER TABLE companies ADD COLUMN invoice_start_number INTEGER DEFAULT 1",
        'address_line1':        "ALTER TABLE companies ADD COLUMN address_line1 VARCHAR(200)",
        'address_line2':        "ALTER TABLE companies ADD COLUMN address_line2 VARCHAR(200)",
        'upi_id':               "ALTER TABLE companies ADD COLUMN upi_id VARCHAR(100)",
        'logo_path':            "ALTER TABLE companies ADD COLUMN logo_path VARCHAR(300)",
        'logo_path':            "ALTER TABLE companies ADD COLUMN logo_path VARCHAR(300)",
        'invoice_footer':       "ALTER TABLE companies ADD COLUMN invoice_footer VARCHAR(300) DEFAULT 'Thank you for your business!'",
        'business_type':        "ALTER TABLE companies ADD COLUMN business_type VARCHAR(50)",
        'show_gst_summary':     "ALTER TABLE companies ADD COLUMN show_gst_summary BOOLEAN DEFAULT 1",
        'show_invoice_qr':      "ALTER TABLE companies ADD COLUMN show_invoice_qr BOOLEAN DEFAULT 1",
        'is_locked':            "ALTER TABLE companies ADD COLUMN is_locked BOOLEAN DEFAULT 0",
        'lock_date':            "ALTER TABLE companies ADD COLUMN lock_date DATE",
        'current_fy':           "ALTER TABLE companies ADD COLUMN current_fy VARCHAR(20)",
        'randomize_vouchers':   "ALTER TABLE companies ADD COLUMN randomize_vouchers BOOLEAN DEFAULT 0",
        'print_layout':         "ALTER TABLE companies ADD COLUMN print_layout VARCHAR(20) DEFAULT 'A4'",
        'auto_save_invoices':   "ALTER TABLE companies ADD COLUMN auto_save_invoices BOOLEAN DEFAULT 0",
        'gst_registration_type': "ALTER TABLE companies ADD COLUMN gst_registration_type VARCHAR(20) DEFAULT 'Regular'",
        'composition_rate':      "ALTER TABLE companies ADD COLUMN composition_rate FLOAT DEFAULT 0",
        'voucher_performa':      "ALTER TABLE companies ADD COLUMN voucher_performa VARCHAR(50) DEFAULT 'modern'",
        'custom_header_text':    "ALTER TABLE companies ADD COLUMN custom_header_text VARCHAR(200)",
        'custom_footer_text':    "ALTER TABLE companies ADD COLUMN custom_footer_text VARCHAR(200)",
        'header_alignment':      "ALTER TABLE companies ADD COLUMN header_alignment VARCHAR(20) DEFAULT 'LEFT'",
        'logo_placement':        "ALTER TABLE companies ADD COLUMN logo_placement VARCHAR(20) DEFAULT 'LEFT'",
        'watermark_path':        "ALTER TABLE companies ADD COLUMN watermark_path VARCHAR(300)",
        'table_header_bg':       "ALTER TABLE companies ADD COLUMN table_header_bg VARCHAR(20) DEFAULT '#1a1a2e'",
        'table_header_text_color': "ALTER TABLE companies ADD COLUMN table_header_text_color VARCHAR(20) DEFAULT '#ffffff'",
        'primary_color':         "ALTER TABLE companies ADD COLUMN primary_color VARCHAR(20) DEFAULT '#e94560'",
        'a4_font_size':          "ALTER TABLE companies ADD COLUMN a4_font_size FLOAT DEFAULT 9.5",
        'a5_font_size':          "ALTER TABLE companies ADD COLUMN a5_font_size FLOAT DEFAULT 8.0",
        'thermal_font_size':     "ALTER TABLE companies ADD COLUMN thermal_font_size FLOAT DEFAULT 7.5",
        'margin_top':            "ALTER TABLE companies ADD COLUMN margin_top FLOAT DEFAULT 10.0",
        'margin_bottom':         "ALTER TABLE companies ADD COLUMN margin_bottom FLOAT DEFAULT 10.0",
        'margin_left':           "ALTER TABLE companies ADD COLUMN margin_left FLOAT DEFAULT 10.0",
        'margin_right':          "ALTER TABLE companies ADD COLUMN margin_right FLOAT DEFAULT 10.0",
        'qr_placement':          "ALTER TABLE companies ADD COLUMN qr_placement VARCHAR(20) DEFAULT 'BOTTOM_CENTER'",
        'block_order':           "ALTER TABLE companies ADD COLUMN block_order VARCHAR(200) DEFAULT 'header,hr,addresses,items,totals,gst,footer'",
        'thermal_width':         "ALTER TABLE companies ADD COLUMN thermal_width FLOAT DEFAULT 80.0",
        'custom_width':          "ALTER TABLE companies ADD COLUMN custom_width FLOAT DEFAULT 210.0",
        'custom_height':         "ALTER TABLE companies ADD COLUMN custom_height FLOAT DEFAULT 297.0",
        'paper_type':            "ALTER TABLE companies ADD COLUMN paper_type VARCHAR(20) DEFAULT 'Plain'",
    }
    for col, sql in co_additions.items():
        if col not in co_cols:
            try:
                db.session.execute(text(sql))
            except Exception:
                pass
    db.session.commit()

    user_cols = columns('users')
    additions = {
        'full_name': "ALTER TABLE users ADD COLUMN full_name VARCHAR(120)",
        'photo_path': "ALTER TABLE users ADD COLUMN photo_path VARCHAR(300)",
        'permissions': "ALTER TABLE users ADD COLUMN permissions TEXT",
        'can_edit': "ALTER TABLE users ADD COLUMN can_edit BOOLEAN DEFAULT 1",
        'can_delete': "ALTER TABLE users ADD COLUMN can_delete BOOLEAN DEFAULT 1",
        'is_active': "ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1",
        'theme': "ALTER TABLE users ADD COLUMN theme VARCHAR(20) DEFAULT 'dark'",
        'accent_color': "ALTER TABLE users ADD COLUMN accent_color VARCHAR(20) DEFAULT '#00e5ff'",
        'keyboard_layout': "ALTER TABLE users ADD COLUMN keyboard_layout VARCHAR(20) DEFAULT 'Standard'",
    }
    for col, sql in additions.items():
        if col not in user_cols:
            db.session.execute(text(sql))
    db.session.commit()

    # ── vouchers table migrations ─────────────────────────
    v_cols = columns('vouchers')
    v_additions = {
        'payment_mode': "ALTER TABLE vouchers ADD COLUMN payment_mode VARCHAR(20) DEFAULT 'Credit'",
        'is_recurring': "ALTER TABLE vouchers ADD COLUMN is_recurring BOOLEAN DEFAULT 0",
        'is_trash':     "ALTER TABLE vouchers ADD COLUMN is_trash BOOLEAN DEFAULT 0",
        'eway_bill_no': "ALTER TABLE vouchers ADD COLUMN eway_bill_no VARCHAR(20)",
        'transporter_name': "ALTER TABLE vouchers ADD COLUMN transporter_name VARCHAR(100)",
        'vehicle_no':   "ALTER TABLE vouchers ADD COLUMN vehicle_no VARCHAR(20)",
        'distance':     "ALTER TABLE vouchers ADD COLUMN distance INTEGER",
        'tds_amount':   "ALTER TABLE vouchers ADD COLUMN tds_amount FLOAT DEFAULT 0",
        'tds_percent':  "ALTER TABLE vouchers ADD COLUMN tds_percent FLOAT DEFAULT 0",
        'is_exported_to_tally': "ALTER TABLE vouchers ADD COLUMN is_exported_to_tally BOOLEAN DEFAULT 0",
        'payment_ledger_id': "ALTER TABLE vouchers ADD COLUMN payment_ledger_id INTEGER",
        'billing_address': "ALTER TABLE vouchers ADD COLUMN billing_address TEXT",
        'billing_city': "ALTER TABLE vouchers ADD COLUMN billing_city VARCHAR(100)",
        'billing_state': "ALTER TABLE vouchers ADD COLUMN billing_state VARCHAR(100)",
        'billing_pincode': "ALTER TABLE vouchers ADD COLUMN billing_pincode VARCHAR(10)",
        'billing_gstin': "ALTER TABLE vouchers ADD COLUMN billing_gstin VARCHAR(15)",
        'shipping_address': "ALTER TABLE vouchers ADD COLUMN shipping_address TEXT",
        'shipping_city': "ALTER TABLE vouchers ADD COLUMN shipping_city VARCHAR(100)",
        'shipping_state': "ALTER TABLE vouchers ADD COLUMN shipping_state VARCHAR(100)",
        'shipping_pincode': "ALTER TABLE vouchers ADD COLUMN shipping_pincode VARCHAR(10)",
        'shipping_gstin': "ALTER TABLE vouchers ADD COLUMN shipping_gstin VARCHAR(15)",
    }
    for col, sql in v_additions.items():
        if col not in v_cols:
            try:
                db.session.execute(text(sql))
            except Exception:
                pass
    db.session.commit()

    # ── ledgers table migrations ──────────────────────────
    l_cols = columns('ledgers')
    l_additions = {
        'is_exported_to_tally': "ALTER TABLE ledgers ADD COLUMN is_exported_to_tally BOOLEAN DEFAULT 0",
        'is_active': "ALTER TABLE ledgers ADD COLUMN is_active BOOLEAN DEFAULT 1",
        'registration_type': "ALTER TABLE ledgers ADD COLUMN registration_type VARCHAR(20) DEFAULT 'Regular'",
    }
    for col, sql in l_additions.items():
        if col not in l_cols:
            try:
                db.session.execute(text(sql))
            except Exception:
                pass
    db.session.commit()

    # ── stock_items table migrations ──────────────────────
    si_cols = columns('stock_items')
    if 'barcode' not in si_cols:
        try:
            db.session.execute(text("ALTER TABLE stock_items ADD COLUMN barcode VARCHAR(100)"))
            db.session.commit()
        except Exception:
            pass
    db.session.commit()
