"""PySide6 desktop interface. All business rules live in database.py."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QSpinBox, QDoubleSpinBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
)

from database import Database

# The MVP uses a single currency and no exchange-rate calculations.
CURRENCY = "USD"  # Change to "SYP" before using the software with Syrian pounds.


def money(cents: int) -> str:
    return f"{cents / 100:,.2f} {CURRENCY}"


def cents(spin: QDoubleSpinBox) -> int:
    return int(Decimal(str(spin.value())) * 100)


def time_text(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(value)


def line(placeholder: str = "", value: str = "") -> QLineEdit:
    widget = QLineEdit(value)
    widget.setPlaceholderText(placeholder)
    return widget


def amount(value_cents: int = 0, allow_zero: bool = True) -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setDecimals(2)
    widget.setMaximum(1_000_000_000)
    widget.setMinimum(0 if allow_zero else 0.01)
    widget.setSingleStep(1)
    widget.setValue(value_cents / 100)
    widget.setSuffix(f" {CURRENCY}")
    return widget


def quantity(value: int = 1, minimum: int = 1) -> QSpinBox:
    widget = QSpinBox()
    widget.setRange(minimum, 1_000_000)
    widget.setValue(value)
    return widget


def button(title: str, handler) -> QPushButton:
    widget = QPushButton(title)
    widget.clicked.connect(handler)
    return widget


def table(headers: list[str]) -> QTableWidget:
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    widget.setAlternatingRowColors(True)
    widget.verticalHeader().hide()
    widget.horizontalHeader().setStretchLastSection(True)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    return widget


def fill_table(widget: QTableWidget, rows: list[tuple]):
    widget.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            item = QTableWidgetItem(str(value))
            if column_index == 0:
                item.setData(Qt.ItemDataRole.UserRole, row[0])
            widget.setItem(row_index, column_index, item)
    widget.resizeRowsToContents()


def selected_id(widget: QTableWidget) -> int | None:
    row = widget.currentRow()
    if row < 0 or widget.item(row, 0) is None:
        return None
    return widget.item(row, 0).data(Qt.ItemDataRole.UserRole)


class Form(QDialog):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self._layout = QVBoxLayout(self)
        self.form = QFormLayout()
        self.form.setSpacing(13)
        self._layout.addLayout(self.form)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                        QDialogButtonBox.StandardButton.Cancel)
        self._layout.addWidget(self.buttons)
        self.buttons.rejected.connect(self.reject)

    def add(self, caption: str, widget):
        self.form.addRow(caption, widget)
        return widget

    def submit(self, operation, on_success):
        def go():
            try:
                operation()
            except (ValueError, sqlite3.Error, OverflowError) as error:
                QMessageBox.warning(self, "Check the information", str(error))
            else:
                self.accept()
                on_success()
        self.buttons.accepted.connect(go)


class MainWindow(QMainWindow):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.setWindowTitle("Workshop Ledger | Inventory & Cash")
        self.resize(1190, 760)
        self.setMinimumSize(860, 560)
        self.setStyleSheet("""
            QMainWindow { background: #f5f7fa; }
            QWidget { font-family: 'Segoe UI', Arial; font-size: 12px; }
            QLabel#brand { font-size: 23px; font-weight: 700; color: #14253d; }
            QLabel#muted { color: #61718a; }
            QTabWidget::pane { border: 1px solid #dfe5ef; border-radius: 5px; background: white; }
            QTabBar::tab { padding: 11px 14px; color: #3d506c; }
            QTabBar::tab:selected { color: #115aa8; font-weight: bold; background: white; }
            QGroupBox { border: 1px solid #dae2ed; border-radius: 7px;
                        padding: 16px 11px 8px; margin-top: 8px; font-weight: 600; }
            QPushButton { padding: 9px 13px; border-radius: 5px; border: 1px solid #ccd8e6;
                          background: #ffffff; color: #14345a; }
            QPushButton:hover { background: #e9f3fd; }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { padding: 7px; border: 1px solid #cbd7e5;
                                                        border-radius: 4px; background: white; }
            QTableWidget { background: white; alternate-background-color: #f7f9fc;
                           gridline-color: #e5eaf2; border: 1px solid #e1e7ef; }
            QHeaderView::section { background: #eaf0f7; padding: 9px; border: 0;
                                   font-weight: 600; color: #203a5a; }
        """)
        main = QWidget()
        main.setObjectName("main")
        root = QVBoxLayout(main)
        root.setSpacing(13)
        root.setContentsMargins(18, 16, 18, 16)
        heading = QHBoxLayout()
        title = QLabel("Workshop Ledger")
        title.setObjectName("brand")
        heading.addWidget(title)
        subtitle = QLabel(f"Engine workshop  •  Offline  •  {CURRENCY}")
        subtitle.setObjectName("muted")
        heading.addWidget(subtitle)
        heading.addStretch()
        heading.addWidget(button("Refresh", self.refresh_all))
        heading.addWidget(button("Back up data", self.backup))
        root.addLayout(heading)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self.tabs.addTab(self.make_dashboard(), "Dashboard")
        self.tabs.addTab(self.make_inventory(), "Inventory")
        self.tabs.addTab(self.make_jobs(), "Workshop Jobs")
        self.tabs.addTab(self.make_sales(), "Sales & Services")
        self.tabs.addTab(self.make_expenses(), "Expenses & Cash")
        self.tabs.addTab(self.make_ledger(), "Cash Ledger")
        self.setCentralWidget(main)
        self.statusBar().showMessage("All records are saved locally in SQLite. Back up regularly.")
        self.refresh_all()

    def page(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 15, 16, 15)
        layout.setSpacing(12)
        return widget, layout

    def heading_row(self, title: str, actions: list[tuple[str, object]]):
        row = QHBoxLayout()
        label = QLabel(title)
        label.setStyleSheet("font-size: 17px; font-weight: 650; color: #203954;")
        row.addWidget(label)
        row.addStretch()
        for title, operation in actions:
            row.addWidget(button(title, operation))
        return row

    def make_dashboard(self):
        widget, layout = self.page()
        layout.addLayout(self.heading_row("Workshop overview", []))
        layout.addWidget(QLabel("Totals since you started using this database. Owner contributions are not profit."))
        grid = QGridLayout()
        self.metrics = {}
        names = [
            ("cash","Cash balance"), ("profit","Operating profit"),
            ("revenue","Total revenue"), ("expenses","Operating expenses"),
            ("inventory_value","Inventory value"), ("open_jobs","Open jobs"),
            ("cogs","Part costs sold"), ("low_stock_count","Low-stock items")
        ]
        for i, (key, title) in enumerate(names):
            box = QGroupBox(title)
            b_layout = QVBoxLayout(box)
            value = QLabel("—")
            value.setStyleSheet("font-size: 22px; font-weight: 700; color: #184e82; padding: 7px 0;")
            b_layout.addWidget(value)
            self.metrics[key] = value
            grid.addWidget(box, i // 4, i % 4)
        layout.addLayout(grid)
        layout.addWidget(QLabel("Recent cash movements"))
        self.recent_table = table(["Date", "Event", "Description", "Cash change"])
        layout.addWidget(self.recent_table, 1)
        return widget

    def make_inventory(self):
        widget, layout = self.page()
        layout.addLayout(self.heading_row("Spare parts and consumables", [
            ("+ New part", self.add_product),
            ("Receive stock", self.receive_stock),
            ("Edit selected", self.edit_product)
        ]))
        layout.addWidget(QLabel("Quantities are whole units. Stock increases via purchases and decreases via part sales."))
        self.products_table = table(["ID", "SKU", "Part", "Category", "Qty", "Avg cost", "Sale price", "Min stock"])
        layout.addWidget(self.products_table, 1)
        return widget

    def make_jobs(self):
        widget, layout = self.page()
        layout.addLayout(self.heading_row("Engine machining work orders", [
            ("+ New job", self.add_job),
            ("Mark complete", lambda: self.change_job("done")),
            ("Reopen", lambda: self.change_job("open"))
        ]))
        layout.addWidget(QLabel("Job quotes are estimates, not income. Record payment under Sales & Services."))
        self.jobs_table = table(["ID", "Customer", "Vehicle", "Engine", "Machining work", "Quote", "Status", "Created"])
        layout.addWidget(self.jobs_table, 1)
        return widget

    def make_sales(self):
        widget, layout = self.page()
        layout.addLayout(self.heading_row("Cash sales and completed services", [
            ("Sell a part", self.sell_part), ("Record a service", self.record_service)
        ]))
        layout.addWidget(QLabel("Each sale is fully paid now. Services can be linked to an existing workshop job."))
        self.sales_table = table(["ID", "Date", "Type", "Description", "Qty", "Revenue", "Part cost", "Job / customer"])
        layout.addWidget(self.sales_table, 1)
        return widget

    def make_expenses(self):
        widget, layout = self.page()
        layout.addLayout(self.heading_row("Operating expenses and owner cash", [
            ("+ Expense", self.record_expense),
            ("Add owner funds", lambda: self.cash_dialog("owner_funding")),
            ("Owner withdrawal", lambda: self.cash_dialog("owner_draw"))
        ]))
        layout.addWidget(QLabel("Parts purchases are inventory assets, not operating expenses. Owner funding is not revenue."))
        self.expenses_table = table(["ID", "Date", "Category", "Description", "Cash paid"])
        layout.addWidget(self.expenses_table, 1)
        return widget

    def make_ledger(self):
        widget, layout = self.page()
        layout.addLayout(self.heading_row("Cash movement history", []))
        layout.addWidget(QLabel("Newest first. Negative balances indicate missing funding or other unrecorded transactions."))
        self.ledger_table = table(["ID", "Date", "Type", "Description", "Money in", "Money out", "Balance after"])
        layout.addWidget(self.ledger_table, 1)
        return widget

    def refresh_all(self):
        summary = self.db.stats()
        for key, value in self.metrics.items():
            raw = summary[key]
            value.setText(str(raw) if key in ("open_jobs", "low_stock_count") else money(raw))
        products = self.db.list_products()
        fill_table(self.products_table, [
            (r["id"], r["sku"], r["name"], r["category"],r["qty"],
             money(r["avg_cost_cents"]),money(r["sale_price_cents"]),r["min_stock"])
            for r in products
        ])
        fill_table(self.jobs_table, [
            (r["id"],r["customer"],r["vehicle"],r["engine"],r["work_type"],
             money(r["quote_cents"]),r["status"],time_text(r["created_at"]))
            for r in self.db.list_jobs()
        ])
        fill_table(self.sales_table, [
            (r["id"],time_text(r["created_at"]),r["kind"],r["description"],r["qty"],
             money(r["revenue_cents"]),money(r["cogs_cents"]),
             (f"#{r['job_id']} {r['job_customer']}" if r["job_id"] is not None else "—"))
            for r in self.db.list_sales()
        ])
        fill_table(self.expenses_table, [
            (r["id"],time_text(r["created_at"]),r["category"],r["description"],money(r["amount_cents"]))
            for r in self.db.list_expenses()
        ])
        ledger = self.db.list_ledger()
        fill_table(self.ledger_table, [
            (r["id"],time_text(r["created_at"]),r["kind"].replace("_"," ").title(),r["description"],
             money(r["delta_cents"]) if r["delta_cents"] > 0 else "",
             money(-r["delta_cents"]) if r["delta_cents"] < 0 else "",
             money(r["running_balance_cents"])) for r in ledger
        ])
        fill_table(self.recent_table, [
            (time_text(r["created_at"]),r["kind"].replace("_"," ").title(),
             r["description"],( "+" if r["delta_cents"] > 0 else "") + money(r["delta_cents"]))
            for r in ledger[:15]
        ])

    def product_fields(self, form: Form, product=None):
        get = (lambda k, d: product[k] if product is not None else d)
        sku = form.add("SKU / part number",line("e.g. BRG-VQ40-STD",get("sku","")))
        name = form.add("Part name",line("e.g. Main bearing set",get("name","")))
        category = form.add("Category",line("Bearings, liners, tools...",get("category","Parts")))
        unit = form.add("Unit",line("pcs / sets",get("unit","pcs")))
        price = form.add("Suggested sale price",amount(get("sale_price_cents",0)))
        minimum = form.add("Low-stock threshold",quantity(get("min_stock",0),0))
        return (sku,name,category,unit,price,minimum)

    def add_product(self):
        form = Form("Add inventory item",self)
        sku,name,category,unit,price,minimum = self.product_fields(form)
        form.submit(lambda: self.db.add_product(sku.text(),name.text(),category.text(),
                                                 unit.text(),cents(price),minimum.value()),self.refresh_all)
        form.exec()

    def edit_product(self):
        product_id = selected_id(self.products_table)
        if product_id is None:
            return QMessageBox.information(self,"Select a part","Select an inventory row first.")
        product = self.db.get_product(product_id)
        form = Form("Edit inventory item",self)
        sku,name,category,unit,price,minimum = self.product_fields(form,product)
        form.submit(lambda: self.db.edit_product(product_id,sku.text(),name.text(),
                    category.text(),unit.text(),cents(price),minimum.value()),self.refresh_all)
        form.exec()

    def product_combo(self):
        combo = QComboBox()
        products = self.db.list_products()
        for part in products:
            combo.addItem(f"{part['sku']} — {part['name']} (stock: {part['qty']})",part["id"])
        return combo

    def job_combo(self):
        combo = QComboBox()
        combo.addItem("No linked job",None)
        for job in self.db.list_jobs():
            combo.addItem(f"#{job['id']} — {job['customer']} / {job['vehicle']}",job["id"])
        return combo

    def receive_stock(self):
        form = Form("Receive purchased stock",self)
        part = form.add("Part",self.product_combo())
        if part.count() == 0:
            return QMessageBox.information(self,"No products","Add a part first.")
        qty = form.add("Quantity received",quantity())
        cost = form.add("Purchase cost per unit",amount())
        note = form.add("Supplier / note",line("Optional"))
        form.submit(lambda: self.db.purchase_stock(part.currentData(),qty.value(),
                                                  cents(cost),note.text()),self.refresh_all)
        form.exec()

    def add_job(self):
        form = Form("New machining job",self)
        customer = form.add("Customer",line("Customer name"))
        vehicle = form.add("Vehicle",line("e.g. Nissan Pathfinder 2007"))
        engine = form.add("Engine code",line("e.g. VQ40DE"))
        work = form.add("Machining work",line("Boring, honing, crankshaft grinding..."))
        note = form.add("Notes",line("Optional"))
        quote = form.add("Quoted price",amount())
        form.submit(lambda: self.db.add_job(customer.text(),vehicle.text(),engine.text(),
                                           work.text(),note.text(),cents(quote)),self.refresh_all)
        form.exec()

    def change_job(self, status: str):
        job_id = selected_id(self.jobs_table)
        if job_id is None:
            return QMessageBox.information(self,"Select a job","Select a workshop job first.")
        try:
            self.db.set_job_status(job_id,status)
        except ValueError as error:
            return QMessageBox.warning(self,"Cannot update job",str(error))
        self.refresh_all()

    def sell_part(self):
        form = Form("Sell an inventory part (cash received)",self)
        part = form.add("Part",self.product_combo())
        if part.count() == 0:
            return QMessageBox.information(self,"No products","Add and receive stock first.")
        qty = form.add("Quantity",quantity())
        price = form.add("Selling price per unit",amount(0,allow_zero=False))
        job = form.add("Workshop job (optional)",self.job_combo())
        def set_price():
            p = self.db.get_product(part.currentData())
            if p is not None:
                price.setValue(p["sale_price_cents"] / 100)
        part.currentIndexChanged.connect(set_price)
        set_price()
        form.submit(lambda: self.db.sell_part(part.currentData(),qty.value(),cents(price),
                                              job.currentData()),self.refresh_all)
        form.exec()

    def record_service(self):
        form = Form("Record paid machining service",self)
        description = form.add("Machining service",line("Cylinder boring, honing, crank grinding..."))
        charge = form.add("Cash received",amount(0,allow_zero=False))
        job = form.add("Workshop job (optional)",self.job_combo())
        form.submit(lambda: self.db.record_service(description.text(),cents(charge),
                                                   job.currentData()),self.refresh_all)
        form.exec()

    def record_expense(self):
        form = Form("Record operating expense",self)
        category = form.add("Category",QComboBox())
        category.addItems(["Wages", "Electricity", "Rent", "Consumables", "Repairs",
                           "Fuel", "Transport", "Other"])
        description = form.add("Description",line("Describe the expense"))
        cost = form.add("Cash paid",amount(0,allow_zero=False))
        form.submit(lambda: self.db.record_expense(category.currentText(),
                                                   description.text(),cents(cost)),self.refresh_all)
        form.exec()

    def cash_dialog(self, kind: str):
        is_funding = kind == "owner_funding"
        form = Form("Add owner funds" if is_funding else "Owner withdrawal",self)
        cash = form.add("Cash amount",amount(0,allow_zero=False))
        note = form.add("Note",line("Opening cash" if is_funding else "Owner withdrawal"))
        form.submit(lambda: self.db.owner_cash(cents(cash),kind,note.text()),self.refresh_all)
        form.exec()

    def backup(self):
        target, _ = QFileDialog.getSaveFileName(self,"Save a workshop database backup",
                                                "workshop-backup.sqlite3", "SQLite database (*.sqlite3)")
        if not target:
            return
        try:
            self.db.backup_to(Path(target))
        except (OSError,sqlite3.Error,ValueError) as error:
            QMessageBox.warning(self,"Backup failed",str(error))
        else:
            QMessageBox.information(self,"Backup saved",f"Database backup saved to:\n{target}")
