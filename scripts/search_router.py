"""Search router (genesis Part VIII): API → direct → DDG (ddgs + stdlib scraper) → Brave."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


SEARCH_FAIL_THRESHOLD = 2


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    source: str

    def as_dict(self): return self.__dict__


@dataclass
class SearchResult:
    query: str
    hits: list
    strategy_used: str
    verdict: str
    diagnostic: dict = field(default_factory=dict)

    def as_dict(self):
        return {"query": self.query, "hits": [h.as_dict() for h in self.hits],
                "strategy_used": self.strategy_used, "verdict": self.verdict,
                "diagnostic": self.diagnostic}


@dataclass
class SearchRouter:
    project_root: Path
    keys: dict = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    @classmethod
    def open(cls, project_root, keys=None):
        return cls(project_root=project_root, keys=keys or {})

    @property
    def discovered_apis_path(self): return self.project_root / "config" / "discovered_apis.json"
    @property
    def learnings_path(self): return self.project_root / "config" / "search_strategy_learnings.json"
    @property
    def institution_registry_path(self): return self.project_root / "config" / "institution_registry.json"

    def _load_json(self, path, default):
        if not path.exists(): return default
        try: return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError: return default

    def _save_json(self, path, data):
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)

    def discovered_apis(self): return self._load_json(self.discovered_apis_path, {"apis": []}).get("apis", [])
    def approved_apis(self): return [a for a in self.discovered_apis() if a.get("status") == "APPROVED"]

    def add_discovered_api(self, entry):
        with self._lock:
            data = self._load_json(self.discovered_apis_path, {"apis": []})
            entry = dict(entry); entry.setdefault("discovered_at", _now())
            entry.setdefault("status", "PENDING")
            entry.setdefault("id", f"API-{len(data.get('apis', [])) + 1:04d}")
            data.setdefault("apis", []).append(entry)
            self._save_json(self.discovered_apis_path, data); return entry

    def institution_registry(self):
        return self._load_json(self.institution_registry_path, {"institutions": {}})

    def record_learning(self, claim_type, strategy, outcome, query):
        with self._lock:
            data = self._load_json(self.learnings_path, {"strategies": {}})
            ct = data.setdefault("strategies", {}).setdefault(claim_type, {})
            entry = ct.setdefault(strategy, {"success": 0, "fail": 0, "last_query": "", "last_seen": ""})
            if outcome == "FOUND": entry["success"] += 1
            else: entry["fail"] += 1
            entry["last_query"] = query; entry["last_seen"] = _now()
            self._save_json(self.learnings_path, data)

    def preferred_strategy(self, claim_type):
        data = self._load_json(self.learnings_path, {"strategies": {}})
        ct = data.get("strategies", {}).get(claim_type, {})
        if not ct: return None
        ranked = sorted(ct.items(), key=lambda kv: (kv[1].get("success", 0) - kv[1].get("fail", 0)), reverse=True)
        top, stats = ranked[0]
        return top if stats.get("success", 0) > stats.get("fail", 0) else None

    def search(self, query, *, claim_type="unknown", institution=None, query_plan=None):
        diagnostic = {"attempted": []}
        plan_primary = (query_plan or {}).get("primary") or {}
        if plan_primary.get("engine") == "api" and plan_primary.get("url"):
            hits, err = self._fetch_url(plan_primary["url"])
            diagnostic["attempted"].append({"engine": "api", "ok": bool(hits), "error": err})
            if hits:
                self.record_learning(claim_type, "api", "FOUND", query)
                return SearchResult(query=query, hits=hits, strategy_used="api", verdict="FOUND", diagnostic=diagnostic)
        if institution:
            reg = self.institution_registry().get("institutions", {})
            entry = reg.get(institution)
            if entry and entry.get("official_url"):
                hits, err = self._fetch_url(entry["official_url"])
                diagnostic["attempted"].append({"engine": "direct", "ok": bool(hits), "error": err})
                if hits:
                    self.record_learning(claim_type, "direct", "FOUND", query)
                    return SearchResult(query=query, hits=hits, strategy_used="direct", verdict="FOUND", diagnostic=diagnostic)
        ddg_hits, ddg_err = self._ddg_search(query)
        diagnostic["attempted"].append({"engine": "ddg", "count": len(ddg_hits), "error": ddg_err})
        if len(ddg_hits) >= SEARCH_FAIL_THRESHOLD:
            self.record_learning(claim_type, "ddg", "FOUND", query)
            return SearchResult(query=query, hits=ddg_hits, strategy_used="ddg", verdict="FOUND", diagnostic=diagnostic)
        brave_hits, brave_err = self._brave_search(query)
        diagnostic["attempted"].append({"engine": "brave", "count": len(brave_hits), "error": brave_err})
        combined = ddg_hits + brave_hits
        if combined:
            strategy = "brave" if brave_hits else "ddg"
            self.record_learning(claim_type, strategy, "FOUND", query)
            return SearchResult(query=query, hits=combined, strategy_used=strategy, verdict="FOUND", diagnostic=diagnostic)
        self.record_learning(claim_type, "exhausted", "FAIL", query)
        return SearchResult(query=query, hits=[], strategy_used="exhausted", verdict="UNVERIFIABLE", diagnostic=diagnostic)

    def _fetch_url(self, url):
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "Shimmer/0.1 (institutional research)"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read(65536).decode("utf-8", errors="ignore")
                ctype = resp.headers.get("Content-Type", "")
            host = urlparse(url).netloc
            snippet = _strip_html(body)[:400]
            self._detect_api_candidate(url, ctype, body)
            return [SearchHit(title=host, url=url, snippet=snippet, source="direct")], ""
        except Exception as e:
            return [], f"{type(e).__name__}: {e}"

    def _ddg_search(self, query, max_results=5):
        hits, err = self._ddg_package(query, max_results=max_results)
        if hits: return hits, ""
        fb, fb_err = self._ddg_html_scrape(query, max_results=max_results)
        if fb: return fb, ""
        combined_err = "; ".join(e for e in (err, fb_err) if e) or "ddgs+scrape returned 0"
        return [], combined_err

    def _ddg_package(self, query, max_results):
        try:
            from ddgs import DDGS
        except ImportError as e:
            return [], f"ddgs not installed: {e}"
        try:
            with DDGS() as ddg:
                raw = list(ddg.text(query, max_results=max_results))
        except Exception as e:
            return [], f"{type(e).__name__}: {e}"
        return [SearchHit(title=r.get("title", ""), url=r.get("href", "") or r.get("url", ""),
                          snippet=r.get("body", "") or r.get("snippet", ""), source="ddg") for r in raw], ""

    _DDG_HTML_RESULT_RE = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
        r'.*?<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE)

    def _ddg_html_scrape(self, query, max_results):
        try:
            import urllib.parse, urllib.request
            data = urllib.parse.urlencode({"q": query}).encode("utf-8")
            req = urllib.request.Request(
                "https://html.duckduckgo.com/html/", data=data,
                headers={"User-Agent": "Mozilla/5.0 (compatible; Shimmer/0.1)",
                         "Accept": "text/html,application/xhtml+xml",
                         "Content-Type": "application/x-www-form-urlencoded"},
                method="POST")
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            return [], f"{type(e).__name__}: {e}"
        hits = []
        for m in self._DDG_HTML_RESULT_RE.finditer(body):
            if len(hits) >= max_results: break
            raw_url, raw_title, raw_snippet = m.group(1), m.group(2), m.group(3)
            url = _unwrap_ddg_redirect(raw_url)
            title = _strip_html(raw_title); snippet = _strip_html(raw_snippet)
            if not url or not title: continue
            hits.append(SearchHit(title=title, url=url, snippet=snippet, source="ddg"))
        if not hits and "result__a" not in body:
            return [], "scrape: no result__a in body (DDG layout changed?)"
        return hits, ""

    def _brave_search(self, query, max_results=5):
        key = self.keys.get("BRAVE_API_KEY")
        if not key: return [], "no BRAVE_API_KEY configured"
        try:
            import urllib.parse, urllib.request
            qs = urllib.parse.urlencode({"q": query, "count": max_results})
            req = urllib.request.Request(
                f"https://api.search.brave.com/res/v1/web/search?{qs}",
                headers={"X-Subscription-Token": key, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            return [], f"{type(e).__name__}: {e}"
        return [SearchHit(title=r.get("title", ""), url=r.get("url", ""),
                          snippet=r.get("description", ""), source="brave")
                for r in (data.get("web") or {}).get("results", [])], ""

    def _detect_api_candidate(self, url, content_type, body):
        host = urlparse(url).netloc.lower()
        looks_like_api = ("json" in content_type.lower() or "/api/" in url.lower() or "/v1/" in url.lower())
        if not looks_like_api: return
        for a in self.discovered_apis():
            if a.get("host") == host: return
        self.add_discovered_api({
            "host": host, "sample_url": url, "content_type": content_type,
            "rationale": "URL pattern matched /api/ or /v1/ or returned JSON; review for free-tier eligibility.",
            "status": "PENDING",
        })


def _now(): return datetime.now(timezone.utc).isoformat()


def _strip_html(s):
    cleaned = re.sub(r"<[^>]+>", " ", s)
    cleaned = (cleaned.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
               .replace("&gt;", ">").replace("&quot;", '"').replace("&#x27;", "'").replace("&#39;", "'"))
    return re.sub(r"\s+", " ", cleaned).strip()


def _unwrap_ddg_redirect(href):
    if href.startswith("//"): href = "https:" + href
    try: parsed = urlparse(href)
    except ValueError: return href
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query); target = qs.get("uddg", [""])[0]
        if target:
            import urllib.parse
            return urllib.parse.unquote(target)
    return href
