# Workshop Ledger — Offline Inventory + Cash for Engine Workshops

A small Windows desktop app for engine machining workshops. UI: Python + PySide6. Storage: SQLite. The desktop app works offline and stores its data **on the Windows PC**, not on your phone or on GitHub.

## Features (first working version)

- Dashboard: cash, revenue, operating profit, inventory value, cost of goods sold, expenses, low-stock count and open machining jobs.
- Inventory: add/edit part numbers, names, categories, unit, selling price, low-stock threshold; receive purchased stock with cost; automatically compute weighted-average cost.
- Workshop jobs: register customer, vehicle, engine code, machining work, notes, quote and status.
- Sales: sell inventory parts (decrease stock), record machining fees; optionally link a sale or service to a job.
- Expenses: wages, rent, electricity, fuel, repairs, etc.
- Owner cash: contributions and withdrawals tracked in the cash ledger without affecting profit.
- Local SQLite data and a **Back up data** button.
- Build a Windows `.exe` using GitHub Actions — no Windows PC needed to compile.

## Accounting rules

**Single-currency, cash-only, whole-unit inventory.** All sales are paid immediately; all recorded stock purchases and operating expenses are paid immediately. No VAT, credit sales, invoicing, returns, foreign currency conversion, payroll accounting, depreciation or full double-entry ledger in v1.

- Inventory purchase: quantity +, inventory asset +, cash -; **profit unchanged**.
- Part sale: quantity -, cash +, revenue +, COGS + (using item's weighted-average cost).
- Service payment: cash +, service revenue +.
- Operating expense: cash -, expense +.
- Owner contribution/withdrawal: cash changes, profit **unchanged**.
- **Operating profit = parts sales + service revenue - COGS - operating expenses.** This is not net profit after tax or depreciation.
- Stock quantities cannot go below zero. Purchase and sale transactions are committed atomically.
- Low-stock count includes any part whose quantity is equal to/below its minimum threshold. Set minimum stock to 1 or more to trigger warnings before running out.
- Job **quotes are not cash receipts**. To recognize income, explicitly record a sale or machining service.
- When a stock purchase is recorded at zero cost, no cash movement is created (e.g. donated parts).
- Inventory valuation is rounded to cents per average-cost unit; rounding can produce small differences from the original purchase totals.
- Owner funding must be recorded if you want a meaningful cash balance; negative cash suggests transactions were not fully recorded.
- There is no stock-consumption write-off for parts used internally in v1; parts billed to customers should be sold as parts, linked to the relevant job where useful.

## Files

```text
app.py                          Program entry point; optional --self-test
windows.py                      Desktop screens, forms and tables
database.py                     SQLite database, transactions, finance rules
tests/test_database.py           Automated accounting/database tests
demo_cli.py                     No-GUI financial demonstration for phone/Codespaces
requirements.txt                Desktop UI and packaging dependencies
.github/workflows/build-windows.yml  Build and test Windows .exe on GitHub
.gitignore                      Excludes databases and build files
```

## Develop and compile entirely from an Android phone

1. Download `workshop-ledger-source.zip` from the ChatGPT response and save it on Android.
2. In your mobile browser, log in to [GitHub](https://github.com/) and create a **private** repository, e.g. `workshop-ledger`. Keep it initialized with a README so the Codespace can start. If mobile controls are limited, enable the browser's **Desktop site** setting.
3. On the repository, select **Code → Codespaces → Create codespace on main**. GitHub opens a VS Code editor in your browser. Codespaces may use included monthly quota or charge according to your account and use.
4. In the browser Codespaces Explorer (left panel), use its menu / right-click context menu **Upload Files** and choose the ZIP from Android's Downloads. If that command is inaccessible on mobile, extract the ZIP on Android and use the repository's GitHub **Add file → Upload files** interface to upload files individually, creating `.github/workflows/build-windows.yml` with the web editor.
5. In the Codespaces terminal (Terminal → New Terminal), run:

   ```bash
   unzip -o workshop-ledger-source.zip -d .
   rm workshop-ledger-source.zip
   python -m unittest discover -s tests -v
   python demo_cli.py
   git add .
   git commit -m "First working inventory app"
   git push
   ```

   **Important:** run these commands only if you uploaded the ZIP to the current repository root. If Android or your browser renamed the ZIP, substitute its actual filename in both commands. If Git says 'nothing to commit', check that extraction created `app.py` in the repository root. If Git requests identity setup, configure `git config user.name "Your Name"` and `git config user.email "you@example.com"` with your own GitHub details.

6. Open the GitHub repository's **Actions** tab, select **Build Windows EXE**, and open the triggered run. It runs database tests, a Qt window construction smoke test, builds the EXE on a Windows runner, and uploads an artifact.
7. Under **Artifacts**, download **WorkshopLedger-Windows**. This is a ZIP containing `WorkshopLedger.exe`. Transfer the EXE from your Android phone to your Windows PC and run it. The EXE is unsigned, so Windows may warn about an unknown publisher: verify you built it from your own trusted source before running it.

**Important limitation:** Codespaces is normally Linux and does not give you a visible Windows desktop window on Android. It lets you *edit and run database tests*; the GitHub Windows runner builds and smoke-tests the app. For visual testing of the real UI, use your Windows computer or a remote Windows machine.

Reference: [GitHub's Codespaces docs](https://docs.github.com/en/codespaces/developing-in-a-codespace/developing-in-a-codespace), [GitHub Actions artifact downloads](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts), and [PyInstaller documentation](https://pyinstaller.org/en/stable/operating-mode.html).

## Running on a Windows PC directly (optional)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

To build locally:

```powershell
pyinstaller --noconfirm --clean --onefile --windowed --name WorkshopLedger app.py
```

For a **single-currency** deployment, edit `CURRENCY = "USD"` inside `windows.py` to the desired three-letter code **before first entering data**. This changes only the display label: it does **not** convert historical amounts. For currencies without fractional units, the interface still uses two decimal places in v1. Never change the currency of a populated database without an intentional accounting migration.

## Sample workflow

1. **Expenses & Cash → Add owner funds:** enter initial cash, e.g. 1,000 USD.
2. **Inventory → New part:** `BRG-VQ40`, "Main bearing set", selling price 90 USD, minimum stock 2.
3. **Inventory → Receive stock:** 10 bearing sets at 50 USD each; the app pays 500 cash and carries 500 inventory value; profit stays zero.
4. **Workshop Jobs → New job:** customer, vehicle, engine and crankshaft grinding work.
5. **Sales & Services → Sell a part:** 1 bearing set at 90 USD, optionally link to the job. Revenue +90, cost of goods sold +50, gross profit +40.
6. **Sales & Services → Record a service:** crankshaft grinding for 200 USD; link the same job.
7. **Expenses & Cash → Expense:** electricity bill 30 USD.
8. Check **Dashboard:** operating profit is **210 USD** (90 + 200 - 50 - 30) and cash balance is **760 USD** (1,000 - 500 + 90 + 200 - 30).
9. **Back up data** to an external drive regularly. Restoring a backup requires closing the app, replacing the database in the path described below and restarting it.

## Database schema

```text
products(id, sku, name, category, unit, qty, avg_cost_cents, sale_price_cents, min_stock, created_at)
purchases(id, product_id, qty, unit_cost_cents, total_cents, note, created_at)
sales(id, kind, product_id?, job_id?, description, qty, unit_price_cents, revenue_cents, cogs_cents, created_at)
expenses(id, category, description, amount_cents, created_at)
jobs(id, customer, vehicle, engine, work_type, notes, quote_cents, status, created_at, completed_at?)
cash_entries(id, kind, ref_table, ref_id?, description, delta_cents, created_at)
stock_movements(id, product_id, kind, delta_qty, ref_id, created_at)
```

Money uses INTEGER cents to avoid binary floating-point totals. Quantity uses whole units for the MVP. Timestamp fields store UTC. Products are never physically deleted in v1, so transaction history keeps its references.

## Where does the Windows app save the data?

`%LOCALAPPDATA%\WorkshopLedger\workshop.sqlite3`

Your GitHub repository and EXE **do not include your inventory and cash data**. It lives on the PC where you run the app. Use **Back up data** to export a consistent SQLite snapshot; keep a second copy somewhere safe. Do not manually copy the live `.sqlite3` while the program is running, because it uses SQLite WAL mode.

## Testing and known MVP limits

Run `python -m unittest discover -s tests -v` for transaction tests. The Windows workflow additionally constructs the Qt UI in offscreen mode and smoke-tests the packaged executable. These checks do not replace visual testing or a user-acceptance test on a real Windows PC.

This MVP deliberately omits tax, multi-currency, customer credit, invoices, refunds, partial payments, job labor costs, direct material consumption, audit permissions, multiuser sync, advanced reports, stock write-offs and expense edits. For real accounting or compliance use, an accountant should validate your setup and workflows first.
