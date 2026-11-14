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
                'owner_funding','owner_draw','purchase','part_sale','service','expense'
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
        """)

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
        d["revenue"] = d["parts_revenue"] + d["service_revenue"]
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
