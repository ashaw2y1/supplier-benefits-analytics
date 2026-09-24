"""Fixed, hash-verified synthetic source. No configurable backend or writes."""
from pathlib import Path
import hashlib
import sqlite3
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'synthetic.sqlite3'
TABLES = ('suppliers','items','locations','agreements','grn','cn_headers','cn_details','noi','targets','metadata')

def connect():
    if DATA.is_symlink() or DATA.parent.is_symlink():
        raise RuntimeError('Fixture integrity error')
    expected = (ROOT / 'data' / 'fixture.sha256').read_text().strip()
    if hashlib.sha256(DATA.read_bytes()).hexdigest() != expected:
        raise RuntimeError('Fixture integrity error')
    conn = sqlite3.connect(DATA.as_uri() + '?mode=ro&immutable=1', uri=True)
    conn.execute('PRAGMA query_only=ON')
    if hasattr(conn, 'enable_load_extension'):
        conn.enable_load_extension(False)
    return conn

def load():
    conn = connect()
    try:
        return {name: pd.read_sql_query('SELECT * FROM '+name, conn) for name in TABLES}
    finally:
        conn.close()
