import sqlite3, os
path = os.path.expandvars(r'%APPDATA%\GND\history.db')
conn = sqlite3.connect(path)
try:
    for table in ('probe_results', 'traceroute_results', 'active_game_servers'):
        cur = conn.execute(f"DELETE FROM {table} WHERE run_id LIKE 'hist-%'")
        print(f'{table}: {cur.rowcount} filas borradas')
    cur = conn.execute("DELETE FROM diagnostic_runs WHERE run_id LIKE 'hist-%'")
    print(f'diagnostic_runs: {cur.rowcount} filas borradas')
    conn.commit()
    print('OK - commit completado')
except Exception as e:
    print(f'ERROR: {e}')
    conn.rollback()
finally:
    conn.close()