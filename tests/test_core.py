import tempfile
import unittest
from vectorlake.metrics import validate, distance
from vectorlake.segments import Segments
from vectorlake.snapshots import snapshot, exact

class CoreTests(unittest.TestCase):
    def test_metric_and_input_contract(self):
        self.assertEqual(distance([0., 1.], [2., 1.], 'l2_squared'), 4.)
        with self.assertRaises(ValueError):
            validate([float('nan')], 1)
        with self.assertRaises(ValueError):
            validate([True], 1)

    def test_snapshot_versions_and_filter_before_ranking(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Segments(tmp, 1)
            first = store.write([{'id': 'a', 'revision': 1, 'vector': [0.], 'metadata': {'area': 'A'}}, {'id': 'b', 'revision': 1, 'vector': [2.], 'metadata': {'area': 'B'}}])
            second = store.write([{'id': 'a', 'revision': 2, 'vector': [3.], 'metadata': {'area': 'B'}}])
            frozen = snapshot([first, second], {'a': 2, 'b': 1})
            self.assertEqual([row['id'] for row in exact(store, frozen, [0.], 2, filters={'area': 'B'})], ['b', 'a'])
            self.assertEqual([row['id'] for row in exact(store, snapshot([first], {'a': 1}), [0.], 1)], ['a'])

    def test_duplicate_segment_not_duplicate_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Segments(tmp, 1)
            token = store.write([{'id': 'a', 'revision': 1, 'vector': [1.], 'metadata': {}}])
            self.assertEqual(len(exact(store, snapshot([token, token], {'a': 1}), [0.], 9)), 1)
