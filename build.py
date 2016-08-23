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

import sys, os, os.path, glob, shutil, collections, json, datetime, re, hashlib

import tqdm
import pytz

REPORTS_DIR = "reports"
BUILD_DIR = "build"
CACHE_DIR = "cache"
SITE_NAME = "EveryCRSReport.com"
SITE_URL = "https://EveryCRSReport.com"

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
        with open(fn) as f:
            report = json.load(f)

        # Do some light processing to aid templates.
        for version in report["versions"]:
            # Parse the datetimes.
            version["date"] = parse_dt(version["date"])
            version["fetched"] = parse_dt(version["fetched"], hasmicro=True, utc=True)

            # Sort the version files - put PDF first.
            version["formats"].sort(key = lambda fmt : fmt["format"] == "PDF", reverse=True)

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
    os.system("unzip -d %s -u branding/favicons.zip" % BUILD_DIR)

def get_report_url_path(report, ext):
    return "reports/%s%s" % (report["number"], ext)


def dict_sha1(report):
    hasher = hashlib.sha1()
    hasher.update(json.dumps(report, sort_keys=True, default=str).encode("ascii"))
    return hasher.hexdigest()

def generate_report_page(report):
    # Sanity check that report numbers won't cause invalid file paths.
    if not re.match(r"^[0-9A-Z-]+$", report["number"]):
        raise Exception("Report has a number that would cause problems for our URL structure.")

    # No need to process this report if it hasn't changed. But we need the
    # cached topics. Never skip if given in the ONLY environment variable.
    current_hash = dict_sha1(report)
    hash_fn = os.path.join(CACHE_DIR, report["number"] + ".hash")
    try:
        with open(hash_fn) as f:
            cache = json.load(f)
            if cache["hash"] == current_hash \
               and (not os.environ.get("ONLY") or report["number"] != os.environ.get("ONLY")):
                report["topics"] = [t for t in topic_areas if t["slug"] in cache["topics"]]
                return
    except (IOError, ValueError):
        pass

    # For debugging, skip this report if we didn't ask for it.
    # e.g. ONLY=R41360
    if os.environ.get("ONLY") and report["number"] != os.environ.get("ONLY"):
        return

    # Find the most recent HTML text, compute the differences between the
    # HTML versions, and find the most recent PDF filename.
    most_recent_text = None
    most_recent_pdf_fn = None
    for version in reversed(report["versions"]):
        for format in version['formats']:
            if format['format'] == "PDF":
                most_recent_pdf_fn = format['filename']

            if format['format'] != 'HTML': continue
            try:
                with open(os.path.join("reports/files", format['filename'][6:])) as f:
                    html = f.read()
            except FileNotFoundError:
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

            break # don't process other formats

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
        "thumbnail_url": SITE_URL + "/" + get_report_url_path(report, '.png')
    }, output_fn=get_report_url_path(report, '.html'))

    # Hard link the metadata file into place. Don't save the stuff we have in
    # memory because then we have to worry about avoiding changes in field
    # order when round-tripping, and also hard linking is cheaper.
    json_fn = os.path.join(BUILD_DIR, get_report_url_path(report, '.json'))
    if not os.path.exists(json_fn):
        os.link(os.path.join(REPORTS_DIR, "reports/%s.json" % report["number"]),
                json_fn)

    # Generate thumbnail image, if a PDF exists.
    if most_recent_pdf_fn and not os.environ.get("FAST"):
        os.system("pdftoppm -png -singlefile -scale-to-x 600 -scale-to-y -1 %s %s" % (
            os.path.join(REPORTS_DIR, most_recent_pdf_fn),
            os.path.join(BUILD_DIR, get_report_url_path(report, '')) # pdftoppm adds ".png"
        ))

    # Save current metadata hash so we know this file has been processed.
    # Also save the topics, since they're dynamically computed and we
    # need them later to generate the topic pages.
    if not os.path.exists(CACHE_DIR): os.mkdir(CACHE_DIR)
    with open(hash_fn, "w") as f:
        json.dump({ "hash": current_hash, "topics": [t["slug"] for t in report.get("topics",[])] }, f)

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


# MAIN


if __name__ == "__main__":
    # Load all of the report metadata.
    reports = load_all_reports()

    # Generate report pages.
    for report in tqdm.tqdm(reports, desc="report pages"):
        generate_report_page(report)

    # Generate topic pages and topic RSS feeds.
    by_topic = index_by_topic(reports)
    for group in tqdm.tqdm(by_topic, desc="topic pages"):
        generate_static_page("topic.html", group, output_fn="topics/%s.html" % group["topic"]["slug"])
        create_feed(group["reports"], "New Reports in " + group["topic"]["name"], "topics/%s-rss.xml" % group["topic"]["slug"])

    # Generate main pages.
    print("Static pages...")
    generate_static_pages({
        "reports_count": len(reports),
        "first_report_date": reports[-1]['versions'][-1]['date'],
        "last_report_date": reports[0]['versions'][0]['date'],
        "topics": by_topic,
        "recent_reports": reports[0:6],
    })

    # Copy static assets (CSS etc.).
    copy_static_assets()

    # Hard-link the reports/files directory into the build directory.
    if not os.path.exists("build/files"):
        print("Creating build/files.")
        os.symlink("../reports/files", "build/files")

    # Create the main feed.
    create_feed(reports, "New Reports", "rss.xml")
