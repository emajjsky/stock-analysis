"""只导出行情目录/历史，排除用户自选、模型设置、账户、研究与私人记录。"""
import argparse
import json
import sqlite3
import time
from pathlib import Path

from backend.history_sync import HistorySync


def main():
    from backend.app import create_app
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='.runtime/release/seed.db')
    parser.add_argument('--source', default='.local/workstation.db')
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    app = create_app(path, network_enabled=False)
    store = app.state.store
    if not store.db.execute('SELECT 1 FROM security_catalog LIMIT 1').fetchone():
        source = sqlite3.connect(args.source)
        with store.lock, store.db:
            store.db.executemany('INSERT OR IGNORE INTO security_catalog VALUES(?,?,?,?,?,?)',source.execute('SELECT * FROM security_catalog'))
            for row in source.execute("SELECT kind,id,payload FROM documents WHERE kind IN ('index_daily','history_coverage')"):
                store.db.execute('INSERT OR IGNORE INTO documents VALUES(?,?,?)',row)
            store.db.executemany('INSERT OR IGNORE INTO provider_bars VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',source.execute('SELECT * FROM provider_bars'))
        source.close()
    sync = HistorySync(store, app.state.terminal)
    if args.download:
        sync.start()
        while sync.thread.is_alive():
            print(json.dumps(sync.status(), ensure_ascii=False), flush=True)
            time.sleep(20)
    print(json.dumps(sync.status(), ensure_ascii=False), flush=True)
    with store.lock:
        store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')


if __name__ == '__main__':
    main()
