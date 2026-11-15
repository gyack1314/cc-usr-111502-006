"""当前全文精确近邻查询。"""
import hashlib
import json
from .metrics import validate, distance

def snapshot(segments, live):
    body = {'segments': list(segments), 'live': dict(live)}
    body['digest'] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return body

def exact(store, frozen, query, k, metric='l2_squared', filters=None):
    query = validate(query, store.dimension)
    if type(k) is not int or k < 0:
        raise ValueError('K必须为非负整数')
    result = []
    seen = set()
    for token in frozen['segments']:
        for row in store.scan(token):
            if frozen['live'].get(row['id']) != row['revision']:
                continue
            key = row['id'], row['revision']
            if key in seen:
                continue
            seen.add(key)
            if any(type(row['metadata'].get(name)) is not type(value) or row['metadata'].get(name) != value for name, value in (filters or {}).items()):
                continue
            result.append({'id': row['id'], 'revision': row['revision'], 'distance': distance(query, row['vector'], metric)})
    return sorted(result, key=lambda row: (row['distance'], row['id'].encode()))[:k]
