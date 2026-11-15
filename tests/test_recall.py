import random
import tempfile
import unittest
from vectorlake.segments import Segments
from vectorlake.snapshots import snapshot
from vectorlake.index import build
from vectorlake.recall import make_queries, check_exact, evaluate

def clustered_rows(seed, clusters, per_cluster, dimension):
    rng = random.Random(seed)
    rows = []
    for c in range(clusters):
        center = [rng.uniform(0, 8) for _ in range(dimension)]
        for i in range(per_cluster):
            rows.append({'id': f'c{c}p{i}', 'revision': 1,
                         'vector': [x + rng.gauss(0, 0.05) for x in center],
                         'metadata': {'area': f'a{c % 3}', 'kind': 'k'}})
    return rows

class RecallTests(unittest.TestCase):
    def test_make_queries_deterministic(self):
        first = make_queries(seed=7, count=3, dimension=2)
        self.assertEqual(first, make_queries(seed=7, count=3, dimension=2))
        self.assertNotEqual(first, make_queries(seed=8, count=3, dimension=2))
        self.assertEqual((len(first), len(first[0])), (3, 2))

    def test_exact_cross_check_on_small_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Segments(tmp, 3)
            rows = clustered_rows(seed=1, clusters=3, per_cluster=8, dimension=3)
            token = store.write(rows)
            frozen = snapshot([token], {row['id']: row['revision'] for row in rows})
            queries = make_queries(seed=2, count=6, dimension=3, low=-1.0, high=9.0)
            plain = check_exact(store, frozen, queries, 4)
            self.assertTrue(plain['ok'], plain['mismatches'])
            filtered = check_exact(store, frozen, queries, 4, filters={'area': 'a1'})
            self.assertTrue(filtered['ok'], filtered['mismatches'])

    def test_evaluate_reports_recall_and_access_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Segments(tmp, 4)
            rows = clustered_rows(seed=3, clusters=8, per_cluster=10, dimension=4)
            token = store.write(rows)
            frozen = snapshot([token], {row['id']: row['revision'] for row in rows})
            index_token = build(store, [token], 'l2_squared', num_cells=8, seed=4)
            queries = make_queries(seed=999, count=10, dimension=4, low=-1.0, high=9.0)
            report = evaluate(store, index_token, frozen, queries, 5,
                              nprobe=2, expand=True, query_seed=999)
            self.assertEqual(report['query_count'], 10)
            self.assertEqual(report['query_seed'], 999)
            self.assertEqual(len(report['per_query']), 10)
            self.assertGreaterEqual(report['mean_recall'], 0.0)
            self.assertLessEqual(report['mean_recall'], 1.0)
            self.assertGreater(report['exact_rows_scanned'], 0)
            self.assertLess(report['approx_rows_examined'], report['exact_rows_scanned'])
            self.assertLess(report['approx_distance_computations'], report['exact_rows_scanned'])
            for row in report['per_query']:
                self.assertGreaterEqual(row['recall'], 0.0)
                self.assertLessEqual(row['recall'], 1.0)
                self.assertGreater(row['distance_computations'], 0)
            full = evaluate(store, index_token, frozen, queries, 5, nprobe=8)
            self.assertEqual(full['mean_recall'], 1.0)
            self.assertEqual(full['exact_order_fraction'], 1.0)
            self.assertEqual(full['certified_fraction'], 1.0)

    def test_evaluate_with_filter_uses_filtered_exact_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Segments(tmp, 2)
            rows = clustered_rows(seed=5, clusters=4, per_cluster=6, dimension=2)
            token = store.write(rows)
            frozen = snapshot([token], {row['id']: row['revision'] for row in rows})
            index_token = build(store, [token], 'l2_squared', num_cells=4, seed=6)
            queries = make_queries(seed=11, count=5, dimension=2, low=-1.0, high=9.0)
            report = evaluate(store, index_token, frozen, queries, 3,
                              filters={'area': 'a2'}, nprobe=4)
            self.assertEqual(report['mean_recall'], 1.0)
            self.assertTrue(all(row['reference_count'] <= 3 for row in report['per_query']))

if __name__ == '__main__':
    unittest.main()
