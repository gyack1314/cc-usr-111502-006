"""演练：快照上构建索引，对比精确、固定 nprobe 近似与候选扩展近似，并跑独立查询集召回核对。"""
import json
import tempfile
from pathlib import Path
from .segments import Segments
from .snapshots import snapshot, exact
from .index import build, approx
from .recall import make_queries, evaluate

body = json.loads(Path('data/sample.json').read_text())
with tempfile.TemporaryDirectory() as tmp:
    store = Segments(tmp, body['dimension'])
    token = store.write(body['rows'])
    frozen = snapshot([token], {row['id']: row['revision'] for row in body['rows']})
    index_token = build(store, [token], 'l2_squared', num_cells=2, seed=11)
    filters = {'area': '海淀'}
    report = {
        'exact': exact(store, frozen, body['query'], 2, filters=filters),
        'approx_fixed_nprobe': approx(store, index_token, frozen, body['query'], 2,
                                      filters=filters, nprobe=1),
        'approx_expand': approx(store, index_token, frozen, body['query'], 2,
                                filters=filters, nprobe=1, expand=True),
        'recall': evaluate(store, index_token, frozen,
                           make_queries(seed=2026, count=4, dimension=body['dimension']),
                           2, nprobe=1, expand=True, query_seed=2026),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
