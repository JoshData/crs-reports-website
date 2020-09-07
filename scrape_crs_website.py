#!/usr/bin/env python3
#
# Scrape reports from https://crsreports.congress.gov.
#
# This site provides many of the same reports that
# are available through our own archive, but only as
# PDFs and only with versions as of the site launch
# date and going forward.

from collections import OrderedDict
import datetime
import hashlib
import json
import os
import re
import subprocess

import scrapelib

BASE_PATH = "incoming/crsreports.congress.gov"

# Create a scraper that automatically throttles our requests
# so that we don't overload the CRS server.
scraper = scrapelib.Scraper(
  requests_per_minute=35,
  retry_attempts=2,
  retry_wait_seconds=10)

ProdTypeDisplayName = {
  "R": "CRS Report",
  "RS": "CRS Report",
  "RL": "CRS Report",
  "IN": "CRS Insight",
  "IF": "CRS In Focus",
}


def scrape_report_listing():
  page_number = 1
  fetched_reports = 0
  total_reports = ""
  last_report_date = ""

  while True:
    # Get the next page of reports...
    url = "https://crsreports.congress.gov/search/results?orderBy=Date&pageNumber={}".format(page_number)
    print("{}... [{}/{}/{}]".format(url, fetched_reports, total_reports, last_report_date))
    body = scraper.get(url).content
    body = json.loads(body.decode("utf8"))

    total_reports = body["TotalRecCount"]
    last_report_date = body["SearchResults"][-1]["CoverDate"].split("T")[0]

    did_fetch = False

    # For each report...
    for report in body["SearchResults"]:
      fetched_reports += 1

      # Skip this --- it doesn't follow the same URL structure for PDFs.
      if report["Title"] == "Appropriations Status Table" \
       or "appropriations" in report["ProductNumber"].lower():
      	continue

      # Get the report versions.
      report_versions = []
      if "PreviousVersions" in report:
        # All of the version (including the current version) are listed
        # in the PreviousVersions field when it is present.
        for prev_version in report["PreviousVersions"].split("|"):
          seq, cover_date, seq_type, seq_code = prev_version.split(";") # "1;13-AUG-20;NEW;Auth"
          seq = int(seq)
          cover_date = datetime.datetime.strptime(cover_date, "%d-%b-%y").date()
          report_versions.append((seq, cover_date))
      else:
        # There is just the current version.
        seq = int(report["CurrentSeqNumber"])
        cover_date = datetime.datetime.strptime(report["CoverDate"], "%Y-%m-%dT%H:%M:%S").date()
        report_versions.append((seq, cover_date))

      # Fetch each report version.
      for seq, cover_date in report_versions:
        did_fetch = did_fetch or fetch_report_version(report, seq, cover_date)

    # If we didn't find anything new on this page, stop here rather than going
    # through all 500+ pages of results.
    if not did_fetch: return

    if fetched_reports == body["TotalRecCount"]:
      return
    page_number += 1

def fetch_report_version(doc, seq, cover_date):
  did_fetch = False

  report_version_id = doc["ProductNumber"] + "_" + str(seq) + "_" + cover_date.isoformat()
  pdf_file = None
  json_fn = BASE_PATH +"/documents/" + report_version_id + ".json"
  if os.path.exists(json_fn):
    # If we've already fetched this report version, there is no need to get
    # the PDF again --- we assume that once published, report versions do not
    # change. We could also skip writting the JSON file, but we may want to
    # update the JSON format.
    with open(json_fn) as f:
      rec = json.load(f)
      assert rec["formats"][0]["format"] == "PDF"
      pdf_file = rec["formats"][0]["filename"]
      pdf_url = rec["formats"][0]["url"]
      pdf_content_hash = rec["formats"][0]["sha1"]

  if not pdf_file or not os.path.exists(BASE_PATH + "/" + rec["formats"][0]["filename"]):
    # Download the PDF.
    pdf_url = "https://crsreports.congress.gov/product/pdf/{}/{}/{}".format(
      doc["ProductTypeCode"], doc["ProductNumber"], str(seq))
    print(pdf_url)
    pdf_content = scraper.get(pdf_url).content
    did_fetch = True
    
    # Get the SHA1 hash of the content, construct a path to save the PDF to,
    # and save it.
    h = hashlib.sha1()
    h.update(pdf_content)
    pdf_content_hash = h.hexdigest()
    pdf_file = "files/" + cover_date.isoformat() + "_" + doc["ProductNumber"] + "_" + pdf_content_hash + ".pdf"
    with open(BASE_PATH + "/" + pdf_file, "wb") as f:
      f.write(pdf_content)

  # Construct metadata record.
  rec = OrderedDict([
    ("source", "CRSReports.Congress.gov"),
    ("sourceLink", "https://crsreports.congress.gov/product/details?prodcode=" + doc["ProductNumber"]),
    ("id", report_version_id),
    ('date', cover_date.isoformat()),
    ('retrieved', datetime.datetime.now().isoformat()),

    ("title", doc["Title"]),
    ("summary", None),

    ("type", ProdTypeDisplayName.get(doc['ProductTypeCode'], "CRS Report Type " + doc['ProductTypeCode'])),
    ("typeId", doc['ProductTypeCode']),
    ("active", doc["StatusFlag"] == "Active"), # "Active" or "Archived", not sure if it's meaningful

    ("formats", [
      OrderedDict([
          ("format", "PDF"),
          ("url", pdf_url),
          ("sha1", pdf_content_hash), # the SHA-1 hash of the file content
          ("filename", pdf_file),
        ]),
      ])
  ])

  # Write out the metadata for this report version.
  with open(json_fn, "w") as f:
    f.write(json.dumps(rec, indent=2))

  return did_fetch

if __name__ == "__main__":
  # Make the directories for the output files.
  os.makedirs(BASE_PATH + "/documents", exist_ok=True)
  os.makedirs(BASE_PATH + "/files", exist_ok=True)
  scrape_report_listing()
