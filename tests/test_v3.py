"""V3 integration: settlement, audit, migration, imports, printing."""
import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path
from database import Database
from reports import customer_statement_html, work_order_html


class V3Tests(unittest.TestCase):
    def setUp(self):
        self.db=Database(':memory:')

    def tearDown(self):
        self.db.close()

    def seed_invoice(self, amount=250000):
        customer=self.db.add_customer('محمود <ورشة>')
        work=self.db.create_work_order(customer,'Toyota 1HZ','لاند كروزر',
                                       'No.1','تجويف وهون',6)
        self.db.add_work_order_line(work,'تجويف سلندر',6,amount//6 if amount%6==0 else 0)
        if amount%6:
            self.db.add_work_order_line(work,'تجليخ كرنك',1,amount)
            self.db.remove_work_order_line(self.db.list_work_order_lines(work)[0]['id'])
        self.db.post_work_order_bill(work)
        return customer,work

    def test_settlement_2500_2300_200(self):
        cid,wid=self.seed_invoice()
        before=self.db.stats()
        self.assertEqual(before['revenue'],250000)
        t=self.db.receive_payment_with_discount(cid,230000,20000,
                   description='دفعة نهائية',discount_reason='حسم 200 للزبون',work_order_id=wid)
        self.assertTrue(t['settled'])
        self.assertEqual(t['remaining_cents'],0)
        self.assertEqual(self.db.stats()['cash'],230000)
        self.assertEqual(self.db.stats()['revenue'],230000)
        self.assertEqual(self.db.stats()['discounts_given'],20000)
        self.assertEqual(self.db.customer_account_totals(cid)['discount_cents'],20000)
        self.assertEqual(self.db.customer_account_totals(cid)['paid_cents'],230000)
        self.assertEqual(self.db.customer_account_totals(cid)['due_cents'],0)
        self.assertEqual([r['kind'] for r in self.db.customer_statement(cid)],
                         ['charge','payment','discount'])
        self.assertEqual([r['running_due_cents'] for r in self.db.customer_statement(cid)],
                         [250000,20000,0])
        self.assertEqual(len(self.db.list_ledger()),1)  # discount has no cash movement

    def test_discount_validation_and_rollback(self):
        cid,_=self.seed_invoice()
        initial=len(self.db.customer_statement(cid))
        for kwargs in [dict(payment_cents=230000,discount_cents=30000,discount_reason='خصم'),
                       dict(payment_cents=230000,discount_cents=20000,discount_reason=''),
                       dict(payment_cents=0,discount_cents=0),
                       dict(payment_cents=-10,discount_cents=100)]:
            with self.assertRaises(ValueError):
                self.db.receive_payment_with_discount(cid,**kwargs)
            self.assertEqual(len(self.db.customer_statement(cid)),initial)
            self.assertEqual(self.db.stats()['cash'],0)
        with self.assertRaises(ValueError):
            self.db.receive_payment_with_discount(cid,240000,20000,discount_reason='خصم')

    def test_partial_then_final_discount(self):
        cid,_=self.seed_invoice()
        self.db.receive_customer_payment(cid,30000)
        result=self.db.receive_payment_with_discount(cid,200000,20000,discount_reason='خصم')
        self.assertTrue(result['settled'])
        self.assertEqual(self.db.stats()['cash'],230000)
        self.assertEqual(self.db.stats()['customer_receivables'],0)

    def test_opening_discount_does_not_reduce_new_revenue(self):
        cid=self.db.add_customer('زبون قديم')
        self.db.add_customer_charge(cid,'رصيد دفتر سابق',250000,opening_debt=True)
        self.db.receive_payment_with_discount(cid,230000,20000,
            discount_reason='تسوية دفتر سابق',legacy_discount=True)
        self.assertEqual(self.db.stats()['cash'],230000)
        self.assertEqual(self.db.stats()['revenue'],0)
        self.assertEqual(self.db.stats()['profit'],0)
        self.assertEqual(self.db.stats()['customer_receivables'],0)

    def test_cylinders_validation_and_html_escaping(self):
        cid,oid=self.seed_invoice()
        self.assertEqual(self.db.get_work_order(oid)['cylinder_count'],6)
        self.assertIn('عدد السلندرات:</b> 6',work_order_html(self.db,oid))
        self.assertIn('محمود &lt;ورشة&gt;',work_order_html(self.db,oid))
        self.assertIn('محمود &lt;ورشة&gt;',customer_statement_html(self.db,cid))
        self.assertNotIn('محمود <ورشة>',customer_statement_html(self.db,cid))
        with self.assertRaises(ValueError):
            self.db.create_work_order(cid,'VQ40',cylinder_count=33)
        with self.assertRaises(ValueError):
            self.db.create_work_order(cid,'VQ40',cylinder_count=-1)

    def test_csv_historical_customer_import_and_no_reimport(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'customers.csv'
            with path.open('w',encoding='utf-8-sig',newline='') as f:
                wr=csv.writer(f)
                wr.writerow(['legacy_page','name','phone','opening_due','notes'])
                wr.writerow(['17','أبو محمود','0999','2500.00','موجود في دفتر 2026'])
                wr.writerow(['18','سعيد','','0',''])
            rows=self.db.preview_legacy_customer_csv(path)
            self.assertEqual(len(rows),2)
            res=self.db.import_legacy_customer_csv(path)
            self.assertEqual(res['customers'],2)
            self.assertEqual(res['opening_due_cents'],250000)
            self.assertEqual(self.db.stats()['cash'],0)
            self.assertEqual(self.db.stats()['revenue'],0)
            self.assertEqual(self.db.stats()['customer_receivables'],250000)
            with self.assertRaises(ValueError):
                self.db.import_legacy_customer_csv(path)
            self.assertEqual(self.db.stats()['customer_count'],2)

    def test_csv_invalid_all_or_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.csv'
            path.write_text('legacy_page,name,phone,opening_due,notes\n17,Ali,,10,\n18,Sam,,INVALID,\n',encoding='utf-8-sig')
            with self.assertRaises(ValueError):
                self.db.import_legacy_customer_csv(path)
            self.assertEqual(self.db.stats()['customer_count'],0)

    def test_v2_database_upgrade_preserves_existing_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbfile=Path(tmp)/'real.sqlite3'
            db=Database(dbfile)
            cid=db.add_customer('Previous')
            oid=db.create_work_order(cid,'OM642')
            db.add_work_order_line(oid,'Grinding',1,250000)
            db.post_work_order_bill(oid)
            db.close()
            # imitate the v2 CHECK and v2 work_orders schema on disk
            con=sqlite3.connect(dbfile)
            con.execute('PRAGMA foreign_keys=OFF')
            con.executescript('''
              CREATE TABLE customer_entries_old (
                id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id),
                work_order_id INTEGER REFERENCES work_orders(id),
                kind TEXT NOT NULL CHECK(kind IN ('charge','payment','opening_debt')),
                description TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
                created_at TEXT NOT NULL);
              INSERT INTO customer_entries_old SELECT * FROM customer_entries;
              DROP TABLE customer_entries;
              ALTER TABLE customer_entries_old RENAME TO customer_entries;
            ''')
            con.commit();con.close()
            newdb=Database(dbfile)
            try:
                self.assertEqual(newdb.customer_account_totals(cid)['due_cents'],250000)
                self.assertEqual(newdb.get_work_order(oid)['cylinder_count'],0)
                newdb.receive_payment_with_discount(cid,230000,20000,discount_reason='Discount')
                self.assertEqual(newdb.customer_account_totals(cid)['due_cents'],0)
                with self.assertRaises(ValueError):
                    newdb.post_work_order_bill(oid)
            finally:
                newdb.close()
            reopened=Database(dbfile)
            try:
                self.assertEqual(reopened.stats()['customer_receivables'],0)
                self.assertEqual(reopened.stats()['cash'],230000)
            finally:
                reopened.close()

if __name__=='__main__': unittest.main()
