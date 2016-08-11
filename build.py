#!/usr/bin/python3
#
# Build the CRS Reports Archive website by generating its static content.
#
# Assumptions:
#
# * The CRS report metadata and document files are in the 'cache/documents' and 'cache/files' directories.
#
# Output:
#
# A static website in ./build.

import sys, os.path, glob, shutil, collections, json, datetime

CACHE_DIR = "cache"
BUILD_DIR = "build"

def load_reports_metadata():
    print("Reading report metadata...")

    # Since we may have multiple metadata records per report if the metadata
    # was updated, collate them by report ID.
    reports = collections.defaultdict(lambda : [])

    # Look through all of the metadata records and combine by report.
    for fn in glob.glob(os.path.join(CACHE_DIR, "documents/*.json")):
        with open(fn) as f:
            doc = json.load(f)

        # Parse the CoverDate into a datetime instance. (TODO: Check timezone.)
        doc['CoverDate'] = datetime.datetime.strptime(doc['CoverDate'], "%Y-%m-%dT%H:%M:%S")

        # Store.
        reports[doc['PrdsProdId']].append(doc)

    # For each report, sort the metadata records in reverse-chronological order, putting
    # the most recent one first.
    for report in reports.values():
        report.sort(key = lambda record : record['CoverDate'], reverse=True)

    # Sort the reports in reverse chronological order by most recent
    # publication date (the first metadata record, since the arrays have
    # already been sorted).
    reports = list(reports.values())
    reports.sort(key = lambda records : records[0]['CoverDate'], reverse=True)

    # Transform the report metadata to our own data format, so that we have a layer
    # of abstraction between our data source and what we commit to publishing.
    reports = [transform_report_metadata(report) for report in reports]

    return reports


def transform_report_metadata(meta):
    # Converts the metadata from the format we fetched directly from CRS into
    # our public metadata format.
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
        ("updateDate", m["CoverDate"]), # most recent cover date
        ("firstFetched", meta[-1]["_fetched"]), # first date we picked up this report
        ("lastFetched", meta[0]["_fetched"]), # last date we picked up this report
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
                ("authors", [author["FirstName"] for author in mm["Authors"]]), # FirstName seems to hold the whole name
                ("topics", [[entry["PrdsCliItemId"], entry["CliTitle"]] for entry in mm["IBCList"]]),
                ("fetched", m["_fetched"]), # date we picked up this report | TODO: ChildIBCs?
            ])
            for mm in meta
        ]),
    ])


def index_by_topic(reports):
    topic_area_names = { }
    topic_area_reports = collections.defaultdict(lambda : [])
    for report in reports:
        topics = set()
        for version in report["versions"]:
            for topic_id, topic_name in version["topics"]:
                topics.add(topic_id)

                # The textual name of a topic area might change, but the ID is probably persistent.
                # Remember the most recent topic area textual name for each topic ID.
                if topic_id not in topic_area_names or topic_area_names[topic_id][0] < version["date"]:
                    topic_area_names[topic_id] = (version["date"], topic_name)

        for topic in topics:
            topic_area_reports[topic].append(report)

    return [{
               "id": topic_id,
               "title": topic_area_names[topic_id][1],
               "reports": topic_area_reports[topic_id],
           }
           for topic_id
           in sorted(topic_area_names, key = lambda topic_id : topic_area_names[topic_id][1])]


def generate_static_page(fn, context, output_fn=None):
    # Generates a static HTML page by executing the Jinja2 template.
    # Given "index.html", it writes out "build/index.html".

    # Construct the output file name.

    if output_fn is None:
        output_fn = fn
    output_fn = os.path.join(BUILD_DIR, output_fn)

    print(output_fn, "...")

    # Prepare Jinja2's environment.

    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(["templates", "pages"]))

    # Add some filters.

    def format_datetime(value):
        return value.strftime("%x")
    env.filters['date'] = format_datetime

    def commonmark(value):
        import CommonMark
        return CommonMark.commonmark(value)
    env.filters['commonmark'] = commonmark

    # Load the template.

    try:
        templ = env.get_template(fn)
    except Exception as e:
        print("Error loading template", fn)
        print(e)
        sys.exit(1)

    # Execute the template.

    try:
        html = templ.render(context)
    except Exception as e:
        print("Error rendering template", fn)
        print(e)
        sys.exit(1)

    # Write the output.

    os.makedirs(os.path.dirname(output_fn), exist_ok=True)
    with open(output_fn, "w") as f:
        f.write(html)


def generate_static_pages(context):
    # Generate a static page for every HTML file in the pages directory.
    for fn in glob.glob("pages/*.html"):
        generate_static_page(os.path.basename(fn), context)


def copy_static_assets():
    # Copy the static assets from the "static" directory to "build/static".

    print("static assets...")

    # Clear the output directory first. (copytree requires that the destination not exist)
    static_dir = os.path.join(BUILD_DIR, "static")
    if os.path.exists(static_dir):
        shutil.rmtree(static_dir)

    # "Copy" the assets. Actually just make hardlinks since we're not going to be
    # modifying the build output, and the source files are under version control anyway.
    shutil.copytree("static", static_dir, copy_function=os.link)

# MAIN

if __name__ == "__main__":
    # Load all of the report metadata.
    reports = load_reports_metadata()
    by_topic = index_by_topic(reports)

    # Generate static pages.
    generate_static_pages({
        "topics": by_topic,
    })
    for topic in by_topic:
        generate_static_page("topic.html", { "topic": topic }, output_fn="topics/%d.html" % topic["id"])

    # Copy static assets (CSS etc.).
    copy_static_assets()

