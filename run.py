"""
Ivy Accountancy - Indian GST Billing & Accounting Software
Supports: Standalone EXE (desktop), Flask web server, LAN hosting
"""
import os
import sys
import threading
import time
import webbrowser
import argparse
import logging
import logging.handlers
import io

# Fix for Windows console encoding issues with box-drawing characters
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, io.UnsupportedOperation):
        pass

# ─── Path resolution for both source and frozen EXE ──────
if getattr(sys, 'frozen', False):
    # Running as PyInstaller EXE
    BASE_DIR = os.path.dirname(sys.executable)
    # Make bundled packages importable
    sys.path.insert(0, sys._MEIPASS)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, BASE_DIR)

# ─── Ensure data / backup dirs exist ─────────────────────
DATA_DIR    = os.path.join(BASE_DIR, 'data')
BACKUP_DIR  = os.path.join(BASE_DIR, 'backups')
EXPORT_DIR  = os.path.join(BASE_DIR, 'exports')
for d in (DATA_DIR, BACKUP_DIR, EXPORT_DIR):
    os.makedirs(d, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, 'gst_billing.db')

# ─── Logging setup ───────────────────────────────────────
LOG_PATH = os.path.join(DATA_DIR, 'tally_sync.log')

def setup_logging(level=logging.DEBUG):
    """Configure root logger: rotating file + console.
    Log file: data/tally_sync.log  (10 MB × 5 backups)
    """
    fmt = logging.Formatter(
        '%(asctime)s  %(levelname)-8s  %(name)s — %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # ── Rotating file handler (always DEBUG) ──────────────
    fh = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=10 * 1024 * 1024, backupCount=5,
        encoding='utf-8'
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # ── Console handler ───────────────────────────────────
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    root.addHandler(ch)

    # Quiet noisy third-party loggers
    for noisy in ('werkzeug', 'urllib3', 'sqlalchemy.engine', 'PIL', 'reportlab'):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.info('='*60)
    logging.info('Ivy Accountancy starting — log file: %s', LOG_PATH)
    logging.info('='*60)

setup_logging()   # initialise as early as possible

# ─── App factory ─────────────────────────────────────────
def get_app():
    from app import create_app
    app = create_app(db_path=DB_PATH)
    app.config['BASE_DIR']   = BASE_DIR
    app.config['DATA_DIR']   = DATA_DIR
    app.config['BACKUP_DIR'] = BACKUP_DIR
    return app

def open_browser(port, delay=1.5):
    """Wait for server to start, then open browser."""
    time.sleep(delay)
    webbrowser.open(f'http://127.0.0.1:{port}')

# ─── Server mode ─────────────────────────────────────────
def run_server(host='127.0.0.1', port=5000, debug=False, auto_browser=False):
    app = get_app()
    banner = f"""
╔══════════════════════════════════════════════════════╗
║       Ivy Accountancy - Indian Accounting Software   ║
╠══════════════════════════════════════════════════════╣
║  URL   :  http://{host}:{port:<5}                    ║
║  Login :  admin / admin123                           ║
║  Data  :  {DATA_DIR[:40]:<40}  ║
║                                                      ║
║  Press Ctrl+C to stop                                ║
╚══════════════════════════════════════════════════════╝"""
    print(banner)
    if auto_browser and host in ('127.0.0.1', 'localhost'):
        threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    app.run(host=host, port=port, debug=debug, use_reloader=False)

# ─── Desktop mode (tkinter launcher) ────────────────────
def run_desktop(auto_browser=False):
    port = _find_free_port()
    app  = get_app()

    # Start Flask in background thread
    flask_thread = threading.Thread(
        target=lambda: app.run(host='127.0.0.1', port=port,
                               debug=False, use_reloader=False),
        daemon=True
    )
    flask_thread.start()

    is_frozen = getattr(sys, 'frozen', False)

    if is_frozen:
        try:
            import webview
            import urllib.request
            import tkinter as tk

            # ── Splash window ─────────────────────────────────────────
            root = tk.Tk()
            root.overrideredirect(True)          # no title bar
            root.attributes('-topmost', True)
            root.configure(bg='#0f1117')

            SW, SH = root.winfo_screenwidth(), root.winfo_screenheight()

            # Try to load the branded splash image
            _splash_photo = None
            try:
                from PIL import Image, ImageTk
                _sp = os.path.join(sys._MEIPASS, 'splash.png')
                img = Image.open(_sp)
                W, H = 760, 368
                img = img.resize((W, H), Image.LANCZOS)
                _splash_photo = ImageTk.PhotoImage(img)
                root.geometry(f'{W}x{H}+{(SW-W)//2}+{(SH-H)//2}')
                tk.Label(root, image=_splash_photo, bd=0,
                         bg='#0f1117').pack()
            except Exception:
                # Fallback branded splash
                W, H = 540, 260
                root.geometry(f'{W}x{H}+{(SW-W)//2}+{(SH-H)//2}')
                try:
                    from PIL import Image, ImageDraw, ImageTk
                    ico = Image.new('RGBA', (64, 64), (0,0,0,0))
                    d   = ImageDraw.Draw(ico)
                    d.rounded_rectangle([0,0,63,63], radius=12, fill='#E8580C')
                    d.polygon([(32,12),(56,52),(8,52)], fill='white')
                    _ico_ph = ImageTk.PhotoImage(ico)
                    tk.Label(root, image=_ico_ph, bg='#0f1117').pack(pady=(30,0))
                    root._ico_ref = _ico_ph
                except Exception:
                    pass
                tk.Label(root, text='IVY PRO', bg='#0f1117', fg='#E8580C',
                         font=('Segoe UI', 30, 'bold')).pack(pady=(10, 0))
                tk.Label(root, text='Indian GST Accounting Software',
                         bg='#0f1117', fg='#8b8fac',
                         font=('Segoe UI', 11)).pack()

            _status = tk.StringVar(value='Starting…')
            tk.Label(root, textvariable=_status, bg='#0f1117', fg='#6c63ff',
                     font=('Segoe UI', 9)).pack(side='bottom', pady=10)
            root.update()

            # ── Poll Flask readiness, then hand off to webview ────────
            _tries = [0]
            def _check():
                _tries[0] += 1
                _status.set(f'Loading IvyPro… ({_tries[0] * 200 // 1000}s)')
                try:
                    urllib.request.urlopen(
                        f'http://127.0.0.1:{port}/login', timeout=0.5)
                    _status.set('Ready!')
                    root.after(300, root.destroy)   # brief "Ready" flash
                except Exception:
                    if _tries[0] < 150:             # max 30 s
                        root.after(200, _check)
                    else:
                        root.destroy()              # timeout

            root.after(200, _check)
            root.mainloop()                         # blocks until splash destroyed

            # ── Webview (runs after splash closes) ────────────────────
            webview.create_window(
                'Ivy Accountancy',
                f'http://127.0.0.1:{port}',
                width=1280, height=800,
                confirm_close=True, maximized=True
            )
            webview.start()
            os._exit(0)

        except Exception as e:
            print(f"Webview failed: {e}")
            open_browser(port, delay=2.0)
            flask_thread.join()

    else:
        print(f"Ivy Accountancy starting at http://127.0.0.1:{port}")
        if auto_browser:
            open_browser(port, delay=2.0)
        flask_thread.join()

def _find_free_port(default=5000):
    import socket
    for port in range(default, default + 20):
        try:
            s = socket.socket()
            s.bind(('127.0.0.1', port))
            s.close()
            return port
        except OSError:
            continue
    return default



# ─── Entry point ──────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Ivy Accountancy - Indian GST Billing & Accounting Software',
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '--server', action='store_true',
        help='Run as headless Flask web server (no desktop window)'
    )
    parser.add_argument(
        '--host', default='127.0.0.1',
        help='Bind host (default: 127.0.0.1)\nUse 0.0.0.0 to allow LAN/internet access'
    )
    parser.add_argument(
        '--port', type=int, default=5000,
        help='Port number (default: 5000)'
    )
    parser.add_argument(
        '--debug', action='store_true',
        help='Enable Flask debug mode (development only)'
    )
    parser.add_argument(
        '--no-browser', action='store_true',
        help='Do not automatically open browser'
    )
    parser.add_argument(
        '--browser', action='store_true',
        help='Force open browser even in server mode'
    )
    args = parser.parse_args()

    if args.server:
        run_server(
            host=args.host,
            port=args.port,
            debug=args.debug,
            auto_browser=args.browser and not args.no_browser
        )
    else:
        run_desktop(auto_browser=args.browser and not args.no_browser)
