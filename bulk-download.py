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

api_base_url = "http://54.183.143.173:8000/"

def hash_file(fn):
	# Computes the SHA1 hash of a file's contents.
	with open(fn, 'rb') as f:
	    hasher = hashlib.sha1()
	    hasher.update(f.read())
	    return hasher.hexdigest()

# Ensure output directories exist.
os.makedirs("reports/documents", exist_ok=True)
os.makedirs("reports/files", exist_ok=True)

# Execute an HTTP request to get the CSV listing file.
with urllib.request.urlopen(api_base_url + "reports.csv") as resp:
	# Parse it as a CSV file.
	reader = csv.DictReader(io.StringIO(resp.read().decode("utf8")))

# Fetch reports.
for report in reader:
	# Where will we save this report?
	metadata_fn = "reports/" + report["url"] # i.e. reports/reports/R1234.json

	# Do we have it already and is it up to date?
	if not os.path.exists(metadata_fn) or report["sha1"] != hash_file(metadata_fn):
		# Download and save the file.
		print(metadata_fn + "...")
		with open(metadata_fn, 'wb') as f:
			with urllib.request.urlopen(api_base_url + report["url"]) as resp:
				f.write(resp.read())

	# Also download the PDF/HTML files for the report.
	with open(metadata_fn) as f:
		metadata = json.load(f)

		# Each report may have multiple versions published.
		for version in metadata["versions"]:
			# Each report version is published in zero or more file formats.
			for report_file in version["formats"]:
				# Where will we save this file?
				file_fn = "reports/" + report_file["filename"]

				# Do we have it already and is it up to date?
				if not os.path.exists(file_fn) or report_file["sha1"] != hash_file(file_fn):
					# Download and save the file.
					print(file_fn + "...")
					with open(file_fn, 'wb') as f:
						try:
							with urllib.request.urlopen(api_base_url + report_file["filename"]) as resp:
								f.write(resp.read())
						except urllib.error.HTTPError as e:
							print("", e)

