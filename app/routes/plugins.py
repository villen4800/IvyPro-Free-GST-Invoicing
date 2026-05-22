from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required
import os
import zipfile
import shutil
import json
from app.plugin_manager import plugin_manager

plugins_bp = Blueprint('plugins', __name__)

@plugins_bp.route('/')
@login_required
def index():
    plugins = plugin_manager.get_plugins()
    return render_template('plugins/index.html', plugins=plugins, current_app=current_app)

@plugins_bp.route('/upload', methods=['POST'])
@login_required
def upload():
    if 'plugin_file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('plugins.index'))
    
    file = request.files['plugin_file']
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('plugins.index'))
    
    if file and file.filename.endswith('.zip'):
        plugin_dir = os.path.join(current_app.root_path, '..', 'plugins')
        os.makedirs(plugin_dir, exist_ok=True)
        
        # Save temp zip
        zip_path = os.path.join(plugin_dir, file.filename)
        file.save(zip_path)
        
        try:
            temp_extract_path = os.path.join(plugin_dir, "_temp_ext")
            os.makedirs(temp_extract_path, exist_ok=True)
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_extract_path)
            
            # Find where manifest.json is
            manifest_loc = None
            for root, dirs, files in os.walk(temp_extract_path):
                if 'manifest.json' in files:
                    manifest_loc = root
                    break
            
            if manifest_loc:
                # Get the folder name containing manifest.json
                plugin_name = os.path.basename(manifest_loc)
                if plugin_name == "_temp_ext": # Files were in root of zip
                    plugin_name = file.filename.rsplit('.', 1)[0]
                
                final_path = os.path.join(plugin_dir, plugin_name)
                if os.path.exists(final_path):
                    shutil.rmtree(final_path)
                
                shutil.move(manifest_loc, final_path)
                result = plugin_manager.register_plugin_by_name(plugin_name)
                if result == "restart_required":
                    flash(f'Plugin {plugin_name} installed, but a RESTART is required to activate its pages.', 'info')
                else:
                    flash(f'Plugin {plugin_name} installed successfully and activated!', 'success')
            else:
                flash('Invalid plugin: manifest.json not found in ZIP.', 'error')
            
            # Cleanup temp
            if os.path.exists(temp_extract_path):
                try:
                    shutil.rmtree(temp_extract_path)
                except:
                    pass
                
        except Exception as e:
            flash(f'Error installing plugin: {str(e)}', 'error')
        finally:
            file.close() # Ensure handle is released
            if os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                except Exception:
                    # On Windows, sometimes the file is still locked by the OS
                    pass
    else:
        flash('Invalid file type. Please upload a .zip file.', 'error')
        
    return redirect(url_for('plugins.index'))

@plugins_bp.route('/toggle/<plugin_id>')
@login_required
def toggle(plugin_id):
    plugin_dir = os.path.join(current_app.root_path, '..', 'plugins', plugin_id)
    manifest_path = os.path.join(plugin_dir, 'manifest.json')
    
    if os.path.exists(manifest_path):
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
        
        manifest['enabled'] = not manifest.get('enabled', True)
        
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=4)
            
        status = "enabled" if manifest['enabled'] else "disabled"
        flash(f'Plugin {plugin_id} {status}. Restart may be required.', 'success')
    else:
        flash('Plugin not found.', 'error')
        
    return redirect(url_for('plugins.index'))

@plugins_bp.route('/delete/<plugin_id>')
@login_required
def delete(plugin_id):
    plugin_dir = os.path.join(current_app.root_path, '..', 'plugins', plugin_id)
    if os.path.exists(plugin_dir):
        shutil.rmtree(plugin_dir)
        flash(f'Plugin {plugin_id} deleted successfully.', 'success')
    else:
        flash('Plugin not found.', 'error')
    return redirect(url_for('plugins.index'))
