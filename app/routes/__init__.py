def register_blueprints(app):
    from app.routes.auth         import auth_bp
    from app.routes.dashboard    import dashboard_bp
    from app.routes.company      import company_bp
    from app.routes.ledger       import ledger_bp
    from app.routes.inventory    import inventory_bp
    from app.routes.vouchers     import vouchers_bp
    from app.routes.reports      import reports_bp
    from app.routes.gst          import gst_bp
    from app.routes.import_export import import_export_bp
    from app.routes.plugins       import plugins_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(company_bp,      url_prefix='/company')
    app.register_blueprint(ledger_bp,       url_prefix='/ledger')
    app.register_blueprint(inventory_bp,    url_prefix='/inventory')
    app.register_blueprint(vouchers_bp,     url_prefix='/voucher')
    app.register_blueprint(reports_bp,      url_prefix='/reports')
    app.register_blueprint(gst_bp,          url_prefix='/gst')
    app.register_blueprint(import_export_bp,url_prefix='/import-export')
    app.register_blueprint(plugins_bp,      url_prefix='/plugins')
