import os
from datetime import datetime, timedelta, UTC
from collections import defaultdict
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


def avg(vals):
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def pct(vals, p):
    if not vals:
        return 0.0
    vals = sorted(vals)
    idx = min(len(vals) - 1, max(0, int((len(vals) - 1) * p)))
    return round(vals[idx], 4)


user = os.environ['MYSQL_USER']
password = os.environ['MYSQL_PASSWORD']
host = os.environ['MYSQL_HOST']
port = os.environ['MYSQL_PORT']
db = os.environ['MYSQL_DB']
url = URL.create(
    drivername="mysql+pymysql",
    username=user,
    password=password,
    host=host,
    port=int(port),
    database=db,
)
engine = create_engine(url)
now = datetime.now(UTC).replace(tzinfo=None)
recent_since = now - timedelta(days=7)
prev_since = now - timedelta(days=21)

with engine.connect() as conn:
    rows = conn.execute(
        text(
            '''
            SELECT
                eql.symbol,
                eql.total_is_bps,
                eql.algo_type,
                eql.quantity_ordered,
                eql.quantity_filled,
                eql.fill_rate,
                eql.created_at,
                aei.status AS intent_status,
                aei.reason AS intent_reason
            FROM execution_quality_log eql
            LEFT JOIN autonomous_execution_intent aei ON aei.id = eql.intent_id
            WHERE eql.account_id = :account_id AND eql.created_at >= :prev_since
            ORDER BY eql.created_at DESC
            LIMIT 500
            '''
        ),
        {"account_id": os.environ['TIGER_ACCOUNT'], "prev_since": prev_since},
    ).mappings().all()

recent = [r for r in rows if r['created_at'] and r['created_at'] >= recent_since]
prev = [r for r in rows if not (r['created_at'] and r['created_at'] >= recent_since)]

print('recent_sample=', len(recent))
print('prev_sample=', len(prev))
print('recent_avg=', avg([float(r['total_is_bps'] or 0) for r in recent]))
print('prev_avg=', avg([float(r['total_is_bps'] or 0) for r in prev]))
print('recent_p50=', pct([float(r['total_is_bps'] or 0) for r in recent], 0.5))
print('prev_p50=', pct([float(r['total_is_bps'] or 0) for r in prev], 0.5))
print('recent_p90=', pct([float(r['total_is_bps'] or 0) for r in recent], 0.9))
print('prev_p90=', pct([float(r['total_is_bps'] or 0) for r in prev], 0.9))

for label, bucket in [('recent', recent), ('prev', prev)]:
    by_symbol = defaultdict(list)
    by_algo = defaultdict(list)
    by_status = defaultdict(list)
    for r in bucket:
        by_symbol[r['symbol']].append(float(r['total_is_bps'] or 0))
        by_algo[str(r['algo_type'] or 'UNKNOWN')].append(float(r['total_is_bps'] or 0))
        by_status[str(r['intent_status'] or 'UNKNOWN')].append(float(r['total_is_bps'] or 0))
    top_symbols = sorted(
        ((s, avg(v), len(v), max(v)) for s, v in by_symbol.items()),
        key=lambda x: x[1],
        reverse=True,
    )[:8]
    top_algos = sorted(
        ((a, avg(v), len(v), max(v)) for a, v in by_algo.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    print(f'-- {label} top symbols --')
    for item in top_symbols:
        print(item)
    print(f'-- {label} algos --')
    for item in top_algos:
        print(item)
    print(f'-- {label} statuses --')
    for item in sorted(((s, avg(v), len(v), max(v)) for s, v in by_status.items()), key=lambda x: x[1], reverse=True):
        print(item)

print('-- recent worst trades --')
for r in sorted(recent, key=lambda x: float(x['total_is_bps'] or 0), reverse=True)[:12]:
    print(
        r['created_at'],
        r['symbol'],
        float(r['total_is_bps'] or 0),
        r['algo_type'],
        r['intent_status'],
        r['quantity_ordered'],
        r['quantity_filled'],
        r['fill_rate'],
        (r['intent_reason'] or '')[:80],
    )
