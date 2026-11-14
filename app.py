"""Entry point for the Windows desktop app."""
import sys
from PySide6.QtWidgets import QApplication
from database import Database
from windows import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Workshop Ledger")
    if "--self-test" in sys.argv:
        db = Database(":memory:")
        window = MainWindow(db)
        window.refresh_all()
        window.close()
        db.close()
        print("UI self-test passed")
        return 0
    db = Database()
    try:
        window = MainWindow(db)
        window.show()
        return app.exec()
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
