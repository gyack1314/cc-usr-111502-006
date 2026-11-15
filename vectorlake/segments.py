"""带摘要的不可变向量段。"""
import hashlib
import json
from pathlib import Path
from .metrics import validate

class Segments:
    def __init__(self, root, dimension):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.dimension = dimension
        self.rows_read = 0

    def write(self, rows):
        seen = set()
        for row in rows:
            key = row['id'], row['revision']
            if key in seen:
                raise ValueError('向量行版本重复')
            seen.add(key)
            validate(row['vector'], self.dimension)
        raw = json.dumps({'dimension': self.dimension, 'rows': rows}, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        token = hashlib.sha256(raw).hexdigest()
        (self.root / token).write_bytes(raw)
        return token

    def scan(self, token):
        raw = (self.root / token).read_bytes()
        if hashlib.sha256(raw).hexdigest() != token:
            raise ValueError('向量段摘要不符')
        body = json.loads(raw)
        if body['dimension'] != self.dimension:
            raise ValueError('段维度不兼容')
        for row in body['rows']:
            validate(row['vector'], self.dimension)
            self.rows_read += 1
            yield row
