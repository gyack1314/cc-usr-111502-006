import json
import tempfile
from pathlib import Path
from .segments import Segments
from .snapshots import snapshot, exact
body = json.loads(Path('data/sample.json').read_text())
with tempfile.TemporaryDirectory() as tmp:
    store = Segments(tmp, body['dimension'])
    token = store.write(body['rows'])
    frozen = snapshot([token], {row['id']: row['revision'] for row in body['rows']})
    print(json.dumps(exact(store, frozen, body['query'], 2), ensure_ascii=False))
