"""
IvyPro V1 - Server Launcher GUI
A premium system-tray + control-panel launcher for the IvyPro Flask server.
"""

import os
import sys
import json
import socket
import threading
import time
import subprocess
import webbrowser
import winreg
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont

# ── Fix Windows taskbar icon BEFORE any Tk window is created ──
try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('IvyPro.Launcher.1.0')
except Exception:
    pass

# ─── Path resolution ─────────────────────────────────────
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
    _RES_DIR = sys._MEIPASS          # bundled files live here
    sys.path.insert(0, _RES_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    _RES_DIR = BASE_DIR

def res(filename):
    """Return path to a bundled resource (works frozen + unfrozen)."""
    return os.path.join(_RES_DIR, filename)

DATA_DIR    = os.path.join(BASE_DIR, 'data')
CONFIG_FILE = os.path.join(DATA_DIR, 'launcher_config.json')
os.makedirs(DATA_DIR, exist_ok=True)

# ─── Config helpers ───────────────────────────────────────
DEFAULT_CONFIG = {
    "port": 5000,
    "auto_start_server": False,
    "auto_open_browser": False,
    "startup_with_windows": False,
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
            # merge with defaults so new keys are never missing
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)

# ─── Windows startup registry ─────────────────────────────
APP_NAME = "IvyProV1Launcher"
RUN_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"

def get_exe_path():
    """Return the path to this launcher executable."""
    if getattr(sys, 'frozen', False):
        return sys.executable
    return os.path.abspath(__file__)

def set_startup(enabled: bool):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
        if enabled:
            exe = get_exe_path()
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe}"')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        messagebox.showerror("Registry Error", f"Could not update startup entry:\n{e}")
        return False

def is_startup_enabled():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False

# ─── Port / server helpers ────────────────────────────────
def is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) != 0

def wait_for_server(port: int, timeout=20) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.3)
    return False

# ─── Main Launcher GUI ────────────────────────────────────
class IvyLauncherApp(tk.Tk):

    # Colour palette
    BG        = "#0f1117"
    CARD      = "#1a1d27"
    BORDER    = "#2a2d3e"
    ACCENT    = "#6c63ff"
    ACCENT2   = "#4ecdc4"
    SUCCESS   = "#43e97b"
    WARNING   = "#f8b739"
    DANGER    = "#f64747"
    TEXT      = "#e8eaf6"
    SUBTEXT   = "#8b8fac"

    def __init__(self):
        super().__init__()
        self.cfg          = load_config()
        self._server_proc = None
        self._server_port = None
        self._status_after = None

        self._setup_window()
        self._load_fonts()
        self._build_ui()
        self._refresh_startup_toggle()

        # Sync startup registry with saved config on launch
        set_startup(self.cfg["startup_with_windows"])

        if self.cfg.get("auto_start_server"):
            self.after(500, self._start_server)

    # ── Window setup ──────────────────────────────────────
    def _setup_window(self):
        self.title("IvyPro Launcher")
        self.resizable(False, False)
        self.configure(bg=self.BG)
        w, h = 540, 680
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x  = (sw - w) // 2
        y  = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        # ── Draw branded icon with PIL (no external file needed) ────────
        try:
            from PIL import Image, ImageDraw, ImageTk
            def _make_icon(size):
                img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
                d = ImageDraw.Draw(img)
                r = max(2, size // 6)
                d.rounded_rectangle([0, 0, size-1, size-1], radius=r, fill='#E8580C')
                m = size // 8
                cx = size // 2
                d.polygon([(cx, m*2), (size-m*2, size-m*2), (m*2, size-m*2)], fill='white')
                return img
            imgs = [ImageTk.PhotoImage(_make_icon(s)) for s in (16, 24, 32, 48)]
            self._icon_imgs = imgs          # keep references alive!
            self.iconphoto(True, *imgs)
        except Exception:
            pass
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _load_fonts(self):
        self.font_title  = tkfont.Font(family="Segoe UI", size=22, weight="bold")
        self.font_sub    = tkfont.Font(family="Segoe UI", size=10)
        self.font_label  = tkfont.Font(family="Segoe UI", size=11)
        self.font_btn    = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self.font_mono   = tkfont.Font(family="Consolas",  size=10)
        self.font_status = tkfont.Font(family="Segoe UI",  size=9)

    # ── UI construction ───────────────────────────────────
    def _build_ui(self):
        # ── Header with branded logo ─────────────────────
        hdr = tk.Frame(self, bg=self.BG, pady=18)
        hdr.pack(fill="x")

        logo_row = tk.Frame(hdr, bg=self.BG)
        logo_row.pack()

        # Try to load actual IVY PRO icon with PIL
        _logo_shown = False
        try:
            from PIL import Image, ImageTk
            ico_path = res('app_icon.ico')
            if os.path.exists(ico_path):
                _ico = Image.open(ico_path).resize((52, 52), Image.LANCZOS)
                self._logo_photo = ImageTk.PhotoImage(_ico)
                tk.Label(logo_row, image=self._logo_photo,
                         bg=self.BG).pack(side='left', padx=(0, 10))
                _logo_shown = True
        except Exception:
            pass

        text_col = tk.Frame(logo_row, bg=self.BG)
        text_col.pack(side='left')

        font_brand = tkfont.Font(family='Segoe UI', size=22, weight='bold')
        if _logo_shown:
            # Orange IVY + white PRO matching splash branding
            brand_row = tk.Frame(text_col, bg=self.BG)
            brand_row.pack(anchor='w')
            tk.Label(brand_row, text='IVY ', font=font_brand,
                     bg=self.BG, fg='#FF6B2B').pack(side='left')
            tk.Label(brand_row, text='PRO', font=font_brand,
                     bg=self.BG, fg=self.TEXT).pack(side='left')
        else:
            tk.Label(text_col, text='🌿 IvyPro', font=font_brand,
                     bg=self.BG, fg=self.TEXT).pack(anchor='w')

        tk.Label(text_col, text='Indian GST Accounting  •  Server Launcher',
                 font=self.font_sub, bg=self.BG, fg=self.SUBTEXT).pack(anchor='w')

        self._sep(self)

        # ── Server Control Card ──────────────────────────
        card = self._card(self, "⚡  Server Control")

        # Port row
        row_port = tk.Frame(card, bg=self.CARD)
        row_port.pack(fill="x", padx=16, pady=(8, 4))
        tk.Label(row_port, text="Port", font=self.font_label,
                 bg=self.CARD, fg=self.TEXT, width=12, anchor="w").pack(side="left")
        self._port_var = tk.StringVar(value=str(self.cfg["port"]))
        port_entry = tk.Entry(
            row_port, textvariable=self._port_var, width=8,
            font=self.font_mono, bg="#252836", fg=self.ACCENT2,
            insertbackground=self.ACCENT2, relief="flat", bd=0,
            highlightthickness=1, highlightcolor=self.ACCENT,
            highlightbackground=self.BORDER
        )
        port_entry.pack(side="left", ipady=4, padx=4)
        port_entry.bind("<FocusOut>", self._validate_port)

        tk.Label(row_port, text="(1024 – 65535)", font=self.font_status,
                 bg=self.CARD, fg=self.SUBTEXT).pack(side="left", padx=6)

        # Status indicator
        self._status_var = tk.StringVar(value="● Server Stopped")
        self._status_lbl = tk.Label(
            card, textvariable=self._status_var,
            font=self.font_status, bg=self.CARD, fg=self.DANGER
        )
        self._status_lbl.pack(anchor="w", padx=16, pady=(4, 8))

        # URL display
        self._url_var = tk.StringVar(value="")
        self._url_lbl = tk.Label(
            card, textvariable=self._url_var,
            font=self.font_mono, bg=self.CARD, fg=self.ACCENT2,
            cursor="hand2"
        )
        self._url_lbl.pack(anchor="w", padx=16)
        self._url_lbl.bind("<Button-1>", lambda e: self._open_browser())

        # Buttons row
        btn_row = tk.Frame(card, bg=self.CARD, pady=14)
        btn_row.pack(fill="x", padx=16)

        self._start_btn = self._btn(
            btn_row, "▶  Start Server", self.ACCENT, self._start_server, width=16)
        self._start_btn.pack(side="left", padx=(0, 8))

        self._stop_btn = self._btn(
            btn_row, "■  Stop Server", self.DANGER, self._stop_server, width=14)
        self._stop_btn.pack(side="left", padx=(0, 8))
        self._stop_btn.configure(state="disabled")

        self._browser_btn = self._btn(
            btn_row, "🌐  Open Browser", self.ACCENT2, self._open_browser, width=14)
        self._browser_btn.pack(side="left")
        self._browser_btn.configure(state="disabled")

        self._sep(self)

        # ── Preferences Card ─────────────────────────────
        pref = self._card(self, "⚙  Preferences")

        self._auto_start_var   = tk.BooleanVar(value=self.cfg["auto_start_server"])
        self._auto_browser_var = tk.BooleanVar(value=self.cfg["auto_open_browser"])
        self._startup_var      = tk.BooleanVar(value=self.cfg["startup_with_windows"])

        self._toggle(pref, "Auto-start server on launch",
                     self._auto_start_var,   self._save_prefs)
        self._toggle(pref, "Auto-open browser when server starts",
                     self._auto_browser_var, self._save_prefs)
        self._startup_toggle_row = self._toggle(
            pref, "Start with Windows  (adds to startup registry)",
            self._startup_var, self._on_startup_toggle
        )

        self._sep(self)

        # ── Log Card ─────────────────────────────────────
        log_card = self._card(self, "📋  Activity Log")
        log_frame = tk.Frame(log_card, bg=self.CARD)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(4, 12))

        self._log = tk.Text(
            log_frame, height=8, bg="#0d0f1a", fg=self.TEXT,
            font=self.font_status, relief="flat", bd=0,
            insertbackground=self.TEXT, state="disabled",
            wrap="word"
        )
        sb = tk.Scrollbar(log_frame, command=self._log.yview, bg=self.CARD)
        self._log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log.pack(side="left", fill="both", expand=True)

        # Tag colours for log
        self._log.tag_configure("INFO",    foreground=self.TEXT)
        self._log.tag_configure("SUCCESS", foreground=self.SUCCESS)
        self._log.tag_configure("WARN",    foreground=self.WARNING)
        self._log.tag_configure("ERROR",   foreground=self.DANGER)
        self._log.tag_configure("URL",     foreground=self.ACCENT2)

        self._log_msg("IvyPro Launcher ready.", "SUCCESS")
        self._log_msg(f"Base directory: {BASE_DIR}", "INFO")

        # ── Footer ───────────────────────────────────────
        footer = tk.Frame(self, bg=self.BG, pady=8)
        footer.pack(fill="x")
        tk.Label(footer, text="IvyPro V1  •  Ivy Accountancy",
                 font=self.font_status, bg=self.BG, fg=self.SUBTEXT).pack()

    # ── Widget helpers ────────────────────────────────────
    def _card(self, parent, title):
        outer = tk.Frame(parent, bg=self.BG)
        outer.pack(fill="x", padx=20, pady=8)
        tk.Label(outer, text=title, font=self.font_label,
                 bg=self.BG, fg=self.ACCENT).pack(anchor="w", pady=(0, 4))
        card = tk.Frame(outer, bg=self.CARD,
                        highlightthickness=1, highlightbackground=self.BORDER)
        card.pack(fill="x")
        return card

    def _sep(self, parent):
        tk.Frame(parent, height=1, bg=self.BORDER).pack(fill="x", padx=20, pady=2)

    def _btn(self, parent, text, color, cmd, width=12):
        b = tk.Button(
            parent, text=text, command=cmd,
            font=self.font_btn, bg=color, fg="white",
            activebackground=self._lighten(color),
            activeforeground="white",
            relief="flat", bd=0, cursor="hand2",
            padx=10, pady=6, width=width
        )
        b.bind("<Enter>", lambda e, b=b, c=color: b.configure(bg=self._lighten(c)))
        b.bind("<Leave>", lambda e, b=b, c=color: b.configure(bg=c))
        return b

    def _toggle(self, parent, label, var, cmd):
        row = tk.Frame(parent, bg=self.CARD)
        row.pack(fill="x", padx=16, pady=5)
        chk = tk.Checkbutton(
            row, text=label, variable=var, command=cmd,
            font=self.font_label, bg=self.CARD, fg=self.TEXT,
            selectcolor=self.BG, activebackground=self.CARD,
            activeforeground=self.TEXT,
            cursor="hand2"
        )
        chk.pack(side="left")
        return row

    @staticmethod
    def _lighten(hex_color):
        """Brighten a hex colour slightly for hover effect."""
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
        r = min(255, r + 30)
        g = min(255, g + 30)
        b = min(255, b + 30)
        return f"#{r:02x}{g:02x}{b:02x}"

    # ── Log helpers ───────────────────────────────────────
    def _log_msg(self, msg, level="INFO"):
        ts = time.strftime("%H:%M:%S")
        self._log.configure(state="normal")
        self._log.insert("end", f"[{ts}] {msg}\n", level)
        self._log.see("end")
        self._log.configure(state="disabled")

    # ── Port validation ───────────────────────────────────
    def _validate_port(self, _event=None):
        try:
            p = int(self._port_var.get())
            if not (1024 <= p <= 65535):
                raise ValueError
            self.cfg["port"] = p
            save_config(self.cfg)
        except ValueError:
            self._port_var.set(str(self.cfg["port"]))
            messagebox.showwarning("Invalid Port",
                                   "Please enter a port between 1024 and 65535.")

    # ── Preference saves ──────────────────────────────────
    def _save_prefs(self):
        self.cfg["auto_start_server"]   = self._auto_start_var.get()
        self.cfg["auto_open_browser"]   = self._auto_browser_var.get()
        self.cfg["startup_with_windows"] = self._startup_var.get()
        save_config(self.cfg)

    def _on_startup_toggle(self):
        self._save_prefs()
        ok = set_startup(self._startup_var.get())
        if ok:
            state = "enabled" if self._startup_var.get() else "disabled"
            self._log_msg(f"Windows startup {state}.", "SUCCESS" if self._startup_var.get() else "WARN")

    def _refresh_startup_toggle(self):
        actual = is_startup_enabled()
        self._startup_var.set(actual)
        self.cfg["startup_with_windows"] = actual

    # ── Server lifecycle ──────────────────────────────────
    def _get_port(self):
        self._validate_port()
        return self.cfg["port"]

    def _start_server(self):
        if self._server_proc and self._server_proc.poll() is None:
            self._log_msg("Server is already running.", "WARN")
            return

        port = self._get_port()
        if not is_port_free(port):
            self._log_msg(f"Port {port} is already in use. Try a different port.", "ERROR")
            messagebox.showerror("Port In Use",
                                 f"Port {port} is already in use.\n"
                                 "Please choose a different port in the settings.")
            return

        self._log_msg(f"Starting IvyPro server on port {port}…", "INFO")
        self._set_server_state("starting")

        def _run():
            server_script = os.path.join(BASE_DIR, "run.py")
            server_exe    = os.path.join(BASE_DIR, "IvyProV1.exe")

            if os.path.exists(server_exe):
                # Launch the compiled server EXE in server mode
                cmd = [server_exe, "--server", "--port", str(port)]
            elif os.path.exists(server_script):
                cmd = [sys.executable, server_script,
                       "--server", "--port", str(port)]
            else:
                self.after(0, lambda: self._log_msg(
                    "Cannot find IvyProV1.exe or run.py!", "ERROR"))
                self.after(0, lambda: self._set_server_state("stopped"))
                return

            try:
                self._server_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                self._server_port = port

                # Wait until server responds
                if wait_for_server(port, timeout=25):
                    url = f"http://127.0.0.1:{port}"
                    self.after(0, lambda: self._log_msg(
                        f"Server running at {url}", "SUCCESS"))
                    self.after(0, lambda: self._url_var.set(f"🔗  {url}  (click to open)"))
                    self.after(0, lambda: self._set_server_state("running"))
                    if self.cfg.get("auto_open_browser"):
                        # Must open browser on the main thread (daemon thread fails on Windows)
                        self.after(100, lambda u=url: webbrowser.open(u))
                else:
                    self.after(0, lambda: self._log_msg(
                        "Server did not respond in time.", "ERROR"))
                    self.after(0, lambda: self._set_server_state("stopped"))
                    self._server_proc.terminate()

                # Poll proc until it exits; update state
                self._server_proc.wait()
                self.after(0, lambda: self._log_msg("Server process exited.", "WARN"))
                self.after(0, lambda: self._set_server_state("stopped"))
                self.after(0, lambda: self._url_var.set(""))

            except Exception as exc:
                self.after(0, lambda: self._log_msg(f"Error: {exc}", "ERROR"))
                self.after(0, lambda: self._set_server_state("stopped"))

        threading.Thread(target=_run, daemon=True).start()

    def _stop_server(self):
        if self._server_proc and self._server_proc.poll() is None:
            self._log_msg("Stopping server…", "WARN")
            self._server_proc.terminate()
            try:
                self._server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._server_proc.kill()
            self._server_proc = None
            self._set_server_state("stopped")
            self._url_var.set("")
            self._log_msg("Server stopped.", "INFO")
        else:
            self._log_msg("No server is running.", "WARN")

    def _open_browser(self):
        port = self._server_port or self._get_port()
        url  = f"http://127.0.0.1:{port}"
        self._log_msg(f"Opening browser → {url}", "INFO")
        webbrowser.open(url)

    # ── UI state helpers ──────────────────────────────────
    def _set_server_state(self, state: str):
        if state == "running":
            self._status_var.set(f"● Server Running  —  port {self._server_port}")
            self._status_lbl.configure(fg=self.SUCCESS)
            self._start_btn.configure(state="disabled")
            self._stop_btn.configure(state="normal")
            self._browser_btn.configure(state="normal")
        elif state == "starting":
            self._status_var.set("◌  Starting server…")
            self._status_lbl.configure(fg=self.WARNING)
            self._start_btn.configure(state="disabled")
            self._stop_btn.configure(state="disabled")
            self._browser_btn.configure(state="disabled")
        else:  # stopped
            self._status_var.set("● Server Stopped")
            self._status_lbl.configure(fg=self.DANGER)
            self._start_btn.configure(state="normal")
            self._stop_btn.configure(state="disabled")
            self._browser_btn.configure(state="disabled")

    # ── Close handler ─────────────────────────────────────
    def _on_close(self):
        if self._server_proc and self._server_proc.poll() is None:
            if not messagebox.askyesno(
                "Server Running",
                "IvyPro server is still running.\n"
                "Stop it and close the launcher?"
            ):
                return
            self._stop_server()
        self.destroy()


# ─── Entry point ─────────────────────────────────────────
if __name__ == "__main__":
    app = IvyLauncherApp()
    app.mainloop()
