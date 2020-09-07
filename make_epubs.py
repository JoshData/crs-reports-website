#!/usr/bin/python3

# Convert the current version of each report into an epub.

import os
import os.path
import json
import subprocess
import tempfile
import re
import html
import datetime

import tqdm

REPORTS_DIR = "reports"

def make_epub(report_id):
	# Generate output filename.
	out_fn = os.path.join(REPORTS_DIR, "epubs", report_id + ".epub")

	# Get report metadata.
	with open(os.path.join(REPORTS_DIR, "reports", report_id + ".json")) as f:
		report = json.load(f)

	# Get current version HTML file.
	ver = report["versions"][0]
	html_formats = [f for f in ver["formats"] if f["format"] == "HTML"]
	if len(html_formats) == 0: return
	html_fn = os.path.join(REPORTS_DIR, html_formats[0]["filename"])
	if not os.path.exists(html_fn): return # we don't have it for some reason

	# Get thumbnail image from corresponding PDF file.
	thumbnail_fn = None
	pdf_formats = [f for f in ver["formats"] if f["format"] == "PDF"]
	if len(pdf_formats) > 0:
		thumbnail_fn = pdf_formats[0]["filename"].replace(".pdf", ".png")
		if not os.path.exists(os.path.join(REPORTS_DIR, thumbnail_fn)):
			thumbnail_fn = None

	# If the epub exists and matches the current content, then no need to
	# regenerate.
	src = html_fn + "|" + (thumbnail_fn or "")
	if os.path.exists(out_fn + ".src") and open(out_fn + ".src").read() == src:
		return

	# Rewrite image paths in HTML.
	with tempfile.NamedTemporaryFile(mode="wb") as html_f:
		with tempfile.NamedTemporaryFile(mode="w") as metadata_f:
			# Read in HTML.
			with open(html_fn, "rb") as src_html_f:
				document = src_html_f.read()

			# Replace images.
			document = re.sub(b"(?<=src=\")/files/.*?(?=\")", lambda m : os.path.join(REPORTS_DIR.encode("ascii"), m.group(0)[1:]), document)

			# Pandoc complains if the HTML file doesn't have a title. It doesn't matter
			# what it is since we set it explicitly in the epub metadata.
			document = b"<html><head><title>" + html.escape(ver["title"]).encode("utf8") + b"</title></head>\n<body>\n" + document

			# Write to tempfile.
			html_f.write(document)
			html_f.flush()

			# Construct metadata in a hackish way.
			metadata = """
<dc:title type="main">{title} ({number}, {nicedate})</dc:title>
<dc:date>{date}</dc:date>
<dc:creator>Congressional Research Service</dc:creator>
<dc:language>en</dc:language>
<dc:rights>Public Domain</dc:rights> 
<dc:publisher>EveryCRSReport.com</dc:publisher> 
""".format(
				title=html.escape(ver["title"]),
				number=html.escape(report_id),
				date=re.sub("T.*", "", ver["date"]),
				nicedate=datetime.datetime.strptime(ver["date"], "%Y-%m-%d" + ("T%H:%M:%S" if "T" in ver["date"] else "")).strftime("%x"),
			)
			metadata_f.write(metadata)
			metadata_f.flush()

			# Convert.
			args = [
				"pandoc",
				"-f", "html",
				"-t", "epub3",
				"-o", out_fn,
				"--epub-metadata=" + metadata_f.name,
			]
			if thumbnail_fn:
				args.extend([
					"--epub-cover-image=" + os.path.join(REPORTS_DIR, thumbnail_fn),
				])
			args.append(html_f.name)
			subprocess.check_call(args)

	# Record the data used to generate the epub so we know in the future if we
	# should regenerate it.
	with open(out_fn + ".src", "w") as f:
		f.write(src)

if __name__ == "__main__":
	# Ensure output directory exists.
	os.makedirs(os.path.join(REPORTS_DIR, "epubs"), exist_ok=True)

	# Generate epubs.
	for fn in tqdm.tqdm(os.listdir(os.path.join(REPORTS_DIR, "reports")), desc="epubs"):
		if fn.endswith(".json"):
			report_id = fn.replace(".json", "")
			make_epub(report_id)
