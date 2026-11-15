"""独立查询集上的召回核对与精确模式交叉验证。

查询集由公开种子均匀生成，不取自索引样本或质心；召回参照过滤后精确 TopK；
报告测得值，不预设固定结论。
"""
import random
from .metrics import validate, distance
from .snapshots import is_live, match_filters, rank, check_k, exact
from .index import load, approx

def make_queries(seed, count, dimension, low=0.0, high=1.0):
    """固定种子的独立查询集：均匀随机生成，与索引构建互不知情。"""
    rng = random.Random(seed)
    return [[rng.uniform(low, high) for _ in range(dimension)] for _ in range(count)]

def brute_force(store, frozen, query, k, metric='l2_squared', filters=None):
    """独立实现的过滤后全扫描 TopK，用于在小快照上核对 exact。"""
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
            result.append({'id': row['id'], 'revision': row['revision'],
                           'distance': distance(query, row['vector'], metric)})
    return rank(result)[:k]

def check_exact(store, frozen, queries, k, metric='l2_squared', filters=None):
    """小快照上用独立全扫描核对 exact：结果应逐条一致。"""
    mismatches = []
    for query in queries:
        want = exact(store, frozen, query, k, metric, filters)
        got = brute_force(store, frozen, query, k, metric, filters)
        if want != got:
            mismatches.append({'query': query, 'exact': want, 'brute_force': got})
    return {'ok': not mismatches, 'queries': len(queries), 'mismatches': mismatches}

def evaluate(store, index_ref, frozen, queries, k, filters=None, nprobe=1,
             expand=False, require_certified=False, query_seed=None):
    """在独立查询集上衡量近似召回与实际访问量，参照为过滤后 exact TopK。"""
    body = load(store, index_ref) if isinstance(index_ref, str) else index_ref
    metric = body['metric']
    per_query = []
    exact_rows_before = store.rows_read
    approx_distances = approx_rows = certified = order_match = 0
    for query in queries:
        reference = exact(store, frozen, query, k, metric, filters)
        got = approx(store, body, frozen, query, k, filters=filters, nprobe=nprobe,
                     expand=expand, require_certified=require_certified)
        ref_ids = [row['id'] for row in reference]
        got_ids = [row['id'] for row in got['results']]
        hits = len(set(ref_ids) & set(got_ids))
        recall = hits / len(ref_ids) if ref_ids else 1.0
        same_order = ref_ids == got_ids
        stats = got['stats']
        approx_distances += stats['distance_computations']
        approx_rows += stats['rows_examined']
        certified += 1 if stats['certified'] else 0
        order_match += 1 if same_order else 0
        per_query.append({'recall': recall, 'reference_count': len(ref_ids),
                          'returned_count': len(got_ids), 'order_match': same_order,
                          'cells_probed': stats['cells_probed'],
                          'distance_computations': stats['distance_computations'],
                          'certified': stats['certified']})
    count = len(queries)
    recalls = [row['recall'] for row in per_query]
    return {'mode': 'recall_report', 'snapshot': frozen.get('digest'), 'metric': metric,
            'k': k, 'nprobe': nprobe, 'expand': bool(expand),
            'require_certified': bool(require_certified),
            'query_count': count, 'query_seed': query_seed,
            'mean_recall': sum(recalls) / count if count else 0.0,
            'min_recall': min(recalls) if recalls else 0.0,
            'exact_order_fraction': order_match / count if count else 0.0,
            'certified_fraction': certified / count if count else 0.0,
            'approx_distance_computations': approx_distances,
            'approx_rows_examined': approx_rows,
            'exact_rows_scanned': store.rows_read - exact_rows_before,
            'per_query': per_query}
