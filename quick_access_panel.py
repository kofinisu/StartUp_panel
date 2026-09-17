#!/usr/bin/env python3
"""
Quick Access Panel for Windows
==============================
A small panel that launches at login and asks whether you want to open your
saved WEBSITES or your saved APPS (or both), then launches the ones you tick.

Requirements : Python 3.8+ for Windows (tkinter is bundled with the official installer)
Config file  : %APPDATA%\QuickAccessPanel\config.json
Autostart    : HKCU\Software\Microsoft\Windows\CurrentVersion\Run

Command line:
    pythonw quick_access_panel.py              # normal launch (asks)
    pythonw quick_access_panel.py --startup    # used by the autostart entry (adds a delay)
    pythonw quick_access_panel.py --manage     # open straight into the manager
    pythonw quick_access_panel.py --install    # register autostart
    pythonw quick_access_panel.py --uninstall  # remove autostart
"""

import json
import os
import subprocess
import sys
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox

# --------------------------------------------------------------------------- #
#  Constants
# --------------------------------------------------------------------------- #
APP_NAME = "Quick Access Panel"
APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "QuickAccessPanel")
CONFIG_FILE = os.path.join(APP_DIR, "config.json")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "QuickAccessPanel"

BG = "#f5f5f7"
HEADER_BG = "#2b2b3c"
ACCENT = "#3b6ef5"
MUTED = "#8a8a9a"


# --------------------------------------------------------------------------- #
#  Configuration
# --------------------------------------------------------------------------- #
def default_config():
    return {
        "startup_delay": 3,
        "websites": [
            {"name": "Gmail", "target": "https://mail.google.com"},
            {"name": "YouTube", "target": "https://www.youtube.com"},
            {"name": "GitHub", "target": "https://github.com"},
        ],
        "apps": [
            {"name": "Notepad", "target": "notepad.exe"},
            {"name": "Calculator", "target": "calc.exe"},
            {"name": "File Explorer", "target": "explorer.exe"},
            {"name": "Task Manager", "target": "taskmgr.exe"},
        ],
    }


def load_config():
    os.makedirs(APP_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        cfg = default_config()
        save_config(cfg)
        return cfg
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        cfg = default_config()
    cfg.setdefault("websites", [])
    cfg.setdefault("apps", [])
    cfg.setdefault("startup_delay", 3)
    return cfg


def save_config(cfg):
    os.makedirs(APP_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)


# --------------------------------------------------------------------------- #
#  Windows autostart helpers
# --------------------------------------------------------------------------- #
def script_path():
    if getattr(sys, "frozen", False):          # packaged with PyInstaller
        return sys.executable
    return os.path.abspath(__file__)


def launcher_path():
    """Prefer pythonw.exe so no console window flashes up at login."""
    if getattr(sys, "frozen", False):
        return sys.executable
    candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return candidate if os.path.exists(candidate) else sys.executable


def startup_command():
    if getattr(sys, "frozen", False):
        return f'"{script_path()}" --startup'
    return f'"{launcher_path()}" "{script_path()}" --startup'


def is_startup_enabled():
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE)
            return bool(value)
    except OSError:
        return False


def set_startup(enabled):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass


# --------------------------------------------------------------------------- #
#  Launching
# --------------------------------------------------------------------------- #
def open_item(category, target):
    if category == "websites":
        webbrowser.open(target, new=2)
        return
    try:
        os.startfile(target)                       # handles paths, .lnk, .exe on PATH
    except OSError:
        subprocess.Popen(target, shell=True)       # handles "prog.exe --args"


# --------------------------------------------------------------------------- #
#  Small UI helpers
# --------------------------------------------------------------------------- #
def center_window(win, parent=None):
    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    if parent is not None and parent.winfo_viewable():
        x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - h) // 3
    else:
        x = (win.winfo_screenwidth() - w) // 2
        y = (win.winfo_screenheight() - h) // 3
    win.geometry(f"+{max(0, x)}+{max(0, y)}")


def shorten(text, limit):
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ScrollArea(tk.Frame):
    """A vertically scrollable frame."""

    def __init__(self, parent, bg=BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        vsb = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


# --------------------------------------------------------------------------- #
#  Main panel
# --------------------------------------------------------------------------- #
class PanelApp(tk.Tk):
    def __init__(self, ask=True, open_manage=False):
        super().__init__()
        self.withdraw()
        self.cancelled = False
        self.cfg = load_config()
        self.vars = {}
        self.categories = ["websites", "apps"]

        if ask:
            choice = self._ask_choice()
            if choice is None:
                self.cancelled = True
                self.destroy()
                return
            self.categories = ["websites", "apps"] if choice == "both" else [choice]

        self._build_ui()
        self.deiconify()
        center_window(self)
        self.attributes("-topmost", True)
        self.after(1000, lambda: self.attributes("-topmost", False))

        if open_manage:
            self.after(200, self.open_manage)

    # ------------------------------------------------------------------ ask
    def _ask_choice(self):
        dlg = tk.Toplevel(self)
        dlg.title(APP_NAME)
        dlg.configure(bg=BG, padx=24, pady=20)
        dlg.resizable(False, False)
        dlg.attributes("-topmost", True)

        tk.Label(dlg, text=APP_NAME, font=("Segoe UI", 15, "bold"),
                 bg=BG, fg="#222").pack()
        tk.Label(dlg, text="What would you like to open?", font=("Segoe UI", 10),
                 bg=BG, fg="#555").pack(pady=(4, 16))

        frame = tk.Frame(dlg, bg=BG)
        frame.pack()

        result = {"value": None}

        def choose(value):
            result["value"] = value
            dlg.destroy()

        n_sites = len(self.cfg.get("websites", []))
        n_apps = len(self.cfg.get("apps", []))

        def add_button(text, value, enabled=True, pady=4):
            btn = tk.Button(frame, text=text, width=24, font=("Segoe UI", 10),
                            relief="flat", bg="#ffffff", activebackground="#e6e6ee",
                            command=lambda: choose(value))
            if not enabled:
                btn.configure(state="disabled")
            btn.pack(pady=pady)
            return btn

        add_button(f"Websites  ({n_sites})", "websites", n_sites > 0)
        add_button(f"Apps  ({n_apps})", "apps", n_apps > 0)
        add_button("Both", "both")
        tk.Button(frame, text="Not now", width=24, font=("Segoe UI", 10),
                  relief="flat", bg="#e9e9ef", activebackground="#dcdce6",
                  command=lambda: choose(None)).pack(pady=(14, 0))

        dlg.protocol("WM_DELETE_WINDOW", lambda: choose(None))
        center_window(dlg)
        self.wait_window(dlg)
        return result["value"]

    # ------------------------------------------------------------------- UI
    def _build_ui(self):
        self.title(APP_NAME)
        self.geometry("470x620")
        self.minsize(400, 420)
        self.configure(bg=BG)

        header = tk.Frame(self, bg=HEADER_BG, padx=16, pady=12)
        header.pack(fill="x")
        tk.Label(header, text=APP_NAME, font=("Segoe UI", 14, "bold"),
                 fg="white", bg=HEADER_BG).pack(anchor="w")
        tk.Label(header, text="Tick what you want to launch, then click Open Selected.",
                 font=("Segoe UI", 9), fg="#c9c9dd", bg=HEADER_BG).pack(anchor="w")

        footer = tk.Frame(self, bg=BG, padx=12, pady=10)
        footer.pack(fill="x", side="bottom")

        row1 = tk.Frame(footer, bg=BG)
        row1.pack(fill="x")
        tk.Button(row1, text="Open Selected", font=("Segoe UI", 10, "bold"),
                  bg=ACCENT, fg="white", activebackground="#2f5bd0",
                  activeforeground="white", relief="flat", padx=14, pady=6,
                  command=self.open_selected).pack(side="left")
        tk.Button(row1, text="Select All", font=("Segoe UI", 9),
                  command=lambda: self.set_all(True)).pack(side="left", padx=(8, 0))
        tk.Button(row1, text="Clear", font=("Segoe UI", 9),
                  command=lambda: self.set_all(False)).pack(side="left", padx=(4, 0))
        tk.Button(row1, text="Close", font=("Segoe UI", 9),
                  command=self.destroy).pack(side="right")

        row2 = tk.Frame(footer, bg=BG)
        row2.pack(fill="x", pady=(8, 0))
        tk.Button(row2, text="Manage items…", font=("Segoe UI", 9),
                  command=self.open_manage).pack(side="left")
        self.startup_var = tk.BooleanVar(value=is_startup_enabled())
        tk.Checkbutton(row2, text="Start with Windows", variable=self.startup_var,
                       bg=BG, activebackground=BG, selectcolor="white",
                       font=("Segoe UI", 9),
                       command=self.toggle_startup).pack(side="right")

        self.scroll = ScrollArea(self, bg=BG)
        self.scroll.pack(fill="both", expand=True)

        self.populate_sections()

    def populate_sections(self):
        for child in self.scroll.inner.winfo_children():
            child.destroy()
        self.vars.clear()

        any_items = False
        for cat, title in (("websites", "Websites"), ("apps", "Applications")):
            if cat not in self.categories:
                continue
            items = self.cfg.get(cat, [])
            if not items:
                continue
            any_items = True

            box = tk.LabelFrame(self.scroll.inner, text=f" {title} ",
                                font=("Segoe UI", 10, "bold"), bg=BG, fg="#333333",
                                padx=10, pady=6, bd=1, relief="groove")
            box.pack(fill="x", padx=12, pady=(12, 0))

            for idx, item in enumerate(items):
                key = f"{cat}:{idx}"
                var = tk.BooleanVar(value=False)
                self.vars[key] = var

                row = tk.Frame(box, bg=BG)
                row.pack(fill="x")
                tk.Checkbutton(row, text=item["name"], variable=var, bg=BG,
                               activebackground=BG, selectcolor="white",
                               font=("Segoe UI", 10), anchor="w").pack(side="left")
                tk.Label(row, text=shorten(item["target"], 38), bg=BG, fg=MUTED,
                         font=("Segoe UI", 8)).pack(side="right")

        if not any_items:
            tk.Label(self.scroll.inner,
                     text="No items saved yet.\nUse “Manage items…” to add some.",
                     bg=BG, fg="#777777", font=("Segoe UI", 10),
                     justify="center").pack(pady=40)

    # -------------------------------------------------------------- actions
    def set_all(self, value):
        for var in self.vars.values():
            var.set(value)

    def open_selected(self):
        chosen = []
        for key, var in self.vars.items():
            if var.get():
                cat, idx = key.split(":")
                chosen.append((cat, self.cfg[cat][int(idx)]))

        if not chosen:
            messagebox.showinfo(APP_NAME, "Nothing is selected.", parent=self)
            return

        errors = []
        for cat, item in chosen:
            try:
                open_item(cat, item["target"])
            except Exception as exc:                       # noqa: BLE001
                errors.append(f"• {item['name']}: {exc}")

        if errors:
            messagebox.showerror(APP_NAME,
                                 "Some items could not be opened:\n\n" + "\n".join(errors),
                                 parent=self)
        else:
            self.destroy()

    def toggle_startup(self):
        try:
            set_startup(self.startup_var.get())
        except Exception as exc:                           # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Could not update the startup setting:\n{exc}",
                                 parent=self)
            self.startup_var.set(is_startup_enabled())

    def open_manage(self):
        win = ManageWindow(self)
        self.wait_window(win)
        self.cfg = load_config()
        self.startup_var.set(is_startup_enabled())
        self.populate_sections()


# --------------------------------------------------------------------------- #
#  Manager window
# --------------------------------------------------------------------------- #
class ManageWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.cfg = load_config()
        self.lists = {}

        self.title("Manage — " + APP_NAME)
        self.geometry("660x480")
        self.minsize(560, 420)
        self.configure(bg=BG)
        self.transient(parent)

        self._build()
        self.refresh()
        center_window(self, parent)

    def _build(self):
        body = tk.Frame(self, bg=BG, padx=12, pady=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        for col, (cat, title) in enumerate((("websites", "Websites"), ("apps", "Applications"))):
            box = tk.LabelFrame(body, text=f" {title} ", font=("Segoe UI", 10, "bold"),
                                bg=BG, padx=8, pady=8)
            pad = (0, 8) if col == 0 else (8, 0)
            box.grid(row=0, column=col, sticky="nsew", padx=pad)

            lb = tk.Listbox(box, font=("Segoe UI", 10), activestyle="none",
                            selectmode="browse", bd=1, relief="solid")
            lb.pack(fill="both", expand=True)
            lb.bind("<Double-Button-1>", lambda e, c=cat: self.edit_item(c))
            self.lists[cat] = lb

            btns = tk.Frame(box, bg=BG)
            btns.pack(fill="x", pady=(8, 0))
            tk.Button(btns, text="Add", width=8,
                      command=lambda c=cat: self.add_item(c)).pack(side="left")
            tk.Button(btns, text="Edit", width=8,
                      command=lambda c=cat: self.edit_item(c)).pack(side="left", padx=4)
            tk.Button(btns, text="Remove", width=8,
                      command=lambda c=cat: self.remove_item(c)).pack(side="left")

        opts = tk.Frame(self, bg=BG, padx=12, pady=8)
        opts.pack(fill="x")

        self.startup_var = tk.BooleanVar(value=is_startup_enabled())
        tk.Checkbutton(opts, text="Start with Windows", variable=self.startup_var,
                       bg=BG, activebackground=BG, selectcolor="white",
                       font=("Segoe UI", 9),
                       command=self._toggle_startup).pack(side="left")

        tk.Label(opts, text="Startup delay (s):", bg=BG,
                 font=("Segoe UI", 9)).pack(side="left", padx=(18, 4))
        self.delay_var = tk.StringVar(value=str(self.cfg.get("startup_delay", 3)))
        tk.Spinbox(opts, from_=0, to=120, width=4,
                   textvariable=self.delay_var).pack(side="left")

        tk.Button(opts, text="Save && Close", command=self._close).pack(side="right")

    # ------------------------------------------------------------------ data
    def refresh(self):
        for cat, lb in self.lists.items():
            lb.delete(0, tk.END)
            for item in self.cfg.get(cat, []):
                lb.insert(tk.END, f"{item['name']}  —  {item['target']}")

    def add_item(self, cat):
        data = self._item_dialog(cat)
        if data:
            self.cfg.setdefault(cat, []).append(data)
            save_config(self.cfg)
            self.refresh()

    def edit_item(self, cat):
        lb = self.lists[cat]
        sel = lb.curselection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select an item first.", parent=self)
            return
        idx = sel[0]
        data = self._item_dialog(cat, self.cfg[cat][idx])
        if data:
            self.cfg[cat][idx] = data
            save_config(self.cfg)
            self.refresh()
            lb.selection_set(idx)

    def remove_item(self, cat):
        lb = self.lists[cat]
        sel = lb.curselection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select an item first.", parent=self)
            return
        idx = sel[0]
        item = self.cfg[cat][idx]
        if messagebox.askyesno(APP_NAME, f"Remove “{item['name']}”?", parent=self):
            del self.cfg[cat][idx]
            save_config(self.cfg)
            self.refresh()

    # --------------------------------------------------------------- dialogs
    def _item_dialog(self, cat, item=None):
        is_site = cat == "websites"
        dlg = tk.Toplevel(self)
        dlg.title(("Edit " if item else "Add ") + ("website" if is_site else "application"))
        dlg.configure(bg=BG, padx=18, pady=16)
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        name_var = tk.StringVar(value=item["name"] if item else "")
        target_var = tk.StringVar(value=item["target"] if item else "")

        tk.Label(dlg, text="Name", bg=BG, font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w")
        tk.Entry(dlg, textvariable=name_var, width=46,
                 font=("Segoe UI", 10)).grid(row=1, column=0, columnspan=2,
                                             sticky="we", pady=(0, 12))

        tk.Label(dlg, text=("URL" if is_site else "Program, path or command"),
                 bg=BG, font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w")
        tk.Entry(dlg, textvariable=target_var, width=46,
                 font=("Segoe UI", 10)).grid(row=3, column=0, columnspan=2,
                                             sticky="we", pady=(0, 12))

        result = {}

        def browse():
            path = filedialog.askopenfilename(
                parent=dlg, title="Choose a program",
                filetypes=[("Programs", "*.exe *.bat *.cmd *.lnk"), ("All files", "*.*")])
            if path:
                target_var.set(os.path.normpath(path))
                if not name_var.get().strip():
                    name_var.set(os.path.splitext(os.path.basename(path))[0])

        def ok(_event=None):
            name = name_var.get().strip()
            target = target_var.get().strip()
            if not name or not target:
                messagebox.showwarning(APP_NAME, "Both fields are required.", parent=dlg)
                return
            result["name"] = name
            result["target"] = target
            dlg.destroy()

        if not is_site:
            tk.Button(dlg, text="Browse…", command=browse).grid(row=3, column=2, padx=(8, 0))

        btns = tk.Frame(dlg, bg=BG)
        btns.grid(row=4, column=0, columnspan=3, sticky="e", pady=(8, 0))
        tk.Button(btns, text="Cancel", width=10, command=dlg.destroy).pack(side="right")
        tk.Button(btns, text="OK", width=10, command=ok).pack(side="right", padx=(0, 6))

        dlg.bind("<Return>", ok)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        center_window(dlg, self)
        self.wait_window(dlg)
        return result or None

    # ------------------------------------------------------------------ misc
    def _toggle_startup(self):
        try:
            set_startup(self.startup_var.get())
        except Exception as exc:                           # noqa: BLE001
            messagebox.showerror(APP_NAME, str(exc), parent=self)

    def _close(self):
        try:
            self.cfg["startup_delay"] = max(0, int(self.delay_var.get()))
        except ValueError:
            self.cfg["startup_delay"] = 3
        save_config(self.cfg)
        self.destroy()


# --------------------------------------------------------------------------- #
#  Entry point
# --------------------------------------------------------------------------- #
def main():
    args = sys.argv[1:]

    if "--install" in args:
        set_startup(True)
        print("Added to Windows startup.")
        return
    if "--uninstall" in args:
        set_startup(False)
        print("Removed from Windows startup.")
        return

    manage_only = "--manage" in args

    delay = 0
    if "--startup" in args:
        delay = int(load_config().get("startup_delay", 3))
    if "--delay" in args:
        try:
            delay = int(args[args.index("--delay") + 1])
        except (IndexError, ValueError):
            pass

    if delay > 0:
        time.sleep(delay)

    app = PanelApp(ask=not manage_only, open_manage=manage_only)
    if not app.cancelled:
        app.mainloop()


if __name__ == "__main__":
    main()