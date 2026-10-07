# Builds heatwave.db from schema.sql and loads seed data.
# `python init_db.py --schema` skips the seed step.
# Drops and recreates everything each time, so it's safe to re-run.

import os
import sqlite3
import sys

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "heatwave.db")
SCHEMA = os.path.join(BASE_DIR, "schema.sql")


def create_schema():
    with open(SCHEMA, "r", encoding="utf-8") as f:
        script = f.read()
    conn = sqlite3.connect(DATABASE)
    conn.executescript(script)
    conn.commit()
    conn.close()
    print(f"[ok] Schema created in {DATABASE}")


def main():
    schema_only = "--schema" in sys.argv
    create_schema()
    if not schema_only:
        import seed
        seed.run()
    print("[done] Database is ready.")


if __name__ == "__main__":
    main()
