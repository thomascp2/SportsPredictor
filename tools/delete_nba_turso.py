import asyncio
import os
import libsql_client
from pathlib import Path

for line in Path('.env').read_text().splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, _, v = line.partition('=')
        os.environ.setdefault(k.strip(), v.strip())

async def _del():
    url = os.getenv('TURSO_NBA_URL', '').replace('libsql://', 'https://')
    token = os.getenv('TURSO_NBA_TOKEN', '')
    c = libsql_client.create_client(url=url, auth_token=token)
    r = await c.execute("DELETE FROM predictions WHERE game_date = '2026-04-18'")
    await c.close()
    print('Deleted rows:', r.rows_affected)

asyncio.run(_del())
