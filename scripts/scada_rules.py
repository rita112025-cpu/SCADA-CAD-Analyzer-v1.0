"""The single SCADA keyword search core (used by CLI, pipeline and GUI; nothing else does matching).

Matching rules
  * ASCII keywords match whole tokens only, case-insensitive.  The keyword must start at a boundary
    (anything that is not [A-Za-z0-9]: "_" "-" " " "/" and CJK characters) and may be followed by a
    boundary or digits, but never by a letter:
        RACK      -> "RACK", "rack", "RACK-01", "RACK_01", "RACK01", "RACK1", "設備RACK機櫃"  match
        RACK      -> "TRACK", "TRACK01", "BRACKET", "RACKS"                                 no match
        UPS       -> "UPS1", "UPS01"  match ; "BACKUPS1" no match
        SB12      -> "SB12-01" match ; "SB123" no match (keywords ending in a digit stay strict)
        PANEL     -> "PANELBOARD"                                          no match
  * A keyword containing a space is a phrase: words may be separated by spaces, "_" or "-"
        SCADA PANEL -> "SCADA_PANEL", "scada-panel", "SCADA  Panel"        match
  * Keywords containing non-ASCII characters (Chinese...) use plain substring matching.
Confidence
  * high_confidence : a configured high-confidence phrase (SCADA PANEL, RTU PANEL, ...)
  * normal          : any other configured keyword
  * excluded_noise  : a generic keyword (default PANEL) that sits inside a known building/architecture
                      phrase (System Panel, Curtain Wall Panel, ...). Never written to scada_hits.csv.
  A generic keyword that is already part of a matched high-confidence phrase is not reported twice.
"""
import re
import unicodedata
from collections import OrderedDict

HIGH, NORMAL, EXCLUDED = "high_confidence", "normal", "excluded_noise"
_RANK = {EXCLUDED: 0, NORMAL: 1, HIGH: 2}

DEFAULT_HIGH_PHRASES = ["SCADA PANEL", "CONTROL PANEL", "PLC PANEL", "RTU PANEL", "UPS PANEL",
                        "DDC PANEL", "MCC PANEL"]
DEFAULT_EXCLUDE_PHRASES = ["System Panel", "Curtain Wall Panel", "Curtain Panel",
                           "Architectural Panel", "Glazed Panel"]
DEFAULT_GENERIC = ["PANEL"]

_SEP = r"[\s_\-]+"
_LB = r"(?<![A-Za-z0-9])"
_LA_LETTERS = r"(?![A-Za-z])"          # a numeric suffix is allowed: RACK01, UPS1, RTU01
_LA_STRICT = r"(?![A-Za-z0-9])"        # keywords that end in a digit (SB12) must not run on


def normalize_text(s):
    """NFKC (full-width -> ASCII), collapse whitespace, casefold."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    return re.sub(r"\s+", " ", s).strip().casefold()


# CAD engineering size naming, only for keywords listed in `engineering_suffix_keywords`:
# TRAY300, TRAY-300, TRAY_X600, trayX600, TRAYW300, TRAYH150
_ENG_SUFFIX = r"(?:[_\-]?[xwh]?[0-9]+(?![A-Za-z0-9])|(?![A-Za-z]))"
DEFAULT_ENGINEERING = ["TRAY"]


def compile_keyword(kw, engineering=False):
    """Compiled regex for one keyword (applied to normalize_text() output)."""
    k = normalize_text(kw)
    if not k:
        return None
    if not k.isascii():                       # Chinese etc.: substring
        return re.compile(re.escape(k))
    parts = [re.escape(p) for p in k.split(" ")]
    if engineering and not k[-1].isdigit():
        return re.compile(_LB + _SEP.join(parts) + _ENG_SUFFIX)
    after = _LA_STRICT if k[-1].isdigit() else _LA_LETTERS
    return re.compile(_LB + _SEP.join(parts) + after)


class Rules:
    def __init__(self, keywords, high_phrases=None, exclude_phrases=None, generic=None,
                 engineering=None):
        self.high = _dedupe(DEFAULT_HIGH_PHRASES if high_phrases is None else high_phrases)
        self.exclude = _dedupe(DEFAULT_EXCLUDE_PHRASES if exclude_phrases is None else exclude_phrases)
        self.generic = {normalize_text(g) for g in
                        (DEFAULT_GENERIC if generic is None else generic)}
        self.keywords = _dedupe(list(keywords) + self.high)          # config order, then phrases
        self.engineering = {normalize_text(e) for e in
                            (DEFAULT_ENGINEERING if engineering is None else engineering)}
        self._pat = OrderedDict((k, compile_keyword(k, normalize_text(k) in self.engineering))
                                for k in self.keywords)
        self._high_norm = {normalize_text(h) for h in self.high}
        self._exc_pat = [compile_keyword(e) for e in self.exclude]
        self._high_pat = [compile_keyword(h) for h in self.high]


def _dedupe(seq):
    seen, out = set(), []
    for x in seq:
        n = normalize_text(x)
        if n and n not in seen:
            seen.add(n)
            out.append(str(x).strip())
    return out


def build_rules(cfg):
    return Rules(cfg.get("keywords", []), cfg.get("high_confidence_phrases"),
                 cfg.get("exclude_phrases"), cfg.get("generic_keywords"),
                 cfg.get("engineering_suffix_keywords"))


def match_keyword(text, keyword, engineering=False):
    """Spans (start, end) of every whole-token match of `keyword` in `text`.
    engineering=True additionally allows a CAD size suffix (TRAYX600, TRAY-300)."""
    pat = compile_keyword(keyword, engineering)
    if pat is None:
        return []
    return [m.span() for m in pat.finditer(normalize_text(text))]


def _spans(pats, norm):
    out = []
    for p in pats:
        if p is not None:
            out += [m.span() for m in p.finditer(norm)]
    return out


def _inside(span, outer):
    return any(o[0] <= span[0] and span[1] <= o[1] for o in outer)


def classify_match(keyword, span, rules, high_spans, exclude_spans):
    """Return confidence for one keyword match, or None if it is redundant (covered by a
    high-confidence phrase)."""
    if normalize_text(keyword) in rules._high_norm:
        return HIGH
    if normalize_text(keyword) in rules.generic:
        if _inside(span, high_spans):
            return None
        if _inside(span, exclude_spans):
            return EXCLUDED
    return NORMAL


def find_matches(text, rules):
    """All keyword matches in `text` -> list of dict(keyword, span, confidence), in keyword order."""
    norm = normalize_text(text)
    if not norm:
        return []
    high_spans = _spans(rules._high_pat, norm)
    exc_spans = _spans(rules._exc_pat, norm)
    out = []
    for kw, pat in rules._pat.items():
        if pat is None:
            continue
        seen = set()       # one row per (keyword, confidence) per text, even if it occurs twice
        for m in pat.finditer(norm):
            conf = classify_match(kw, m.span(), rules, high_spans, exc_spans)
            if conf is not None and conf not in seen:
                seen.add(conf)
                out.append(dict(keyword=kw, span=m.span(), confidence=conf))
    return out


def is_scada_related(text_values, rules):
    """True if any of the strings has at least one non-excluded keyword match."""
    return any(m["confidence"] != EXCLUDED for t in text_values for m in find_matches(t, rules))


# hit_source = which kind of CAD element produced the hit (TEXT / MTEXT / ATTRIB / BLOCK_NAME / LAYER_NAME).
# It is appended, never renamed: in the multi-format output source_type stays the source category ("CAD").
HIT_SOURCES = ("TEXT", "MTEXT", "ATTRIB", "BLOCK_NAME", "LAYER_NAME")
HIT_FIELDS = ["file", "keyword", "source_type", "layer", "block", "text", "x", "y", "z", "handle",
              "confidence", "hit_source"]
OBJECT_FIELDS = ["file", "source_type", "handle", "layer", "block", "text", "x", "y", "z",
                 "matched_keywords", "match_count", "confidence", "hit_source"]
BLOCK_SUMMARY_FIELDS = ["file", "block_name", "layer", "count", "first_x", "first_y", "first_z",
                        "scada_related", "scada_related_by"]


def object_key(row):
    """Stable identity of an entity: handle if present, otherwise a positional fallback.
    Uses hit_source (not source_type, which the multi-format writer overwrites with the category)."""
    kind = row.get("hit_source") or row["source_type"]
    if row.get("handle"):
        return (row["file"], kind, row["handle"])
    return (row["file"], kind, row["layer"], row["x"], row["y"], row["z"],
            row["text"] if kind != "BLOCK_NAME" else row["block"])


def build_object_hits(hit_rows):
    """One row per entity, keywords merged: 'SCADA|TRAY'. confidence = highest of its hits."""
    objs = OrderedDict()
    for r in hit_rows:
        k = object_key(r)
        o = objs.get(k)
        if o is None:
            o = objs[k] = dict(file=r["file"], source_type=r["source_type"], handle=r["handle"],
                               layer=r["layer"], block=r["block"], text=r["text"], x=r["x"],
                               y=r["y"], z=r["z"], kws=[], confidence=r["confidence"],
                               hit_source=r.get("hit_source", r["source_type"]))
        if r["keyword"] not in o["kws"]:
            o["kws"].append(r["keyword"])
        if _RANK[r["confidence"]] > _RANK[o["confidence"]]:
            o["confidence"] = r["confidence"]
    rows = []
    for o in objs.values():
        kws = o.pop("kws")
        rows.append(dict(o, matched_keywords="|".join(kws), match_count=len(kws)))
    return rows


def build_block_summary(blocks, rules, attribs=None):
    """blocks: rows of blocks.csv (file, layer, block_name, handle, x, y, z ...).
    attribs: optional rows of attribs.csv; their text counts as the 'text' evidence of the parent block.
    scada_related_by lists what actually matched: block_name | layer | text (empty when false).
    Sorted by file, count desc, block_name."""
    att = {}
    for a in attribs or []:
        att.setdefault((a["file"], a.get("parent_handle", "")), []).append(a["text"])
    groups = OrderedDict()
    for b in blocks:
        k = (b["file"], b["block_name"], b["layer"])
        g = groups.get(k)
        if g is None:
            g = groups[k] = dict(file=b["file"], block_name=b["block_name"], layer=b["layer"],
                                 count=0, first_x=b["x"], first_y=b["y"], first_z=b["z"], _texts=[])
        g["count"] += 1
        g["_texts"] += att.get((b["file"], b.get("handle", "")), [])
    rows = []
    for g in groups.values():
        by = [name for name, vals in (("block_name", [g["block_name"]]), ("layer", [g["layer"]]),
                                      ("text", g.pop("_texts")))
              if is_scada_related(vals, rules)]
        g["scada_related"] = "true" if by else "false"
        g["scada_related_by"] = "|".join(by)
        rows.append(g)
    rows.sort(key=lambda r: (r["file"], -r["count"], r["block_name"]))
    return rows
