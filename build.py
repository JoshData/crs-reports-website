#!/usr/bin/python3
#
# Build the CRS Reports Archive website by generating its static content.
#
# Assumptions:
#
# * The CRS report metadata and document files are in the 'reports/reports' and 'reports/files' directories.
#   (Thie JSON metadata is the transformed metadata that we published, not what we scraped from CRS.)
#
# Output:
#
# * A static website in ./build.

import sys, os.path, glob, shutil, collections, json, datetime, re

REPORTS_DIR = "reports"
BUILD_DIR = "build"


def load_all_reports():
    # Load all of the reports into memory, because we'll have to scan them all for what topic
    # they are in.
    reports = []
    for fn in glob.glob(os.path.join(REPORTS_DIR, "reports/*.json")):
        # Parse the JSON.
        with open(fn) as f:
            report = json.load(f)

        # Do some light processing to aid templates.
        for version in report["versions"]:
            # Parse the datetimes.
            version["date"] = datetime.datetime.strptime(version["date"], "%Y-%m-%dT%H:%M:%S")
            version["fetched"] = datetime.datetime.strptime(version["fetched"], "%Y-%m-%dT%H:%M:%S.%f")

            # Sort the version files - put PDF first.
            version["formats"].sort(key = lambda fmt : fmt["format"] == "PDF", reverse=True)

        reports.append(report)

    # Sort them reverse-chronologically on the most recent publication date.
    # Other functions here depend on that.
    reports.sort(key = lambda report : report["versions"][0]["date"], reverse=True)

    return reports


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
        return value.strftime("%B %-d, %Y")
    env.filters['date'] = format_datetime

    def format_summary(text):
        # Some summaries have double-newlines that are probably paragraph breaks.
        # Others have newlines at the ends of ~60-column lines that we don't care about.
        # Finally, some summaries have single linebreaks that seem to represent paragraphs.
        # Which are we dealing with?
        def avg(items): return sum(items)/len(items)
        avg_line_length = avg([len(line) for line in text.split("\n")+[""]])
        if avg_line_length > 100:
            # Seems like newlines probably indicate paragraphs. Double them up so that we
            # can pass the rest through a renderer.
            text = text.replace("\n", "\n\n")
        # Turn the text into HTML. This is a fast way to do it that might work nicely.
        import CommonMark
        return CommonMark.commonmark(text)
    env.filters['format_summary'] = format_summary

    def intcomma(value):
        return format(value, ",d")
    env.filters['intcomma'] = intcomma

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


def generate_report_page(report):
    # Sanity check that report numbers won't cause invalid file paths.
    if not re.match(r"^[0-9A-Z-]+$", report["number"]):
        raise Exception("Report has a number that would cause problems for our URL structure.")

    # Find the most recent HTML text and also compute the differences between the
    # HTML versions.
    most_recent_text = None
    for version in reversed(report["versions"]):
        for format in version['formats']:
            if format['format'] != 'HTML': continue
            try:
                with open(os.path.join("reports/files", format['filename'][6:])) as f:
                    html = f.read()
            except FileNotFoundError:
                html = None

            if html and most_recent_text:
                # Can do a comparison.
                import difflib
                version["percent_change"] = int(round(100*(1-difflib.SequenceMatcher(None, most_recent_text, html).quick_ratio())))

            # Keep for next iteration & for displaying most recent text.
            most_recent_text = html

            break # don't process other formats

    # Generate the report HTML page.
    generate_static_page("report.html", {
        "report": report,
        "html": most_recent_text,
    }, output_fn="reports/%s.html" % report["number"])

    # Hard link the metadata file into place. Don't save the stuff we have in
    # memory because then we have to worry about avoiding changes in field
    # order when round-tripping, and also hard linking is cheaper.
    if not os.path.exists(BUILD_DIR + "/reports/%s.json" % report["number"]):
        os.link("reports/reports/%s.json" % report["number"],
                BUILD_DIR + "/reports/%s.json" % report["number"])

    # Copy the actual document files into build output.
    for version in report['versions']:
       for format in version['formats']:
           pass


# MAIN


if __name__ == "__main__":
    # Load all of the report metadata.
    reports = load_all_reports()
    by_topic = index_by_topic(reports)

    # Generate static pages.
    generate_static_pages({
        "reports_count": len(reports),
        "first_report_date": reports[-1]['versions'][-1]['date'],
        "last_report_date": reports[0]['versions'][0]['date'],
        "topics": by_topic,
        "recent_reports": reports[0:20],
    })
    for topic in by_topic:
        if os.environ.get("ONLY"): continue # for debugging
        generate_static_page("topic.html", { "topic": topic }, output_fn="topics/%d.html" % topic["id"])

    # Copy static assets (CSS etc.).
    copy_static_assets()

    # Generate report pages.
    for report in reports:
        # For debugging, skip this report if we didn't ask for it.
        # e.g. ONLY=R41360
        if os.environ.get("ONLY") and report["number"] != os.environ.get("ONLY"):
            continue

        generate_report_page(report)

    # Hard-link the reports/files directory into the build directory.
    if not os.path.exists("build/files"):
        os.symlink("../reports/files", "build/files")


