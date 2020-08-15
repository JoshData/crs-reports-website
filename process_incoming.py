#!/usr/bin/env python3

# This script processes the raw (non-public) CRS files,
# including metadata, PDFs, and HTML, and prepares it
# for publication:
#
# a) The metadata for report versions is scanned and
#    collated to create a single metadata file per
#    report, with multiple entries within it for
#    versions.
#
# b) The HTML files are sanitized and scrubbed of
#    some author information. Image files are copied
#    to the output directory.
#
# c) The PDF files are scrubbed of some author information,
#    our back page is appended to each, and a PNG
#    thumbnail image of the first page is generated.
#
# d) Reports from the University of North Texas archive
#    are extracted and added into the metadata.

import collections
import datetime
import glob
import hashlib
import html
import os
import os.path
import json
import re
import random
import shelve
import subprocess

import tqdm
import bleach
import lxml.etree
import html5lib

INCOMING_DIR = 'incoming'
UNT_ARCHIVE = 'incoming/untl-crs-collection.tar'
UNT_SOURCE_STRING = "University of North Texas Libraries Government Documents Department"
REPORTS_DIR = 'reports'


def read_reports_metadata():
    # Load our block list.
    with open("withheld-reports.txt") as f:
        withheld_reports = set(line.split("\t")[0] for line in f)

    # Load the report version JSON metadata which is by report-version
    # and collate by report. We get report version JSON data from three
    # sources.
    reports = collections.defaultdict(lambda : [])
    load_crs_dot_gov_reports(reports, withheld_reports)
    load_unt_reports(reports)
    load_crsreports_dot_congress_dot_gov_reports(reports)

    # For each report, sort the report version records in reverse-chronological order, putting
    # the most recent one first. Sort on the report date and on the retrieved date, since the
    # cover date is a date (without time) and if there are multiple updates on the same
    # date we should take the most recent fetch as the newer one.
    for report in reports.values():
        report.sort(key = lambda record : (record['date'], record['retrieved']), reverse=True)

    # Sort the reports in reverse chronological order by most recent
    # report version (based on the first version record, since the
    # arrays have already been sorted).
    reports = list(reports.items())
    reports.sort(key = lambda kv : (kv[1][0]['date'], kv[1][0]['retrieved']), reverse=True)

    # Transform to the public metadata format.
    reports = [
      transform_report_metadata(report_number, report_versions)
      for report_number, report_versions in reports
    ]

    return reports

def write_reports_metadata(reports):
    # Write the reports out to disk.
    all_files = set()
    for report in reports:
        # Construct a file name for the JSON.
        out_fn = os.path.join(REPORTS_DIR, "reports", report["id"] + ".json")

        # Remember it so we can delete orphaned files.
        all_files.add(out_fn)

        # Write it out.
        with open(out_fn, "w") as f2:
            f2.write(json.dumps(report, indent=2))


    # Delete orphaned files.
    for fn in glob.glob(os.path.join(REPORTS_DIR, 'reports', '*')):
        if fn not in all_files:
            print("deleting", fn)
            raise ValueError(fn)
            os.unlink(fn)

    return reports


def load_crs_dot_gov_reports(reports, withheld_reports):
    # Load all of the CRS report version metadata that was submitted through
    # our inside-the-Capitol scraper. Add each report version into the reports
    # dictionary that is keyed by the report ID (not the report version ID).

    print("Reading CRS.gov report metadata...")

    # Scan the "incoming" directory for report version metadata...
    for fn in sorted(glob.glob(os.path.join(INCOMING_DIR, "documents/*.json"))):
        with open(fn) as f:
            try:
                doc = json.load(f)
            except ValueError as e:
                print(fn, e)
                continue

        # Skip document types that we have access to but do not want to
        # expose publicly.
        if doc['ProdTypeGroupCode'] not in ("REPORTS", "INSIGHTS"):
            if doc['ProdTypeGroupCode'] not in ("BLOG","SIDEBAR"):
                print("Saw unrecognized ProdTypeGroupCode:", doc['ProdTypeGroupCode'])
            continue

        # Skip reports in our withheld_reports list.
        if doc['ProductNumber'] in withheld_reports:
            continue

        # Turn this into our public metadata format.
        rec = collections.OrderedDict([
            ("source", "EveryCRSReport.com"),
            ("id", doc["PrdsProdVerId"]), # report version ID, which changes with each version

            # Validate and normalize the fetch date and CoverDate into an ISO date string.
            # We need these for chronological sorting but turning them into datetime instances
            # would break JSON serialization. (TODO: Probably want to strip the time from
            # CoverDate and treat it as timezoneless, and probably want to add a UTC indication
            # to _fetched.)
            ('date', datetime.datetime.strptime(doc['CoverDate'], "%Y-%m-%dT%H:%M:%S").isoformat()),
            ('retrieved', datetime.datetime.strptime(doc['_fetched'], "%Y-%m-%dT%H:%M:%S.%f").isoformat()),

            ("title", doc["Title"]), # title
            ("summary", doc.get("Summary", "").strip()) or None, # summary, sometimes not present - set to None if not a non-empty string

            ("type", doc['ProdTypeDisplayName']),
            ("typeId", doc['ProdTypeGroupCode']),
            ("active", doc["StatusFlag"] == "Active"), # "Active" or "Archived", not sure if it's meaningful

            ("formats", [
                collections.OrderedDict([
                    ("format", f["FormatType"]), # "PDF" or "HTML"

                    # these fields we inserted when we scraped the content
                    ("encoding", f["_"]["encoding"]), # best guess at encoding of HTML content
                    ("url", f["_"]["url"]), # the URL we fetched the file from
                    ("sha1", f["_"]["sha1"]), # the SHA-1 hash of the file content
                    ("filename", f["_"]["filename"]), # the path where the content is stored in our cache
                    ("images", f["_"]["images"] if "images" in f["_"] else None), # mapped image paths found in the HTML file (this could be omitted from the public files but we need it in a later step of processing)
                ])
                for f in sorted(doc["FormatList"], key = lambda ff : ff["Order"])
                ]),
            ("topics", # there's no indication that the PrdsCliItemId has a clash between the two types (IBCList, CongOpsList)
                [collections.OrderedDict([("source", "IBCList"), ("id", int(entry["PrdsCliItemId"])), ("name", entry["CliTitle"]) ]) for entry in doc["IBCList"]]
              + [collections.OrderedDict([("source", "CongOpsList"), ("id", int(entry["PrdsCliItemId"])), ("name", entry["CliTitle"]) ]) for entry in doc["CongOpsList"]]
                ), # TODO: ChildIBCs?
        ])

        # Check that we don't have this version already - sometimes we have multiple
        # scrapes on the same date.
        for v in reports[doc['ProductNumber']]:
            if v["date"] == rec["date"]:
                # There's already a document for this date.
                break
        else:
            # This record is new.
            # Store by report number.
            reports[doc['ProductNumber']].append(rec)

def load_unt_reports(reports):
    # Scan the University of North Texas archive for report metadata...
    if not os.path.exists(UNT_ARCHIVE): return

    import tarfile

    print("Reading UNT report metadata...")

    with tarfile.open(UNT_ARCHIVE) as untarchive:
     with shelve.open(UNT_ARCHIVE+"_hashes.db") as hashcache:
        # Read the entire tar directory. We'll need it a few times, and since
        # extracting PDFs is expensive we want to know how many items we have
        # in total so we can show a progress meter.
        tardir = []
        while True:
            fi = untarchive.next()
            if fi is None: break
            tardir.append(fi)

        # Do a first pass, mapping directories to the name of the PDF file
        # within them, since the PDF filename is not predictable.
        directory_pdf_name = { }
        for fi in tardir:
            if fi.name.endswith(".pdf"):
                p = fi.name.split("/")
                directory_pdf_name["/".join(p[:-1])] = fi.name

        # Do a third pass locating XML metadata records and corresponding PDFs.
        unt_reports = []
        for fi in tardir:
            if not fi.name.endswith(".xml"): continue
            if fi.name.endswith(".pro.xml"): continue # some other metadata stuff
            fi_dirname = "/".join(fi.name.split("/")[:-1])
            pdf_fn = directory_pdf_name.get(fi_dirname)
            if not pdf_fn: continue # no PDF here
            unt_reports.append((fi, pdf_fn))

        # Do a fourth pass creating metadata records.
        existing_reports = set(reports.keys())
        num_new_reports = 0
        num_new_versions = 0
        for (fi, pdf_src_fn) in tqdm.tqdm(unt_reports, desc="UNT reports"):
            # Parse its metadata XML file.
            md = lxml.etree.parse(untarchive.extractfile(fi))
            #print(lxml.etree.tostring(md, encoding=str))

            # Helper function to get values out of the XML DOM by tag and attribute.
            def getvalue(tag, qualifier, fallback=False, required=True):
                node = md.find(tag + "[@qualifier='" + qualifier + "']")
                if node is None and fallback:
                    node = md.find(tag + "[@qualifier='']")
                if node is None:
                    if not required:
                        return None
                    raise ValueError("No %s in: %s" % (tag, lxml.etree.tostring(md)))
                return node.text

            if getvalue("title", "seriestitle", False, False) in ("Legal Sidebar", "Legal Sidebars"):
                # Legal Sidebars don't seem to have report numbers / identifiers.
                continue

            # Extract the CRS report number and date.
            try:
                report_number = getvalue("identifier", "CRS")\
                                 .replace(" ", "")
                if not re.match(r"^[0-9A-Z-]+$", report_number): continue # invalid, will be problematic to make a URL
                report_date = getvalue("date", "creation")
                if len(report_date) == 4: report_date += "-01-01" # make up a date
                if len(report_date) == 7: report_date += "-01" # make up a date
                if report_date == "2009-02-29": report_date = "2009-02-28" # weird, that date did not exist
            except ValueError:
                # no report number or date?
                continue

            # Construct a filename that we'll save the PDF as. Use the report number, date, and SHA1 hash
            # of the file content as we do with the newer files. Since the metadata extraction may fail,
            # we don't write to disk until after. Cache the hashes.
            if pdf_src_fn in hashcache:
                pdf_content_hash = hashcache[pdf_src_fn]
                pdf_content = None
            else:
                h = hashlib.sha1()
                with untarchive.extractfile(pdf_src_fn) as f1:
                    pdf_content = f1.read()
                h.update(pdf_content)
                pdf_content_hash = h.hexdigest()
                hashcache[pdf_src_fn] = pdf_content_hash # store for next time
            pdf_fn = "files/" + report_date.replace("-", "") + "_" + report_number + "_" + pdf_content_hash + ".pdf"

            # Get an identifier for this version.
            try:
                report_version_id = getvalue("identifier", "LOCAL-CONT-NO")
            except:
                try:
                    report_version_id = getvalue("identifier", "ark")
                except:
                    report_version_id = fi.name

            # Create the metadata record for this report version.
            try:
                rec = collections.OrderedDict([
                    ("source", UNT_SOURCE_STRING),
                    ("sourceLink", "https://digital.library.unt.edu/" + getvalue("meta", "ark") + "/"),
                    ("id", report_version_id),
                    ("date", report_date + "T00:00:00"),
                    ("retrieved", getvalue("meta", "metadataCreationDate").replace(", ", "T")), # not ISO format originally but this fix seems to work, don't know what time zone though
                    ("title", getvalue("title", "officialtitle", True)),
                    ("summary", getvalue("description", "content", False, False)),
                    ("type", "CRS Report"), # title[qualifier=seriestitle] is sometimes "Legal Sidebar" but other values are weird
                    ("typeId", "REPORT"),
                    ("active", False),
                    ("formats", [
                        collections.OrderedDict([
                            ("format", "PDF"),
                            ("filename", pdf_fn),
                        ])
                        ]),
                    ("topics", # there's no indication that the PrdsCliItemId has a clash between the two types (IBCList, CongOpsList)
                        [collections.OrderedDict([
                            ("source", subject.get("qualifier")),
                            ("id", subject.text),
                            ("name", subject.text)
                            ])
                            for subject in md.findall("subject")]
                        ),
                ])

            except ValueError as e:
                # TODO: Not all of the metadata provides all of the data values
                # we're try to extract above, and we are skipping over any
                # errors extracting metadata. There are probably more reports
                # that we could extract from this archive if we inspect the
                # errors we're getting.
                #print(report_version_id, e)
                #print(lxml.etree.tostring(md, encoding=str))
                continue

            # Store this document by report number since it may be a version
            # of a document that may have multiple versions.
            #
            # Since we're collecting from multiple sources, don't add it if
            # we have a version for this document with the same date.
            if report_number not in existing_reports and report_number not in reports:
                num_new_reports += 1
            is_dup = False
            for v in reports[report_number]:
                if v["date"][:10] == rec["date"][:10]:
                    # There's already a document for this date.
                    # We seem to have duplicates within the UNT archive
                    # and of course also across collections.
                    is_dup = True
                    break

            if is_dup:
                continue

            # This record is new.
            if report_number in existing_reports:
                num_new_versions += 1
            reports[report_number].append(rec)

            # Save PDF file. We may or may not have read it earlier.
            pdf_fn = os.path.join(REPORTS_DIR, pdf_fn)
            if not os.path.exists(pdf_fn):
                if pdf_content is None:
                    with untarchive.extractfile(pdf_src_fn) as f1:
                        pdf_content = f1.read()
                with open(pdf_fn, "wb") as f:
                    f.write(pdf_content)

        print(num_new_reports, "new reports from UNT,", num_new_versions, "new versions of existing reports")


def load_crsreports_dot_congress_dot_gov_reports(reports):
    # Load all of the CRS report version metadata that was scraped from
    # crsreports.congress.gov, the public website. Add each report version into the reports
    # dictionary that is keyed by the report ID (not the report version ID).

    print("Reading CRSReports.Congress.gov report metadata...")

    # Scan the "incoming" directory for report version metadata...
    source_dir = "crsreports.congress.gov"
    for fn in sorted(glob.glob(os.path.join(INCOMING_DIR, source_dir + "/documents/*.json"))):
        with open(fn) as f:
            try:
                doc = json.load(f)
            except ValueError as e:
                print(fn, e)
                continue

        m = re.search(r"/([^/]+)_(\d+)_[\d-]+\.json$", fn)
        reportId = m.group(1)

        # Check that we don't have this version already --- we may have it from
        # a different data source.
        for v in reports[reportId]:
            if v["date"] == doc["date"]:
                # There's already a document for this date.
                break
        else:
            # This record is new.
            # Store by report number.
            doc["source_dir"] = source_dir
            reports[reportId].append(doc)


def add_missing_html_formats(reports, all_files):
    for report, version, file in tqdm.tqdm(list(iter_files()), desc="extracting text"):
            # What formats are available for this version?
            formats = { format["format"]: format["filename"] for format in version["formats"] }
            if "HTML" in formats: continue
            if file["format"] == "PDF" and os.path.exists(os.path.join(REPORTS_DIR, formats["PDF"])):
                html_fn = file["filename"].replace(".pdf", ".html")
                all_files.add(html_fn)

                # Convert, unless we have it already from the last run of this script.
                if not os.path.exists(os.path.join(REPORTS_DIR, html_fn)):
                    # Convert to plain text and then wrap in a preformatted div.
                    try:
                      html_fmt = subprocess.check_output(["pdftotext", os.path.join(REPORTS_DIR, formats["PDF"]), "-"]).decode("utf8")
                    except:
                      # Skip errors.
                      continue
                    html_fmt = "<div style='white-space: pre; word-break: break-all; word-wrap: break-word;'>{}</div>".format(html.escape(html_fmt))

                    # # pdftohtml will also extract images using the given filename as
                    # # a prefix for the generated files and those paths will also be the SRC attributes
                    # # in the HTML. Since the HTML will be saved into the same directory as the images
                    # # (as the PDF file), change to the 'files' directory so that the SRC attributes
                    # # have no directory path, otherwise they will have an extra path.
                    # try:
                    #   html_content = subprocess.check_output([
                    #     "pdftohtml", "-stdout", "-zoom", "1.75", "-enc", "UTF-8", os.path.basename(pdf_file)
                    #   ], cwd=BASE_PATH + "/files")
                    # except subprocess.CalledProcessError:
                    #     # PDF conversion failed. Maybe there was an error getting the PDF.
                    #     # Skip for now. We seem to get a lot of zero-length PDF files.
                    #     return

                    # # Just take the body of the HTML file --- trash generated META tags.
                    # html_content = re.search(b"<body(?:.*?)>(.*)</body>", html_content, re.S).group(1)

                    # # Make a mapping of image files from their path in the HTML IMG SRC attributes
                    # # to their path on disk relative to BASE_PATH.
                    # image_path_map = { }
                    # for img_fn in re.findall(b"<img src=\"(.*?)\"", html_content, re.S):
                    #     img_fn = img_fn.decode("utf8")
                    #     if os.path.exists(os.path.join(BASE_PATH, 'files', img_fn)):
                    #         image_path_map[img_fn] = "files/" + img_fn

                    # Save the HTML.
                    with open(os.path.join(REPORTS_DIR, html_fn), "w") as f:
                        f.write(html_fmt)

                # Add to metadata.
                version["formats"].append(collections.OrderedDict([
                    ("format", "HTML"),
                    ("filename", html_fn),
                    #("images", image_path_map)
                ]))

              
def transform_report_metadata(report_number, report_versions):
    # Construct the data structure for a report, given a list of report versions.
    #
    # The return value is an OrderedDict so that our output maintains the fields
    # in a consistent order.

    # construct a source string that lists sources in reverse chronological order
    sources = []
    for m in report_versions:
        if m["source"] not in sources:
            sources.append(m["source"])

    m = report_versions[0]
    return collections.OrderedDict([
        ("id", report_number),
        ("type", m['type']),
        ("typeId", m['typeId']),
        ("number", report_number),
        ("active", m["active"]),
        ("source", ", ".join(sources)),
        ("versions", report_versions),
    ])


# Iterate through all of the HTML and PDF files, yielding
# each file that needs processing.
def iter_files():
    for report in reports:
        for version in reversed(report["versions"]):
            for file in version["formats"]:
                yield (
                    report,
                    version,
                    file,
                )


def clean_files(reports, all_files):
    # Use a multiprocessing pool to divide the load across processors.
    from multiprocessing import Pool
    pool = Pool()

    open_tasks = []

    for report, version, file in tqdm.tqdm(list(iter_files()), desc="cleaning HTML/PDFs"):
        fn = file["filename"]
        if "ONLY" in os.environ and os.environ["ONLY"] not in fn: continue

        # Remmeber that this was a file and also remember any related files we generate from it.
        all_files.add(fn)
        
        # Process the file.
        in_fn = os.path.join(INCOMING_DIR, version.get("source_dir", ""), fn)
        out_fn = os.path.join(REPORTS_DIR, fn)

        # For every HTML/PDF file, if we haven't yet processed it, then process it.
        # We'll skip files that we've processed already. Since the files have their
        # own SHA1 hash in their file name, we know once we processed it that it's
        # done. If we change the logic in this module then you should delete the
        # whole reports/files directory and re-run this.
        if os.path.exists(in_fn) and not os.path.exists(out_fn):
            if fn.endswith(".html"):
                ar = pool.apply_async(trap_all, [clean_html, in_fn, out_fn, version, file])
            elif fn.endswith(".pdf"):
                ar = pool.apply_async(trap_all, [clean_pdf, in_fn, out_fn, version])
            else:
                continue
            open_tasks.append(ar)

        # Link scraped images into the output folder.
        if fn.endswith(".html") and file.get("images"):
            for img in file["images"].values():
                img_fn = os.path.join(INCOMING_DIR, version.get("source_dir", ""), img)
                if not os.path.exists(img_fn): continue # ignore missing images
                make_link(img_fn, os.path.join(REPORTS_DIR, img))
                all_files.add(img)

        # So that the tqdm progress meter works, wait synchronously
        # every so often.
        if len(open_tasks) > 20:
            open_tasks.pop(0).wait()

    for report, version, file in tqdm.tqdm(list(iter_files()), desc="generating thumbnails"):
        fn = file["filename"]
        if not fn.endswith(".pdf"): continue
        if "ONLY" in os.environ and os.environ["ONLY"] not in fn: continue

        # Process the file.
        pdf_fn = os.path.join(REPORTS_DIR, fn)
        png_fn = pdf_fn.replace(".pdf", ".png")

        # Remmeber that we generated this file.
        all_files.add(fn.replace(".pdf", ".png"))

        # Since the files have their own SHA1 hash in their file name, we know once we
        # processed it that it's done.
        if os.path.exists(png_fn): continue

        ar = pool.apply_async(trap_all, [make_pdf_thumbnail, pdf_fn])
        open_tasks.append(ar)

        # So that the tqdm progress meter works, wait synchronously
        # every so often.
        if len(open_tasks) > 5:
            open_tasks.pop(0).wait()

    # Wait for the last processes to be done.
    pool.close()
    pool.join()


def clean_html(content_fn, out_fn, report_metadata, file_metadata):
    # Transform the scraped HTML page to the one that we publish:
    #
    # * The HTML file contains the entire HTML page from CRS.gov that the report was
    #   scraped from. Extract just the report content, dropping the CRS.gov header/footer.
    # * Sanitize the HTML to ensure no unsafe content is injected into our site,
    #   and clean up the HTML so we can make it look good with CSS.
    # * Replace image paths with references to our "files/" directory that holds
    #   a scraped version of the image.
    # * Rewrite internal crs.gov links to point to the corresponding report on
    #   everycrsreport.com.
    # * Scrub author phone numbers and email addresses.

    with open(content_fn, "rb") as f:
        content_bytes = f.read()

    # Parse the page as HTML5. html5lib gives some warnings about malformed
    # content that we don't care about -- hide warnings.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        content = html5lib.parse(content_bytes, treebuilder="lxml")
    
    if report_metadata["source"] == "CRSReports.Congress.gov":
        # Get the body node. Change it to a div.
        content = content.getroot().find("{http://www.w3.org/1999/xhtml}body")
        content.tag = "div"
    else:
        # For HTML scraped from crs.gov...

        # Extract the report itself from the whole page.
        n = content.find(".//*[@class='Report']")
        if n is None:
            n = content.find(".//*[@id='Insightsdiv']/*[@class='ReportContent']")
        if n is None:
            raise ValueError("HTML page doesn't contain an element that we know to pull body content from")
        content = n

        # Some reports are invalid HTML with a whole doctype and html node inside
        # the main report container element. See if this is one of those documents.
        if b'<div class="Report"><!DOCTYPE' in content_bytes:
            content = content.find("{http://www.w3.org/1999/xhtml}blockquote")
            if content is None:
                raise ValueError("HTML page didn't have the expected blockquote.")
            content.tag = "div"

    # Remove the XHTML namespace to make processing easier.
    for tag in [content] + content.findall(".//*"):
        if isinstance(tag.tag, str): # is an element
            tag.tag = tag.tag.replace("{http://www.w3.org/1999/xhtml}", "")

    # Scrub content and adjust some tags.

    allowed_classes = { 'ReportHeader' }

    def scrub_text(text):
        # Scrub crs.gov email addresses from the text.
        # There's a separate filter later for addresses in mailto: links.
        text = re.sub(r"[a-zA-Z0-9_!#\$%&\'\*\+\-/=\?\^`\{\|\}~]+@crs\.(loc\.)?gov", "[email address scrubbed]", text)

        # Scrub CRS telephone numbers --- in 7-xxxx format. We have to exclude
        # cases that have a preceding digit, because otherwise we match
        # strings like "2007-2009". But the number can also occur at the start
        # of a node, so it may be the start of a string.
        text = re.sub(r"(^|[^\d])7-\d\d\d\d", r"\1[phone number scrubbed]", text)

        # Scrub all telephone numbers --- in (xxx) xxx-xxxx format.
        text = re.sub(r"\(\d\d\d\) \d\d\d-\d\d\d\d", "[phone number scrubbed]", text)

        return text

    whitelisted_image_paths = set()

    for tag in [content] + content.findall(".//*"):
        # Skip non-element nodes.
        if not isinstance(tag.tag, str): continue

        # Scrub the text.
        if tag.text is not None: tag.text = scrub_text(tag.text)
        if tag.tail is not None: tag.tail = scrub_text(tag.tail)

        css_classes = set(tag.attrib.get('class', '').split(" "))

        # Modern reports have a ReportHeader node with title, authors, date, report number,
        # and an internal link to just past the table of contents. Since we are scrubbing
        # author names, we must remove at least that. We also want to remove that internal
        # link and replace the title with an <h1> tag.
        if "ReportHeader" in css_classes:
            for node in tag:
                node_css_classes = set(node.attrib.get('class', '').split(" "))
                if "Title" in node_css_classes:
                    node.tag = "h1"
                elif "CoverDate" in node_css_classes:
                    pass # keep this one
                else:
                    node.getparent().remove(node)

        # Older reports had a "titleline" class for the title.
        if "titleline" in css_classes:
            tag.tag = "h1"
            css_classes.add("Title") # so the h1 doesn't get demoted below

        # Older reports had an "authorline" with author names, which we scrub by
        # removing completely.
        if "authorline" in css_classes:
            tag.getparent().remove(tag)

        # Older reports had a "Print Version" link, which we can remove.
        if tag.tag == "a" and tag.text == "Print Version":
            tag.getparent().remove(tag)

        # Scrub mailto: links, which have author emails, which we want to scrub,
        # as well as email addresses of other people mentioned in the reports.
        if 'href' in tag.attrib and tag.attrib['href'].lower().startswith("mailto:"):
            tag.tag = "span"
            del tag.attrib['href']
            tag.text = "[email address scrubbed]"
            for n in tag: # remove all child nodes
                tag.remove(n)

        # Replace img files with scraped files.
        if tag.tag == "img" and tag.attrib["src"] in (file_metadata.get("images") or {}):
            # Get the path to the scraped file.
            # Make the path absolute because the relative location will be different
            # for the raw HTML (in the files directory just like the image) and
            # the published report path (in /reports).
            path = "/" + file_metadata["images"][tag.attrib["src"]]
            tag.attrib["src"] = path
            whitelisted_image_paths.add(tag.attrib["src"])

        # Rewrite internal crs.gov links to point to the corresponding report on
        # everycrsreport.com.
        if tag.tag == "a" and "href" in tag.attrib:
            if tag.attrib["href"].startswith("http://www.crs.gov/Reports/"):
                tag.attrib["href"] = re.sub("^http://www\\.crs\\.gov/Reports/([0-9A-Z-]+)$",
                                            "https://www.everycrsreport.com/reports/\\1.html",
                                            tag.attrib["href"])

        # Demote h#s. These seem to occur around the table of contents only. Don't
        # demote the one we just made above for the title.
        if tag.tag in ("h1", "h2", "h3", "h4", "h5") and "Title" not in css_classes:
            tag.tag = "h" + str(int(tag.tag[1:])+1)

        # Turn some classes into h#s.
        for cls in css_classes:
            if cls in ("Heading1", "Heading2", "Heading3", "Heading4", "Heading5"):
                tag.tag = "h" + str(int(cls[7:])+1)
            if cls == "SummaryHeading":
                tag.tag = "h2"

        # Sanitize CSS classes using the whitelist above.
        if "class" in tag.attrib:
            new_classes = " ".join(sorted(set(tag.attrib["class"].split(" ")) & allowed_classes))
            if new_classes:
                tag.attrib["class"] = new_classes
            else:
                del tag.attrib["class"]

    # Serialize back to XHTML.
    content = lxml.etree.tostring(content, encoding=str, method="html")

    # Guard against unsafe content.
    import bleach
    def link_filter(tag, name, value):
        if name in ("name", "class"):
            return True # "name" is for link targets
        if name == "href" and (value.startswith("http:") or value.startswith("https:") or value.startswith("#")):
            return True
        return False
    def image_filter(tag, name, value):
        if name in ("class",):
            return True
        if name == "src" and (value.startswith("http:") or value.startswith("https:") or value in whitelisted_image_paths):
            return True
        return False
    content = bleach.clean(
        content,
        tags=["a", "img", "b", "strong", "i", "em", "u", "sup", "sub", "span", "div", "p", "br", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td", "hr", "h1", "h2", "h3", "h4", "h5", "h6"],
        attributes={
            "*": ["title", "class"],
            "a": link_filter,
            "img": image_filter,
            "td": ["colspan", "rowspan"],
            "th": ["colspan", "rowspan"],
        }
    )

    # Write it out.
    with open(out_fn, "w") as f2:
        f2.write(content)

def trap_all(func, in_file, *args):
    try:
        func(in_file, *args)
    except Exception as e:
        # Catch all exceptions because we are in a subprocess and untrapped
        # exceptions get lost.
        print(in_file)
        print("\t", e)
        return


def clean_pdf(in_file, out_file, file_metadata):
    if file_metadata["source"] == "EveryCRSReport.com":
    	# Perform redaction on non-public PDFs.
    	redact_pdf(in_file, out_file, file_metadata)
    elif file_metadata["source"] in (UNT_SOURCE_STRING, "CRSReports.Congress.gov"):
    	# Don't do any special redaction. Just use the PDF as-is.
    	make_link(in_file, out_file)
    else:
    	raise ValueError(file_metadata["source"])


def make_pdf_thumbnail(pdf_file):
    # Generate a thumbnail image of the PDF.
    # Note that pdftoppm adds ".png" to the end of the file name.
    import subprocess
    subprocess.check_call(['pdftoppm', '-png', '-singlefile',
                           '-scale-to-x', '600', '-scale-to-y', '-1',
                           pdf_file, pdf_file.replace(".pdf", "")])


def redact_pdf(in_file, out_file, file_metadata):
    from pdf_redactor import redactor, RedactorOptions
    import io, re, subprocess, tempfile, shutil

    # Set redaction options.

    redactor_options = RedactorOptions()

    # Perform redaction on non-public PDFs.
    redactor_options.metadata_filters = {
        # Set PDF metadata from report metadata, replacing any existing metadata.
        "Title": [lambda value : file_metadata['title']],
        "Author": [lambda value : "Congressional Research Service, Library of Congress, USA"],
        "CreationDate": [lambda value : file_metadata['date']],

        # Set these.
        "Producer": [lambda value : "EveryCRSReport.com"],
        "ModDate": [lambda value : datetime.datetime.utcnow()],

        # Clear all other fields.
        "DEFAULT": [lambda value : None],
    }

    # Clear XMP.
    redactor_options.xmp_filters = [lambda xml : None]

    # Redact phone numbers and email addresses.
    # See the notes on the regular expressions above for the HTML scrubber.
    redactor_options.content_filters = [
        (re.compile("((^|[^\d])7-)\d{4}"), lambda m : m.group(1) + "...."), # use a symbol likely to be available
        (re.compile("\(\d\d\d\) \d\d\d-\d\d\d\d"), lambda m : "[redacted]"), # use a symbol likely to be available
        (re.compile("[a-zA-Z0-9_!#\$%&\'\*\+\-/=\?\^`\{\|\}~]+(@crs.?(loc|gov))"), lambda m : ("[redacted]" + m.group(1))),
    ]

    # Avoid inserting ?'s and spaces.
    redactor_options.content_replacement_glyphs = ['#', '*', '/', '-']

    # Filter out links to email addresses which might also hold CRS staffer email addresses.
    redactor_options.link_filters = [
        lambda href, annotation : None if "mailto:" in href else href
    ]

    # Run qpdf to decompress.
    try:
        data = subprocess.check_output(['qpdf', '--normalize-content=y', '--stream-data=uncompress', in_file, "-"])
    except subprocess.CalledProcessError as e:
        if e.returncode == 3:
            # There were warnings but output was otherwise OK.
            data = e.output
        else:
            raise

    with tempfile.NamedTemporaryFile() as f1:
        with tempfile.NamedTemporaryFile() as f2:

            # Run the redactor. Since qpdf in the next step requires an actual file for the input,
            # write the output to a file.
            redactor_options.input_stream = io.BytesIO(data)
            redactor_options.output_stream = f1
            try:
                redactor(redactor_options)
            except:
                # The redactor has some trouble on old files. Post them anyway.
                if file_metadata['date'] < "2003-01-01":
                    print("Writing", out_file, "without redacting.")
                    f1.seek(0)
                    f1.write(data)
                else:
                    raise
            f1.flush()

            # Linearize and add our own page to the end of the PDF. The qpdf command
            # for this is pretty weird. All we're doing is appending a page.
            import subprocess
            subprocess.check_call(['qpdf', '--optimize-images', '--linearize', f1.name,
                "--pages", f1.name, "branding/pdf-addendum-page.pdf", "--",
                f2.name])

            # Copy the final PDF to the output location. We don't write directly to
            # out_file in the previous qpdf step in case of errors. If there's an
            # error during writing, let's not leave a broken file.
            shutil.copyfile(f2.name, out_file)

def make_link(fn1, fn2):
    if os.path.exists(fn2):
        if os.stat(fn1).st_ino == os.stat(fn2).st_ino:
            # Files are already hard links.
            return
        #elif os.islink(fn2) and os.readlink(fn2) == os.path.abspath(fn1):
        #    # File is already a symlink to the right place.
        #    return
        else:
            # File links to the wrong place. Replace it.
            os.unlink(fn2)
    os.link(fn1, fn2)
    # if crossing file-system boundaries:
    #os.symlink(os.path.abspath(fn1), fn2)

# MAIN

if __name__ == "__main__":
    # Make the output directories.
    os.makedirs(os.path.join(REPORTS_DIR, 'reports'), exist_ok=True)
    os.makedirs(os.path.join(REPORTS_DIR, 'files'), exist_ok=True)

    # Combine and transform the report JSON.
    reports = read_reports_metadata()

    all_files = set()

    # Clean/sanitize the HTML and PDF files and generate PNG thumbnails.
    clean_files(reports, all_files)

    # For any report with a PDF but no HTML, convert the PDF to HTML via pdftotext.
    # Do this after sanitization so that we don't leak redacted information.
    add_missing_html_formats(reports, all_files)

    # Write out JSON.
    write_reports_metadata(reports)

    # Delete orphaned files.
    if "ONLY" not in os.environ:
        for fn in glob.glob(os.path.join(REPORTS_DIR, 'files', '*')):
            if fn[len(REPORTS_DIR)+1:] not in all_files:
                print("deleting", fn)
                raise ValueError(fn)
                os.unlink(fn)

