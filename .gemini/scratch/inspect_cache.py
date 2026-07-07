import sqlite3, json

conn = sqlite3.connect("data/slidevision-cache.sqlite")
conn.row_factory = sqlite3.Row

# List all tables
tables = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall()
print("=== Tables ===")
for t in tables:
    print(f"\n{t['name']}:")
    print(t['sql'])

# Count rows in each
for t in tables:
    count = conn.execute(f"SELECT COUNT(*) as c FROM [{t['name']}]").fetchone()['c']
    print(f"\n{t['name']}: {count} rows")

# Show a sample row's keys
rows = conn.execute("SELECT * FROM visual_descriptions LIMIT 1").fetchall()
if rows:
    print(f"\nvisual_descriptions columns: {list(rows[0].keys())}")

conn.close()
