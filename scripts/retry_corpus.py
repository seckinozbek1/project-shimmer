"""Retry the missed downloads via DDG search for 'filetype:pdf' alternatives."""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from download_corpus import CORPUS, _is_pdf
from search_router import SearchRouter


def _try_url(url, out_path, timeout=60):
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Shimmer/0.1)",
            "Accept": "application/pdf,*/*",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            blob = resp.read()
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:80]}"
    if not blob:
        return False, "empty body"
    if _is_pdf(blob, content_type):
        out_path.write_bytes(blob)
        return True, f"OK ({len(blob)} bytes, {content_type})"
    return False, f"not pdf ({content_type})"


def main():
    out_dir = ROOT / "input" / "context"
    out_dir.mkdir(parents=True, exist_ok=True)
    router = SearchRouter.open(ROOT)
    results = []
    missing = [doc for doc in CORPUS if not (out_dir / f"{doc['slug']}.pdf").exists()
               or (out_dir / f"{doc['slug']}.pdf").stat().st_size < 1024]
    print(f"[retry] {len(missing)} missing slugs", file=sys.stderr)
    for i, doc in enumerate(missing, 1):
        slug = doc["slug"]; title = doc["title"]
        out_path = out_dir / f"{slug}.pdf"
        query = f"{title} filetype:pdf"
        try:
            res = router.search(query, claim_type="institutional")
        except Exception as e:
            print(f"[{i:2d}/{len(missing)}] SEARCHERR {slug}: {e}", file=sys.stderr)
            results.append({"slug": slug, "ok": False, "msg": f"search err: {e}"})
            continue
        found = False
        tried = 0
        for hit in res.hits[:8]:
            url = hit.url
            tried += 1
            ok, msg = _try_url(url, out_path)
            if ok:
                print(f"[{i:2d}/{len(missing)}] OK  {slug}: {url[:80]} -> {msg}", file=sys.stderr)
                results.append({"slug": slug, "ok": True, "url": url, "msg": msg})
                found = True
                break
        if not found:
            print(f"[{i:2d}/{len(missing)}] MISS {slug}: no PDF in {len(res.hits)} hits (tried {tried})",
                  file=sys.stderr)
            results.append({"slug": slug, "ok": False, "msg": f"no PDF after {tried} attempts",
                            "hits": [h.url for h in res.hits[:5]]})
        time.sleep(1.0)
    n_ok = sum(1 for r in results if r.get("ok"))
    print(f"\n[retry] {n_ok}/{len(missing)} recovered", file=sys.stderr)
    (out_dir / "_retry_manifest.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
