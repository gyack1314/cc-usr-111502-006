"""快照定义与可认证精确近邻查询；可见性、过滤、并列排序是各查询路径共用的正文语义。"""
import hashlib
import json
from .metrics import validate, distance

def snapshot(segments, live):
    body = {'segments': list(segments), 'live': dict(live)}
    body['digest'] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return body

def is_live(live, row):
    """快照可见性：live 映射决定可见 revision，删除即映射不再包含该 id。"""
    return live.get(row['id']) == row['revision']

def match_filters(metadata, filters):
    """有类型相等与 AND；bool 与数值不同型，字符串数字不隐式转换。"""
    return all(type(metadata.get(name)) is type(value) and metadata.get(name) == value
               for name, value in (filters or {}).items())

def rank(rows):
    """相同距离按逻辑 id 的 UTF-8 顺序稳定排列；调用方截断前 K，不扩展 ties。"""
    return sorted(rows, key=lambda row: (row['distance'], row['id'].encode()))

def check_k(k):
    if type(k) is not int or k < 0:
        raise ValueError('K必须为非负整数')

def exact(store, frozen, query, k, metric='l2_squared', filters=None):
    """可认证精确模式：全扫描，过滤后前 K 条即完整答案。"""
    query = validate(query, store.dimension)
    check_k(k)
    result = []
    seen = set()
    for token in frozen['segments']:
        for row in store.scan(token):
            if not is_live(frozen['live'], row):
                continue
            key = row['id'], row['revision']
            if key in seen:
                continue
            seen.add(key)
            if not match_filters(row['metadata'], filters):
                continue
            result.append({'id': row['id'], 'revision': row['revision'], 'distance': distance(query, row['vector'], metric)})
    return rank(result)[:k]
