#!/usr/bin/env python3
#
# Build the CRS Reports Archive website by generating its static content.
#
# Assumptions:
#
# * The CRS report metadata and document files are in the 'reports/reports' and 'reports/files' directories.
#   (This JSON metadata is the transformed metadata that we published, not what we scraped from CRS.)
#
# Output:
#
# * A static website in ./build.

import sys, os, os.path, glob, shutil, collections, json, datetime, re, hashlib, csv, subprocess

import tqdm
import pytz

REPORTS_DIR = "reports"
BUILD_DIR = "build"
CACHE_DIR = "cache"
SITE_NAME = "EveryCRSReport.com"
SITE_URL = "https://www.EveryCRSReport.com"

us_eastern_tz = pytz.timezone('America/New_York')
utc_tz = pytz.timezone("UTC")


def parse_dt(s, hasmicro=False, utc=False):
    dt = datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S" + (".%f" if hasmicro else ""))
    return (utc_tz if utc else us_eastern_tz).localize(dt)


# Load the categories.
topic_areas = []
for line in open("topic_areas.txt"):
    if line.startswith("#") or line.strip() == "": continue # comment or empty line
    terms = line.strip().split("|")
    name = terms[0]
    if name.startswith("*"): name = name[1:]
    topic_areas.append({
        "name": name,
        "terms": set(terms),
        "slug": re.sub(r"\W+", "-", name.lower()),
        "sort": 1,
    })
topic_areas.append({
    "name": "Uncategorized",
    "terms": set(),
    "slug": "uncategorized",
    "sort": 0,
})

def load_all_reports():
    # Load all of the reports into memory, because we'll have to scan them all for what topic
    # they are in.
    reports = []
    for fn in glob.glob(os.path.join(REPORTS_DIR, "reports/*.json")):
        # Parse the JSON.
        with open(fn, 'rb') as f:
            # compute a hash of the raw file content
            f_content = f.read()
            hasher = hashlib.sha1()
            hasher.update(f_content)
            digest = hasher.hexdigest()

            # parse the JSON
            report = json.loads(f_content.decode("utf8"))

        # Remember the hash.
        report["_hash"] = digest

        # Do some light processing to aid templates.
        for version in report["versions"]:
            # Parse the datetimes.
            version["date"] = parse_dt(version["date"])
            #version["fetched"] = parse_dt(version["fetched"], hasmicro=True, utc=True)

            # Turn the formats array into a dictionary mapping the format
            # type (PDF, HTML) to the format dict.
            version["formats"] = { f["format"]: f for f in version["formats"] }

        reports.append(report)

    # Sort them reverse-chronologically on the most recent publication date.
    # Other functions here depend on that.
    reports.sort(key = lambda report : report["versions"][0]["date"], reverse=True)

    return reports


def index_by_topic(reports):
    # Apply categories to the reports.
    return [{
               "topic": topic,
               "reports": [r for r in reports if topic["slug"] in set(t["slug"] for t in r.get("topics") or [{"slug": "uncategorized"}])],
           }
           for topic
           in sorted(topic_areas, key = lambda topic : (topic["sort"], topic["name"]))]


def generate_static_page(fn, context, output_fn=None):
    # Generates a static HTML page by executing the Jinja2 template.
    # Given "index.html", it writes out "build/index.html".

    # Construct the output file name.

    if output_fn is None:
        output_fn = fn
    output_fn = os.path.join(BUILD_DIR, output_fn)

    #print(output_fn, "...")

    # Prepare Jinja2's environment.

    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(["templates", "pages"]))

    # Add some filters.

    env.filters['date'] = lambda value : value.strftime("%B %-d, %Y")
    env.filters['date_short'] = lambda value : value.strftime("%b. %-d, %Y")

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

    def as_json(value):
        import jinja2
        return jinja2.Markup(json.dumps(value))
    env.filters['json'] = as_json

    # Load the template.

    try:
        templ = env.get_template(fn)
    except Exception as e:
        print("Error loading template", fn)
        print(e)
        #sys.exit(1)

    # Execute the template.

    try:
        html = templ.render(context)
    except Exception as e:
        print("Error rendering template", fn)
        print(e)
        return
        #sys.exit(1)

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

    #print("static assets...")

    # Clear the output directory first. (copytree requires that the destination not exist)
    static_dir = os.path.join(BUILD_DIR, "static")
    if os.path.exists(static_dir):
        shutil.rmtree(static_dir)

    # "Copy" the assets. Actually just make hardlinks since we're not going to be
    # modifying the build output, and the source files are under version control anyway.
    shutil.copytree("static", static_dir, copy_function=os.link)

    # Extract the favicon assets.
    subprocess.check_call(["unzip", "-d", BUILD_DIR, "-u", "branding/favicons.zip"])

def get_report_url_path(report, ext):
    # Sanity check that report numbers won't cause invalid file paths.
    if not re.match(r"^[0-9A-Z-]+$", report["number"]):
        raise Exception("Report has a number that would cause problems for our URL structure.")

    # Construct a URL path.
    return "reports/%s%s" % (report["number"], ext)

def dict_sha1(report, dependency_files):
    hasher = hashlib.sha1()
    hasher.update(json.dumps(report, sort_keys=True, default=str).encode("ascii"))
    for fn in dependency_files:
        with open(fn, "rb") as f:
            hasher.update(f.read())
    return hasher.hexdigest()

def generate_report_page(report):
    output_fn = get_report_url_path(report, '.html')

    # Regenerating a report page is a bit expensive so we'll skip it if a
    # generated file already exists and is up to date.
    current_hash = dict_sha1(report, [__file__, "templates/master.html", "templates/report.html"])
    if os.path.exists(os.path.join(BUILD_DIR, output_fn)):
        with open(os.path.join(BUILD_DIR, output_fn)) as f:
            existing_page = f.read()
            m = re.search(r'<meta name="topics" content="(.*)" />\s+<meta name="source-content-hash" content="(.*)" />', existing_page)
            if not m:
                raise Exception("Generated report file doesn't match pattern.")
            topics = m.group(1).split(",")
            existing_hash = m.group(2)
            if existing_hash == current_hash:
                report["topics"] = [t for t in topic_areas if t["slug"] in topics]
                return

    # For debugging, skip this report if we didn't ask for it.
    # e.g. ONLY=R41360
    if os.environ.get("ONLY") and report["number"] != os.environ.get("ONLY"):
        return

    # Find the most recent HTML text, compute the differences between the
    # HTML versions, and find the most recent PDF filename.
    most_recent_text = None
    most_recent_pdf_fn = None
    for version in reversed(report["versions"]):
        if 'PDF' in version['formats']:
            most_recent_pdf_fn = version['formats']['PDF']['filename']
        
        if 'HTML' in version['formats']:
            try:
                with open(os.path.join(REPORTS_DIR, version['formats']['HTML']['filename'])) as f:
                    html = f.read()
            except FileNotFoundError:
                print("Missing HTML", report["number"], version["date"])
                html = None

            if html and most_recent_text and not os.environ.get("FAST"):
                # Can do a comparison.
                if html == most_recent_text:
                    version["percent_change"] = "no-change"
                else:
                    import difflib
                    version["percent_change"] = int(round(100*(1-difflib.SequenceMatcher(None, most_recent_text, html).quick_ratio())))

            # Keep for next iteration & for displaying most recent text.
            most_recent_text = html

    # Assign topic areas.
    topics = []
    for topic in topic_areas:
        for term in topic["terms"]:
            if term.startswith("*"):
                # search title only
                term = term[1:]
                if term.lower() in report["versions"][0]["title"].lower() or term.lower() in report["versions"][0]["summary"].lower():
                    topics.append(topic)
                    break # only add topic once
            elif most_recent_text and term in most_recent_text:
                topics.append(topic)
                break # only add topic once
            elif term in report["versions"][0]["title"] or term in report["versions"][0]["summary"]:
                # if no text is available, fall back to title and summary
                topics.append(topic)
                break # only add topic once
    report["topics"] = sorted(topics, key = lambda topic : topic["name"])

    # Generate the report HTML page.
    generate_static_page("report.html", {
        "report": report,
        "html": most_recent_text,
        "thumbnail_url": SITE_URL + "/" + get_report_url_path(report, '.png'),

        # cache some information
        "source_content_hash": current_hash,
        "topics": ",".join([t["slug"] for t in report.get("topics",[])]),

    }, output_fn=output_fn)

    # Hard link the metadata file into place. Don't save the stuff we have in
    # memory because then we have to worry about avoiding changes in field
    # order when round-tripping, the digest would change, and also hard linking
    # is cheaper.
    json_fn = os.path.join(BUILD_DIR, get_report_url_path(report, '.json'))
    if not os.path.exists(json_fn):
        os.link(os.path.join(REPORTS_DIR, "reports/%s.json" % report["number"]), json_fn)

    # Hard link the thumbnail image of the most recent PDF, if it exists, as
    # the thumbnail for the report.
    if most_recent_pdf_fn:
        thumbnail_source_fn = os.path.join(REPORTS_DIR, most_recent_pdf_fn.replace(".pdf", ".png"))
        thumbnail_fn = os.path.join(BUILD_DIR, get_report_url_path(report, '.png'))
        if os.path.exists(thumbnail_source_fn) and not os.path.exists(thumbnail_fn):
            os.link(thumbnail_source_fn, thumbnail_fn)


def remove_orphaned_reports(reports):
    # Delete any report HTML, JSON, and thumbnail files for reports that no longer exist.

    # Build a dictionary of all expected report paths, minus file extension.
    all_reports = set(get_report_url_path(report, '') for report in reports)

    # Scan existing files.
    for fn in glob.glob(os.path.join(BUILD_DIR, 'reports', '*')):
        basename = os.path.splitext(fn)[0][len(BUILD_DIR)+1:]
        if basename not in all_reports:
            print("deleting", fn)
            os.unlink(fn)



def create_feed(reports, title, fn):
    # The feed is a notice of new (versions of) reports, so collect the
    # most recent report-versions.
    feeditems = []
    for i, report in enumerate(reports):
        for j, version in enumerate(report['versions']):
            feeditems.append((version['date'], i, j))
    feeditems.sort(reverse=True)
    feeditems = feeditems[0:75]

    # Create a feed.
    from feedgen.feed import FeedGenerator
    feed = FeedGenerator()
    feed.id(SITE_URL)
    feed.title(SITE_NAME + ' - ' + title)
    feed.link(href=SITE_URL, rel='alternate')
    feed.language('en')
    feed.description(description="New Congressional Research Service reports tracked by " + SITE_NAME + ".")
    for _, report_index, version_index in feeditems:
        report = reports[report_index]
        version = report["versions"][version_index]
        fe = feed.add_entry()
        fe.id(SITE_URL + "/" + get_report_url_path(report, '.html'))
        fe.title(version["title"])
        fe.description(description=version["summary"])
        fe.link(href=SITE_URL + "/" + get_report_url_path(report, '.html'))
        fe.pubdate(version["date"])
    feed.rss_file(os.path.join(BUILD_DIR, fn))

def create_sitemap(reports):
    import xml.etree.ElementTree as ET
    root = ET.Element(
        "urlset",
        {
            "xmlns": "http://www.sitemaps.org/schemas/sitemap/0.9"
        })
    root.text = "\n  " # pretty
    for report in reports:
        node = ET.SubElement(root, "url")
        node.text = "\n    " # pretty
        node.tail = "\n  " # pretty

        n = ET.SubElement(node, "loc")
        n.text = SITE_URL + "/" + get_report_url_path(report, '.html')
        n.tail = "\n    " # pretty

        n = ET.SubElement(node, "lastmod")
        n.text = report["versions"][0]["date"].date().isoformat()
        n.tail = "\n  " # pretty
    node.tail = "\n" # change the pretty whitespace of the last child

    # Serialize
    xml = ET.tostring(root, encoding='utf8')

    # check this is a valid sitemap
    assert len(reports) <= 50000
    assert len(xml) <= 10485760

    with open(os.path.join(BUILD_DIR, "sitemap.xml"), "wb") as f:
        f.write(xml)

def generate_csv_listing():
    # Generate a CSV listing of all of the reports.
    with open(os.path.join(BUILD_DIR, "reports.csv"), "w") as f:
        w = csv.writer(f)
        w.writerow(["number", "url", "sha1", "latestPubDate", "latestPDF", "latestHTML"])
        for report in reports:
            w.writerow([
                report["number"],
                get_report_url_path(report, ".json"),
                report["_hash"],
                report["versions"][0]["date"].date().isoformat(),
                report["versions"][0]["formats"].get("PDF", {}).get("filename", ""),
                report["versions"][0]["formats"].get("HTML", {}).get("filename", ""),
            ])

    # Read back the top lines -- we'll show the excerpt on the
    # developer docs page.
    reports_csv_excerpt = ""
    for line in open("build/reports.csv"):
        reports_csv_excerpt += line
        if len(reports_csv_excerpt) > 512: break
    return reports_csv_excerpt

# MAIN


if __name__ == "__main__":
    # Load all of the report metadata.
    reports = load_all_reports()

    # Ensure the build output directory exists.
    os.makedirs(BUILD_DIR, exist_ok=True)

    # Generate report listing file and an excerpt of the file for the documentation page.
    reports_csv_excerpt = generate_csv_listing()

    # Generate report pages.
    for report in tqdm.tqdm(reports, desc="report pages"):
        generate_report_page(report)

    # Delete any generated report files for reports we are no longer publishing.
    remove_orphaned_reports(reports)

    # Generate topic pages and topic RSS feeds.
    by_topic = index_by_topic(reports)
    for group in tqdm.tqdm(by_topic, desc="topic pages"):
        generate_static_page("topic.html", group, output_fn="topics/%s.html" % group["topic"]["slug"])
        create_feed(group["reports"], "New Reports in " + group["topic"]["name"], "topics/%s-rss.xml" % group["topic"]["slug"])

    # Generate main pages.
    print("Static pages...")
    generate_static_pages({
        "reports_count": len(reports),
        "topics": by_topic,
        "recent_reports": reports[0:6],
        "reports_csv_excerpt": reports_csv_excerpt,
        "all_reports": reports,
    })

    # Copy static assets (CSS etc.).
    copy_static_assets()

    # Sym-link the reports/files directory into the build directory since we can just
    # expose these paths directly.
    if not os.path.exists("build/files"):
        print("Creating build/files.")
        os.symlink("../reports/files", "build/files")

    # Create the main feed.
    print("Feed and sitemap...")
    create_feed(reports, "New Reports", "rss.xml")
    create_sitemap(reports)
