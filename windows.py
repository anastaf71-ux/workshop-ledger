"""PySide6 desktop interface. All business rules live in database.py."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QSpinBox, QDoubleSpinBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QDateEdit,
    QCheckBox
)

from database import Database
from reports import customer_statement_html, work_order_html

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
        global CURRENCY
        CURRENCY = db.get_currency()
        self.setWindowTitle("Workshop Ledger V3 | إدارة ورشة المحركات")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(1280, 800)
        self.setMinimumSize(900, 580)
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
        title = QLabel("Workshop Ledger | إدارة الورشة")
        title.setObjectName("brand")
        heading.addWidget(title)
        subtitle = QLabel(f"Engine workshop  •  Offline  •  {CURRENCY}")
        subtitle.setObjectName("muted")
        heading.addWidget(subtitle)
        heading.addStretch()
        heading.addWidget(QLabel('عملة الدفتر:'))
        self.currency_combo=QComboBox()
        self.currency_combo.addItems(['USD','SYP'])
        self.currency_combo.setCurrentText(CURRENCY)
        self.currency_combo.currentTextChanged.connect(self.change_currency)
        heading.addWidget(self.currency_combo)
        heading.addWidget(button("تحديث البيانات", self.refresh_all))
        heading.addWidget(button("نسخة احتياطية", self.backup))
        root.addLayout(heading)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self.tabs.addTab(self.make_dashboard(), "الرئيسية")
        self.tabs.addTab(self.make_daily_cash(), "اليومية")
        self.tabs.addTab(self.make_customers(), "الزبائن")
        self.account_page = self.make_customer_account()
        self.tabs.addTab(self.account_page, "حساب الزبون")
        self.tabs.addTab(self.make_work_book(), "أوامر الشغل")
        self.tabs.addTab(self.make_inventory(), "المخزون")
        self.tabs.addTab(self.make_expenses(), "المصاريف")
        self.other_tabs = QTabWidget()
        self.other_tabs.addTab(self.make_jobs(), "أوامر قديمة")
        self.other_tabs.addTab(self.make_sales(), "مبيعات نقدية قديمة")
        self.other_tabs.addTab(self.make_ledger(), "حركة الصندوق")
        self.tabs.addTab(self.other_tabs, "المزيد")
        self.setCentralWidget(main)
        self.statusBar().showMessage("All records are saved locally in SQLite. Back up regularly.")
        self.refresh_all()

    def change_currency(self, new_currency: str):
        global CURRENCY
        if new_currency==CURRENCY:
            return
        answer=QMessageBox.warning(self,'اختيار العملة',
             'تغيير العملة يغيّر اسم وحدة العرض فقط، ولا يحوّل القيم بسعر صرف.\n'
             'استخدم عملة واحدة لجميع حركات الدفتر، ولا تغيّرها بعد تسجيل معاملات فعلية.\n'
             f'هل تريد اعتماد {new_currency}؟',
             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
             QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            self.currency_combo.blockSignals(True)
            self.currency_combo.setCurrentText(CURRENCY)
            self.currency_combo.blockSignals(False)
            return
        self.db.set_currency(new_currency)
        CURRENCY=new_currency
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
        layout.addLayout(self.heading_row("نظرة عامة على الورشة", [
            ("+ زبون جديد", self.add_customer_dialog),
            ("+ أمر شغل", self.new_order_dialog),
            ("قبض وتسوية", self.receive_payment_dialog),
            ("+ مصروف", self.record_expense)
        ]))
        layout.addWidget(QLabel("Owner funding is not profit. New work-order invoices count as revenue when billed; estimated work costs are not posted expenses."))
        grid = QGridLayout()
        self.metrics = {}
        names = [
            ("cash","Cash balance"), ("profit","Operating profit"),
            ("revenue","Total revenue"), ("expenses","Operating expenses"),
            ("inventory_value","Inventory value"), ("open_jobs","Open jobs"),
            ("cogs","Part costs sold"), ("low_stock_count","Low-stock items"),
            ("customer_receivables","ذمم الزبائن"), ("customer_count","عدد الزبائن"),
            ("discounts_given","الخصومات الممنوحة")
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

    # --- Notebook pages copied from the paper workshop workflow ---
    def make_daily_cash(self):
        widget, layout = self.page()
        heading = QHBoxLayout()
        heading.addWidget(QLabel("دفتر اليومية — cash received and cash paid"))
        heading.addStretch()
        self.cash_date = QDateEdit(QDate.currentDate())
        self.cash_date.setCalendarPopup(True)
        self.cash_date.setDisplayFormat("yyyy-MM-dd")
        self.cash_date.dateChanged.connect(lambda _: self.refresh_daily_cash())
        heading.addWidget(QLabel("Day:"))
        heading.addWidget(self.cash_date)
        layout.addLayout(heading)
        layout.addWidget(QLabel("Customer payments, stock purchases, paid expenses and cash sales are recorded here automatically."))
        self.daily_totals = QLabel("—")
        self.daily_totals.setStyleSheet("font-size: 15px; font-weight: 700; color: #115aa8;")
        layout.addWidget(self.daily_totals)
        self.daily_table = table(["ID", "Time", "Type", "Details", "Received | وارد", "Paid | مصروف"])
        layout.addWidget(self.daily_table, 1)
        return widget

    def make_customers(self):
        widget, layout = self.page()
        layout.addLayout(self.heading_row("فهرس الزبائن — customers index", [
            ("+ إضافة زبون", self.add_customer_dialog),
            ("استيراد الفهرس القديم CSV", self.import_old_customers),
            ("فتح حساب الزبون", self.open_selected_customer)
        ]))
        self.customer_search = line("Search by name or phone / بحث بالاسم أو الهاتف")
        self.customer_search.textChanged.connect(lambda _: self.refresh_customer_index())
        layout.addWidget(self.customer_search)
        layout.addWidget(QLabel("رقم الفهرس ثابت. انقر مرتين على اسم الزبون لعرض كشف حسابه."))
        self.customer_index_table = table(["Index / رقم", "Customer / الزبون", "Phone", "Work orders", "Remaining balance"])
        self.customer_index_table.cellDoubleClicked.connect(lambda *_: self.open_selected_customer())
        layout.addWidget(self.customer_index_table, 1)
        return widget

    def make_customer_account(self):
        widget, layout = self.page()
        layout.addLayout(self.heading_row("صفحة حساب الزبون — customer statement", [
            ("قبض / خصم / تسوية", self.receive_payment_dialog),
            ("طباعة كشف الحساب", self.print_account),
            ("حفظ الحساب PDF", self.export_account_pdf),
            ("مبلغ مستحق", lambda: self.customer_charge_dialog(False)),
            ("رصيد سابق", lambda: self.customer_charge_dialog(True))
        ]))
        self.account_customer_combo = QComboBox()
        self.account_customer_combo.currentIndexChanged.connect(lambda _: self.refresh_account())
        layout.addWidget(self.account_customer_combo)
        self.account_totals = QLabel("Choose a customer")
        self.account_totals.setStyleSheet("font-size: 14px; font-weight: 700; color: #184e82;")
        layout.addWidget(self.account_totals)
        layout.addWidget(QLabel("الفواتير ترفع الرصيد المستحق. القبض يدخل الصندوق، والخصم يخفض الرصيد دون إدخال نقد."))
        self.account_table = table(["Entry", "Date", "Work order", "Type", "Details", "Debit / مطلوب", "Paid / مدفوع", "Balance / الباقي"])
        layout.addWidget(self.account_table, 1)
        return widget

    def make_work_book(self):
        widget, layout = self.page()
        layout.addLayout(self.heading_row("دفتر الأشغال — engine machining work book", [
            ("+ أمر شغل جديد", self.new_order_dialog),
            ("+ عملية", self.new_work_item_dialog),
            ("حذف عملية", self.remove_work_item),
            ("ترحيل الحساب", self.post_selected_bill),
            ("طباعة الأمر", self.print_work_order),
            ("حفظ الأمر PDF", self.export_work_order_pdf)
        ]))
        layout.addWidget(QLabel("Define the engine and the machining jobs. Draft lines do NOT create customer debt until 'Post bill'."))
        self.work_orders_table = table(["رقم", "الزبون", "المحرك", "السلندرات", "السيارة / الآلة", "قيمة الأشغال", "الحالة", "الترحيل"])
        self.work_orders_table.itemSelectionChanged.connect(self.refresh_selected_work_order)
        layout.addWidget(self.work_orders_table, 2)
        status_actions=QHBoxLayout()
        status_actions.addWidget(button("Mark ready",lambda: self.change_selected_order_status('ready')))
        status_actions.addWidget(button("Mark delivered",lambda: self.change_selected_order_status('delivered')))
        status_actions.addStretch()
        layout.addLayout(status_actions)
        self.work_order_description = QLabel("Select an engine order to see its work items")
        self.work_order_description.setWordWrap(True)
        layout.addWidget(self.work_order_description)
        self.work_lines_table = table(["Line", "Machining work / الأشغال", "Qty", "Unit price", "Job amount", "Est. direct cost"])
        layout.addWidget(self.work_lines_table, 1)
        return widget

    def refresh_daily_cash(self):
        if not hasattr(self,'daily_table'):
            return
        chosen=self.cash_date.date().toString('yyyy-MM-dd')
        entries=self.db.daily_cash(chosen)
        received=sum(max(0,r['delta_cents']) for r in entries)
        paid=sum(max(0,-r['delta_cents']) for r in entries)
        self.daily_totals.setText(f"Received / المقبوض: {money(received)}     Paid / المدفوع: {money(paid)}     Net: {money(received-paid)}")
        fill_table(self.daily_table,[(r['id'],time_text(r['created_at'])[11:],
                  r['kind'].replace('_',' ').title(),r['description'],
                  money(r['delta_cents']) if r['delta_cents']>0 else '',
                  money(-r['delta_cents']) if r['delta_cents']<0 else '') for r in entries])

    def refresh_customer_index(self):
        if not hasattr(self,'customer_index_table'):
            return
        rows=self.db.customer_index(self.customer_search.text())
        fill_table(self.customer_index_table,[(r['id'],r['name'],r['phone'],r['order_count'],
                  money(r['balance_cents'])) for r in rows])

    def refresh_customer_combos(self):
        if not hasattr(self,'account_customer_combo'):
            return
        old=self.account_customer_combo.currentData()
        self.account_customer_combo.blockSignals(True)
        self.account_customer_combo.clear()
        for c in self.db.customer_index():
            self.account_customer_combo.addItem(f"#{c['id']} — {c['name']}", c['id'])
        idx=self.account_customer_combo.findData(old)
        if idx>=0:
            self.account_customer_combo.setCurrentIndex(idx)
        self.account_customer_combo.blockSignals(False)
        self.refresh_account()

    def refresh_account(self):
        if not hasattr(self,'account_table'):
            return
        cid=self.account_customer_combo.currentData()
        if cid is None:
            self.account_totals.setText('No customer selected')
            fill_table(self.account_table,[])
            return
        t=self.db.customer_account_totals(cid)
        self.account_totals.setText(f"الأشغال: {money(t['billed_cents'])}   الرصيد القديم: {money(t['opening_cents'])}   المقبوض: {money(t['paid_cents'])}   الخصم: {money(t['discount_cents']+t['opening_discount_cents'])}   المتبقي: {money(t['due_cents'])}  {'✓ مكتمل' if t['due_cents']==0 else 'مستحق' if t['due_cents']>0 else 'رصيد دائن'}")
        rows=self.db.customer_statement(cid)
        fill_table(self.account_table,[(r['id'],time_text(r['created_at']),
             f"#{r['work_order_id']} — {r['engine_model']}" if r['work_order_id'] else '—',
             {'charge':'أشغال','payment':'دفعة','opening_debt':'رصيد سابق', 'discount':'خصم','opening_discount':'تسوية رصيد سابق'}[r['kind']],
             r['description'],money(r['amount_cents']) if r['kind'] in ('charge','opening_debt') else '',
             money(r['amount_cents']) if r['kind'] in ('payment','discount','opening_discount') else '',money(r['running_due_cents'])) for r in rows])

    def refresh_work_book(self):
        if not hasattr(self,'work_orders_table'):
            return
        old=selected_id(self.work_orders_table)
        rows=self.db.list_work_orders()
        self.work_orders_table.blockSignals(True)
        fill_table(self.work_orders_table,[(r['id'],r['customer_name'],r['engine_model'],r['vehicle'],
                  r['cylinder_count'] or '—',r['vehicle'],money(r['total_cents']),r['status'],
                  'Yes' if r['billed_at'] else 'Draft') for r in rows])
        select=next((i for i,r in enumerate(rows) if r['id']==old),0)
        if rows:
            self.work_orders_table.selectRow(select)
        self.work_orders_table.blockSignals(False)
        self.refresh_selected_work_order()

    def refresh_selected_work_order(self):
        if not hasattr(self,'work_lines_table'):
            return
        oid=selected_id(self.work_orders_table)
        if oid is None:
            self.work_order_description.setText('No work order selected')
            fill_table(self.work_lines_table,[])
            return
        order=next((r for r in self.db.list_work_orders() if r['id']==oid),None)
        if order is None:
            return
        lines=self.db.list_work_order_lines(oid)
        estimated=sum(r['estimated_total_cents'] for r in lines)
        self.work_order_description.setText(f"أمر #{oid} | المحرك: {order['engine_model']} | السلندرات: {order['cylinder_count'] or 'غير محدد'} | رقم المحرك: {order['engine_number'] or '—'} | الإجمالي: {money(order['total_cents'])} | التكلفة التقديرية: {money(estimated)} (ليست مصروفاً مدفوعاً) | {order['notes']}")
        fill_table(self.work_lines_table,[(r['id'],r['description'],r['qty'],
               money(r['unit_price_cents']),money(r['total_cents']),money(r['estimated_total_cents'])) for r in lines])

    def customer_picker(self, selected=None):
        combo=QComboBox()
        for r in self.db.customer_index():
            combo.addItem(f"#{r['id']} — {r['name']}",r['id'])
        if selected is not None and combo.findData(selected)>=0:
            combo.setCurrentIndex(combo.findData(selected))
        return combo

    def add_customer_dialog(self):
        form=Form('New customer / زبون جديد',self)
        name=form.add('Customer name',line('اسم الزبون'))
        phone=form.add('Phone',line('Optional'))
        notes=form.add('Notes',line('Optional'))
        form.submit(lambda: self.db.add_customer(name.text(),phone.text(),notes.text()),self.refresh_all)
        form.exec()

    def open_selected_customer(self):
        cid=selected_id(self.customer_index_table)
        if cid is None:
            return QMessageBox.information(self,'Choose a customer','Select a customer from the index.')
        index=self.account_customer_combo.findData(cid)
        if index>=0:
            self.account_customer_combo.setCurrentIndex(index)
        self.tabs.setCurrentWidget(self.account_page)

    def receive_payment_dialog(self):
        cid=self.account_customer_combo.currentData()
        if cid is None:
            return QMessageBox.information(self,'الزبائن','أضف زبوناً أولاً.')
        due=self.db.customer_account_totals(cid)['due_cents']
        if due<=0:
            return QMessageBox.information(self,'حساب الزبون','لا يوجد مبلغ مستحق لهذا الزبون.')
        form=Form('قبض دفعة أو تسوية الحساب بخصم',self)
        form.add('المبلغ المستحق',QLabel(money(due)))
        received=form.add('الدفعة المقبوضة',amount(0,allow_zero=True))
        discount=form.add('الخصم الممنوح',amount(0,allow_zero=True))
        reason=form.add('سبب الخصم',line('مثال: حسم تسوية نهائية'))
        desc=form.add('بيان الدفعة',line('دفعة على حساب الأشغال','قبض من الزبون'))
        historical=form.add('خصم على رصيد قديم',QCheckBox('الرصيد من الدفتر الورقي (لا يخص أرباح هذه الفترة)'))
        balance=form.add('المتبقي بعد العملية',QLabel('—'))
        fill_discount=button('احتساب الخصم لتصفية الحساب',
            lambda:discount.setValue(max(0,(due-cents(received))/100)))
        form.add('اختصار',fill_discount)
        def update():
            remaining=due-cents(received)-cents(discount)
            balance.setText(('✓ مكتمل — ' if remaining==0 else 'المتبقي: ' if remaining>0 else 'المبلغ المدخل أكبر من المستحق: ')+money(abs(remaining)))
            balance.setStyleSheet('font-weight:700;color:'+('#168260' if remaining==0 else '#bc394b' if remaining<0 else '#165a91'))
        received.valueChanged.connect(update)
        discount.valueChanged.connect(update)
        update()
        def save():
            paid=cents(received)
            deducted=cents(discount)
            if paid+deducted>due:
                raise ValueError('القبض مع الخصم أكبر من المبلغ المستحق.')
            if deducted and not reason.text().strip():
                raise ValueError('يرجى توضيح سبب الخصم.')
            self.db.receive_payment_with_discount(cid,paid,deducted,
                description=desc.text(),discount_reason=reason.text(),
                legacy_discount=historical.isChecked())
        form.submit(save,self.refresh_all)
        form.exec()

    def customer_charge_dialog(self, opening=False):
        cid=self.account_customer_combo.currentData()
        if cid is None:
            return QMessageBox.information(self,'Add a customer','Create a customer first.')
        form=Form('Opening debt / رصيد افتتاحي' if opening else 'Manual customer charge',self)
        description=form.add('Description',line('رصيد سابق' if opening else 'Work or materials'))
        charge=form.add('Charge amount',amount(0,allow_zero=False))
        form.submit(lambda:self.db.add_customer_charge(cid,description.text(),cents(charge),opening_debt=opening),self.refresh_all)
        form.exec()

    def new_order_dialog(self):
        form=Form('New engine work order / دفتر الأشغال',self)
        customers=form.add('Customer',self.customer_picker(self.account_customer_combo.currentData()))
        if not customers.count():
            return QMessageBox.information(self,'Customers required','Add a customer from the index first.')
        engine=form.add('Engine model / نوع المحرك',line('e.g. Toyota 1HZ / VQ40'))
        vehicle=form.add('Vehicle or equipment',line('e.g. Nissan Pathfinder'))
        serial=form.add('Engine serial / رقم المحرك',line('Optional'))
        cylinders=form.add('عدد السلندرات',quantity(0,minimum=0))
        cylinders.setMaximum(32)
        note=form.add('ملاحظات / قياسات',line('Measurements, missing parts...'))
        form.submit(lambda:self.db.create_work_order(customers.currentData(),engine.text(),
                   vehicle.text(),serial.text(),note.text(),cylinders.value()),self.refresh_all)
        form.exec()

    def new_work_item_dialog(self):
        oid=selected_id(self.work_orders_table)
        if oid is None:
            return QMessageBox.information(self,'Select an order','Choose a work order first.')
        order=self.db.get_work_order(oid)
        if order['billed_at']:
            return QMessageBox.warning(self,'Already billed','A posted bill cannot be changed.')
        form=Form(f'Add work item to order #{oid}',self)
        description=form.add('العملية / Machining operation',QComboBox())
        description.setEditable(True)
        description.addItems(['تجويف سلندر','هون سلندر','تجليخ كرنك - ثابت','تجليخ كرنك - متحرك',
                             'قص بوش','تركيب قشور','تسوية وجه بلوك','تسوية رأس','تركيب لاينرات',
                             'فحص وقياسات','أعمال أخرى'])
        qty=form.add('العدد',quantity())
        def suggest_quantity(text):
            if text.startswith(('تجويف سلندر','هون سلندر')) and order['cylinder_count']:
                qty.setValue(order['cylinder_count'])
        description.currentTextChanged.connect(suggest_quantity)
        suggest_quantity(description.currentText())
        price=form.add('Price per unit',amount())
        cost=form.add('Estimated direct cost per unit',amount())
        form.submit(lambda:self.db.add_work_order_line(oid,description.currentText(),qty.value(),
                             cents(price),cents(cost)),self.refresh_all)
        form.exec()

    def remove_work_item(self):
        line_id=selected_id(self.work_lines_table)
        if line_id is None:
            return QMessageBox.information(self,'Select an item','Choose a work item first.')
        if QMessageBox.question(self,'Remove work item','Remove this draft work item?') != QMessageBox.StandardButton.Yes:
            return
        try:
            self.db.remove_work_order_line(line_id)
        except (ValueError,sqlite3.Error) as ex:
            return QMessageBox.warning(self,'Cannot remove',str(ex))
        self.refresh_all()

    def post_selected_bill(self):
        oid=selected_id(self.work_orders_table)
        if oid is None:
            return QMessageBox.information(self,'Select an order','Choose a work order first.')
        if QMessageBox.question(self,'Post customer bill',
           f'Post charges for work order #{oid} to the customer account?\nThis will not receive cash and cannot be posted twice.') != QMessageBox.StandardButton.Yes:
            return
        try:
            self.db.post_work_order_bill(oid)
        except (ValueError,sqlite3.Error) as ex:
            return QMessageBox.warning(self,'Cannot post bill',str(ex))
        self.refresh_all()

    def change_selected_order_status(self,status):
        oid=selected_id(self.work_orders_table)
        if oid is None:
            return QMessageBox.information(self,'Select an order','Choose a work order first.')
        try:
            self.db.change_work_order_status(oid,status)
        except (ValueError,sqlite3.Error) as ex:
            return QMessageBox.warning(self,'Cannot change status',str(ex))
        self.refresh_all()

    def _preview_print(self, html: str):
        doc=QTextDocument(self)
        doc.setHtml(html)
        printer=QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog=QPrintPreviewDialog(printer,self)
        dialog.setWindowTitle('معاينة الطباعة / Print preview')
        dialog.paintRequested.connect(lambda p:doc.print_(p))
        dialog.exec()

    def _export_pdf(self, html: str, basename: str):
        filename,_=QFileDialog.getSaveFileName(self,'حفظ PDF',str(Path.home()/basename),'PDF files (*.pdf)')
        if not filename:
            return
        if not filename.lower().endswith('.pdf'):
            filename += '.pdf'
        try:
            doc=QTextDocument(self)
            doc.setHtml(html)
            printer=QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(filename)
            doc.print_(printer)
        except Exception as ex:
            return QMessageBox.warning(self,'Export error',str(ex))
        QMessageBox.information(self,'PDF','تم حفظ الملف: '+filename)

    def _account_report(self):
        cid=self.account_customer_combo.currentData()
        if cid is None:
            QMessageBox.information(self,'الزبائن','اختر زبوناً أولاً.')
            return None
        return cid,customer_statement_html(self.db,cid,CURRENCY)

    def print_account(self):
        report=self._account_report()
        if report:
            self._preview_print(report[1])

    def export_account_pdf(self):
        report=self._account_report()
        if report:
            self._export_pdf(report[1],f'customer_{report[0]}_statement.pdf')

    def _work_order_report(self):
        oid=selected_id(self.work_orders_table)
        if oid is None:
            QMessageBox.information(self,'أمر الشغل','اختر أمر شغل أولاً.')
            return None
        return oid,work_order_html(self.db,oid,CURRENCY)

    def print_work_order(self):
        report=self._work_order_report()
        if report:
            self._preview_print(report[1])

    def export_work_order_pdf(self):
        report=self._work_order_report()
        if report:
            self._export_pdf(report[1],f'work_order_{report[0]}.pdf')

    def import_old_customers(self):
        filename,_=QFileDialog.getOpenFileName(self,'استيراد فهرس الزبائن',str(Path.home()),'CSV files (*.csv)')
        if not filename:
            return
        try:
            data=self.db.preview_legacy_customer_csv(filename)
        except (ValueError,UnicodeError, OSError) as exc:
            return QMessageBox.warning(self,'CSV error',str(exc))
        total=sum(x['opening_due_cents'] for x in data)
        reply=QMessageBox.question(self,'تأكيد الاستيراد',
            f'إضافة {len(data)} زبوناً جديداً مع رصيد افتتاحي إجمالي {money(total)}؟\n'
            'لن يتم تسجيل هذا الرصيد كإيراد أو قبض نقدي.\n'
            'تأكد من صحة الإدخال قبل المتابعة.')
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.db.import_legacy_customer_csv(filename)
        except (ValueError,sqlite3.Error,OSError) as exc:
            return QMessageBox.warning(self,'CSV error',str(exc))
        self.refresh_all()
        QMessageBox.information(self,'تم','تم استيراد الفهرس والأرصدة الافتتاحية بنجاح.')

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
        layout.addWidget(QLabel("Cash-only standalone sales. Do NOT record the same work order charge here and in Customer Account."))
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
            value.setText(str(raw) if key in ("open_jobs", "low_stock_count", "customer_count") else money(raw))
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

        self.refresh_daily_cash()
        self.refresh_customer_index()
        self.refresh_customer_combos()
        self.refresh_work_book()

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
