"""Demonstrate the accounting model in a Codespaces terminal; no GUI required."""
from database import Database


def display_cents(value):
    return f"{value / 100:,.2f}"


def main():
    db = Database(":memory:")
    try:
        db.owner_cash(100_000, "owner_funding", "Opening cash")
        item = db.add_product("BRG-VQ40", "Main bearing set", sale_price_cents=9000, min_stock=2)
        db.purchase_stock(item, 10, 5000, "Parts supplier")
        job = db.add_job("Example customer", "Nissan Pathfinder", "VQ40DE", "Crankshaft grinding")
        db.sell_part(item, 1, 9000, job)
        db.record_service("Crankshaft grinding", 20000, job)
        db.record_expense("Electricity", "Workshop power", 3000)
        db.set_job_status(job, "done")
        stats = db.stats()
        print("\nWORKSHOP LEDGER EXAMPLE (in USD)")
        for key in ("cash", "revenue", "cogs", "expenses", "profit", "inventory_value"):
            print(f"{key.replace('_',' ').title():<22}: {display_cents(stats[key]):>10}")
        print("Stock remaining        :", db.get_product(item)["qty"])
        assert stats["cash"] == 76000
        assert stats["profit"] == 21000
        print("\nExample calculations passed. No local data was saved.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
