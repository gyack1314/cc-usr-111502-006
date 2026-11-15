"""IVF 近似近邻索引：构建、落盘恢复、合并与带候选扩展的快照过滤近似查询。

索引按内容寻址写入 段根目录/indexes/，绑定段摘要列表、维度、距离规则与种子。
分格使用确定性 k-means（kmeans++，种子固定），质心指派始终按平方欧氏，
与查询时距离规则无关；索引只为构建时的距离规则服务。
"""
import hashlib
import json
import math
import random
from bisect import insort
from pathlib import Path
from .metrics import validate, distance
from .snapshots import is_live, match_filters, check_k, exact

METRICS = ('l2_squared', 'negative_dot')

def _index_dir(store):
    return Path(store.root) / 'indexes'

def _check_index(body, dimension):
    if body.get('kind') != 'ivf' or body.get('version') != 1:
        raise ValueError('未知索引格式')
    if body['dimension'] != dimension:
        raise ValueError('索引维度不兼容')

def _squared_l2(left, right):
    return distance(left, right, 'l2_squared')

def _kmeans(points, num_cells, seed, max_iter):
    rng = random.Random(seed)
    centroids = [points[rng.randrange(len(points))]]
    while len(centroids) < num_cells:
        weights = [min(_squared_l2(point, centroid) for centroid in centroids) for point in points]
        total = math.fsum(weights)
        if total <= 0:
            pick = rng.randrange(len(points))
        else:
            threshold = rng.random() * total
            pick = len(points) - 1
            acc = 0.0
            for i, weight in enumerate(weights):
                acc += weight
                if threshold <= acc:
                    pick = i
                    break
        centroids.append(points[pick])
    assignments = None
    for _ in range(max_iter):
        new = [min(range(len(centroids)), key=lambda c: (_squared_l2(point, centroids[c]), c)) for point in points]
        if new == assignments:
            break
        assignments = new
        for cell in range(len(centroids)):
            members = [point for point, assigned in zip(points, assignments) if assigned == cell]
            if members:
                centroids[cell] = tuple(math.fsum(values) / len(members) for values in zip(*members))
    assignments = [min(range(len(centroids)), key=lambda c: (_squared_l2(point, centroids[c]), c)) for point in points]
    cells = [[] for _ in centroids]
    for i, cell in enumerate(assignments):
        cells[cell].append(i)
    return centroids, cells

def build(store, tokens, metric, num_cells, seed=0, max_iter=32):
    """在指定段集合上构建索引，返回内容寻址 token。同一 (id, revision) 去重，内容冲突即报错。"""
    if metric not in METRICS:
        raise ValueError('未知距离规则')
    if type(num_cells) is not int or num_cells < 1:
        raise ValueError('格数必须为正整数')
    if type(seed) is not int:
        raise ValueError('种子必须为整数')
    rows = []
    seen = {}
    for token in tokens:
        for row in store.scan(token):
            key = row['id'], row['revision']
            if key in seen:
                first = seen[key]
                if first['vector'] != row['vector'] or first['metadata'] != row['metadata']:
                    raise ValueError('向量行版本冲突')
                continue
            seen[key] = row
            rows.append({'id': row['id'], 'revision': row['revision'],
                         'vector': list(row['vector']), 'metadata': dict(row['metadata'])})
    points = [tuple(row['vector']) for row in rows]
    if rows:
        cell_count = min(num_cells, len(rows))
        centroids, cells = _kmeans(points, cell_count, seed, max_iter)
    else:
        cell_count, centroids, cells = 0, [], []
    postings = [[rows[i] for i in cell] for cell in cells]
    radii = [max((math.sqrt(_squared_l2(centroids[c], points[i])) for i in cell), default=0.0)
             for c, cell in enumerate(cells)]
    body = {'kind': 'ivf', 'version': 1, 'dimension': store.dimension, 'metric': metric,
            'segments': list(tokens), 'seed': seed, 'num_cells': cell_count,
            'centroids': [list(centroid) for centroid in centroids], 'radii': radii,
            'postings': postings}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    token = hashlib.sha256(raw).hexdigest()
    directory = _index_dir(store)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / token).write_bytes(raw)
    return token

def load(store, token):
    """从磁盘恢复索引并校验摘要、格式与维度。"""
    raw = (_index_dir(store) / token).read_bytes()
    if hashlib.sha256(raw).hexdigest() != token:
        raise ValueError('索引摘要不符')
    body = json.loads(raw)
    _check_index(body, store.dimension)
    return body

def merge(store, tokens, num_cells=None, seed=None):
    """合并同维度、同距离规则的索引为新索引；旧索引与旧段保留，旧快照仍由旧索引服务。"""
    indexes = [load(store, token) for token in tokens]
    if not indexes:
        raise ValueError('没有可合并的索引')
    metric = indexes[0]['metric']
    if any(body['metric'] != metric for body in indexes):
        raise ValueError('距离规则不同，不能合并')
    segments = []
    for body in indexes:
        for token in body['segments']:
            if token not in segments:
                segments.append(token)
    if num_cells is None:
        num_cells = max([body['num_cells'] for body in indexes] + [1])
    if seed is None:
        seed = min(body['seed'] for body in indexes)
    return build(store, segments, metric, num_cells, seed)

def _cell_bound(centroid_distance, radius):
    """格内向量距离的保守下界（三角不等式，向零留浮点余量）；溢出时放弃认证。"""
    if not math.isfinite(centroid_distance) or not math.isfinite(radius):
        return 0.0
    base = math.sqrt(centroid_distance) - radius
    if base <= 0:
        return 0.0
    bound = base * base
    return math.nextafter(math.nextafter(bound, 0.0), 0.0)

def _certified(body, ranked, k, metric, centroid_distances, order, probed):
    """已探测结果是否可认证为完整答案：全部耗尽，或 l2 下界证明剩余格进不了前 K。"""
    if probed >= body['num_cells']:
        return True
    if metric != 'l2_squared' or k == 0 or len(ranked) < k:
        return False
    kth = ranked[k - 1][0]
    return kth < min(_cell_bound(centroid_distances[c], body['radii'][c]) for c in order[probed:])

def _approx_result(params, cells_total, centroid_distances, cells_probed, rows_examined,
                   visible, computations, matched, results, exhausted, certified, stop_reason):
    return {'mode': 'approx', 'params': params,
            'stats': {'cells_total': cells_total, 'cells_probed': cells_probed,
                      'centroid_distances': centroid_distances,
                      'rows_examined': rows_examined, 'visible_candidates': visible,
                      'distance_computations': computations, 'matched_candidates': matched,
                      'exhausted': exhausted, 'certified': certified, 'stop_reason': stop_reason},
            'results': results}

def approx(store, index_ref, frozen, query, k, metric=None, filters=None, nprobe=1,
           expand=False, require_certified=False, on_incompatible='raise'):
    """快照上的近似近邻查询。

    逐格探测：快照可见性先于距离计算，元数据过滤在距离计算之后。
    expand=False 只探测 nprobe 格；expand=True 探测到过滤后候选满 K；
    require_certified=True 继续扩到可认证或耗尽。结果不承诺恰有 K 条，
    除非 stats 中 exhausted 或 certified 为真。
    """
    body = load(store, index_ref) if isinstance(index_ref, str) else index_ref
    _check_index(body, store.dimension)
    if metric is not None and metric != body['metric']:
        raise ValueError('距离规则与索引不符')
    used_metric = body['metric']
    params = {'k': k, 'metric': used_metric, 'filters': dict(filters or {}),
              'nprobe_requested': nprobe, 'expand': bool(expand),
              'require_certified': bool(require_certified), 'snapshot': frozen.get('digest')}
    if set(frozen['segments']) != set(body['segments']):
        if on_incompatible == 'fallback':
            before = store.rows_read
            results = exact(store, frozen, query, k, used_metric, filters)
            return {'mode': 'exact_fallback', 'reason': '索引段集合与快照不一致',
                    'params': params, 'stats': {'rows_scanned': store.rows_read - before},
                    'results': results}
        if on_incompatible == 'raise':
            raise ValueError('索引段集合与快照不一致')
        raise ValueError('未知的不一致处理策略')
    query = validate(query, store.dimension)
    check_k(k)
    if type(nprobe) is not int or nprobe < 1:
        raise ValueError('nprobe必须为正整数')
    cell_count = body['num_cells']
    if k == 0 or cell_count == 0:
        return _approx_result(params, cell_count, 0, 0, 0, 0, 0, 0, [],
                              exhausted=cell_count == 0, certified=True,
                              stop_reason='empty' if cell_count == 0 else 'k_zero')
    probe_limit = min(nprobe, cell_count)
    centroid_distances = [_squared_l2(query, centroid) for centroid in body['centroids']]
    order = sorted(range(cell_count), key=lambda c: (centroid_distances[c], c))
    ranked = []
    rows_examined = visible = computations = matched = 0
    probed = 0
    stop_reason = None
    for cell in order:
        if probed >= probe_limit:
            if not expand:
                stop_reason = 'fixed_nprobe'
                break
            if require_certified:
                if _certified(body, ranked, k, used_metric, centroid_distances, order, probed):
                    stop_reason = 'certified'
                    break
            elif len(ranked) >= k:
                stop_reason = 'count_reached'
                break
        for row in body['postings'][cell]:
            rows_examined += 1
            if not is_live(frozen['live'], row):
                continue
            visible += 1
            score = distance(query, row['vector'], used_metric)
            computations += 1
            if not match_filters(row['metadata'], filters):
                continue
            matched += 1
            insort(ranked, (score, row['id'].encode(), row['id'], row['revision']))
        probed += 1
    if stop_reason is None:
        stop_reason = 'exhausted'
    exhausted = probed == cell_count
    certified = exhausted or _certified(body, ranked, k, used_metric, centroid_distances, order, probed)
    results = [{'id': item[2], 'revision': item[3], 'distance': item[0]} for item in ranked[:k]]
    return _approx_result(params, cell_count, cell_count, probed, rows_examined, visible,
                          computations, matched, results, exhausted, certified, stop_reason)
