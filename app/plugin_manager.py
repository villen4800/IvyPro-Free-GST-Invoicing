import os
import importlib
import json
import sys
from flask import Blueprint, current_app

class PluginManager:
    def __init__(self, app=None):
        self.plugins = {}
        if app:
            self.init_app(app)

    def init_app(self, app):
        self.app = app
        self.plugin_dir = os.path.join(app.root_path, '..', 'plugins')
        if not os.path.exists(self.plugin_dir):
            os.makedirs(self.plugin_dir)
        
        self.load_plugins()

    def load_plugins(self):
        """Discovers and loads enabled plugins."""
        if not os.path.exists(self.plugin_dir):
            return

        for plugin_name in os.listdir(self.plugin_dir):
            plugin_path = os.path.join(self.plugin_dir, plugin_name)
            if os.path.isdir(plugin_path):
                manifest_path = os.path.join(plugin_path, 'manifest.json')
                if os.path.exists(manifest_path):
                    try:
                        with open(manifest_path, 'r') as f:
                            manifest = json.load(f)
                        
                        if manifest.get('enabled', True):
                            self.register_plugin(plugin_name, manifest)
                    except Exception as e:
                        print(f"Error loading plugin {plugin_name}: {e}")

    def register_plugin_by_name(self, plugin_name):
        """Discovers and registers a specific plugin by its name."""
        plugin_path = os.path.join(self.plugin_dir, plugin_name)
        if os.path.isdir(plugin_path):
            manifest_path = os.path.join(plugin_path, 'manifest.json')
            if os.path.exists(manifest_path):
                with open(manifest_path, 'r') as f:
                    manifest = json.load(f)
                if manifest.get('enabled', True):
                    self.register_plugin(plugin_name, manifest)
                    return True
        return False

    def register_plugin(self, plugin_name, manifest):
        """Registers a plugin's blueprint and other features."""
        try:
            # Dynamically import the plugin's package
            module_name = f"plugins.{plugin_name}"
            
            if module_name in sys.modules:
                importlib.reload(sys.modules[module_name])
            
            module = importlib.import_module(module_name)
            
            if hasattr(module, 'setup_plugin'):
                try:
                    module.setup_plugin(self.app)
                    self.plugins[plugin_name] = manifest
                    print(f"Plugin {plugin_name} registered successfully.")
                except AssertionError as e:
                    if "can no longer be called" in str(e):
                        # Mark as partially loaded (manifest exists, but routes pending)
                        self.plugins[plugin_name] = manifest
                        print(f"Plugin {plugin_name} loaded, but routing requires restart.")
                        return "restart_required"
                    raise e
            
            return True
        except Exception as e:
            print(f"Failed to register plugin {plugin_name}: {e}")
            return False

    def get_plugins(self):
        """Returns a list of all plugins and their status."""
        all_plugins = []
        if not os.path.exists(self.plugin_dir):
            return []
            
        for plugin_name in os.listdir(self.plugin_dir):
            plugin_path = os.path.join(self.plugin_dir, plugin_name)
            if os.path.isdir(plugin_path):
                manifest_path = os.path.join(plugin_path, 'manifest.json')
                if os.path.exists(manifest_path):
                    with open(manifest_path, 'r') as f:
                        manifest = json.load(f)
                    manifest['id'] = plugin_name
                    all_plugins.append(manifest)
        return all_plugins

    def is_enabled(self, plugin_name):
        """Checks if a plugin is currently enabled by reading its manifest."""
        plugin_path = os.path.join(self.plugin_dir, plugin_name)
        manifest_path = os.path.join(plugin_path, 'manifest.json')
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, 'r') as f:
                    manifest = json.load(f)
                return manifest.get('enabled', True)
            except:
                return False
        return False

plugin_manager = PluginManager()
