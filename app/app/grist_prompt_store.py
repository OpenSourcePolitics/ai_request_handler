import os
import time
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from grist_api import GristDocAPI

_LOG = logging.getLogger(__name__)

@dataclass
class PromptBundle:
    prompt: str
    config: Dict[str, Any]

def _short(val, n=300):
    try:
        s = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False, default=str)
    except Exception:
        s = repr(val)
    s = "None" if s is None else str(s)
    return s if len(s) <= n else s[:n] + f"... <+{len(s)-n} chars>"

def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Coerce a Grist row (dict or object) into a plain dict with lowercase keys."""
    if isinstance(row, dict):
        return {str(k).lower(): v for k, v in row.items()}
    out: Dict[str, Any] = {}
    for attr in dir(row):
        if attr.startswith("_"):
            continue
        try:
            val = getattr(row, attr)
        except Exception:
            continue
        if callable(val):
            continue
        out[attr.lower()] = val
    # Fallback representation (helps debugging)
    if not out:
        out["_repr"] = repr(row)
    return out

class GristPromptStore:
    """
    Fetches prompt + config from a Grist document table.
    Designed for the "Prompt_Database" user table you defined in Grist.
    """

    def __init__(
        self,
        doc_id: Optional[str] = None,
        api_key: Optional[str] = None,
        server: Optional[str] = None,
        table_name: str = "Prompt_Database",
        cache_ttl: int = 300,
    ) -> None:
        self.doc_id = doc_id or os.getenv("GRIST_DOC_ID")
        self.api_key = api_key or os.getenv("GRIST_API_KEY")
        self.server = server or os.getenv("GRIST_SERVER")
        self.table = table_name
        self.cache_ttl = cache_ttl

        if not (self.doc_id and self.api_key and self.server):
            raise RuntimeError("Missing Grist credentials. Provide GRIST_DOC_ID, GRIST_API_KEY, GRIST_SERVER.")

        self.api = GristDocAPI(self.doc_id, server=self.server, api_key=self.api_key)
        self._last_fetch: float = 0
        self._cache: List[Dict[str, Any]] = []

    def _refresh_cache(self) -> None:
        now = time.time()
        if self._cache and now - self._last_fetch <= self.cache_ttl:
            return
        rows = self.api.fetch_table(self.table)
        # Normalize to dicts with lowercase keys
        self._cache = [_row_to_dict(r) for r in (rows or [])]
        self._last_fetch = now
        # Light debug about columns present
        if self._cache:
            sample_keys = sorted(list(self._cache[0].keys()))[:20]
            _LOG.debug("Loaded %d rows. Sample keys=%s", len(self._cache), sample_keys)
        else:
            _LOG.warning("Grist table '%s' is empty.", self.table)

    def _num(self, x, default=None):
        try:
            return None if x is None else float(x)
        except Exception:
            return default

    def get_by_spam_type(self, spam_type: str) -> PromptBundle:
        """
        Returns the prompt + config for a given spam_type (e.g. "comment", "proposal", "user"...).
        """
        self._refresh_cache()
        want = (spam_type or "").lower()

        try:
            distinct_types = sorted({str((r.get("spam_type") or "")).lower() for r in self._cache})
            _LOG.debug("Available spam_type values in Grist: %s", distinct_types)
        except Exception as e:
            _LOG.debug("Could not compute distinct spam_type values: %s", e)

        candidates = [r for r in self._cache if str(r.get("spam_type") or "").lower() == want]
        _LOG.debug("Matched %d rows for spam_type=%r", len(candidates), want)

        if not candidates:
            # show a couple sample rows to help diagnose schema/field name issues
            _LOG.error(
                "No prompt found in Grist for spam_type=%r in table=%s (doc=%s). Sample rows: %s",
                spam_type, self.table, self.doc_id, _short(self._cache[:3], 800)
            )
            raise LookupError(f"No prompt found in Grist for spam_type='{spam_type}'")

        # Prefer rows with non-empty prompt
        candidates.sort(key=lambda r: 0 if (str(r.get("prompt") or "").strip()) else 1)
        row = candidates[0]

        prompt_text = (row.get("prompt") or "").strip()
        if not prompt_text:
            _LOG.error("Row selected has empty 'prompt'. Row: %s", _short(row, 800))
            raise ValueError(f"Row for spam_type='{spam_type}' has empty prompt")

        model = (row.get("model") or "").strip()
        cfg = {
            "model":            model,
            "max_tokens":       int(self._num(row.get("max_tokens"), 0) or 0),
            "temperature":      self._num(row.get("temperature"), 0.0) or 0.0,
            "top_p":            self._num(row.get("top_p"), 1.0) or 1.0,
            "presence_penalty": self._num(row.get("presence_penalty"), 0.0) or 0.0,
            "model_input_cost_per_million": self._num(row.get("model_input_cost_per_million"), 0.0) or 0.0,
            "model_output_cost_per_million": self._num(row.get("model_output_cost_per_million"), 0.0) or 0.0,

        }

        if not cfg["model"]:
            _LOG.error("Row selected has empty 'model'. Row: %s", _short(row, 800))
            raise ValueError(f"Row for spam_type='{spam_type}' has empty 'model'")

        return PromptBundle(prompt=prompt_text, config=cfg)


    def get_for_content_type(self, content_type_enum) -> PromptBundle:
        """
        Helper that maps directly from your ContentType enum (value = spam_type in Grist).
        """
        return self.get_by_spam_type(content_type_enum.value)
