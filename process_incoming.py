#!/usr/bin/env python3

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
import html5lib


INCOMING_DIR = 'incoming'
REPORTS_DIR = 'reports'


def write_report_json_files():
    # Load our block list.
    with open("withheld-reports.txt") as f:
        withheld_reports = set(line.split("\t")[0] for line in f)

    # Load the incoming report JSON metadata.
    reports = load_reports_metadata(withheld_reports)

    # Collect a list of author names which we'll use for redaction.
    author_names = set()
    for report in reports:
        for version in report:
            for author in version["Authors"]:
                author_names.add(author["FirstName"]) # has full name

    # Transform the dicts and write them out to disk.
    all_files = set()
    for i, report in enumerate(reports):
        # Construct a file name for the JSON.
        out_fn = os.path.join(REPORTS_DIR, "reports", report[0]["ProductNumber"] + ".json")

        # Remember it so we can delete orphaned files.
        all_files.add(out_fn)

        # Transform and write it out.
        try:
            reports[i] = transform_report_metadata(report)
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

    return (reports, author_names)


def load_reports_metadata(withheld_reports):
    # Load all of the CRS reports metadata into memory. We do this because each report
    # is spread across multiple JSON files, each representing a snapshop of a metadata
    # record at a point in time when we fetched the information. The metadata snapshots
    # occur when there is a change in the metadata or file content.
    #
    # However, we want to make available data that is structured by report, not by
    # version. So we must scan the whole dataset and put together report version
    # records that are for the same report.
    #
    # We'll return a list of lists of metadata records.

    print("Reading report metadata...")

    # Collect metadata records by report ID.
    reports = collections.defaultdict(lambda : [])

    # Look through all of the metadata records on disk and combine by report.
    for fn in glob.glob(os.path.join(INCOMING_DIR, "documents/*.json")):
        with open(fn) as f:
            try:
                doc = json.load(f)
            except ValueError as e:
                print(fn, e)
                continue

        # Skip reports in our withheld_reports list.
        if doc['ProductNumber'] in withheld_reports:
            continue

        # Validate and normalize the fetch date and CoverDate into an ISO date string.
        # We need these for chronological sorting but turning them into datetime instances
        # would break JSON serialization. (TODO: Probably want to strip the time from
        # CoverDate and treat it as timezoneless, and probably want to add a UTC indication
        # to _fetched.)
        doc['_fetched'] = datetime.datetime.strptime(doc['_fetched'], "%Y-%m-%dT%H:%M:%S.%f").isoformat()
        doc['CoverDate'] = datetime.datetime.strptime(doc['CoverDate'], "%Y-%m-%dT%H:%M:%S").isoformat()

        # Store.
        reports[doc['PrdsProdId']].append(doc)

    # For each report, sort the metadata records in reverse-chronological order, putting
    # the most recent one first. Sort on the CoverDate and on the _fetched date, since the
    # cover date is a date (without time) and if there are multiple updates on the same
    # date we should take the most recent fetch as the newer one.
    for report in reports.values():
        report.sort(key = lambda record : (record['CoverDate'], record['_fetched']), reverse=True)

    # Sort the reports in reverse chronological order by most recent
    # publication date (the first metadata record, since the arrays have
    # already been sorted).
    reports = list(reports.values())
    reports.sort(key = lambda records : records[0]['CoverDate'], reverse=True)

    return reports


def transform_report_metadata(meta):
    # Converts the metadata from the JSON format we fetched directly from CRS.gov hidden API
    # into our public metadata format. This way, we're not committed to their schema.
    #
    # meta is a *list* of metadata records, newest first, for the same report.
    # The list gives us a change history of metadata, including when a document
    # is modified.
    #
    # The return value is an collections.OrderedDict so that our output maintains the fields
    # in a consistent order.

    m = meta[0]

    return collections.OrderedDict([
        ("id", m["PrdsProdId"]), # report ID, which is persistent across CRS updates to a report
        ("number", m["ProductNumber"]), # report display number, e.g. 96-123
        ("active", m["StatusFlag"] == "Active"), # not sure
        ("versions", [
            collections.OrderedDict([
                ("id", mm["PrdsProdVerId"]), # report version ID, which changes with each version
                ("date", mm["CoverDate"]), # publication/cover date
                ("title", mm["Title"]), # title
                ("summary", mm.get("Summary", "").strip()) or None, # summary, sometimes not present - set to None if not a non-empty string
                ("formats", [
                    collections.OrderedDict([
                        ("format", f["FormatType"]), # "PDF" or "HTML"

                        # these fields we inserted when we scraped the content
                        ("encoding", f["_"]["encoding"]), # best guess at encoding of HTML content
                        ("url", f["_"]["url"]), # the URL we fetched the file from
                        ("sha1", f["_"]["sha1"]), # the SHA-1 hash of the file content
                        ("filename", f["_"]["filename"]), # the path where the content is stored in our cache
                    ])
                    for f in sorted(mm["FormatList"], key = lambda ff : ff["Order"])
                    ]),
                ("topics", # there's no indication that the PrdsCliItemId has a clash between the two types (IBCList, CongOpsList)
                    [{ "source": "IBCList", "id": int(entry["PrdsCliItemId"]), "name": entry["CliTitle"] } for entry in mm["IBCList"]]
                  + [{ "source": "CongOpsList", "id": int(entry["PrdsCliItemId"]), "name": entry["CliTitle"]} for entry in mm["CongOpsList"]]
                    ), # TODO: ChildIBCs?
                #("fetched", m["_fetched"]), # date we picked up this report version
            ])
            for mm in meta
        ]),
    ])


def clean_files(reports, author_names):
    # Use a multiprocessing pool to divide the load across processors.
    from multiprocessing import Pool
    pool = Pool()

    # For every HTML/PDF file, if we haven't yet processed it, then process it.
    # We'll skip files that we've processed already. Since the files have their
    # own SHA1 hash in their file name, we know once we processed it that it's
    # done. If we change the logic in this module then you should delete the
    # whole reports/files directory and re-run this.
    def iter_files():
        for report in reports:
            for version in report["versions"]:
                for format in version["formats"]:
                    yield (report, version, format["filename"])

    all_files = set()
    open_tasks = []
    process_list = sorted(iter_files(), key=lambda x:x[2])
    for report, version, fn in tqdm.tqdm(process_list, desc="cleaning HTML/PDFs"):
        # Remmeber that this was a file and also remember any related files we generate from it.
        all_files.add(fn)
        if fn.endswith(".pdf"): all_files.add(fn.replace(".pdf", ".png"))
        
        # Process the file.
        in_fn = os.path.join(INCOMING_DIR, fn)
        out_fn = os.path.join(REPORTS_DIR, fn)
        if os.path.exists(in_fn) and not os.path.exists(out_fn):
            if fn.endswith(".html"):
                ar = pool.apply_async(trap_all, [clean_html, in_fn, out_fn, author_names])
            elif fn.endswith(".pdf"):
                ar = pool.apply_async(trap_all, [clean_pdf, in_fn, out_fn, version, author_names])
            else:
                continue
            open_tasks.append(ar)
        if len(open_tasks) > 20:
            # So that the tqdm progress meter works, wait synchronously
            # every so often.
            open_tasks.pop(0).wait()

    # Wait for the last processes to be done.
    pool.close()
    pool.join()

    # Delete orphaned files.
    for fn in glob.glob(os.path.join(REPORTS_DIR, 'files', '*')):
        if fn[len(REPORTS_DIR)+1:] not in all_files:
            print("deleting", fn)
            os.unlink(fn)


def clean_html(content_fn, out_fn, author_names):
    import lxml.etree

    # The HTML file contains the entire HTML page from CRS.gov that the report was
    # scraped from. Extract just the report content, dropping the CRS.gov header/footer.

    with open(content_fn) as f:
        content = f.read()

    # Some reports are invalid HTML with a whole doctype and html node inside
    # the main report container element. See if this is one of those documents.
    extract_blockquote = ('<div class="Report"><!DOCTYPE' in content)

    # Extract the report itself from the whole page.
    content = html5lib.parse(content, treebuilder="lxml")
    content = content.find(".//*[@class='Report']")

    if content is None:
        raise ValueError("HTML page doesn't contain an element with the Report CSS class")

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
        text = re.sub("|".join([re.escape(an) for an in author_names]), "[author name scrubbed]", text)

        return text

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
    def link_filter(name, value):
        if name in ("name", "class"):
            return True # "name" is for link targets
        if name == "href" and (value.startswith("http:") or value.startswith("https:") or value.startswith("#")):
            return True
        return False
    def image_filter(name, value):
        if name in ("class",):
            return True
        if name == "src" and (value.startswith("http:") or value.startswith("https:")):
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
    os.system("pdftoppm -png -singlefile -scale-to-x 600 -scale-to-y -1 %s %s" % (
         out_file,
         out_file.replace(".pdf", "") # pdftoppm adds ".png" to the end of the file name
     ))


# MAIN

if __name__ == "__main__":
    # Make the output directories.
    os.makedirs(os.path.join(REPORTS_DIR, 'reports'), exist_ok=True)
    os.makedirs(os.path.join(REPORTS_DIR, 'files'), exist_ok=True)

    # Combine and transform the report JSON.
    reports, author_names = write_report_json_files()

    # Clean/sanitize the HTML and PDF files.
    clean_files(reports, author_names)
