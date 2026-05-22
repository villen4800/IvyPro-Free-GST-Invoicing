from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from app.models import User, Company, ActivityLog, PERMISSION_KEYS
from app import db
from app.plugin_manager import plugin_manager
import json
import os

auth_bp = Blueprint('auth', __name__)
PERMISSION_LABELS = {
    'dashboard': 'Dashboard',
    'vouchers': 'Vouchers & Invoices',
    'ledger': 'Ledgers',
    'inventory': 'Inventory',
    'reports': 'Reports',
    'gst': 'GST Returns',
    'whatsapp': 'WhatsApp',
    'import_export': 'Import / Export',
    'company': 'Companies',
    'settings': 'Settings',
    'users': 'User Management',
    'service_job': 'Service Job / Repairs',
    'attendance': 'Attendance System',
}

def _log(action, feature='users', detail=''):
    db.session.add(ActivityLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        username=current_user.username if current_user.is_authenticated else None,
        action=action,
        feature=feature,
        detail=detail,
        ip_address=request.remote_addr
    ))

def _save_photo(file):
    if not file or not file.filename:
        return None
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
        return None
    folder = os.path.join(current_app.static_folder, 'uploads', 'users')
    os.makedirs(folder, exist_ok=True)
    name = secure_filename(file.filename)
    filename = f"user_{int(__import__('time').time())}_{name}"
    file.save(os.path.join(folder, filename))
    return f"uploads/users/{filename}"

@auth_bp.route('/', methods=['GET'])
def root():
    if not User.query.first():
        return redirect(url_for('auth.first_setup'))
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    return redirect(url_for('auth.login'))

@auth_bp.route('/setup', methods=['GET', 'POST'])
def first_setup():
    if User.query.first():
        return redirect(url_for('auth.login'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        full_name = request.form.get('full_name', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if not username or len(password) < 6:
            flash('Username and a 6 character password are required.', 'error')
        elif password != confirm:
            flash('Passwords do not match.', 'error')
        else:
            user = User(
                username=username,
                full_name=full_name or username,
                password=generate_password_hash(password),
                role='admin',
                permissions=json.dumps(PERMISSION_KEYS),
                can_edit=True,
                can_delete=True,
                is_active=True,
            )
            photo = _save_photo(request.files.get('photo'))
            if photo:
                user.photo_path = photo
            db.session.add(user)
            db.session.commit()
            login_user(user, remember=True)
            flash('Welcome to Ivy Accountancy. Create your company to continue.', 'success')
            return redirect(url_for('company.setup'), 303)
    return render_template('auth/setup.html')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if not User.query.first():
        return redirect(url_for('auth.first_setup'))
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()

        if user and getattr(user, 'is_active', True) and check_password_hash(user.password, password):
            login_user(user, remember=True)
            db.session.add(ActivityLog(user_id=user.id, username=user.username, action='login',
                                       feature='auth', detail='Signed in', ip_address=request.remote_addr))
            db.session.commit()
            # Pick active company
            company = Company.query.filter_by(is_active=True).first()
            if not company:
                # Use 303 to guarantee GET on redirect
                return redirect(url_for('company.setup'), 303)
            session['company_id'] = company.id
            next_url = request.args.get('next')
            target = next_url if next_url and next_url.startswith('/') else url_for('dashboard.index')
            return redirect(target, 303)

        flash('Invalid username or password', 'error')

    return render_template('auth/login.html')

@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    """Robust logout that clears everything regardless of current state."""
    if current_user.is_authenticated:
        try:
            _log('logout', 'auth', 'Signed out')
            db.session.commit()
        except:
            db.session.rollback()
        logout_user()
    session.clear()
    response = redirect(url_for('auth.login'), 303)
    response.set_cookie(current_app.config.get('REMEMBER_COOKIE_NAME', 'remember_token'), '', expires=0)
    response.set_cookie(current_app.config.get('SESSION_COOKIE_NAME', 'session'), '', expires=0)
    return response

@auth_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    old_pw = request.form.get('old_password', '')
    new_pw = request.form.get('new_password', '')
    if not new_pw or len(new_pw) < 4:
        flash('New password must be at least 4 characters', 'error')
    elif check_password_hash(current_user.password, old_pw):
        current_user.password = generate_password_hash(new_pw)
        _log('change_password', 'settings', 'Changed own password')
        db.session.commit()
        flash('Password changed successfully', 'success')
    else:
        flash('Current password is incorrect', 'error')
    return redirect(url_for('dashboard.settings'), 303)

def _admin_required():
    if current_user.role != 'admin' and not current_user.can_access('users'):
        flash('Only admins can manage users.', 'error')
        return False
    return True

@auth_bp.route('/users')
@login_required
def users():
    if not _admin_required():
        return redirect(url_for('dashboard.index'))
    users_list = User.query.order_by(User.role, User.username).all()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    
    # Using explicit db.paginate for compatibility with Flask-SQLAlchemy 3.x
    audit_pagination = db.paginate(
        db.select(ActivityLog).order_by(ActivityLog.created_at.desc()),
        page=page, 
        per_page=per_page,
        error_out=False
    )
    
    active_keys = []
    for k in PERMISSION_KEYS:
        if k in ['service_job', 'attendance', 'tally_sync']:
            if plugin_manager.is_enabled(k):
                active_keys.append(k)
        else:
            active_keys.append(k)
            
    return render_template('auth/users.html', 
                           users=users_list, 
                           audit_pagination=audit_pagination,
                           logs=audit_pagination.items,
                           companies=Company.query.filter_by(is_active=True).all(),
                           permission_keys=active_keys, 
                           permission_labels=PERMISSION_LABELS)



@auth_bp.route('/users/create', methods=['POST'])
@login_required
def create_user():
    if not _admin_required():
        return redirect(url_for('dashboard.index'))
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    if not username or len(password) < 6:
        flash('Username and a 6 character password are required.', 'error')
        return redirect(url_for('auth.users'))
    if User.query.filter_by(username=username).first():
        flash('Username already exists.', 'error')
        return redirect(url_for('auth.users'))
    role = request.form.get('role', 'staff')
    user = User(
        username=username,
        full_name=request.form.get('full_name', '').strip() or username,
        password=generate_password_hash(password),
        role='admin' if role == 'admin' else 'staff',
        permissions=json.dumps(request.form.getlist('permissions')),
        allowed_companies=json.dumps(request.form.getlist('allowed_companies')),
        can_edit=bool(request.form.get('can_edit')),
        can_delete=bool(request.form.get('can_delete')),
        is_active=bool(request.form.get('is_active', 'on')),
    )
    photo = _save_photo(request.files.get('photo'))
    if photo:
        user.photo_path = photo
    if user.role == 'admin':
        user.permissions = json.dumps(PERMISSION_KEYS)
        user.can_edit = True
        user.can_delete = True
    db.session.add(user)
    _log('create_user', 'users', username)
    db.session.commit()
    flash('User created.', 'success')
    return redirect(url_for('auth.users'))

@auth_bp.route('/users/<int:id>/update', methods=['POST'])
@login_required
def update_user(id):
    if not _admin_required():
        return redirect(url_for('dashboard.index'))
    user = User.query.get_or_404(id)
    user.full_name = request.form.get('full_name', '').strip() or user.username
    role = request.form.get('role', user.role)
    user.role = 'admin' if role == 'admin' else 'staff'
    user.is_active = bool(request.form.get('is_active'))
    user.can_edit = bool(request.form.get('can_edit'))
    user.can_delete = bool(request.form.get('can_delete'))
    user.permissions = json.dumps(request.form.getlist('permissions'))
    user.allowed_companies = json.dumps(request.form.getlist('allowed_companies'))
    if user.role == 'admin':
        user.permissions = json.dumps(PERMISSION_KEYS)
        user.can_edit = True
        user.can_delete = True
    new_password = request.form.get('new_password', '')
    if new_password:
        if len(new_password) < 6:
            flash('New password must be at least 6 characters.', 'error')
            return redirect(url_for('auth.users'))
        user.password = generate_password_hash(new_password)
    photo = _save_photo(request.files.get('photo'))
    if photo:
        user.photo_path = photo
    _log('update_user', 'users', user.username)
    db.session.commit()
    flash('User updated.', 'success')
    return redirect(url_for('auth.users'))

@auth_bp.route('/users/<int:id>/delete')
@login_required
def delete_user(id):
    if not _admin_required():
        return redirect(url_for('dashboard.index'))
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'error')
    elif User.query.filter_by(role='admin', is_active=True).count() <= 1 and user.role == 'admin':
        flash('At least one active admin is required.', 'error')
    else:
        _log('delete_user', 'users', user.username)
        db.session.delete(user)
        db.session.commit()
        flash('User deleted.', 'success')
    return redirect(url_for('auth.users'))

@auth_bp.route('/save-preferences', methods=['POST'])
@login_required
def save_preferences():
    data = request.get_json()
    if not data:
        return {'success': False}, 400
    
    theme = data.get('theme')
    accent_color = data.get('accent_color')
    keyboard_layout = data.get('keyboard_layout')
    
    if theme:
        current_user.theme = theme
    if accent_color:
        current_user.accent_color = accent_color
    if keyboard_layout:
        current_user.keyboard_layout = keyboard_layout
    
    db.session.commit()
    return {'success': True}
