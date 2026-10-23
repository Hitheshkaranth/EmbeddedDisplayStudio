"""Durable image brief and validation evidence shared by Studio stages."""
import base64
import hashlib
import json
from pathlib import Path


def save_design_context(root, brief, images):
    folder = Path(root) / '.studio' / 'design'
    folder.mkdir(parents=True, exist_ok=True)
    references = []
    for image in images or []:
        raw = base64.b64decode(image.data, validate=True)
        name = hashlib.sha256(raw).hexdigest() + ('.png' if image.mime == 'image/png' else '.jpg')
        (folder / name).write_bytes(raw)
        references.append({'file': name, 'name': image.name, 'mime': image.mime})
    (folder / 'brief.json').write_text(json.dumps({'brief': brief, 'references': references},
                                                indent=2, ensure_ascii=False), encoding='utf-8')
