"""Storage and accounting rules for Workshop Ledger.

All money is represented as integer minor units (e.g. USD cents).
Quantities are whole units. This release is cash-only and single-currency.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import os
import csv
from decimal import Decimal, InvalidOperation


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_database_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        directory = Path(base) / "WorkshopLedger"
    else:
        directory = Path.home() / ".workshop_ledger"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "workshop.sqlite3"


def positive_int(value: int, label: str = "Quantity") -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive whole number.")
    return value


def valid_money(value: int, label: str = "Amount", *, zero_ok: bool = False) -> int:
    if type(value) is not int or (value < 0 if zero_ok else value <= 0):
        raise ValueError(f"{label} must be {'zero or greater' if zero_ok else 'greater than zero'}.")
    return value


def required_text(text: str, label: str) -> str:
    cleaned = str(text).strip()
    if not cleaned:
        raise ValueError(f"{label} is required.")
    return cleaned


class Database:
    def __init__(self, path: str | Path | None = None):
        self.path = str(default_database_path() if path is None else path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, isolation_level=None, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 15000")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def close(self):
        self.conn.close()

    @contextmanager
    def transaction(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    def _create_schema(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            sku TEXT NOT NULL COLLATE NOCASE UNIQUE,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'Parts',
            unit TEXT NOT NULL DEFAULT 'pcs',
            qty INTEGER NOT NULL DEFAULT 0 CHECK(qty >= 0),
            avg_cost_cents INTEGER NOT NULL DEFAULT 0 CHECK(avg_cost_cents >= 0),
            sale_price_cents INTEGER NOT NULL DEFAULT 0 CHECK(sale_price_cents >= 0),
            min_stock INTEGER NOT NULL DEFAULT 0 CHECK(min_stock >= 0),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY,
            customer TEXT NOT NULL,
            vehicle TEXT NOT NULL,
            engine TEXT NOT NULL DEFAULT '',
            work_type TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            quote_cents INTEGER NOT NULL DEFAULT 0 CHECK(quote_cents >= 0),
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','done')),
            created_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY,
            product_id INTEGER NOT NULL REFERENCES products(id),
            qty INTEGER NOT NULL CHECK(qty > 0),
            unit_cost_cents INTEGER NOT NULL CHECK(unit_cost_cents >= 0),
            total_cents INTEGER NOT NULL CHECK(total_cents >= 0),
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL CHECK(kind IN ('part','service')),
            product_id INTEGER REFERENCES products(id),
            job_id INTEGER REFERENCES jobs(id),
            description TEXT NOT NULL,
            qty INTEGER NOT NULL CHECK(qty > 0),
            unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents >= 0),
            revenue_cents INTEGER NOT NULL CHECK(revenue_cents > 0),
            cogs_cents INTEGER NOT NULL CHECK(cogs_cents >= 0),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cash_entries (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL CHECK(kind IN (
                'owner_funding','owner_draw','purchase','part_sale','service','expense','customer_payment'
            )),
            ref_table TEXT NOT NULL DEFAULT '',
            ref_id INTEGER,
            description TEXT NOT NULL,
            delta_cents INTEGER NOT NULL CHECK(delta_cents != 0),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stock_movements (
            id INTEGER PRIMARY KEY,
            product_id INTEGER NOT NULL REFERENCES products(id),
            kind TEXT NOT NULL CHECK(kind IN ('purchase','sale')),
            delta_qty INTEGER NOT NULL CHECK(delta_qty != 0),
            ref_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_sales_created ON sales(created_at);
        CREATE INDEX IF NOT EXISTS ix_cash_created ON cash_entries(created_at);
        CREATE INDEX IF NOT EXISTS ix_stock_product ON stock_movements(product_id);
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS work_orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES customers(id),
            vehicle TEXT NOT NULL DEFAULT '',
            engine_model TEXT NOT NULL,
            engine_number TEXT NOT NULL DEFAULT '',
            cylinder_count INTEGER NOT NULL DEFAULT 0 CHECK(cylinder_count BETWEEN 0 AND 32),
            notes TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','ready','delivered')),
            billed_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS work_order_lines (
            id INTEGER PRIMARY KEY,
            work_order_id INTEGER NOT NULL REFERENCES work_orders(id),
            description TEXT NOT NULL,
            qty INTEGER NOT NULL CHECK(qty > 0),
            unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents >= 0),
            estimated_cost_cents INTEGER NOT NULL DEFAULT 0 CHECK(estimated_cost_cents >= 0),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS customer_entries (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES customers(id),
            work_order_id INTEGER REFERENCES work_orders(id),
            kind TEXT NOT NULL CHECK(kind IN ('charge','payment','opening_debt','discount','opening_discount')),
            description TEXT NOT NULL,
            amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS legacy_customer_refs (
            id INTEGER PRIMARY KEY,
            book_name TEXT NOT NULL DEFAULT 'دفتر الزبائن',
            legacy_page TEXT NOT NULL,
            customer_id INTEGER NOT NULL REFERENCES customers(id),
            UNIQUE(book_name, legacy_page)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ix_one_bill_per_order
          ON customer_entries(work_order_id) WHERE kind='charge' AND work_order_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS ix_customers_name ON customers(name);
        CREATE INDEX IF NOT EXISTS ix_orders_customer ON work_orders(customer_id);
        CREATE INDEX IF NOT EXISTS ix_customer_entries_customer ON customer_entries(customer_id,id);
        """)
        # Upgrade existing v1 databases safely. SQLite cannot ALTER a CHECK clause.
        # Cash entries have no inbound foreign keys and their IDs are preserved.
        old_schema = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='cash_entries'"
        ).fetchone()[0]
        if "customer_payment" not in old_schema:
            with self.transaction():
                self.conn.execute("""CREATE TABLE cash_entries_new (
                    id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL CHECK(kind IN
                     ('owner_funding','owner_draw','purchase','part_sale','service','expense','customer_payment')),
                    ref_table TEXT NOT NULL DEFAULT '', ref_id INTEGER,
                    description TEXT NOT NULL,
                    delta_cents INTEGER NOT NULL CHECK(delta_cents != 0),
                    created_at TEXT NOT NULL
                )""")
                self.conn.execute("""INSERT INTO cash_entries_new
                    (id,kind,ref_table,ref_id,description,delta_cents,created_at)
                    SELECT id,kind,ref_table,ref_id,description,delta_cents,created_at
                    FROM cash_entries""")
                self.conn.execute("DROP TABLE cash_entries")
                self.conn.execute("ALTER TABLE cash_entries_new RENAME TO cash_entries")
                self.conn.execute("CREATE INDEX IF NOT EXISTS ix_cash_created ON cash_entries(created_at)")

        # v3: retain all previous invoices, payments, IDs and links.  A rebuild of
        # customer_entries is required because SQLite cannot alter a CHECK clause.
        cols = {r['name'] for r in self.conn.execute('PRAGMA table_info(work_orders)')}
        if 'cylinder_count' not in cols:
            with self.transaction():
                self.conn.execute("ALTER TABLE work_orders ADD COLUMN cylinder_count INTEGER NOT NULL DEFAULT 0 CHECK(cylinder_count BETWEEN 0 AND 32)")
        ce_schema = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='customer_entries'"
        ).fetchone()[0]
        if 'opening_discount' not in ce_schema:
            with self.transaction():
                self.conn.execute("""CREATE TABLE customer_entries_v3 (
                    id INTEGER PRIMARY KEY,
                    customer_id INTEGER NOT NULL REFERENCES customers(id),
                    work_order_id INTEGER REFERENCES work_orders(id),
                    kind TEXT NOT NULL CHECK(kind IN
                      ('charge','payment','opening_debt','discount','opening_discount')),
                    description TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
                    created_at TEXT NOT NULL
                )""")
                self.conn.execute("""INSERT INTO customer_entries_v3
                    (id,customer_id,work_order_id,kind,description,amount_cents,created_at)
                    SELECT id,customer_id,work_order_id,kind,description,amount_cents,created_at
                    FROM customer_entries""")
                self.conn.execute("DROP TABLE customer_entries")
                self.conn.execute("ALTER TABLE customer_entries_v3 RENAME TO customer_entries")
                self.conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS ix_one_bill_per_order
                    ON customer_entries(work_order_id)
                    WHERE kind='charge' AND work_order_id IS NOT NULL""")
                self.conn.execute("""CREATE INDEX IF NOT EXISTS ix_customer_entries_customer
                    ON customer_entries(customer_id,id)""")

    def get_currency(self) -> str:
        row=self.conn.execute("SELECT value FROM app_settings WHERE key='currency'").fetchone()
        return row[0] if row and row[0] in ('USD','SYP') else 'USD'

    def set_currency(self, currency: str):
        if currency not in ('USD','SYP'):
            raise ValueError('Currency must be USD or SYP.')
        with self.transaction():
            self.conn.execute("""INSERT INTO app_settings(key,value) VALUES ('currency',?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",(currency,))

    def _cash(self, kind: str, description: str, delta: int, timestamp: str,
              ref_table: str = "", ref_id: int | None = None):
        if delta == 0:
            # Purchases of donated stock still get a stock movement; no cash movement.
            return
        self.conn.execute("""INSERT INTO cash_entries
            (kind,ref_table,ref_id,description,delta_cents,created_at)
            VALUES (?,?,?,?,?,?)""", (kind, ref_table, ref_id, description, delta, timestamp))

    def add_product(self, sku: str, name: str, category: str = "Parts",
                    unit: str = "pcs", sale_price_cents: int = 0,
                    min_stock: int = 0) -> int:
        sku = required_text(sku, "SKU")
        name = required_text(name, "Product name")
        category = required_text(category, "Category")
        unit = required_text(unit, "Unit")
        valid_money(sale_price_cents, "Sale price", zero_ok=True)
        if type(min_stock) is not int or min_stock < 0:
            raise ValueError("Minimum stock must be zero or greater.")
        with self.transaction():
            cursor = self.conn.execute("""INSERT INTO products
                (sku,name,category,unit,sale_price_cents,min_stock,created_at)
                VALUES (?,?,?,?,?,?,?)""",
                (sku,name,category,unit,sale_price_cents,min_stock,now_utc()))
            return cursor.lastrowid

    def edit_product(self, product_id: int, sku: str, name: str, category: str,
                     unit: str, sale_price_cents: int, min_stock: int):
        sku = required_text(sku, "SKU")
        name = required_text(name, "Product name")
        category = required_text(category, "Category")
        unit = required_text(unit, "Unit")
        valid_money(sale_price_cents, "Sale price", zero_ok=True)
        if type(min_stock) is not int or min_stock < 0:
            raise ValueError("Minimum stock must be zero or greater.")
        with self.transaction():
            cur = self.conn.execute("""UPDATE products SET
                sku=?,name=?,category=?,unit=?,sale_price_cents=?,min_stock=?
                WHERE id=?""", (sku,name,category,unit,sale_price_cents,min_stock,product_id))
            if not cur.rowcount:
                raise ValueError("Product does not exist.")

    def get_product(self, product_id: int):
        return self.conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()

    def list_products(self):
        return self.conn.execute("SELECT * FROM products ORDER BY name COLLATE NOCASE, id").fetchall()

    def purchase_stock(self, product_id: int, qty: int, unit_cost_cents: int,
                       note: str = "") -> int:
        positive_int(qty)
        valid_money(unit_cost_cents, "Unit cost", zero_ok=True)
        with self.transaction():
            product = self.get_product(product_id)
            if product is None:
                raise ValueError("Product does not exist.")
            old_qty, old_cost = product["qty"], product["avg_cost_cents"]
            new_qty = old_qty + qty
            # Weighted average of stocked units, rounded half up to one cent.
            new_cost = (old_qty * old_cost + qty * unit_cost_cents + new_qty // 2) // new_qty
            total = qty * unit_cost_cents
            stamp = now_utc()
            cur = self.conn.execute("""INSERT INTO purchases
                (product_id,qty,unit_cost_cents,total_cents,note,created_at)
                VALUES (?,?,?,?,?,?)""", (product_id,qty,unit_cost_cents,total,str(note).strip(),stamp))
            self.conn.execute("UPDATE products SET qty=?,avg_cost_cents=? WHERE id=?",
                              (new_qty,new_cost,product_id))
            self.conn.execute("""INSERT INTO stock_movements
                (product_id,kind,delta_qty,ref_id,created_at) VALUES (?,'purchase',?,?,?)""",
                (product_id,qty,cur.lastrowid,stamp))
            self._cash("purchase", f"Stock: {qty} × {product['name']}", -total,
                       stamp, "purchases", cur.lastrowid)
            return cur.lastrowid

    def add_job(self, customer: str, vehicle: str, engine: str,
                work_type: str, notes: str = "", quote_cents: int = 0) -> int:
        customer = required_text(customer,"Customer")
        vehicle = required_text(vehicle,"Vehicle")
        work_type = required_text(work_type,"Work type")
        valid_money(quote_cents,"Quote",zero_ok=True)
        with self.transaction():
            cur = self.conn.execute("""INSERT INTO jobs
                (customer,vehicle,engine,work_type,notes,quote_cents,created_at)
                VALUES (?,?,?,?,?,?,?)""", (customer,vehicle,str(engine).strip(),work_type,
                                            str(notes).strip(),quote_cents,now_utc()))
            return cur.lastrowid

    def set_job_status(self, job_id: int, status: str):
        if status not in ("open", "done"):
            raise ValueError("Invalid job status.")
        with self.transaction():
            cur = self.conn.execute("UPDATE jobs SET status=?, completed_at=? WHERE id=?",
                                    (status,now_utc() if status == "done" else None,job_id))
            if not cur.rowcount:
                raise ValueError("Job not found.")

    def list_jobs(self):
        return self.conn.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()

    def sell_part(self, product_id: int, qty: int, unit_price_cents: int,
                  job_id: int | None = None) -> int:
        positive_int(qty)
        valid_money(unit_price_cents,"Unit sale price")
        with self.transaction():
            product = self.get_product(product_id)
            if product is None:
                raise ValueError("Product does not exist.")
            if product["qty"] < qty:
                raise ValueError(f"Insufficient stock. Only {product['qty']} available.")
            revenue = unit_price_cents * qty
            cogs = product["avg_cost_cents"] * qty
            stamp = now_utc()
            cur = self.conn.execute("""INSERT INTO sales
                (kind,product_id,job_id,description,qty,unit_price_cents,revenue_cents,cogs_cents,created_at)
                VALUES ('part',?,?,?,?,?,?,?,?)""",
                (product_id,job_id,product["name"],qty,unit_price_cents,revenue,cogs,stamp))
            self.conn.execute("UPDATE products SET qty=qty-? WHERE id=?",(qty,product_id))
            self.conn.execute("""INSERT INTO stock_movements
                (product_id,kind,delta_qty,ref_id,created_at) VALUES (?,'sale',?,?,?)""",
                (product_id,-qty,cur.lastrowid,stamp))
            self._cash("part_sale",f"Part sale: {qty} × {product['name']}",revenue,
                       stamp,"sales",cur.lastrowid)
            return cur.lastrowid

    def record_service(self, description: str, amount_cents: int,
                       job_id: int | None = None) -> int:
        description = required_text(description,"Service description")
        valid_money(amount_cents,"Service amount")
        with self.transaction():
            stamp = now_utc()
            cur = self.conn.execute("""INSERT INTO sales
                (kind,product_id,job_id,description,qty,unit_price_cents,revenue_cents,cogs_cents,created_at)
                VALUES ('service',NULL,?,?,1,?,?,0,?)""",
                (job_id,description,amount_cents,amount_cents,stamp))
            self._cash("service",f"Service: {description}",amount_cents,
                       stamp,"sales",cur.lastrowid)
            return cur.lastrowid

    def record_expense(self, category: str, description: str, amount_cents: int) -> int:
        category = required_text(category,"Category")
        description = required_text(description,"Expense description")
        valid_money(amount_cents,"Expense amount")
        with self.transaction():
            stamp = now_utc()
            cur = self.conn.execute("""INSERT INTO expenses
                (category,description,amount_cents,created_at) VALUES (?,?,?,?)""",
                (category,description,amount_cents,stamp))
            self._cash("expense",f"{category}: {description}",-amount_cents,
                       stamp,"expenses",cur.lastrowid)
            return cur.lastrowid

    def owner_cash(self, amount_cents: int, kind: str, note: str = "") -> int:
        valid_money(amount_cents,"Cash amount")
        if kind not in ("owner_funding","owner_draw"):
            raise ValueError("Unsupported cash adjustment.")
        delta = amount_cents if kind == "owner_funding" else -amount_cents
        with self.transaction():
            stamp = now_utc()
            self._cash(kind, note.strip() or ("Owner contribution" if delta > 0 else "Owner withdrawal"),
                       delta,stamp)
            return self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def stats(self) -> dict:
        r = self.conn.execute("""SELECT
            COALESCE((SELECT SUM(delta_cents) FROM cash_entries),0) AS cash,
            COALESCE((SELECT SUM(revenue_cents) FROM sales WHERE kind='part'),0) AS parts_revenue,
            COALESCE((SELECT SUM(revenue_cents) FROM sales WHERE kind='service'),0) AS service_revenue,
            COALESCE((SELECT SUM(cogs_cents) FROM sales),0) AS cogs,
            COALESCE((SELECT SUM(amount_cents) FROM expenses),0) AS expenses,
            COALESCE((SELECT SUM(qty*avg_cost_cents) FROM products),0) AS inventory_value,
            (SELECT COUNT(*) FROM products) AS product_count,
            (SELECT COUNT(*) FROM products WHERE qty <= min_stock) AS low_stock_count,
            (SELECT COUNT(*) FROM jobs WHERE status='open') AS open_jobs
        """).fetchone()
        d = dict(r)
        extra = self.conn.execute("""SELECT
          COALESCE(SUM(CASE WHEN kind='charge' THEN amount_cents
                            WHEN kind='discount' THEN -amount_cents ELSE 0 END),0) AS billed_revenue,
          COALESCE(SUM(CASE WHEN kind IN ('discount','opening_discount') THEN amount_cents ELSE 0 END),0) AS discounts_given,
          COALESCE(SUM(CASE WHEN kind IN ('charge','opening_debt') THEN amount_cents
                        WHEN kind IN ('payment','discount','opening_discount') THEN -amount_cents
                        ELSE 0 END),0) AS receivables
          FROM customer_entries""").fetchone()
        d["billed_revenue"] = extra["billed_revenue"]
        d["discounts_given"] = extra["discounts_given"]
        d["customer_receivables"] = extra["receivables"]
        d["customer_count"] = self.conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        d["revenue"] = d["parts_revenue"] + d["service_revenue"] + d["billed_revenue"]
        d["profit"] = d["revenue"] - d["cogs"] - d["expenses"]
        return d

    def list_sales(self, limit: int = 200):
        return self.conn.execute("""SELECT s.*,j.customer AS job_customer
            FROM sales s LEFT JOIN jobs j ON j.id=s.job_id
            ORDER BY s.id DESC LIMIT ?""",(limit,)).fetchall()

    def list_expenses(self, limit: int = 200):
        return self.conn.execute("SELECT * FROM expenses ORDER BY id DESC LIMIT ?",(limit,)).fetchall()

    def list_ledger(self, limit: int = 300):
        # Window function calculates the running balance BEFORE limiting rows.
        return self.conn.execute("""SELECT * FROM (
            SELECT *, SUM(delta_cents) OVER (ORDER BY id) AS running_balance_cents
            FROM cash_entries
        ) ORDER BY id DESC LIMIT ?""",(limit,)).fetchall()

    # --- Paper notebook equivalents (v2) ---
    # Customers index -> customer account -> detailed work book -> daily cash.
    def add_customer(self, name: str, phone: str = "", notes: str = "") -> int:
        name = required_text(name, "Customer name")
        with self.transaction():
            cur = self.conn.execute("""INSERT INTO customers(name,phone,notes,created_at)
                VALUES (?,?,?,?)""", (name,str(phone).strip(),str(notes).strip(),now_utc()))
            return cur.lastrowid

    def get_customer(self, customer_id: int):
        return self.conn.execute("SELECT * FROM customers WHERE id=?",(customer_id,)).fetchone()

    def customer_index(self, search: str = ""):
        pattern = '%' + search.strip().replace('!','!!').replace('%','!%').replace('_','!_') + '%'
        return self.conn.execute("""SELECT c.*,
          COALESCE((SELECT SUM(CASE WHEN kind IN ('charge','opening_debt') THEN amount_cents
                             ELSE -amount_cents END)
                    FROM customer_entries e WHERE e.customer_id=c.id),0) AS balance_cents,
          (SELECT COUNT(*) FROM work_orders w WHERE w.customer_id=c.id) AS order_count
          FROM customers c
          WHERE c.name LIKE ? ESCAPE '!' OR c.phone LIKE ? ESCAPE '!'
          ORDER BY c.id ASC""",(pattern,pattern)).fetchall()

    def create_work_order(self, customer_id: int, engine_model: str, vehicle: str = "",
                          engine_number: str = "", notes: str = "", cylinder_count: int = 0) -> int:
        engine_model = required_text(engine_model, "Engine model")
        if type(cylinder_count) is not int or not 0 <= cylinder_count <= 32:
            raise ValueError("Cylinder count must be between 1 and 32, or 0 if unknown.")
        with self.transaction():
            if not self.get_customer(customer_id):
                raise ValueError("Customer not found.")
            cur = self.conn.execute("""INSERT INTO work_orders
             (customer_id,vehicle,engine_model,engine_number,notes,cylinder_count,created_at)
             VALUES (?,?,?,?,?,?,?)""",(customer_id,str(vehicle).strip(),engine_model,
                       str(engine_number).strip(),str(notes).strip(),cylinder_count,now_utc()))
            return cur.lastrowid

    def get_work_order(self, order_id: int):
        return self.conn.execute("SELECT * FROM work_orders WHERE id=?",(order_id,)).fetchone()

    def list_work_orders(self, customer_id: int | None = None):
        query = """SELECT w.*,c.name AS customer_name,
            COALESCE((SELECT SUM(qty*unit_price_cents) FROM work_order_lines l
                      WHERE l.work_order_id=w.id),0) AS total_cents,
            COALESCE((SELECT SUM(qty*estimated_cost_cents) FROM work_order_lines l
                      WHERE l.work_order_id=w.id),0) AS estimated_cost_total_cents
            FROM work_orders w JOIN customers c ON c.id=w.customer_id"""
        if customer_id is not None:
            return self.conn.execute(query+" WHERE w.customer_id=? ORDER BY w.id DESC",(customer_id,)).fetchall()
        return self.conn.execute(query+" ORDER BY w.id DESC").fetchall()

    def list_work_order_lines(self, order_id: int):
        return self.conn.execute("""SELECT *,qty*unit_price_cents AS total_cents,
                 qty*estimated_cost_cents AS estimated_total_cents
                 FROM work_order_lines WHERE work_order_id=? ORDER BY id""",(order_id,)).fetchall()

    def add_work_order_line(self, order_id: int, description: str, qty: int,
                            unit_price_cents: int, estimated_cost_cents: int = 0) -> int:
        description = required_text(description,"Work description")
        positive_int(qty)
        valid_money(unit_price_cents,"Price",zero_ok=True)
        valid_money(estimated_cost_cents,"Estimated cost",zero_ok=True)
        with self.transaction():
            order = self.get_work_order(order_id)
            if not order:
                raise ValueError("Work order not found.")
            if order["billed_at"]:
                raise ValueError("Cannot change work items after posting the invoice.")
            cur = self.conn.execute("""INSERT INTO work_order_lines
               (work_order_id,description,qty,unit_price_cents,estimated_cost_cents,created_at)
               VALUES (?,?,?,?,?,?)""",(order_id,description,qty,unit_price_cents,
                                             estimated_cost_cents,now_utc()))
            return cur.lastrowid

    def remove_work_order_line(self, line_id: int):
        with self.transaction():
            item = self.conn.execute("""SELECT l.id,w.billed_at FROM work_order_lines l
               JOIN work_orders w ON w.id=l.work_order_id WHERE l.id=?""",(line_id,)).fetchone()
            if not item:
                raise ValueError("Work item not found.")
            if item['billed_at']:
                raise ValueError("Cannot remove a work item after billing.")
            self.conn.execute("DELETE FROM work_order_lines WHERE id=?",(line_id,))

    def change_work_order_status(self, order_id: int, status: str):
        if status not in ('open','ready','delivered'):
            raise ValueError('Invalid work order status.')
        with self.transaction():
            cur=self.conn.execute('UPDATE work_orders SET status=? WHERE id=?',(status,order_id))
            if not cur.rowcount:
                raise ValueError('Work order not found.')

    def post_work_order_bill(self, order_id: int) -> int:
        # Posting (not drafting) is what creates a customer debt and earned revenue.
        # Repeating the action is forbidden; collecting payment never creates revenue again.
        with self.transaction():
            order = self.get_work_order(order_id)
            if not order:
                raise ValueError("Work order not found.")
            if order["billed_at"]:
                raise ValueError("This work order is already billed.")
            total = self.conn.execute("""SELECT COALESCE(SUM(qty*unit_price_cents),0)
                         FROM work_order_lines WHERE work_order_id=?""",(order_id,)).fetchone()[0]
            if total <= 0:
                raise ValueError("Add at least one priced work item before billing.")
            stamp=now_utc()
            cur=self.conn.execute("""INSERT INTO customer_entries
               (customer_id,work_order_id,kind,description,amount_cents,created_at)
               VALUES (?,?,'charge',?,?,?)""",(order['customer_id'],order_id,
                f"Work order #{order_id} — {order['engine_model']}",total,stamp))
            self.conn.execute("UPDATE work_orders SET billed_at=? WHERE id=?",(stamp,order_id))
            return cur.lastrowid

    def add_customer_charge(self, customer_id: int, description: str, amount_cents: int,
                            *, opening_debt: bool = False) -> int:
        # Opening balances migrate old notebooks without inflating current-period sales.
        description=required_text(description,"Description")
        valid_money(amount_cents)
        with self.transaction():
            if not self.get_customer(customer_id):
                raise ValueError("Customer not found.")
            cur=self.conn.execute("""INSERT INTO customer_entries
              (customer_id,work_order_id,kind,description,amount_cents,created_at)
              VALUES (?,NULL,?,?,?,?)""",(customer_id,
               'opening_debt' if opening_debt else 'charge',description,amount_cents,now_utc()))
            return cur.lastrowid

    def receive_customer_payment(self, customer_id: int, amount_cents: int,
                                 description: str = "Payment received",
                                 work_order_id: int | None = None) -> int:
        valid_money(amount_cents)
        with self.transaction():
            customer=self.get_customer(customer_id)
            if not customer:
                raise ValueError("Customer not found.")
            if work_order_id is not None:
                order=self.get_work_order(work_order_id)
                if order is None or order["customer_id"] != customer_id:
                    raise ValueError("Work order does not belong to this customer.")
            stamp=now_utc()
            desc=required_text(description,"Payment description")
            cur=self.conn.execute("""INSERT INTO customer_entries
              (customer_id,work_order_id,kind,description,amount_cents,created_at)
              VALUES (?,?,'payment',?,?,?)""",(customer_id,work_order_id,desc,amount_cents,stamp))
            self._cash("customer_payment",f"{customer['name']}: {desc}",amount_cents,
                       stamp,"customer_entries",cur.lastrowid)
            return cur.lastrowid

    def receive_payment_with_discount(self, customer_id: int, payment_cents: int,
                                      discount_cents: int = 0, *,
                                      description: str = "دفعة على الحساب",
                                      discount_reason: str = "",
                                      legacy_discount: bool = False,
                                      work_order_id: int | None = None) -> dict:
        """One atomic customer settlement. Discount never changes cash.

        Current-period discounts reduce booked revenue and profit. Historical
        opening-balance write-offs reduce receivables but not new revenue.
        """
        valid_money(payment_cents, "Cash received", zero_ok=True)
        valid_money(discount_cents, "Discount", zero_ok=True)
        if payment_cents + discount_cents <= 0:
            raise ValueError("Enter a payment or a discount.")
        description = required_text(description, "Payment description")
        if discount_cents:
            discount_reason = required_text(discount_reason, "Discount reason")
        with self.transaction():
            customer = self.get_customer(customer_id)
            if not customer:
                raise ValueError("Customer not found.")
            if work_order_id is not None:
                order = self.get_work_order(work_order_id)
                if order is None or order['customer_id'] != customer_id:
                    raise ValueError("Work order does not belong to this customer.")
            due = self.customer_account_totals(customer_id)['due_cents']
            if due <= 0:
                raise ValueError("This customer has no outstanding balance.")
            if payment_cents + discount_cents > due:
                raise ValueError("Payment plus discount exceeds amount due.")
            stamp = now_utc()
            if payment_cents:
                cur = self.conn.execute("""INSERT INTO customer_entries
                    (customer_id,work_order_id,kind,description,amount_cents,created_at)
                    VALUES (?,?,'payment',?,?,?)""",
                    (customer_id,work_order_id,description,payment_cents,stamp))
                self._cash('customer_payment',f"{customer['name']}: {description}",
                           payment_cents,stamp,'customer_entries',cur.lastrowid)
            if discount_cents:
                kind = 'opening_discount' if legacy_discount else 'discount'
                self.conn.execute("""INSERT INTO customer_entries
                    (customer_id,work_order_id,kind,description,amount_cents,created_at)
                    VALUES (?,?,?,?,?,?)""",
                    (customer_id,work_order_id,kind,discount_reason,discount_cents,stamp))
            return {'payment_cents': payment_cents,
                    'discount_cents': discount_cents,
                    'remaining_cents': due-payment_cents-discount_cents,
                    'settled': due==payment_cents+discount_cents}

    def customer_statement(self, customer_id: int):
        if not self.get_customer(customer_id):
            raise ValueError("Customer not found.")
        return self.conn.execute("""SELECT * FROM (
          SELECT e.*, w.engine_model, SUM(CASE
            WHEN e.kind IN ('charge','opening_debt') THEN e.amount_cents
            ELSE -e.amount_cents END) OVER (PARTITION BY e.customer_id ORDER BY e.id)
              AS running_due_cents
          FROM customer_entries e LEFT JOIN work_orders w ON e.work_order_id=w.id
          WHERE e.customer_id=?
        ) ORDER BY id ASC""",(customer_id,)).fetchall()

    def customer_account_totals(self, customer_id: int):
        return self.conn.execute("""SELECT
          COALESCE(SUM(CASE WHEN kind='charge' THEN amount_cents ELSE 0 END),0) AS billed_cents,
          COALESCE(SUM(CASE WHEN kind='opening_debt' THEN amount_cents ELSE 0 END),0) AS opening_cents,
          COALESCE(SUM(CASE WHEN kind='payment' THEN amount_cents ELSE 0 END),0) AS paid_cents,
          COALESCE(SUM(CASE WHEN kind='discount' THEN amount_cents ELSE 0 END),0) AS discount_cents,
          COALESCE(SUM(CASE WHEN kind='opening_discount' THEN amount_cents ELSE 0 END),0) AS opening_discount_cents,
          COALESCE(SUM(CASE WHEN kind IN ('charge','opening_debt') THEN amount_cents
                           ELSE -amount_cents END),0) AS due_cents
          FROM customer_entries WHERE customer_id=?""",(customer_id,)).fetchone()

    def daily_cash(self, date_iso: str):
        # UTC timestamps are converted to the computer's local date before filtering.
        entries=[]
        from datetime import datetime
        for row in self.conn.execute("SELECT * FROM cash_entries ORDER BY id ASC"):
            local_date=datetime.fromisoformat(row['created_at']).astimezone().date().isoformat()
            if local_date == date_iso:
                entries.append(row)
        return entries

    def preview_legacy_customer_csv(self, file_path: str | Path) -> list[dict]:
        """Import ONLY transcribed index and outstanding balance, never guess OCR.

        legacy_page is a stable notebook reference to prevent repeat import.
        opening_due is a decimal currency-unit amount, not cents.
        """
        rows = []
        with open(file_path, 'r', encoding='utf-8-sig', newline='') as file:
            reader = csv.DictReader(file)
            expected = {'legacy_page','name','phone','opening_due','notes'}
            if reader.fieldnames is None or not expected.issubset(reader.fieldnames):
                raise ValueError('CSV headers required: legacy_page,name,phone,opening_due,notes')
            seen = set()
            for number, row in enumerate(reader,2):
                if len(rows) >= 1000:
                    raise ValueError('Import at most 1,000 customers at once.')
                legacy_page = required_text(row['legacy_page'] or '',f'Notebook page on row {number}')
                name = required_text(row['name'] or '',f'Customer name on row {number}')
                if legacy_page in seen:
                    raise ValueError(f'Duplicate notebook page: {legacy_page}')
                seen.add(legacy_page)
                existing = self.conn.execute("""SELECT 1 FROM legacy_customer_refs
                    WHERE book_name='دفتر الزبائن' AND legacy_page=?""",(legacy_page,)).fetchone()
                if existing:
                    raise ValueError(f'Notebook page {legacy_page} was already imported.')
                try:
                    amount = Decimal((row['opening_due'] or '0').strip())
                except (InvalidOperation, AttributeError):
                    raise ValueError(f'Invalid opening due on row {number}.') from None
                if not amount.is_finite() or amount < 0 or amount * 100 != (amount * 100).to_integral_value():
                    raise ValueError(f'Invalid opening due on row {number}: use nonnegative amounts with up to 2 decimals.')
                money_cents = int(amount * 100)
                if money_cents > 2**63 - 1:
                    raise ValueError(f'Opening due too large on row {number}.')
                rows.append({'legacy_page':legacy_page,'name':name,
                             'phone':str(row['phone'] or '').strip(),
                             'notes':str(row['notes'] or '').strip(),
                             'opening_due_cents':money_cents})
        if not rows:
            raise ValueError('No customers found in the CSV.')
        return rows

    def import_legacy_customer_csv(self, file_path: str | Path) -> dict:
        rows = self.preview_legacy_customer_csv(file_path)
        with self.transaction():
            for row in rows:
                stamp = now_utc()
                cur = self.conn.execute("""INSERT INTO customers
                    (name,phone,notes,created_at) VALUES (?,?,?,?)""",
                    (row['name'],row['phone'],row['notes'],stamp))
                cid = cur.lastrowid
                self.conn.execute("""INSERT INTO legacy_customer_refs
                    (book_name,legacy_page,customer_id) VALUES ('دفتر الزبائن',?,?)""",
                    (row['legacy_page'],cid))
                if row['opening_due_cents']:
                    self.conn.execute("""INSERT INTO customer_entries
                        (customer_id,work_order_id,kind,description,amount_cents,created_at)
                        VALUES (?,NULL,'opening_debt',?,?,?)""",
                        (cid,f"رصيد سابق من دفتر الزبائن، صفحة {row['legacy_page']}",
                         row['opening_due_cents'],stamp))
        return {'customers':len(rows),
                'opening_due_cents':sum(row['opening_due_cents'] for row in rows)}

    def backup_to(self, path: str | Path):
        destination = Path(path).expanduser().resolve()
        if self.path != ":memory:" and destination == Path(self.path).resolve():
            raise ValueError("Choose a different location for the backup.")
        destination.parent.mkdir(parents=True,exist_ok=True)
        target = sqlite3.connect(destination)
        try:
            self.conn.backup(target)
        finally:
            target.close()
