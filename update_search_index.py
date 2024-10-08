#!/usr/bin/env python3

import datetime
import glob
import hashlib
import json
import os.path
import html5lib
import lxml.etree
import pytz
import tqdm

from utils import parse_dt

REPORTS_DIR = "processed-reports"
INDEX_CACHE_FN = "/mnt/volume_nyc1_02/algolia-index-cache.json"


def update_search_index():
    # Load credentials.
    config = { }
    for line in open("secrets/credentials.txt"):
        line = line.strip().split("=", 1) + [""] # ensure at least two items
        config[line[0]] = line[1]

    # Initialize client.
    from algoliasearch.search_client import SearchClient
    client = SearchClient.create(config["ALGOLIA_CLIENT_ID"], config["ALGOLIA_ADMIN_ACCESS_KEY"])
    index = client.init_index(config["ALGOLIA_INDEX_NAME"])
    index.set_settings({
        "searchableAttributes": ["title", "summary", "text"],
        "attributesForFaceting": ["type", "topics", "isUpdated", "lastPubYear"],
        "unretrievableAttributes": ["text"],
        "attributesToHighlight": ["summary"],
    })

    # Remember docs we've already pushed to the index.
    cache = { }
    if os.path.exists(INDEX_CACHE_FN):
        cache = json.load(open(INDEX_CACHE_FN))

    # Scan for reports that need to be updated.
    reports = []
    for reportfn in tqdm.tqdm(glob.glob(REPORTS_DIR + "/reports/*.json"), "checking for stale search index objects"):
        # Did we already do this file? Compute a hash of the report JSON
        # (which includes the document hash) and use it as a cache key.
        cache_key = reportfn.replace(REPORTS_DIR, "reports") # old path
        hasher = hashlib.sha1()
        with open(reportfn, 'rb') as f:
            hasher.update(f.read())
        cache_value = hasher.hexdigest()
        if cache.get(cache_key) == cache_value: continue

        reports.append((reportfn, cache_key, cache_value))

    # Update index.
    for reportfn, cache_key, cache_value in tqdm.tqdm(reports, "updating search index"):
        # Push to index.
        with open(reportfn) as f:
            report = json.load(f)
            update_search_index_for(report, index)

        # Save to cache that we did this file & update cache (using a two-stage save).
        cache[cache_key] = cache_value
        json.dump(cache, open(INDEX_CACHE_FN + ".1", "w"))
        os.rename(INDEX_CACHE_FN + ".1", INDEX_CACHE_FN)

def update_search_index_for(report, index):
    # Find the most recent HTML text, which we'll use for indexing.
    text_fn = None
    text = None
    for version in reversed(report["versions"]):
        for versionformat in version["formats"]:
            if versionformat["format"] == "HTML":
                text_fn = os.path.join("reports", versionformat['filename'])
    if text_fn:
        try:
            with open(text_fn) as f:
                # Parse the page as HTML5. html5lib gives some warnings about malformed
                # content that we don't care about -- hide warnings.
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    dom = html5lib.parse(f.read(), treebuilder="lxml")

                # Convert to plain text.
                text = lxml.etree.tostring(dom, method='text', encoding=str)
        except (FileNotFoundError, ValueError):
            pass # print("Missing/invalid HTML", report["number"], version["date"])

    # There's a quota on the size of the index_data, 10KB minified JSON
    # according to the docs, although we seem to be able to push more
    # than that. Limit the amount of text we send up.
    max_text_length = 13000 - len(report["versions"][0]["title"]) - len(report["topics"])
    summary = (report["versions"][0].get("summary") or "")[0:max_text_length]
    if text:
        text = text[:(max_text_length - len(summary))]

    # Construct index data.
    index_data = {
        "objectID": ("crs:%s" % report["number"]),
        "type": report["type"],
        "reportNumber": report["number"],
        "title": report["versions"][0]["title"],
        "lastPubDate": report["versions"][0]["date"],
        "firstPubDate": report["versions"][-1]["date"],
        "lastPubYear": int(report["versions"][0]["date"][0:4]),
        "firstPubYear": int(report["versions"][-1]["date"][0:4]),
        "date": parse_dt(report["versions"][0]["date"]).strftime("%b. %-d, %Y"),
        "summary": summary,
        "topics": report["topics"],
        "isUpdated": len(report["versions"]) > 1,
        "text": text,
        "url": "https://www.everycrsreport.com/reports/%s.html" % report["number"],
    }

    #print(json.dumps(index_data, indent=2))
    #print()

    index.save_object(index_data)

if __name__ == "__main__":
    update_search_index()
