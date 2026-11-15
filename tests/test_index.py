import random
import tempfile
import unittest
from vectorlake.segments import Segments
from vectorlake.snapshots import snapshot, exact
from vectorlake.index import build, load, merge, approx

def make_rows(prefix, count, dimension, seed, area='A', kind='x', base=0.0):
    rng = random.Random(seed)
    return [{'id': f'{prefix}{i}', 'revision': 1,
             'vector': [base + rng.random() for _ in range(dimension)],
             'metadata': {'area': area, 'kind': kind}} for i in range(count)]

def live_of(rows):
    return {row['id']: row['revision'] for row in rows}

class IndexTests(unittest.TestCase):
    def test_approx_reports_and_reduces_distance_computations(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Segments(tmp, 4)
            rows = make_rows('p', 60, 4, seed=1)
            token = store.write(rows)
            frozen = snapshot([token], live_of(rows))
            index_token = build(store, [token], 'l2_squared', num_cells=6, seed=2)
            result = approx(store, index_token, frozen, [0.5, 0.5, 0.5, 0.5], 5, nprobe=1)
            self.assertEqual(result['mode'], 'approx')
            self.assertEqual(result['params']['nprobe_requested'], 1)
            self.assertEqual(result['params']['metric'], 'l2_squared')
            stats = result['stats']
            self.assertEqual(stats['cells_probed'], 1)
            self.assertEqual(stats['cells_total'], 6)
            self.assertLess(stats['distance_computations'], 60)
            self.assertEqual(stats['distance_computations'], stats['visible_candidates'])
            self.assertFalse(stats['exhausted'])
            self.assertFalse(stats['certified'])
            keys = [(row['distance'], row['id'].encode()) for row in result['results']]
            self.assertEqual(keys, sorted(keys))
            self.assertLessEqual(len(result['results']), 5)

    def test_persistence_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Segments(tmp, 2)
            rows = make_rows('p', 20, 2, seed=3)
            token = store.write(rows)
            frozen = snapshot([token], live_of(rows))
            index_token = build(store, [token], 'l2_squared', num_cells=3, seed=4)
            before = approx(store, index_token, frozen, [0.1, 0.2], 4, nprobe=2)
            reopened = Segments(tmp, 2)
            loaded = load(reopened, index_token)
            after = approx(reopened, loaded, frozen, [0.1, 0.2], 4, nprobe=2)
            self.assertEqual(before['results'], after['results'])

    def test_snapshot_isolation_after_revision_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Segments(tmp, 1)
            first = store.write([
                {'id': 'a', 'revision': 1, 'vector': [0.], 'metadata': {'area': 'A'}},
                {'id': 'b', 'revision': 1, 'vector': [1.], 'metadata': {'area': 'A'}},
                {'id': 'c', 'revision': 1, 'vector': [2.], 'metadata': {'area': 'A'}}])
            old_index = build(store, [first], 'l2_squared', num_cells=2, seed=1)
            second = store.write([{'id': 'a', 'revision': 2, 'vector': [5.], 'metadata': {'area': 'A'}}])
            old = snapshot([first], {'a': 1, 'b': 1, 'c': 1})
            new = snapshot([first, second], {'a': 2, 'b': 1})
            old_result = approx(store, old_index, old, [0.], 3, nprobe=2)
            self.assertEqual([(row['id'], row['revision']) for row in old_result['results']],
                             [('a', 1), ('b', 1), ('c', 1)])
            with self.assertRaises(ValueError):
                approx(store, old_index, new, [0.], 3)
            fallback = approx(store, old_index, new, [0.], 3, on_incompatible='fallback')
            self.assertEqual(fallback['mode'], 'exact_fallback')
            self.assertEqual(fallback['results'], exact(store, new, [0.], 3))
            new_index = build(store, [first, second], 'l2_squared', num_cells=2, seed=1)
            new_result = approx(store, new_index, new, [0.], 3, nprobe=2)
            self.assertEqual([(row['id'], row['revision']) for row in new_result['results']],
                             [('b', 1), ('a', 2)])

    def test_narrow_filter_expansion(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Segments(tmp, 2)
            near = [{'id': f'n{i}', 'revision': 1, 'vector': [0.01 * i, 0.],
                     'metadata': {'area': 'X'}} for i in range(10)]
            mid = [{'id': f'f{i}', 'revision': 1, 'vector': [5. + 0.1 * i, 5.],
                    'metadata': {'area': 'Y'}} for i in range(2)]
            far = [{'id': f'z{i}', 'revision': 1, 'vector': [20. + 0.1 * i, 20.],
                    'metadata': {'area': 'X'}} for i in range(6)]
            rows = near + mid + far
            token = store.write(rows)
            frozen = snapshot([token], live_of(rows))
            index_token = build(store, [token], 'l2_squared', num_cells=3, seed=1)
            fixed = approx(store, index_token, frozen, [0., 0.], 2,
                           filters={'area': 'Y'}, nprobe=1)
            self.assertEqual(fixed['stats']['stop_reason'], 'fixed_nprobe')
            self.assertLess(len(fixed['results']), 2)
            expanded = approx(store, index_token, frozen, [0., 0.], 2,
                              filters={'area': 'Y'}, nprobe=1, expand=True)
            self.assertEqual(expanded['stats']['stop_reason'], 'count_reached')
            self.assertGreater(expanded['stats']['cells_probed'], 1)
            self.assertEqual([row['id'] for row in expanded['results']], ['f0', 'f1'])
            self.assertEqual(expanded['results'], exact(store, frozen, [0., 0.], 2, filters={'area': 'Y'}))

    def test_exhaustive_and_certified_match_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Segments(tmp, 3)
            rows = make_rows('p', 40, 3, seed=5)
            token = store.write(rows)
            frozen = snapshot([token], live_of(rows))
            index_token = build(store, [token], 'l2_squared', num_cells=5, seed=6)
            query = [0.3, 0.4, 0.5]
            want = exact(store, frozen, query, 6)
            exhaustive = approx(store, index_token, frozen, query, 6, nprobe=5)
            self.assertTrue(exhaustive['stats']['exhausted'])
            self.assertTrue(exhaustive['stats']['certified'])
            self.assertEqual(exhaustive['results'], want)
            certified = approx(store, index_token, frozen, query, 6,
                               nprobe=1, expand=True, require_certified=True)
            self.assertTrue(certified['stats']['certified'])
            self.assertEqual(certified['results'], want)
            dot_index = build(store, [token], 'negative_dot', num_cells=5, seed=6)
            dot = approx(store, dot_index, frozen, query, 6,
                         nprobe=1, expand=True, require_certified=True)
            self.assertTrue(dot['stats']['exhausted'])
            self.assertEqual(dot['results'], exact(store, frozen, query, 6, metric='negative_dot'))

    def test_merge_keeps_old_indexes_and_rejects_mixed_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Segments(tmp, 2)
            rows_a = make_rows('a', 12, 2, seed=7, area='A')
            rows_b = make_rows('b', 12, 2, seed=8, area='B')
            token_a = store.write(rows_a)
            token_b = store.write(rows_b)
            index_a = build(store, [token_a], 'l2_squared', num_cells=2, seed=3)
            index_b = build(store, [token_b], 'l2_squared', num_cells=2, seed=5)
            merged = merge(store, [index_a, index_b])
            both = snapshot([token_a, token_b], live_of(rows_a + rows_b))
            self.assertEqual(approx(store, merged, both, [0.5, 0.5], 4, nprobe=99)['results'],
                             exact(store, both, [0.5, 0.5], 4))
            only_a = snapshot([token_a], live_of(rows_a))
            self.assertEqual(approx(store, index_a, only_a, [0.5, 0.5], 4, nprobe=99)['results'],
                             exact(store, only_a, [0.5, 0.5], 4))
            with self.assertRaises(ValueError):
                approx(store, merged, only_a, [0.5, 0.5], 4)
            dot_index = build(store, [token_a], 'negative_dot', num_cells=2, seed=3)
            with self.assertRaises(ValueError):
                merge(store, [index_a, dot_index])

    def test_merge_dedups_versions_and_rejects_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Segments(tmp, 1)
            row = {'id': 'a', 'revision': 1, 'vector': [1.], 'metadata': {'area': 'A'}}
            first = store.write([row])
            second = store.write([dict(row)])
            merged = merge(store, [build(store, [first], 'l2_squared', 1),
                                   build(store, [second], 'l2_squared', 1)])
            body = load(store, merged)
            self.assertEqual(sum(len(cell) for cell in body['postings']), 1)
            conflict = store.write([{'id': 'a', 'revision': 1, 'vector': [9.], 'metadata': {'area': 'A'}}])
            with self.assertRaises(ValueError):
                build(store, [first, conflict], 'l2_squared', 1)

    def test_tie_handling_matches_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Segments(tmp, 1)
            rows = [{'id': 'b', 'revision': 1, 'vector': [1.], 'metadata': {}},
                    {'id': 'a', 'revision': 1, 'vector': [-1.], 'metadata': {}}]
            token = store.write(rows)
            frozen = snapshot([token], live_of(rows))
            index_token = build(store, [token], 'l2_squared', num_cells=1, seed=1)
            got = approx(store, index_token, frozen, [0.], 2)
            self.assertEqual([row['id'] for row in got['results']], ['a', 'b'])
            self.assertEqual(got['results'], exact(store, frozen, [0.], 2))
            self.assertEqual([row['id'] for row in approx(store, index_token, frozen, [0.], 1)['results']], ['a'])

    def test_metric_and_dimension_not_mixable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Segments(tmp, 2)
            rows = make_rows('p', 8, 2, seed=9)
            token = store.write(rows)
            frozen = snapshot([token], live_of(rows))
            index_token = build(store, [token], 'l2_squared', num_cells=2, seed=1)
            with self.assertRaises(ValueError):
                approx(store, index_token, frozen, [0., 0.], 2, metric='negative_dot')
            with self.assertRaises(ValueError):
                load(Segments(tmp, 3), index_token)

    def test_overflow_reported_without_nan(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Segments(tmp, 2)
            rows = [{'id': 'finite', 'revision': 1, 'vector': [1e308, 1e308], 'metadata': {}},
                    {'id': 'overflow', 'revision': 1, 'vector': [1e308, -1e308], 'metadata': {}}]
            token = store.write(rows)
            frozen = snapshot([token], live_of(rows))
            result = exact(store, frozen, [1e308, 1e308], 2)
            self.assertEqual([row['id'] for row in result], ['finite', 'overflow'])
            self.assertEqual(result[1]['distance'], float('inf'))
            with self.assertRaises(ValueError):
                exact(store, frozen, [1e308, 1e308], 2, metric='negative_dot')

    def test_argument_validation_and_empty_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Segments(tmp, 2)
            rows = make_rows('p', 6, 2, seed=10)
            token = store.write(rows)
            frozen = snapshot([token], live_of(rows))
            index_token = build(store, [token], 'l2_squared', num_cells=2, seed=1)
            with self.assertRaises(ValueError):
                approx(store, index_token, frozen, [0., 0.], -1)
            with self.assertRaises(ValueError):
                approx(store, index_token, frozen, [0., 0.], 1, nprobe=0)
            with self.assertRaises(ValueError):
                approx(store, index_token, frozen, [0.], 1)
            clamped = approx(store, index_token, frozen, [0., 0.], 2, nprobe=99)
            self.assertEqual(clamped['stats']['cells_probed'], 2)
            self.assertTrue(clamped['stats']['exhausted'])
            empty = store.write([])
            empty_index = build(store, [empty], 'l2_squared', num_cells=2, seed=1)
            result = approx(store, empty_index, snapshot([empty], {}), [0., 0.], 3)
            self.assertEqual(result['results'], [])
            self.assertTrue(result['stats']['exhausted'])
            self.assertTrue(result['stats']['certified'])

if __name__ == '__main__':
    unittest.main()
