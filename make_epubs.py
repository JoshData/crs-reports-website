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
import base64

import tqdm
import fitz

REPORTS_DIR = "reports"

def generate_html(doc: fitz.Document, title: str) -> str:
	"""This is the heart of the conversion. It works as follows:

	1. Extracting "blocks" information from the PDF using pymupdf
	2. Converting each block into appropriate html elements using inferences about font and size

	Args:
		doc: a PyMuPDF document
		title: the document title

	Returns:
		An HTML string
	"""

	def span_css(span):
		"""A helper function to make font flags human readable and to create styled spans."""

		# font: font-style, font-variant, font-weight, font-size, font-family
		flags = span["flags"]
		css = []
		font = span["font"]
		if flags & 2**1:
			css.append("italic")
		if flags & 2**4:
			css.append("bold")
		if flags & 2**0:
			css.append("super")

		css.append(f"{1.6 * span['size']}px")

		if flags & 2**3:
			css.append(f"{font}, monospace")
		elif flags & 2**2:
			css.append(f"{font}, serif")
		else:
			css.append(f"{font}, sans-serif")
		return "font: " + " ".join(css)

	def create_text(spans):
		res = []
		for span_set in spans:
			for span in span_set:
				style = span_css(span)
				text = span["text"]
				if "...." in text:
					res.append(f"<p style='{style}'>{text}</p>")
				elif text.strip() == "\uf0b7":
					res.append(f"<span style='{style}'>• </span>")
				elif text.strip() != "":
					res.append(f"<span style='{style}'>{text}</span>")
		return "".join(res)


	# Generate the "front matter" of the html
	elements = [
		f"<!DOCTYPE html><html><head><title>{title}</title><body>"
	]
	footnotes = ["<h2>Footnotes</h2>"]

	# Iterate through the pages
	for page in doc:
		blocks = page.get_text("dict")
		for b_idx, block in enumerate(blocks["blocks"]):

			if block["type"] == 1:
				# If we're here, that means we've got an image block!
				# Let's base encode this and append it to the block_html
				data = base64.b64encode(block["image"]).decode('utf-8')
				data = f"<img src='data:image/{block['ext']};base64,{data}'/>"
				elements.append(data)

			else:


				lines = block["lines"]
				spans = [line["spans"] for line in lines]

				# We are being greedy here... to check to see what we're inserting.
				block_font = [line[0]["font"] for line in [lines["spans"] for lines in block["lines"]]][0]
				block_color = [line[0]["color"] for line in [lines["spans"] for lines in block["lines"]]][0]
				block_size = [line[0]["size"] for line in [
						lines["spans"] for lines in block["lines"]
					] if line[0]["text"].strip() != ""]

				block_text = create_text(spans)
				if block_text == "":
					continue
				if block_font == "Verdana-Italic":	# CRS headers/footers/page numbers/etc
					continue
				elif block_font == "ArialMT":	# CRS headers/footers/page numbers/etc
					continue
				elif block_size != [] and block_size[0] > 18:	# An h1 header
					elements.append(f"<h1>{block_text}</h1>")
				elif block_size != [] and block_size[0]> 14:	# An h2 header
					elements.append(f"<h2>{block_text}</h2>")
				elif block_size != [] and block_font == "GillSansMT-Bold" and block_color == 3369617:
					heading_span = spans.pop(0)
					elements.append(f"<h2>{create_text([heading_span])}</h2><div>{create_text(spans)}</div>")
				elif block_size != [] and block_size[0] <= 9.0 and block_font == "TimesNewRomanPSMT":	# Footnotes
					footnotes.append(f"<aside class='footnote' epub:type='footnote'>{block_text}</aside>")
				else:
					elements.append(f"<div>{block_text}</div>")

	# Put the footnotes at the end and a disclaimer and generate the html
	if len(footnotes) > 1:
		elements.append("".join(footnotes))
	elements.append("<h1>EveryCRSReport Disclaimer</h1><p>This document was generated for and is published on <a href='https://www.everycrsreport.com/'>EveryCRSReport.com</a>. It required custom software to convert it from a PDF into a readable ePUB. Think this is silly? <a href='https://medium.com/demand-progress/why-i-came-to-believe-crs-reports-should-be-publicly-available-and-built-a-website-to-make-it-77b4b0f6233e#.enxkr4ia9'>So do we!</a>")
	elements.append("</body></html>")
	return "".join(elements)

def make_epub(report_id):
	# Generate output filename.
	out_fn = os.path.join(REPORTS_DIR, "epubs", report_id + ".epub")

	# Get report metadata.
	with open(os.path.join(REPORTS_DIR, "reports", report_id + ".json")) as f:
		report = json.load(f)

	# Get current version.
	ver = report["versions"][0]

	# Get current version HTML file and use it if not "generated"
	html_formats = [f for f in ver["formats"] if f["format"] == "HTML"]
	pdf_fn = None
	if len(html_formats) != 0 and html_formats[0].get("source"):
		html_fn = os.path.join(REPORTS_DIR, html_formats[0]["filename"])
		if not os.path.exists(html_fn): return # we don't have it for some reason
	else:
	# Get current version PDF file
		pdf_formats = [f for f in ver["formats"] if f["format"] == "PDF"]
		if len(pdf_formats) == 0: return
		pdf_fn = os.path.join(REPORTS_DIR, pdf_formats[0]["filename"])
		if not os.path.exists(pdf_fn): return # we don't have it for some reason
	report_fn = pdf_fn or html_fn

	# Get thumbnail image from corresponding PDF file.
	thumbnail_fn = None
	pdf_formats = [f for f in ver["formats"] if f["format"] == "PDF"]
	if len(pdf_formats) > 0:
		thumbnail_fn = pdf_formats[0]["filename"].replace(".pdf", ".png")
		if not os.path.exists(os.path.join(REPORTS_DIR, thumbnail_fn)):
			thumbnail_fn = None

	# If the epub exists and matches the current content, then no need to
	# regenerate.
	src = report_fn + "|" + (thumbnail_fn or "")
	if os.path.exists(out_fn + ".src") and open(out_fn + ".src").read() == src:
		return

	# Rewrite image paths in HTML.
	with tempfile.NamedTemporaryFile(mode="wb") as pdf_f:
		with tempfile.NamedTemporaryFile(mode="w") as metadata_f:
			# Generate HTML
			if pdf_fn:
				document = bytes(generate_html(fitz.open(pdf_fn), ver["title"]), 'utf-8')
			else:
				with open(html_fn, "rb") as src_html_f:
					document = src_html_f.read()

					# Replace images.
					document = re.sub(b"(?<=src=\")/files/.*?(?=\")", lambda m : os.path.join(REPORTS_DIR.encode("ascii"), m.group(0)[1:]), document)

					# Pandoc complains if the HTML file doesn't have a title. It doesn't matter
					# what it is since we set it explicitly in the epub metadata.
					document = b"<html><head><title>" + html.escape(ver["title"]).encode("utf8") + b"</title></head>\n<body>\n" + document

			# Write HTML to temporary file
			pdf_f.write(document)
			pdf_f.flush()

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
				"--css", "epub.css",
			]
			if thumbnail_fn:
				args.extend([
					"--epub-cover-image=" + os.path.join(REPORTS_DIR, thumbnail_fn),
				])
			args.append(pdf_f.name)
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
