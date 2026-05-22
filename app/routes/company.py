from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required
from app.models import Company, LedgerGroup, Ledger
from app import db
import os
import base64
from datetime import datetime

company_bp = Blueprint('company', __name__)

INDIAN_STATES = [
    ('01','Jammu & Kashmir'),('02','Himachal Pradesh'),('03','Punjab'),
    ('04','Chandigarh'),('05','Uttarakhand'),('06','Haryana'),
    ('07','Delhi'),('08','Rajasthan'),('09','Uttar Pradesh'),
    ('10','Bihar'),('11','Sikkim'),('12','Arunachal Pradesh'),
    ('13','Nagaland'),('14','Manipur'),('15','Mizoram'),
    ('16','Tripura'),('17','Meghalaya'),('18','Assam'),
    ('19','West Bengal'),('20','Jharkhand'),('21','Odisha'),
    ('22','Chhattisgarh'),('23','Madhya Pradesh'),('24','Gujarat'),
    ('25','Daman & Diu'),('26','Dadra & Nagar Haveli'),('27','Maharashtra'),
    ('28','Andhra Pradesh'),('29','Karnataka'),('30','Goa'),
    ('31','Lakshadweep'),('32','Kerala'),('33','Tamil Nadu'),
    ('34','Puducherry'),('35','Andaman & Nicobar Islands'),
    ('36','Telangana'),('37','Andhra Pradesh (New)'),('38','Ladakh'),
    ('97','Other Territory'),('99','Centre Jurisdiction'),
]

@company_bp.route('/setup', methods=['GET','POST'])
@login_required
def setup():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Company name is required!', 'error')
            return render_template('company/setup.html', states=INDIAN_STATES)

        c = Company(
            name=name,
            legal_name=request.form.get('legal_name'),
            enable_gst='enable_gst' in request.form,
            gstin=request.form.get('gstin','').upper(),
            pan=request.form.get('pan','').upper(),
            address=request.form.get('address'),
            city=request.form.get('city'),
            state=request.form.get('state'),
            state_code=request.form.get('state_code'),
            pincode=request.form.get('pincode'),
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            website=request.form.get('website'),
            bank_name=request.form.get('bank_name'),
            bank_account=request.form.get('bank_account'),
            bank_ifsc=request.form.get('bank_ifsc'),
            bank_branch=request.form.get('bank_branch'),
            upi_id=request.form.get('upi_id',''),
            invoice_prefix=request.form.get('invoice_prefix','INV').upper(),
            invoice_start_number=int(request.form.get('invoice_start_number',1) or 1),
            financial_year_start=request.form.get('fy_start','04-01'),
            show_gst_summary='show_gst_summary' in request.form,
            gst_registration_type=request.form.get('gst_registration_type', 'Regular'),
            composition_rate=float(request.form.get('composition_rate', 0) or 0),
            show_invoice_qr='show_invoice_qr' in request.form,
            show_upi_qr='show_upi_qr' in request.form,
            is_locked='is_locked' in request.form,
            lock_date=datetime.strptime(request.form.get('lock_date'), '%Y-%m-%d').date() if request.form.get('lock_date') else None,
            current_fy=request.form.get('current_fy'),
            randomize_vouchers='randomize_vouchers' in request.form,
            print_layout=request.form.get('print_layout', 'A4'),
            invoice_copies=int(request.form.get('invoice_copies', 1)),
            auto_save_invoices='auto_save_invoices' in request.form,
            terms=request.form.get('terms'),
            voucher_performa=request.form.get('voucher_performa', 'modern'),
            custom_header_text=request.form.get('custom_header_text') if request.form.get('custom_header_text') != 'None' else None,
            custom_footer_text=request.form.get('custom_footer_text') if request.form.get('custom_footer_text') != 'None' else None,
            header_alignment=request.form.get('header_alignment', 'LEFT'),
            logo_placement=request.form.get('logo_placement', 'LEFT'),
            table_header_bg=request.form.get('table_header_bg', '#1a1a2e'),
            table_header_text_color=request.form.get('table_header_text_color', '#ffffff'),
            primary_color=request.form.get('primary_color', '#e94560'),
            a4_font_size=float(request.form.get('a4_font_size', 9.5) or 9.5),
            a5_font_size=float(request.form.get('a5_font_size', 8.0) or 8.0),
            thermal_font_size=float(request.form.get('thermal_font_size', 7.5) or 7.5),
            margin_top=float(request.form.get('margin_top', 10.0) or 10.0),
            margin_bottom=float(request.form.get('margin_bottom', 10.0) or 10.0),
            margin_left=float(request.form.get('margin_left', 10.0) or 10.0),
            margin_right=float(request.form.get('margin_right', 10.0) or 10.0),
            qr_placement=request.form.get('qr_placement', 'BOTTOM_CENTER'),
            block_order=request.form.get('block_order', 'header,hr,addresses,items,totals,gst,footer'),
            thermal_width=float(request.form.get('thermal_width', 80.0) or 80.0),
            custom_width=float(request.form.get('custom_width', 210.0) or 210.0),
            custom_height=float(request.form.get('custom_height', 297.0) or 297.0),
            paper_type=request.form.get('paper_type', 'Plain'),
        )
        db.session.add(c)
        db.session.commit()
        _handle_signature(c)
        _handle_logo(c)
        _handle_watermark(c)
        db.session.commit()
        _create_default_ledgers(c)
        session['company_id'] = c.id
        flash(f'Company "{c.name}" created successfully!', 'success')
        return redirect(url_for('dashboard.index'))
    return render_template('company/setup.html', states=INDIAN_STATES)

@company_bp.route('/list')
@login_required
def list_companies():
    companies = Company.query.filter_by(is_active=True).all()
    return render_template('company/list.html', companies=companies)

@company_bp.route('/select/<int:id>')
@login_required
def select(id):
    c = Company.query.get_or_404(id)
    session['company_id'] = c.id
    flash(f'Switched to company: {c.name}', 'success')
    return redirect(url_for('dashboard.index'))

@company_bp.route('/create', methods=['GET','POST'])
@login_required
def create():
    return setup()

@company_bp.route('/edit/<int:id>', methods=['GET','POST'])
@login_required
def edit(id):
    c = Company.query.get_or_404(id)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Company name is required!', 'error')
            return render_template('company/setup.html', edit_company=c, states=INDIAN_STATES, edit=True)

        c.name = name
        c.legal_name = request.form.get('legal_name')
        c.enable_gst = 'enable_gst' in request.form
        c.gstin = request.form.get('gstin','').upper()
        c.pan = request.form.get('pan','').upper()
        c.address = request.form.get('address')
        c.city = request.form.get('city')
        c.state = request.form.get('state')
        c.state_code = request.form.get('state_code')
        c.pincode = request.form.get('pincode')
        c.phone = request.form.get('phone')
        c.email = request.form.get('email')
        c.website = request.form.get('website')
        c.bank_name = request.form.get('bank_name')
        c.bank_account = request.form.get('bank_account')
        c.bank_ifsc = request.form.get('bank_ifsc')
        c.bank_branch = request.form.get('bank_branch')
        c.upi_id = request.form.get('upi_id','')
        c.invoice_prefix = request.form.get('invoice_prefix','INV').upper()
        c.invoice_start_number = int(request.form.get('invoice_start_number',1) or 1)
        c.show_gst_summary = 'show_gst_summary' in request.form
        c.gst_registration_type = request.form.get('gst_registration_type', 'Regular')
        c.composition_rate = float(request.form.get('composition_rate', 0) or 0)
        c.show_invoice_qr = 'show_invoice_qr' in request.form
        c.show_upi_qr = 'show_upi_qr' in request.form
        c.terms = request.form.get('terms')
        c.is_locked = 'is_locked' in request.form
        c.lock_date = datetime.strptime(request.form.get('lock_date'), '%Y-%m-%d').date() if request.form.get('lock_date') else None
        c.current_fy = request.form.get('current_fy')
        c.randomize_vouchers = 'randomize_vouchers' in request.form
        c.print_layout = request.form.get('print_layout', 'A4')
        c.invoice_copies = int(request.form.get('invoice_copies', 1))
        c.auto_save_invoices = 'auto_save_invoices' in request.form
        c.voucher_performa = request.form.get('voucher_performa', 'modern')
        c.custom_header_text = request.form.get('custom_header_text') if request.form.get('custom_header_text') != 'None' else None
        c.custom_footer_text = request.form.get('custom_footer_text') if request.form.get('custom_footer_text') != 'None' else None
        c.header_alignment = request.form.get('header_alignment', 'LEFT')
        c.logo_placement = request.form.get('logo_placement', 'LEFT')
        c.table_header_bg = request.form.get('table_header_bg', '#1a1a2e')
        c.table_header_text_color = request.form.get('table_header_text_color', '#ffffff')
        c.primary_color = request.form.get('primary_color', '#e94560')
        c.a4_font_size = float(request.form.get('a4_font_size', 9.5) or 9.5)
        c.a5_font_size = float(request.form.get('a5_font_size', 8.0) or 8.0)
        c.thermal_font_size = float(request.form.get('thermal_font_size', 7.5) or 7.5)
        c.margin_top = float(request.form.get('margin_top', 10.0) or 10.0)
        c.margin_bottom = float(request.form.get('margin_bottom', 10.0) or 10.0)
        c.margin_left = float(request.form.get('margin_left', 10.0) or 10.0)
        c.margin_right = float(request.form.get('margin_right', 10.0) or 10.0)
        c.qr_placement = request.form.get('qr_placement', 'BOTTOM_CENTER')
        c.block_order = request.form.get('block_order', 'header,hr,addresses,items,totals,gst,footer')
        c.thermal_width = float(request.form.get('thermal_width', 80.0) or 80.0)
        c.custom_width = float(request.form.get('custom_width', 210.0) or 210.0)
        c.custom_height = float(request.form.get('custom_height', 297.0) or 297.0)
        c.paper_type = request.form.get('paper_type', 'Plain')
        _handle_signature(c)
        _handle_logo(c)
        _handle_watermark(c)
        db.session.commit()
        flash('Company updated!', 'success')
        return redirect(url_for('company.list_companies'))
    return render_template('company/setup.html', edit_company=c, states=INDIAN_STATES, edit=True)

@company_bp.route('/manage/<int:id>')
@login_required
def manage(id):
    c = Company.query.get_or_404(id)
    all_cos = Company.query.filter(Company.id != id, Company.is_active == True).all()
    return render_template('company/manage.html', company=c, other_companies=all_cos)

@company_bp.route('/merge', methods=['POST'])
@login_required
def merge():
    source_id = request.form.get('source_id')
    target_id = request.form.get('target_id')
    if not source_id or not target_id:
        flash('Invalid merge request', 'error')
        return redirect(url_for('company.list_companies'))
    
    # Placeholder for merge logic
    flash('Merge feature is currently under development.', 'info')
    return redirect(url_for('company.manage', id=target_id))

@company_bp.route('/delete/<int:id>')
@login_required
def delete(id):
    c = Company.query.get_or_404(id)
    c.is_active = False
    db.session.commit()
    flash('Company deleted', 'success')
    return redirect(url_for('company.list_companies'))

@company_bp.route('/archive/<int:id>')
@login_required
def archive(id):
    import zipfile
    from flask import send_file
    from app import db
    
    c = Company.query.get_or_404(id)
    fy_str = c.display_fy.replace('/', '-')
    archive_name = f"{c.name.replace(' ', '_')}_Archive_FY_{fy_str}"
    
    # Path to database
    db_uri = db.engine.url.database
    # For SQLite, it might be a relative or absolute path
    db_path = db_uri
    if not os.path.isabs(db_path):
        # Try to resolve relative to app root
        db_path = os.path.abspath(db_path)

    temp_dir = 'app/static/temp'
    os.makedirs(temp_dir, exist_ok=True)
    zip_path = os.path.join(temp_dir, f"{archive_name}.zip")
    
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # 1. Add database
            if os.path.exists(db_path):
                zf.write(db_path, 'database.db')
            
            # 2. Add Readme / Meta
            info = [
                f"GST BILLING ARCHIVE",
                f"===================",
                f"Company: {c.name}",
                f"Financial Year: {c.display_fy}",
                f"Export Date: {datetime.now().strftime('%d-%m-%Y %H:%M')}",
                f"Status: Read-Only Backup",
                f"",
                f"Instructions:",
                f"This archive contains the database file for the specified FY.",
                f"To view this data, you can point a fresh installation of the app",
                f"to this 'database.db' file."
            ]
            zf.writestr('Archive_Info.txt', "\n".join(info))
            
            # 3. Add static uploads (optional but good for logos/sigs)
            upload_dir = 'app/static/uploads'
            if os.path.exists(upload_dir):
                for root, dirs, files in os.walk(upload_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # Relative path inside zip
                        rel_path = os.path.relpath(file_path, 'app/static')
                        zf.write(file_path, rel_path)

        return send_file(os.path.abspath(zip_path), as_attachment=True, download_name=f"{archive_name}.zip")
    except Exception as e:
        flash(f'Error creating archive: {str(e)}', 'error')
        return redirect(url_for('company.edit', id=id))

def _handle_signature(company):
    # Handle File Upload
    file = request.files.get('signature_file')
    if file and file.filename:
        filename = f"sig_{company.id}_{int(datetime.now().timestamp())}.png"
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(app_dir, 'static', 'uploads', 'signatures', filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        file.save(path)
        company.signature_path = f"uploads/signatures/{filename}"
    
    # Handle Drawn Signature (Base64)
    sig_data = request.form.get('signature_data')
    if sig_data and sig_data.startswith('data:image/png;base64,'):
        filename = f"sig_drawn_{company.id}_{int(datetime.now().timestamp())}.png"
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(app_dir, 'static', 'uploads', 'signatures', filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(sig_data.split(',')[1]))
        company.signature_path = f"uploads/signatures/{filename}"

def _handle_logo(company):
    # Handle Logo Upload
    file = request.files.get('logo_file')
    if file and file.filename:
        filename = f"logo_{company.id}_{int(datetime.now().timestamp())}.png"
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(app_dir, 'static', 'uploads', 'logos', filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        file.save(path)
        company.logo_path = f"uploads/logos/{filename}"

def _handle_watermark(company):
    # Handle Watermark Upload
    file = request.files.get('watermark_file')
    if file and file.filename:
        filename = f"watermark_{company.id}_{int(datetime.now().timestamp())}.png"
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(app_dir, 'static', 'uploads', 'watermarks', filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        file.save(path)
        company.watermark_path = f"uploads/watermarks/{filename}"

def _create_default_ledgers(company):
    groups = {g.name: g for g in LedgerGroup.query.all()}
    defaults = [
        Ledger(name='Cash', group_id=groups.get('Cash-in-Hand').id if groups.get('Cash-in-Hand') else None, company_id=company.id),
        Ledger(name='Bank Account', group_id=groups.get('Bank Accounts').id if groups.get('Bank Accounts') else None, company_id=company.id),
        Ledger(name='Sales', group_id=groups.get('Sales Accounts').id if groups.get('Sales Accounts') else None, company_id=company.id),
        Ledger(name='Purchase', group_id=groups.get('Purchase Accounts').id if groups.get('Purchase Accounts') else None, company_id=company.id),
        Ledger(name='CGST Payable', group_id=groups.get('Duties & Taxes').id if groups.get('Duties & Taxes') else None, company_id=company.id),
        Ledger(name='SGST Payable', group_id=groups.get('Duties & Taxes').id if groups.get('Duties & Taxes') else None, company_id=company.id),
        Ledger(name='IGST Payable', group_id=groups.get('Duties & Taxes').id if groups.get('Duties & Taxes') else None, company_id=company.id),
        Ledger(name='CGST Input', group_id=groups.get('Current Assets').id if groups.get('Current Assets') else None, company_id=company.id),
        Ledger(name='SGST Input', group_id=groups.get('Current Assets').id if groups.get('Current Assets') else None, company_id=company.id),
        Ledger(name='IGST Input', group_id=groups.get('Current Assets').id if groups.get('Current Assets') else None, company_id=company.id),
        Ledger(name='Discount Allowed', group_id=groups.get('Indirect Expenses').id if groups.get('Indirect Expenses') else None, company_id=company.id),
        Ledger(name='Discount Received', group_id=groups.get('Indirect Income').id if groups.get('Indirect Income') else None, company_id=company.id),
        Ledger(name='Round Off', group_id=groups.get('Indirect Expenses').id if groups.get('Indirect Expenses') else None, company_id=company.id),
    ]
    db.session.add_all(defaults)
    db.session.commit()
