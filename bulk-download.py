# Sample script to download CRS reports from EveryCRSReport.com.
#
# EveryCRSReport publishes a listing file at
# https://www.everycrsreport.com/reports.csv which has the number,
# last publication date, relative URL to a report metadata JSON
# file, and the SHA1 hash of the metadata file.
#
# We use that file to download new reports into:
#
# reports/reports/xxxxxx.json
# reports/files/yyyyy.pdf
# reports/files/yyyyy.html
#
# This script was written in Python 3.

import hashlib
import urllib.request
import io
import csv
import os, os.path
import json

api_base_url = "https://www.everycrsreport.com/"

def download_file(url, fn, expected_digest):
    # Do we have it already?
    if os.path.exists(fn):
        # Compute the SHA1 hash of the existing file's contents.
        with open(fn, 'rb') as f:
            hasher = hashlib.sha1()
            hasher.update(f.read())
            digest = hasher.hexdigest()

        # Is the existing file up to date?
        if digest == expected_digest or expected_digest is None:
            # No need to download
            return

    # Download and save the file.
    print(fn + "...")
    with open(fn, 'wb') as f:
        try:
            with urllib.request.urlopen(url) as resp:
                f.write(resp.read())
        except urllib.error.HTTPError as e:
            print("", e)

# Ensure output directories exist.
os.makedirs("reports/reports", exist_ok=True)
os.makedirs("reports/files", exist_ok=True)

# Execute an HTTP request to get the CSV listing file.
with urllib.request.urlopen(api_base_url + "reports.csv") as resp:
    # Parse it as a CSV file.
    reader = csv.DictReader(io.StringIO(resp.read().decode("utf8")))

# Fetch reports.
for report in reader:
    # Where will we save this report?
    metadata_fn = "reports/" + report["url"] # i.e. reports/reports/R1234.json

    # Download it if we don't have it or it's modified.
    download_file(api_base_url + report["url"], metadata_fn, report["sha1"])

    # Also download the PDF/HTML files for the report.
    # Parse the metadata JSON file to figure out what the PDF/HTML file names are.
    with open(metadata_fn) as f:
        metadata = json.load(f)

        # Each report may have multiple versions published.
        for version in metadata["versions"]:
            # Each report version is published in zero or more file formats.
            for report_file in version["formats"]:
                # Where will we save this file?
                file_fn = "reports/" + report_file["filename"]

                # Download it if we don't have it or it's modified.
                download_file(api_base_url + report_file["filename"], file_fn, None)
