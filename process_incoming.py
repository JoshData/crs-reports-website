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
#    author information. Image files are copied
#    to the output directory.
#
# c) The PDF files are scrubbed of author information,
#    our back page is appended to each, and a PNG
#    thumbnail image of the first page is generated.

import collections
import datetime
import glob
import os
import os.path
import json
import re
import random

import tqdm
import bleach
import lxml.etree
import html5lib

INCOMING_DIR = 'incoming'
UNT_ARCHIVE = 'untl-crs-collection.tar'
REPORTS_DIR = 'reports'


def write_report_json_files():
    # Load our block list.
    with open("withheld-reports.txt") as f:
        withheld_reports = set(line.split("\t")[0] for line in f)

    # Load the incoming report JSON metadata which is by report-version
    # and collate by unique report.
    reports = collections.defaultdict(lambda : [])
    author_names = set()
    load_ecr_reports_metadata(reports, author_names, withheld_reports)
    load_unt_reports_metadata(reports, author_names)

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

    # Write the reports out to disk.
    all_files = set()
    for i, (report_number, report_versions) in enumerate(reports):
        # Construct a file name for the JSON.
        out_fn = os.path.join(REPORTS_DIR, "reports", report_number + ".json")

        # Remember it so we can delete orphaned files.
        all_files.add(out_fn)

        # Transform and write it out.
        try:
            reports[i] = transform_report_metadata(report_number, report_versions)
        except Exception as e:
            print(out_fn)
            print("\t", e)
        else:
            with open(out_fn, "w") as f2:
                f2.write(json.dumps(reports[i], indent=2))

    # Delete orphaned files.
    for fn in glob.glob(os.path.join(REPORTS_DIR, 'reports', '*')):
        if fn not in all_files:
            print("deleting", fn)
            os.unlink(fn)

    # At least one author appears with a first initial in
    # the metadata but the initial is dropped in the PDF
    # (RL30240).
    for name in list(author_names):
        name_spl = name.split(" ")
        if len(name_spl) >= 3 and name_spl[0].endswith('.'):
            rest_of_name = " ".join(name_spl[1:])
            author_names.add(rest_of_name)

    return (reports, author_names)


def load_ecr_reports_metadata(reports, author_names, withheld_reports):
    # Load all of the CRS reports metadata into memory. We do this because each report
    # is spread across multiple JSON files, each representing a snapshop of a metadata
    # record at a point in time when we fetched the information. The metadata snapshots
    # occur when there is a change in the metadata or file content.
    #
    # However, we want to make available data that is structured by report, not by
    # version. So we must scan the whole dataset and put together report version
    # records that are for the same report.
    #
    # We'll return a list of lists of metadata records collated by unique report.

    print("Reading CRS.gov report metadata...")

    # Scan the "incoming" directory for report version metadata...
    for fn in glob.glob(os.path.join(INCOMING_DIR, "documents/*.json")):
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

        # Store by report number.
        reports[doc['ProductNumber']].append(rec)

        # Collect a list of author names which we'll use for redaction.
        for author in doc["Authors"]:
            author_names.add(author["FirstName"]) # has full name

def load_unt_reports_metadata(reports, author_names):
    # Scan the University of North Texas archive for report metadata...
    if not os.path.exists(UNT_ARCHIVE): return
    print("Reading UNT report metadata...")
    import tarfile
    with tarfile.open(UNT_ARCHIVE) as untarchive:
        while True:
            # Get next entry in the tar file.
            fi = untarchive.next()
            if fi is None: break
            if not fi.name.endswith(".xml"): continue

            # Parse its metadata XML file.
            md = lxml.etree.parse(untarchive.extractfile(fi))
            def getvalue(tag, qualifier, fallback=False, required=True):
                node = md.find(tag + "[@qualifier='" + qualifier + "']")
                if node is None and fallback:
                    node = md.find(tag + "[@qualifier='']")
                if node is None:
                    if not required:
                        return None
                    raise ValueError("No %s in: %s" % (tag, lxml.etree.tostring(md)))
                return node.text

            # Get an identifier for this version.
            try:
                report_version_id = getvalue("identifier", "LOCAL-CONT-NO")
            except:
                try:
                    report_version_id = getvalue("identifier", "ark")
                except:
                    report_version_id = fi.name

            if getvalue("title", "seriestitle", False, False) == "Legal Sidebar":
                # Legal Sidebars don't seem to have report numbers / identifiers.
                continue

            try:
                report_number = getvalue("identifier", "CRS")
                rec = collections.OrderedDict([
                    ("source", "UNT"),
                    ("id", report_version_id),
                    ("date", getvalue("date", "creation")),
                    ("retrieved", getvalue("meta", "metadataCreationDate")), # not ISO format
                    ("title", getvalue("title", "officialtitle", True)),
                    ("summary", getvalue("description", "content", False, False)),
                    ("type", "CRS Report"), # title[qualifier=seriestitle] is sometimes "Legal Sidebar" but other values are weird
                    ("typeId", "REPORT"),
                    ("formats", [
                        collections.OrderedDict([
                            ("format", "PDF"),
                            ("filename", fi.name),
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

                # Store by report number.
                reports[report_number].append(rec)

            except ValueError as e:
                print(report_version_id, e)
                #print(lxml.etree.tostring(md).decode("ascii"))


def transform_report_metadata(report_number, report_versions):
    # Construct the data structure for a report, given a list of report versions.
    #
    # The return value is an OrderedDict so that our output maintains the fields
    # in a consistent order.
    m = report_versions[0]
    return collections.OrderedDict([
        ("id", report_number),
        ("type", m['type']),
        ("typeId", m['typeId']),
        ("number", report_number),
        ("active", m["active"]),
        ("source", ", ".join(set(mm["source"] for mm in report_versions))),
        ("versions", report_versions),
    ])

def clean_files(reports, author_names):
    # Use a multiprocessing pool to divide the load across processors.
    from multiprocessing import Pool
    pool = Pool()

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

    all_files = set()
    open_tasks = []
    for report, version, file in tqdm.tqdm(list(iter_files()), desc="cleaning HTML/PDFs"):
        fn = file["filename"]
        if "ONLY" in os.environ and os.environ["ONLY"] not in fn: continue

        # Remmeber that this was a file and also remember any related files we generate from it.
        all_files.add(fn)
        if fn.endswith(".pdf"): all_files.add(fn.replace(".pdf", ".png"))
        
        # Process the file.
        in_fn = os.path.join(INCOMING_DIR, fn)
        out_fn = os.path.join(REPORTS_DIR, fn)

        # For every HTML/PDF file, if we haven't yet processed it, then process it.
        # We'll skip files that we've processed already. Since the files have their
        # own SHA1 hash in their file name, we know once we processed it that it's
        # done. If we change the logic in this module then you should delete the
        # whole reports/files directory and re-run this.
        if os.path.exists(in_fn) and not os.path.exists(out_fn):
            if fn.endswith(".html"):
                ar = pool.apply_async(trap_all, [clean_html, in_fn, out_fn, file, author_names])
            elif fn.endswith(".pdf"):
                ar = pool.apply_async(trap_all, [clean_pdf, in_fn, out_fn, version, author_names])
            else:
                continue
            open_tasks.append(ar)

        # Link scraped images into the output folder.
        if fn.endswith(".html") and file.get("images"):
            for img in file["images"].values():
                make_link(os.path.join(INCOMING_DIR, img), os.path.join(REPORTS_DIR, img))
                all_files.add(img)

        # So that the tqdm progress meter works, wait synchronously
        # every so often.
        if len(open_tasks) > 20:
            open_tasks.pop(0).wait()

    # Wait for the last processes to be done.
    pool.close()
    pool.join()

    # Delete orphaned files.
    if "ONLY" not in os.environ:
        for fn in glob.glob(os.path.join(REPORTS_DIR, 'files', '*')):
            if fn[len(REPORTS_DIR)+1:] not in all_files:
                print("deleting", fn)
                os.unlink(fn)


def clean_html(content_fn, out_fn, file_metadata, author_names):
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
    # * Scrub author names.

    with open(content_fn, "rb") as f:
        content = f.read()

    # Some reports are invalid HTML with a whole doctype and html node inside
    # the main report container element. See if this is one of those documents.
    extract_blockquote = (b'<div class="Report"><!DOCTYPE' in content)

    # Parse the page as HTML5. html5lib gives some warnings about malformed
    # content that we don't care about -- hide warnings.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        content = html5lib.parse(content, treebuilder="lxml")
    
    # Extract the report itself from the whole page.
    n = content.find(".//*[@class='Report']")
    if n is None:
        n = content.find(".//*[@id='Insightsdiv']/*[@class='ReportContent']")
    if n is None:
        raise ValueError("HTML page doesn't contain an element that we know to pull body content from")
    content = n

    if extract_blockquote:
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

    author_names_re = re.compile("|".join([re.escape(an) for an in author_names]))

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

        # Scrub all author names.
        text = author_names_re.sub("[author name scrubbed]", text)

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

def clean_pdf(in_file, out_file, file_metadata, author_names):
    from pdf_redactor import redactor, RedactorOptions
    import io, re, subprocess, tempfile, shutil

    # Form a regex for author names, replacing spaces with optional whitespace.

    author_name_regex = "|".join(
        r"\s?".join(re.escape(an1) for an1 in an.split(" "))
        for an in author_names
    )

    # Set redaction options.

    redactor_options = RedactorOptions()

    redactor_options.metadata_filters = {
        # Copy from report metadata.
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

    # Redact phone numbers, email addresses, and author names.
    # See the notes on the regular expressions above for the HTML scrubber.
    redactor_options.content_filters = [
        (re.compile("((^|[^\d])7-)\d{4}"), lambda m : m.group(1) + "...."), # use a symbol likely to be available
        (re.compile("\(\d\d\d\) \d\d\d-\d\d\d\d"), lambda m : "[redacted]"), # use a symbol likely to be available
        (re.compile("[a-zA-Z0-9_!#\$%&\'\*\+\-/=\?\^`\{\|\}~]+(@crs.?(loc|gov))"), lambda m : ("[redacted]" + m.group(1))),
        (re.compile(author_name_regex), lambda m : "(name redacted)"),
    ]

    # Avoid inserting ?'s and spaces.
    redactor_options.content_replacement_glyphs = ['#', '*', '/', '-']

    # Run qpdf to decompress.

    data = subprocess.check_output(['qpdf', '--qdf', '--stream-data=uncompress', in_file, "-"])

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
            subprocess.check_call(['qpdf', '--linearize', f1.name,
                "--pages", f1.name, "branding/pdf-addendum-page.pdf", "--",
                f2.name])

            # Copy the final PDF to the output location. We don't write directly to
            # out_file in the previous qpdf step in case of errors. If there's an
            # error during writing, let's not leave a broken file.
            shutil.copyfile(f2.name, out_file)

    # Generate a thumbnail image of the PDF.
    # Note that pdftoppm adds ".png" to the end of the file name.
    subprocess.check_call(['pdftoppm', '-png', '-singlefile',
                           '-scale-to-x', '600', '-scale-to-y', '-1',
                           out_file, out_file.replace(".pdf", "")])

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
    os.makedirs(os.path.join(REPORTS_DIR, 'diffs'), exist_ok=True)

    # Combine and transform the report JSON.
    reports, author_names = write_report_json_files()

    # Clean/sanitize the HTML and PDF files and generate PNG thumbnails.
    clean_files(reports, author_names)
