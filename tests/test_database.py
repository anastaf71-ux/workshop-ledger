"""Run: python -m unittest discover -s tests -v"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from database import Database


class WorkshopLedgerTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def tearDown(self):
        self.db.close()

    def test_inventory_purchase_sale_and_profit(self):
        self.db.owner_cash(100_000,"owner_funding","Opening cash")
        bearing = self.db.add_product("VQ40-BRG","VQ40 bearing set",sale_price_cents=9000,min_stock=2)
        self.db.purchase_stock(bearing,10,5000,"Supplier A")
        s = self.db.stats()
        self.assertEqual(s["cash"],50_000)
        self.assertEqual(s["inventory_value"],50_000)
        self.assertEqual(s["profit"],0)
        self.db.sell_part(bearing,3,9000)
        s = self.db.stats()
        self.assertEqual(self.db.get_product(bearing)["qty"],7)
        self.assertEqual(s["cash"],77_000)
        self.assertEqual(s["inventory_value"],35_000)
        self.assertEqual(s["cogs"],15_000)
        self.assertEqual(s["revenue"],27_000)
        self.assertEqual(s["profit"],12_000)
        self.assertEqual(s["low_stock_count"],0)

    def test_weighted_average(self):
        part = self.db.add_product("L-001","Cylinder liner")
        self.db.purchase_stock(part,2,1000)
        self.db.purchase_stock(part,2,2000)
        self.assertEqual(self.db.get_product(part)["avg_cost_cents"],1500)
        self.db.sell_part(part,1,3000)
        self.assertEqual(self.db.stats()["cogs"],1500)

    def test_services_expenses_and_owner_draw(self):
        self.db.owner_cash(50_000,"owner_funding")
        job = self.db.add_job("Ali","Mercedes W212","OM642","Crankshaft grinding",quote_cents=20_000)
        self.db.record_service("Crankshaft grinding",20_000,job)
        self.db.record_expense("Electricity","Power",3_000)
        self.db.owner_cash(5_000,"owner_draw")
        self.db.set_job_status(job,"done")
        s = self.db.stats()
        self.assertEqual(s["revenue"],20_000)
        self.assertEqual(s["expenses"],3_000)
        self.assertEqual(s["profit"],17_000)
        self.assertEqual(s["cash"],62_000)
        self.assertEqual(s["open_jobs"],0)
        self.assertEqual(self.db.list_sales()[0]["job_id"],job)

    def test_insufficient_stock_rolls_back(self):
        part = self.db.add_product("T-001","Piston")
        self.db.purchase_stock(part,1,200)
        before = self.db.stats()
        with self.assertRaisesRegex(ValueError,"Insufficient stock"):
            self.db.sell_part(part,2,1000)
        self.assertEqual(dict(self.db.stats()),before)
        self.assertEqual(self.db.get_product(part)["qty"],1)
        self.assertEqual(len(self.db.list_sales()),0)

    def test_duplicate_sku_and_invalid_amounts(self):
        self.db.add_product("abc","Oil seal")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.add_product("ABC","Other seal")
        with self.assertRaises(ValueError):
            self.db.record_expense("Fuel","Diesel",0)
        with self.assertRaises(ValueError):
            self.db.owner_cash(-100,"owner_funding")

    def test_ledger_running_balance(self):
        self.db.owner_cash(10000,"owner_funding")
        self.db.record_expense("Rent","Monthly rent",3000)
        self.db.record_service("Honing",5000)
        ledger = self.db.list_ledger()
        self.assertEqual([r["running_balance_cents"] for r in ledger],[12000,7000,10000])

    def test_backup_is_readable(self):
        self.db.add_product("BK","Backup test")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"backup.sqlite3"
            self.db.backup_to(path)
            backed = Database(path)
            try:
                self.assertEqual(backed.list_products()[0]["sku"],"BK")
            finally:
                backed.close()

    def test_bad_job_reference_does_not_change_stock(self):
        product = self.db.add_product("JOB","Bearing")
        self.db.purchase_stock(product,5,100)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.sell_part(product,1,200,99999)
        self.assertEqual(self.db.get_product(product)["qty"],5)


if __name__ == "__main__":
    unittest.main()
