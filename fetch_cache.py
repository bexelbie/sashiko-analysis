# ABOUTME: Fetches and caches patchset index and review data from the sashiko.dev API.
# ABOUTME: Writes to a cache directory to avoid repeated API calls during analysis.

import json
import os
import sys
import time
import urllib.request
import urllib.error

API_BASE = "https://sashiko.dev/api"
DEFAULT_CACHE_DIR = "/tmp/sashiko_cache"
DEFAULT_MAILING_LIST = "org.kvack.linux-mm"


def fetch_json(url):
    """Fetch JSON from a URL with a short delay to be polite."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def fetch_patchsets(mailing_list, cache_dir):
    """Fetch all patchsets for a mailing list, paginating through results."""
    all_items = []
    page = 1
    per_page = 50
    total = None

    while True:
        url = f"{API_BASE}/patchsets?per_page={per_page}&page={page}&mailing_list={mailing_list}"
        print(f"Fetching patchsets page {page}...", end=" ", flush=True)
        data = fetch_json(url)
        items = data.get("items", [])
        total = data.get("total", 0)
        all_items.extend(items)
        print(f"got {len(items)} (total so far: {len(all_items)} of {total})")

        if len(all_items) >= total or not items:
            break
        page += 1
        time.sleep(0.5)

    result = {
        "items": all_items,
        "total": total,
        "mailing_list": mailing_list,
        "fetched_at": time.strftime("%Y-%m-%d"),
    }
    path = os.path.join(cache_dir, "patchsets.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Saved {len(all_items)} patchsets to {path}")
    return all_items


def fetch_reviews(patchsets, cache_dir):
    """Fetch individual reviews for each patchset, skipping already-cached ones."""
    fetched = 0
    skipped = 0
    errors = 0

    for ps in patchsets:
        ps_id = ps["id"]
        path = os.path.join(cache_dir, f"review_{ps_id}.json")
        if os.path.exists(path):
            skipped += 1
            continue

        url = f"{API_BASE}/review?patchset_id={ps_id}"
        try:
            data = fetch_json(url)
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            fetched += 1
            if fetched % 20 == 0:
                print(f"  Fetched {fetched} reviews...")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                errors += 1
            else:
                print(f"  Error fetching review for patchset {ps_id}: {e}")
                errors += 1
        time.sleep(0.3)

    print(f"Reviews: {fetched} fetched, {skipped} cached, {errors} errors")


def main():
    cache_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CACHE_DIR
    mailing_list = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MAILING_LIST

    os.makedirs(cache_dir, exist_ok=True)
    print(f"Cache directory: {cache_dir}")
    print(f"Mailing list: {mailing_list}")

    patchsets_path = os.path.join(cache_dir, "patchsets.json")
    if os.path.exists(patchsets_path):
        print(f"Loading cached patchset index from {patchsets_path}")
        with open(patchsets_path) as f:
            patchsets = json.load(f)["items"]
    else:
        patchsets = fetch_patchsets(mailing_list, cache_dir)

    print(f"\nFetching reviews for {len(patchsets)} patchsets...")
    fetch_reviews(patchsets, cache_dir)
    print("Done.")


if __name__ == "__main__":
    main()
