import csv
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from urllib import request

from google_auth_oauthlib.flow import InstalledAppFlow
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


DB_FILE = Path(__file__).with_name("finance_simple.db")
TOKEN_FILE = Path(__file__).with_name("google_token.json")
ENV_FILE = Path(__file__).with_name(".env")


def load_env_file():
    if not ENV_FILE.exists():
        return

    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env_file()

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

CATEGORIES = ["Food", "Travel", "Bills", "Shopping", "Study", "Health", "Salary", "Other"]
GOOGLE_SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"]


class FinanceApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Finance Tracker Pro")
        self.root.geometry("980x680")

        self.conn = sqlite3.connect(DB_FILE)
        self.create_tables()

        self.type_var = tk.StringVar(value="Expense")
        self.category_var = tk.StringVar(value=CATEGORIES[0])
        self.amount_var = tk.StringVar()
        self.date_var = tk.StringVar(value=datetime.today().strftime("%Y-%m-%d"))
        self.note_var = tk.StringVar()
        self.budget_category_var = tk.StringVar(value=CATEGORIES[0])
        self.budget_amount_var = tk.StringVar()
        self.month_var = tk.StringVar()
        self.login_var = tk.StringVar(value="Please log in to continue")
        self.mode_var = tk.StringVar(value="Mode: Locked")
        self.signin_username_var = tk.StringVar()
        self.signin_password_var = tk.StringVar()
        self.signup_name_var = tk.StringVar()
        self.signup_username_var = tk.StringVar()
        self.signup_password_var = tk.StringVar()

        self.user_name = ""
        self.user_email = ""
        self.user_role = ""
        self.guest_transactions = []
        self.guest_budgets = {}
        self.pages = {}
        self.login_screen = None
        self.nav_buttons = {}

        self.setup_style()
        self.build_ui()
        self.update_admin_visibility()
        self.set_dashboard_enabled(False)
        self.root.withdraw()

        self.root.protocol("WM_DELETE_WINDOW", self.close_app)
        self.root.after(200, self.show_login_screen)

    def setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Card.TLabelframe", padding=10)
        style.configure("Primary.TButton", padding=6)
        style.configure("Login.TNotebook", background="white", borderwidth=0)
        style.configure(
            "Login.TNotebook.Tab",
            background="white",
            foreground="black",
            padding=(18, 8),
            font=("Arial", 10, "bold"),
        )
        style.map(
            "Login.TNotebook.Tab",
            background=[("selected", "#dfe8f2"), ("active", "#eef3f8")],
            foreground=[("selected", "#12304a"), ("active", "black")],
        )

    def create_tables(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                name TEXT,
                role TEXT DEFAULT 'user',
                username TEXT UNIQUE,
                password TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_email TEXT,
                entry_type TEXT,
                category TEXT,
                amount REAL,
                entry_date TEXT,
                note TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_email TEXT,
                category TEXT,
                amount REAL,
                UNIQUE(owner_email, category)
            )
            """
        )

        self.ensure_column("transactions", "owner_email", "TEXT")
        self.ensure_column("users", "username", "TEXT")
        self.ensure_column("users", "password", "TEXT")
        self.move_old_budgets_if_needed()
        self.conn.commit()

    def ensure_column(self, table_name, column_name, column_type):
        columns = self.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        names = [column[1] for column in columns]
        if column_name not in names:
            self.conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    def move_old_budgets_if_needed(self):
        columns = self.conn.execute("PRAGMA table_info(budgets)").fetchall()
        names = [column[1] for column in columns]

        if "owner_email" in names and "id" in names:
            return

        old_rows = self.conn.execute("SELECT category, amount FROM budgets").fetchall()
        self.conn.execute("ALTER TABLE budgets RENAME TO budgets_old")
        self.conn.execute(
            """
            CREATE TABLE budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_email TEXT,
                category TEXT,
                amount REAL,
                UNIQUE(owner_email, category)
            )
            """
        )
        for category, amount in old_rows:
            self.conn.execute(
                "INSERT INTO budgets (owner_email, category, amount) VALUES (?, ?, ?)",
                ("legacy@local", category, amount),
            )
        self.conn.execute("DROP TABLE budgets_old")

    def build_ui(self):
        header = tk.Frame(self.root, bg="#12304a", padx=18, pady=16)
        header.pack(fill="x")

        title_box = tk.Frame(header, bg="#12304a")
        title_box.pack(side="left")
        tk.Label(
            title_box,
            text="Finance Tracker Pro",
            font=("Arial", 18, "bold"),
            fg="white",
            bg="#12304a",
        ).pack(anchor="w")
        tk.Label(
            title_box,
            text="Login first, keep each user's data private, or continue as guest",
            font=("Arial", 10),
            fg="#d7e5f2",
            bg="#12304a",
        ).pack(anchor="w")

        auth_box = tk.Frame(header, bg="#12304a")
        auth_box.pack(side="right")
        tk.Label(
            auth_box,
            textvariable=self.login_var,
            font=("Arial", 10, "bold"),
            fg="white",
            bg="#12304a",
        ).pack(anchor="e")
        tk.Label(
            auth_box,
            textvariable=self.mode_var,
            font=("Arial", 10),
            fg="#d7e5f2",
            bg="#12304a",
        ).pack(anchor="e", pady=(4, 8))

        action_row = tk.Frame(auth_box, bg="#12304a")
        action_row.pack(anchor="e")
        ttk.Button(action_row, text="Switch User", command=self.show_login_screen, style="Primary.TButton").pack(
            side="left", padx=4
        )
        ttk.Button(action_row, text="Logout", command=self.logout_user).pack(side="left", padx=4)
        self.admin_button = ttk.Button(action_row, text="Manage Users", command=self.open_admin_panel)
        self.admin_button.pack(side="left", padx=4)

        self.build_menu()

        self.main = tk.Frame(self.root, padx=12, pady=12, bg="#eef3f8")
        self.main.pack(fill="both", expand=True)
        self.main.columnconfigure(1, weight=1)
        self.main.rowconfigure(0, weight=1)

        self.build_sidebar()

        self.page_container = tk.Frame(self.main, bg="#eef3f8")
        self.page_container.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.page_container.rowconfigure(0, weight=1)
        self.page_container.columnconfigure(0, weight=1)

        self.build_home_page()
        self.build_records_page()
        self.build_budget_page()
        self.build_reports_page()
        self.build_admin_page()
        self.show_page("home")

    def build_sidebar(self):
        sidebar = tk.Frame(self.main, bg="#dfe8f2", width=210, padx=10, pady=10)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)

        tk.Label(
            sidebar,
            text="Navigation",
            font=("Arial", 13, "bold"),
            bg="#dfe8f2",
            fg="#12304a",
        ).pack(anchor="w", pady=(4, 10))

        links = [("home", "Dashboard"), ("records", "Add Record"), ("budget", "Budget"), ("reports", "Reports")]

        for page_name, label in links:
            button = tk.Button(
                sidebar,
                text=label,
                font=("Arial", 11),
                bg="white",
                fg="#12304a",
                relief="flat",
                width=18,
                pady=8,
                command=lambda name=page_name: self.show_page(name),
            )
            button.pack(fill="x", pady=4)
            self.nav_buttons[page_name] = button

        self.admin_nav_button = tk.Button(
            sidebar,
            text="Admin",
            font=("Arial", 11),
            bg="white",
            fg="#12304a",
            relief="flat",
            width=18,
            pady=8,
            command=lambda: self.show_page("admin"),
        )
        self.nav_buttons["admin"] = self.admin_nav_button

        self.quick_graph_button = ttk.Button(sidebar, text="Open Graph", command=self.show_graph)
        self.quick_graph_button.pack(fill="x", pady=(16, 6))
        self.quick_export_button = ttk.Button(sidebar, text="Export This Month", command=self.export_csv)
        self.quick_export_button.pack(fill="x", pady=6)

    def build_menu(self):
        self.menu_bar = tk.Menu(self.root)
        self.root.config(menu=self.menu_bar)
        self.refresh_menu()

    def refresh_menu(self):
        self.menu_bar.delete(0, "end")

        navigate_menu = tk.Menu(self.menu_bar, tearoff=0)
        navigate_menu.add_command(label="Home", command=lambda: self.show_page("home"))
        navigate_menu.add_command(label="Add Record", command=lambda: self.show_page("records"))
        navigate_menu.add_command(label="Budget", command=lambda: self.show_page("budget"))
        navigate_menu.add_command(label="Reports", command=lambda: self.show_page("reports"))
        if self.user_role == "admin":
            navigate_menu.add_command(label="Admin", command=lambda: self.show_page("admin"))
        self.menu_bar.add_cascade(label="Navigate", menu=navigate_menu)

        account_menu = tk.Menu(self.menu_bar, tearoff=0)
        account_menu.add_command(label="Switch User", command=self.show_login_screen)
        account_menu.add_command(label="Logout", command=self.logout_user)
        self.menu_bar.add_cascade(label="Account", menu=account_menu)

    def build_home_page(self):
        page = tk.Frame(self.page_container, bg="#eef3f8")
        self.pages["home"] = page
        page.grid(row=0, column=0, sticky="nsew")

        intro = tk.Frame(page, bg="#eef3f8")
        intro.pack(fill="x", pady=(0, 10))
        tk.Label(
            intro,
            text="Dashboard",
            font=("Arial", 18, "bold"),
            bg="#eef3f8",
            fg="#12304a",
        ).pack(anchor="w")
        tk.Label(
            intro,
            text="Your main features are shown here. You can still use the menu or the left navigation anytime.",
            font=("Arial", 10),
            bg="#eef3f8",
            fg="#44576b",
        ).pack(anchor="w", pady=(2, 0))

        quick_actions = ttk.LabelFrame(page, text="Quick Actions", style="Card.TLabelframe")
        quick_actions.pack(fill="x", pady=(0, 10))

        ttk.Button(quick_actions, text="Add New Record", command=lambda: self.show_page("records")).pack(
            side="left", padx=8, pady=8
        )
        ttk.Button(quick_actions, text="Set Budget", command=lambda: self.show_page("budget")).pack(
            side="left", padx=8, pady=8
        )
        ttk.Button(quick_actions, text="Open Reports", command=lambda: self.show_page("reports")).pack(
            side="left", padx=8, pady=8
        )
        ttk.Button(quick_actions, text="Show Graph", command=self.show_graph).pack(side="left", padx=8, pady=8)
        ttk.Button(quick_actions, text="Income vs Expense", command=self.show_income_expense_graph).pack(
            side="left", padx=8, pady=8
        )

        summary = ttk.LabelFrame(page, text="Summary", style="Card.TLabelframe")
        summary.pack(fill="x", pady=(0, 10))

        self.income_label = tk.Label(summary, text="Income: Rs 0", font=("Arial", 11), anchor="w")
        self.income_label.pack(fill="x")
        self.expense_label = tk.Label(summary, text="Expense: Rs 0", font=("Arial", 11), anchor="w")
        self.expense_label.pack(fill="x")
        self.balance_label = tk.Label(summary, text="Balance: Rs 0", font=("Arial", 11, "bold"), anchor="w")
        self.balance_label.pack(fill="x")

        self.budget_info = tk.Text(summary, height=7, width=45, relief="flat", bg="#f7f9fb", fg="#12304a")
        self.budget_info.pack(fill="x", pady=(8, 0))

        table = ttk.LabelFrame(page, text="Transactions", style="Card.TLabelframe")
        table.pack(fill="both", expand=True)

        columns = ("date", "type", "category", "amount", "note")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", height=16)
        for column, width in zip(columns, [100, 90, 110, 90, 240]):
            self.tree.heading(column, text=column.title())
            self.tree.column(column, width=width)

        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def build_records_page(self):
        page = ttk.LabelFrame(self.page_container, text="Add Record", style="Card.TLabelframe")
        self.pages["records"] = page
        page.grid(row=0, column=0, sticky="nsew")

        fields = [
            ("Type", ttk.Combobox(page, textvariable=self.type_var, values=["Income", "Expense"], state="readonly", width=22)),
            ("Category", ttk.Combobox(page, textvariable=self.category_var, values=CATEGORIES, state="readonly", width=22)),
            ("Amount", ttk.Entry(page, textvariable=self.amount_var, width=25)),
            ("Date", ttk.Entry(page, textvariable=self.date_var, width=25)),
            ("Note", ttk.Entry(page, textvariable=self.note_var, width=25)),
        ]

        for i, (label, widget) in enumerate(fields):
            ttk.Label(page, text=label).grid(row=i, column=0, sticky="w", pady=6, padx=(10, 6))
            widget.grid(row=i, column=1, sticky="w", pady=6, padx=(0, 10))

        self.add_button = ttk.Button(page, text="Add Record", command=self.add_transaction)
        self.add_button.grid(row=len(fields), column=0, columnspan=2, pady=10)

    def build_budget_page(self):
        page = ttk.LabelFrame(self.page_container, text="Budget", style="Card.TLabelframe")
        self.pages["budget"] = page
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        page.columnconfigure(1, weight=1)

        ttk.Label(page, text="Category").grid(row=0, column=0, sticky="w", pady=6, padx=(10, 6))
        ttk.Combobox(
            page,
            textvariable=self.budget_category_var,
            values=[c for c in CATEGORIES if c != "Salary"],
            state="readonly",
            width=22,
        ).grid(row=0, column=1, sticky="w", pady=6, padx=(0, 10))

        ttk.Label(page, text="Amount").grid(row=1, column=0, sticky="w", pady=6, padx=(10, 6))
        ttk.Entry(page, textvariable=self.budget_amount_var, width=25).grid(
            row=1, column=1, sticky="w", pady=6, padx=(0, 10)
        )

        self.budget_button = ttk.Button(page, text="Save Budget", command=self.save_budget)
        self.budget_button.grid(row=2, column=0, columnspan=2, pady=10)

        budget_list_frame = ttk.LabelFrame(page, text="Current Budgets", style="Card.TLabelframe")
        budget_list_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=10, pady=(10, 0))
        budget_list_frame.columnconfigure(0, weight=1)

        self.budget_list = tk.Text(budget_list_frame, height=12, relief="flat", bg="#f7f9fb", fg="#12304a")
        self.budget_list.grid(row=0, column=0, sticky="nsew")

    def build_reports_page(self):
        page = ttk.LabelFrame(self.page_container, text="Reports", style="Card.TLabelframe")
        self.pages["reports"] = page
        page.grid(row=0, column=0, sticky="nsew")

        ttk.Label(page, text="Month").grid(row=0, column=0, sticky="w", pady=6, padx=(10, 6))
        self.month_box = ttk.Combobox(page, textvariable=self.month_var, state="readonly", width=16)
        self.month_box.grid(row=0, column=1, sticky="w", pady=6, padx=(0, 10))
        self.month_box.bind("<<ComboboxSelected>>", lambda event: self.refresh_data())

        self.export_button = ttk.Button(page, text="Export CSV", command=self.export_csv)
        self.export_button.grid(row=1, column=0, pady=10, padx=10, sticky="w")
        self.graph_button = ttk.Button(page, text="Show Graph", command=self.show_graph)
        self.graph_button.grid(row=1, column=1, pady=10, sticky="w")
        self.income_expense_button = ttk.Button(
            page, text="Income vs Expense", command=self.show_income_expense_graph
        )
        self.income_expense_button.grid(row=1, column=2, pady=10, padx=10, sticky="w")

        info = tk.Label(
            page,
            text="Use this page to select a month, export your data, or view the graph.",
            font=("Arial", 10),
            anchor="w",
            justify="left",
        )
        info.grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=6)

    def build_admin_page(self):
        page = ttk.LabelFrame(self.page_container, text="Admin", style="Card.TLabelframe")
        self.pages["admin"] = page
        page.grid(row=0, column=0, sticky="nsew")

        tk.Label(
            page,
            text="Admin tools are available only for the hardcoded admin account.",
            font=("Arial", 11),
            anchor="w",
            justify="left",
        ).pack(fill="x", padx=10, pady=(10, 6))

        self.admin_page_button = ttk.Button(page, text="Open User Manager", command=self.open_admin_panel)
        self.admin_page_button.pack(anchor="w", padx=10, pady=10)

    def show_page(self, page_name):
        self.pages[page_name].tkraise()
        for name, button in self.nav_buttons.items():
            button.config(bg="#ffffff")
        if page_name in self.nav_buttons:
            self.nav_buttons[page_name].config(bg="#c8d9ea")

    def set_dashboard_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        readonly_state = "readonly" if enabled else "disabled"

        self.add_button.config(state=state)
        self.budget_button.config(state=state)
        self.export_button.config(state=state)
        self.graph_button.config(state=state)
        self.income_expense_button.config(state=state)
        self.quick_graph_button.config(state=state)
        self.quick_export_button.config(state=state)
        self.month_box.config(state=readonly_state)
        self.admin_button.config(state=state if self.user_role == "admin" else "disabled")
        self.admin_page_button.config(state=state if self.user_role == "admin" else "disabled")
        if "admin" in self.nav_buttons:
            self.nav_buttons["admin"].config(state=state if self.user_role == "admin" else "disabled")

    def update_admin_visibility(self):
        if self.user_role == "admin":
            if not self.admin_button.winfo_manager():
                self.admin_button.pack(side="left", padx=4)
            if not self.admin_nav_button.winfo_manager():
                self.admin_nav_button.pack(fill="x", pady=4)
        else:
            if self.admin_button.winfo_manager():
                self.admin_button.pack_forget()
            if self.admin_nav_button.winfo_manager():
                self.admin_nav_button.pack_forget()

    def show_login_screen(self):
        if self.login_screen and self.login_screen.winfo_exists():
            self.login_screen.lift()
            return

        self.root.withdraw()
        dialog = tk.Toplevel(self.root)
        self.login_screen = dialog
        dialog.title("Login Required")
        dialog.attributes("-fullscreen", True)
        dialog.configure(bg="#12304a")
        dialog.grab_set()
        dialog.focus_force()

        shell = tk.Frame(dialog, bg="#12304a")
        shell.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(
            shell,
            text="Finance Tracker Pro",
            font=("Arial", 24, "bold"),
            bg="#12304a",
            fg="white",
        ).pack(pady=(0, 8))
        tk.Label(
            shell,
            text="Sign in to continue to your private dashboard",
            font=("Arial", 11),
            bg="#12304a",
            fg="#d7e5f2",
        ).pack(pady=(0, 18))

        card = tk.Frame(shell, bg="white", padx=28, pady=28, bd=0)
        card.pack()

        ttk.Button(card, text="Continue with Google", command=lambda: self.login_with_google(dialog)).pack(
            fill="x", pady=(0, 14)
        )

        tk.Label(card, text="or use your account", bg="white", fg="#5a6b7b", font=("Arial", 10)).pack(pady=(0, 10))

        tabs = ttk.Notebook(card, style="Login.TNotebook")
        tabs.pack(fill="both", expand=True)

        signin_tab = tk.Frame(tabs, bg="white", padx=14, pady=14)
        signup_tab = tk.Frame(tabs, bg="white", padx=14, pady=14)
        tabs.add(signin_tab, text="Sign In")
        tabs.add(signup_tab, text="Sign Up")

        tk.Label(
            signin_tab,
            text="Sign in with your username and password",
            bg="white",
            fg="#12304a",
            font=("Arial", 10, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        tk.Label(signin_tab, text="Username", bg="white", fg="black", anchor="w", font=("Arial", 10)).grid(
            row=1, column=0, sticky="w", pady=6
        )
        tk.Entry(
            signin_tab,
            textvariable=self.signin_username_var,
            width=32,
            bg="white",
            fg="black",
            insertbackground="black",
        ).grid(row=2, column=0, sticky="ew", pady=(0, 8))
        tk.Label(signin_tab, text="Password", bg="white", fg="black", anchor="w", font=("Arial", 10)).grid(
            row=3, column=0, sticky="w", pady=6
        )
        tk.Entry(
            signin_tab,
            textvariable=self.signin_password_var,
            width=32,
            show="*",
            bg="white",
            fg="black",
            insertbackground="black",
        ).grid(row=4, column=0, sticky="ew", pady=(0, 12))
        ttk.Button(signin_tab, text="Sign In", command=lambda: self.login_with_password(dialog)).grid(
            row=5, column=0, sticky="ew"
        )

        tk.Label(
            signup_tab,
            text="Create a new account",
            bg="white",
            fg="#12304a",
            font=("Arial", 10, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        tk.Label(signup_tab, text="Full Name", bg="white", fg="black", anchor="w", font=("Arial", 10)).grid(
            row=1, column=0, sticky="w", pady=6
        )
        tk.Entry(
            signup_tab,
            textvariable=self.signup_name_var,
            width=32,
            bg="white",
            fg="black",
            insertbackground="black",
        ).grid(row=2, column=0, sticky="ew", pady=(0, 8))
        tk.Label(signup_tab, text="Username", bg="white", fg="black", anchor="w", font=("Arial", 10)).grid(
            row=3, column=0, sticky="w", pady=6
        )
        tk.Entry(
            signup_tab,
            textvariable=self.signup_username_var,
            width=32,
            bg="white",
            fg="black",
            insertbackground="black",
        ).grid(row=4, column=0, sticky="ew", pady=(0, 8))
        tk.Label(signup_tab, text="Password", bg="white", fg="black", anchor="w", font=("Arial", 10)).grid(
            row=5, column=0, sticky="w", pady=6
        )
        tk.Entry(
            signup_tab,
            textvariable=self.signup_password_var,
            width=32,
            show="*",
            bg="white",
            fg="black",
            insertbackground="black",
        ).grid(row=6, column=0, sticky="ew", pady=(0, 12))
        ttk.Button(signup_tab, text="Create Account", command=self.sign_up_user).grid(row=7, column=0, sticky="ew")

        tk.Label(
            card,
            text="Guest mode is temporary and does not save data.",
            bg="white",
            fg="#5a6b7b",
            font=("Arial", 9),
        ).pack(pady=(14, 6))
        ttk.Button(card, text="Continue as Guest", command=lambda: self.login_as_guest(dialog)).pack(fill="x")

        dialog.protocol("WM_DELETE_WINDOW", self.close_app)

    def login_with_google(self, dialog):
        if not CLIENT_ID or not CLIENT_SECRET:
            messagebox.showerror("Login Error", "Google login is not configured. Add credentials to the .env file.")
            return

        client_config = {
            "installed": {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }

        try:
            flow = InstalledAppFlow.from_client_config(client_config, GOOGLE_SCOPES)
            credentials = flow.run_local_server(port=0)
            TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
            user = self.get_google_user(credentials.token)

            self.user_name = user.get("name", "Google User")
            self.user_email = user.get("email", "")
            self.user_role = "user"
            self.save_user(self.user_email, self.user_name, "user")
            self.claim_legacy_data(self.user_email)
            self.finish_login(dialog, self.user_name, self.user_email, "user")
        except Exception as error:
            messagebox.showerror("Login Error", f"Google login failed.\n\n{error}")

    def login_as_guest(self, dialog):
        self.user_name = "Guest"
        self.user_email = ""
        self.user_role = "guest"
        self.guest_transactions = []
        self.guest_budgets = {}
        self.finish_login(dialog, "Guest", "", "guest")

    def login_with_password(self, dialog):
        username = self.signin_username_var.get().strip()
        password = self.signin_password_var.get()

        if not username or not password:
            messagebox.showerror("Login Error", "Enter username and password")
            return

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            self.user_name = "Admin"
            self.user_email = f"local:{ADMIN_USERNAME}"
            self.user_role = "admin"
            self.save_user(self.user_email, "Admin", "admin", ADMIN_USERNAME, ADMIN_PASSWORD)
            self.finish_login(dialog, "Admin", ADMIN_USERNAME, "admin")
            return

        row = self.conn.execute(
            "SELECT email, name, role, password FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if not row or row[3] != password:
            messagebox.showerror("Login Error", "Invalid username or password")
            return

        self.user_name = row[1] or username
        self.user_email = row[0]
        self.user_role = row[2] or "user"
        self.finish_login(dialog, self.user_name, username, self.user_role)

    def sign_up_user(self):
        name = self.signup_name_var.get().strip()
        username = self.signup_username_var.get().strip()
        password = self.signup_password_var.get()

        if not name or not username or not password:
            messagebox.showerror("Sign Up Error", "Enter name, username, and password")
            return

        if username == ADMIN_USERNAME:
            messagebox.showerror("Sign Up Error", "This username is reserved")
            return

        existing = self.conn.execute(
            "SELECT 1 FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if existing:
            messagebox.showerror("Sign Up Error", "Username already exists")
            return

        owner_key = f"local:{username}"
        self.save_user(owner_key, name, "user", username, password)
        self.signup_name_var.set("")
        self.signup_username_var.set("")
        self.signup_password_var.set("")
        messagebox.showinfo("Sign Up", "Account created. You can sign in now.")

    def finish_login(self, dialog, name, email, role):
        self.login_var.set(f"User: {name}" if email else f"User: {name}")
        if role == "guest":
            self.mode_var.set("Mode: Guest (data is not saved)")
        elif role == "admin":
            self.mode_var.set("Mode: Admin")
        else:
            self.mode_var.set(f"Mode: Logged in as {email}")

        self.set_dashboard_enabled(True)
        self.update_admin_visibility()
        self.refresh_menu()
        self.load_months()
        self.refresh_data()
        self.root.deiconify()
        self.root.lift()
        self.show_page("admin" if role == "admin" else "home")
        self.login_screen = None
        self.signin_password_var.set("")
        dialog.destroy()

    def get_google_user(self, token):
        api_request = request.Request(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"},
        )
        with request.urlopen(api_request, timeout=20) as response:
            return json.load(response)

    def save_user(self, email, name, role, username=None, password=None):
        self.conn.execute(
            "INSERT INTO users (email, name, role, username, password) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(email) DO UPDATE SET name=excluded.name, role=excluded.role, username=excluded.username, password=excluded.password",
            (email, name, role, username, password),
        )
        self.conn.commit()

    def claim_legacy_data(self, email):
        user_rows = self.conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE owner_email = ?",
            (email,),
        ).fetchone()[0]
        legacy_rows = self.conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE owner_email IS NULL OR owner_email = ''",
        ).fetchone()[0]

        if user_rows == 0 and legacy_rows > 0:
            self.conn.execute(
                "UPDATE transactions SET owner_email = ? WHERE owner_email IS NULL OR owner_email = ''",
                (email,),
            )

        user_budgets = self.conn.execute(
            "SELECT COUNT(*) FROM budgets WHERE owner_email = ?",
            (email,),
        ).fetchone()[0]
        legacy_budgets = self.conn.execute(
            "SELECT COUNT(*) FROM budgets WHERE owner_email = 'legacy@local' OR owner_email IS NULL OR owner_email = ''",
        ).fetchone()[0]

        if user_budgets == 0 and legacy_budgets > 0:
            self.conn.execute(
                "UPDATE budgets SET owner_email = ? WHERE owner_email = 'legacy@local' OR owner_email IS NULL OR owner_email = ''",
                (email,),
            )

        self.conn.commit()

    def logout_user(self):
        self.user_name = ""
        self.user_email = ""
        self.user_role = ""
        self.login_var.set("Please log in to continue")
        self.mode_var.set("Mode: Locked")
        self.guest_transactions = []
        self.guest_budgets = {}
        self.signin_username_var.set("")
        self.signin_password_var.set("")

        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()

        self.set_dashboard_enabled(False)
        self.update_admin_visibility()
        self.refresh_menu()
        self.clear_dashboard()
        self.show_login_screen()

    def clear_dashboard(self):
        self.tree.delete(*self.tree.get_children())
        self.budget_info.delete("1.0", tk.END)
        self.income_label.config(text="Income: Rs 0")
        self.expense_label.config(text="Expense: Rs 0")
        self.balance_label.config(text="Balance: Rs 0")
        self.month_box["values"] = []
        self.month_var.set("")

    def get_owner_filter(self):
        if self.user_role == "admin":
            return None
        if self.user_role == "guest":
            return "guest"
        return self.user_email

    def add_transaction(self):
        try:
            amount = float(self.amount_var.get())
            if amount <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Enter a valid amount greater than 0")
            return

        date_text = self.date_var.get().strip()
        try:
            datetime.strptime(date_text, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Error", "Use date format YYYY-MM-DD")
            return

        record = (
            self.type_var.get(),
            self.category_var.get(),
            amount,
            date_text,
            self.note_var.get().strip(),
        )

        if self.user_role == "guest":
            self.guest_transactions.append(record)
        else:
            self.conn.execute(
                "INSERT INTO transactions (owner_email, entry_type, category, amount, entry_date, note) VALUES (?, ?, ?, ?, ?, ?)",
                (self.user_email, *record),
            )
            self.conn.commit()

        self.amount_var.set("")
        self.note_var.set("")
        self.load_months(date_text[:7])
        self.refresh_data()
        messagebox.showinfo("Saved", "Record added")

    def save_budget(self):
        try:
            amount = float(self.budget_amount_var.get())
            if amount <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Enter a valid budget amount")
            return

        category = self.budget_category_var.get()

        if self.user_role == "guest":
            self.guest_budgets[category] = amount
        else:
            self.conn.execute(
                "INSERT INTO budgets (owner_email, category, amount) VALUES (?, ?, ?) "
                "ON CONFLICT(owner_email, category) DO UPDATE SET amount=excluded.amount",
                (self.user_email, category, amount),
            )
            self.conn.commit()

        self.budget_amount_var.set("")
        self.refresh_data()
        messagebox.showinfo("Saved", "Budget saved")

    def load_months(self, selected=None):
        if self.user_role == "guest":
            months = sorted({row[3][:7] for row in self.guest_transactions}, reverse=True)
            months = months or [datetime.today().strftime("%Y-%m")]
        elif self.user_role == "admin":
            rows = self.conn.execute(
                "SELECT DISTINCT substr(entry_date, 1, 7) AS month FROM transactions ORDER BY month DESC"
            ).fetchall()
            months = [row[0] for row in rows] or [datetime.today().strftime("%Y-%m")]
        else:
            rows = self.conn.execute(
                "SELECT DISTINCT substr(entry_date, 1, 7) AS month FROM transactions "
                "WHERE owner_email = ? ORDER BY month DESC",
                (self.user_email,),
            ).fetchall()
            months = [row[0] for row in rows] or [datetime.today().strftime("%Y-%m")]

        self.month_box["values"] = months

        if selected and selected in months:
            self.month_var.set(selected)
        elif self.month_var.get() not in months:
            self.month_var.set(months[0])

    def get_transactions_for_month(self, month):
        if self.user_role == "guest":
            return [row for row in self.guest_transactions if row[3][:7] == month]

        if self.user_role == "admin":
            return self.conn.execute(
                "SELECT entry_type, category, amount, entry_date, COALESCE(note, '') "
                "FROM transactions WHERE substr(entry_date, 1, 7) = ? ORDER BY entry_date DESC, id DESC",
                (month,),
            ).fetchall()

        return self.conn.execute(
            "SELECT entry_type, category, amount, entry_date, COALESCE(note, '') "
            "FROM transactions WHERE owner_email = ? AND substr(entry_date, 1, 7) = ? "
            "ORDER BY entry_date DESC, id DESC",
            (self.user_email, month),
        ).fetchall()

    def get_budgets(self):
        if self.user_role == "guest":
            return list(self.guest_budgets.items())

        if self.user_role == "admin":
            return self.conn.execute(
                "SELECT category, amount FROM budgets ORDER BY owner_email, category"
            ).fetchall()

        return self.conn.execute(
            "SELECT category, amount FROM budgets WHERE owner_email = ? ORDER BY category",
            (self.user_email,),
        ).fetchall()

    def refresh_data(self):
        month = self.month_var.get()
        rows = self.get_transactions_for_month(month)

        self.tree.delete(*self.tree.get_children())

        income = 0
        expense = 0
        category_expense = {}

        for entry_type, category, amount, entry_date, note in rows:
            self.tree.insert("", "end", values=(entry_date, entry_type, category, amount, note))

            if entry_type == "Income":
                income += amount
            else:
                expense += amount
                category_expense[category] = category_expense.get(category, 0) + amount

        self.income_label.config(text=f"Income: Rs {income:.2f}")
        self.expense_label.config(text=f"Expense: Rs {expense:.2f}")
        self.balance_label.config(text=f"Balance: Rs {income - expense:.2f}")

        budgets = self.get_budgets()
        self.budget_info.delete("1.0", tk.END)
        self.refresh_budget_list(budgets)

        if not budgets:
            self.budget_info.insert(tk.END, "No budgets set yet.")
            return

        for category, budget in budgets:
            left = budget - category_expense.get(category, 0)
            if left < 0:
                self.budget_info.insert(tk.END, f"{category}: Over by Rs {abs(left):.2f}\n")
            else:
                self.budget_info.insert(tk.END, f"{category}: Rs {left:.2f} left of Rs {budget:.2f}\n")

    def refresh_budget_list(self, budgets):
        self.budget_list.delete("1.0", tk.END)

        if not budgets:
            self.budget_list.insert(tk.END, "No budgets saved yet.")
            return

        for category, amount in budgets:
            self.budget_list.insert(tk.END, f"{category}: Rs {amount:.2f}\n")

    def get_expense_totals(self, month):
        if self.user_role == "guest":
            totals = {}
            for entry_type, category, amount, entry_date, note in self.guest_transactions:
                if entry_type == "Expense" and entry_date[:7] == month:
                    totals[category] = totals.get(category, 0) + amount
            return sorted(totals.items(), key=lambda item: item[1], reverse=True)

        if self.user_role == "admin":
            return self.conn.execute(
                "SELECT category, SUM(amount) FROM transactions "
                "WHERE entry_type = 'Expense' AND substr(entry_date, 1, 7) = ? "
                "GROUP BY category ORDER BY SUM(amount) DESC",
                (month,),
            ).fetchall()

        return self.conn.execute(
            "SELECT category, SUM(amount) FROM transactions "
            "WHERE owner_email = ? AND entry_type = 'Expense' AND substr(entry_date, 1, 7) = ? "
            "GROUP BY category ORDER BY SUM(amount) DESC",
            (self.user_email, month),
        ).fetchall()

    def show_graph(self):
        month = self.month_var.get()
        rows = self.get_expense_totals(month)

        if not rows:
            messagebox.showinfo("Graph", "No expense data available for this month")
            return

        categories = [row[0] for row in rows]
        amounts = [row[1] for row in rows]

        graph_window = tk.Toplevel(self.root)
        graph_window.title(f"Monthly Expense Graph - {month}")
        graph_window.geometry("760x500")

        tk.Label(
            graph_window,
            text=f"Expense by Category ({month})",
            font=("Arial", 14, "bold"),
            pady=10,
        ).pack()

        figure = Figure(figsize=(7, 4), dpi=100)
        chart = figure.add_subplot(111)
        chart.bar(categories, amounts, color="#2f7ed8")
        chart.set_title("Monthly Expenses")
        chart.set_xlabel("Category")
        chart.set_ylabel("Amount (Rs)")
        chart.tick_params(axis="x", rotation=25)
        figure.tight_layout()

        canvas = FigureCanvasTkAgg(figure, master=graph_window)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

    def show_income_expense_graph(self):
        month = self.month_var.get()
        rows = self.get_transactions_for_month(month)

        if not rows:
            messagebox.showinfo("Graph", "No data available for this month")
            return

        income = 0
        expense = 0
        for entry_type, category, amount, entry_date, note in rows:
            if entry_type == "Income":
                income += amount
            else:
                expense += amount

        graph_window = tk.Toplevel(self.root)
        graph_window.title(f"Income vs Expense - {month}")
        graph_window.geometry("700x480")

        tk.Label(
            graph_window,
            text=f"Income vs Expense ({month})",
            font=("Arial", 14, "bold"),
            pady=10,
        ).pack()

        figure = Figure(figsize=(6.5, 4), dpi=100)
        chart = figure.add_subplot(111)
        chart.bar(["Income", "Expense"], [income, expense], color=["#2e8b57", "#c94c4c"])
        chart.set_title("Monthly Comparison")
        chart.set_ylabel("Amount (Rs)")
        figure.tight_layout()

        canvas = FigureCanvasTkAgg(figure, master=graph_window)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

    def export_csv(self):
        month = self.month_var.get()
        rows = self.get_transactions_for_month(month)

        if not rows:
            messagebox.showinfo("Info", "No data to export")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV file", "*.csv")],
            initialfile=f"finance_{month}.csv",
        )
        if not path:
            return

        with open(path, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["Date", "Type", "Category", "Amount", "Note"])
            for entry_type, category, amount, entry_date, note in rows:
                writer.writerow([entry_date, entry_type, category, amount, note])

        messagebox.showinfo("Done", "CSV exported")

    def open_admin_panel(self):
        if self.user_role != "admin":
            return

        panel = tk.Toplevel(self.root)
        panel.title("Admin Panel")
        panel.geometry("560x380")

        tk.Label(panel, text="Users", font=("Arial", 14, "bold")).pack(pady=10)

        columns = ("email", "name", "role")
        tree = ttk.Treeview(panel, columns=columns, show="headings", height=12)
        for column, width in zip(columns, [220, 160, 100]):
            tree.heading(column, text=column.title())
            tree.column(column, width=width)
        tree.pack(fill="both", expand=True, padx=10)

        self.fill_user_tree(tree)

        buttons = tk.Frame(panel)
        buttons.pack(fill="x", pady=10)
        ttk.Button(buttons, text="Rename User", command=lambda: self.rename_user(tree)).pack(side="left", padx=8)
        ttk.Button(buttons, text="Delete User", command=lambda: self.delete_user(tree)).pack(side="left", padx=8)
        ttk.Button(buttons, text="Refresh", command=lambda: self.fill_user_tree(tree)).pack(side="left", padx=8)

    def fill_user_tree(self, tree):
        tree.delete(*tree.get_children())
        rows = self.conn.execute("SELECT email, name, role FROM users ORDER BY name, email").fetchall()
        for row in rows:
            tree.insert("", "end", values=row)

    def rename_user(self, tree):
        selected = tree.selection()
        if not selected:
            messagebox.showinfo("Admin", "Select a user first")
            return

        email, name, role = tree.item(selected[0], "values")
        new_name = simpledialog.askstring("Rename User", f"New name for {email}:", initialvalue=name, parent=tree)
        if not new_name:
            return

        self.conn.execute("UPDATE users SET name = ? WHERE email = ?", (new_name, email))
        self.conn.commit()
        self.fill_user_tree(tree)

    def delete_user(self, tree):
        selected = tree.selection()
        if not selected:
            messagebox.showinfo("Admin", "Select a user first")
            return

        email, name, role = tree.item(selected[0], "values")
        if not messagebox.askyesno("Delete User", f"Delete {email} and all saved data?"):
            return

        self.conn.execute("DELETE FROM transactions WHERE owner_email = ?", (email,))
        self.conn.execute("DELETE FROM budgets WHERE owner_email = ?", (email,))
        self.conn.execute("DELETE FROM users WHERE email = ?", (email,))
        self.conn.commit()
        self.fill_user_tree(tree)
        self.refresh_data()

    def close_app(self):
        self.conn.close()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    FinanceApp(root)
    root.mainloop()
