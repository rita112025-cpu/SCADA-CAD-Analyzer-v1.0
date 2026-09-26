"""Conservative comparison names; source spelling is always retained."""
import re
import unicodedata


def normalize_name(value):
    raw = '' if value is None else str(value)
    name = unicodedata.normalize('NFKC', raw).strip().upper()
    name = re.sub(r'[\s_-]+', '', name)
    return dict(raw_name=raw, normalized_name=name)
