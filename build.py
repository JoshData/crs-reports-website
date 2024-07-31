#!/usr/bin/env python3
#
# Build the CRS Reports Archive website by generating its static content.
#
# Assumptions:
#
# * The CRS report metadata and document files are in the 'processed-reports/reports' and 'processed-reports/files' directories.
#   (This JSON metadata is the transformed metadata that we published, not what we scraped from CRS.)
#
# Output:
#
# * A static website in ./build.

import sys, os, os.path, glob, shutil, collections, json, datetime, re, hashlib, csv, subprocess, html

import tqdm
import pytz

REPORTS_DIR = "processed-reports"
BUILD_DIR = "static-site"
SITE_NAME = "EveryCRSReport.com"
SITE_URL = "https://www.EveryCRSReport.com"

us_eastern_tz = pytz.timezone('America/New_York')
utc_tz = pytz.timezone("UTC")


def parse_dt(s, hasmicro=False, utc=False):
    dt = datetime.datetime.strptime(s, "%Y-%m-%d" + ("T%H:%M:%S" if "T" in s else "") + (".%f" if hasmicro else ""))
    return (utc_tz if utc else us_eastern_tz).localize(dt)

# Load config info --- some are passed into page templates.
config = { }
try:
    for line in open("credentials.txt"):
        line = line.strip().split("=", 1) + [""] # ensure at least two items
        config[line[0]] = line[1]
except IOError:
    pass

# Load the topic areas and make slugs to use for topic page file names.
topic_areas = { }
for line in open("topic_areas.txt"):
    if line.startswith("#") or line.strip() == "": continue # comment or empty line
    terms = line.strip().split("|")
    name = terms[0]
    if name.startswith("*"): name = name[1:] # strip asterisk from name
    topic_areas[name] = {
        "slug": re.sub(r"\W+", "-", name.lower()),
        "sort": 1,
    }
topic_areas["CRS Insights"] = {
    "slug": "crs-insights",
    "sort": 0,
}
topic_areas["Uncategorized"] = {
    "slug": "uncategorized",
    "sort": 0,
}

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


def get_trending_reports(reports):
    # Map IDs to records.
    reports_by_id = { report["id"]: report for report in reports } 

    # Load top accessed reports from analytics-trending.py.
    trending_reports = []
    if not os.path.exists("trending-reports.txt"): return []
    with open("trending-reports.txt") as f:
        for line in f:
            report_id = line.strip()
            if report_id in reports_by_id:
                trending_reports.append(reports_by_id[report_id])

    return trending_reports


def get_most_viewed_reports(reports):
    # Map IDs to records.
    reports_by_id = { report["id"]: report for report in reports }

    # Load top accessed reports from JSON file whose keys are dates
    # in ISO format (not important here) and whose values are stats
    # for the week ending on that date.
    if not os.path.exists("top-reports-by-week.json"): return []
    with open("top-reports-by-week.json") as f:
        most_accessed_reports = json.load(f)

    # Sort in reverse-chronological order. Keep just the values, drop
    # the keys. The values have the date range strings.
    most_accessed_reports = sorted(most_accessed_reports.items(), reverse=True)
    most_accessed_reports = [ kv[1] for kv in most_accessed_reports ]

    # Replace report IDs with their data dictionaries.
    for statsweek in most_accessed_reports:
      statsweek["reports"] = [
       (
         reports_by_id[reportrec[0]],
         reportrec[1], # pageviews
       )
       for reportrec in statsweek["reports"]
       if reportrec[0] in reports_by_id
      ]

    return most_accessed_reports


def index_by_topic(reports):
    # Apply categories to the reports.
    return [{
               "topic": topic,
               "slug": topic_areas[topic]["slug"],
               "reports": [r for r in reports
                           if topic in (r.get("topics") or ["Uncategorized"])],
           }
           for topic
           in sorted(topic_areas, key = lambda topic : (topic_areas[topic]["sort"], topic))]


def generate_static_page(fn, context, output_fn=None):
    # Generates a static HTML page by executing the Jinja2 template.
    # Given "index.html", it writes out "BUILD_DIR/index.html".

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
        import commonmark
        return commonmark.commonmark(text)
    env.filters['format_summary'] = format_summary

    def intcomma(value):
        return format(value, ",d")
    env.filters['intcomma'] = intcomma

    def as_json(value):
        # Encode for the <script type="application/ld+json"> tag
        # for Schema.org tags. Embedding JSON within HTML requires
        # escaping "</script>" if it occurs within JSON.
        import jinja2, json, markupsafe
        value = json.dumps(value, sort_keys=True)
        value = value.replace("<", r'\u003c')
        value = value.replace(">", r'\u003e') # not necessary but for good measure
        value = value.replace("&", r'\u0026') # not necessary but for good measure
        return markupsafe.Markup(value)
    env.filters['json'] = as_json

    # Load the template.

    try:
        templ = env.get_template(fn)
    except Exception as e:
        print("Error loading template", fn)
        print(e)
        sys.exit(1)

    # Add some global context variables.

    if "ALGOLIA_CLIENT_ID" in config:
        context.update({
            "ALGOLIA_CLIENT_ID": config["ALGOLIA_CLIENT_ID"],
            "ALGOLIA_SEARCH_ACCESS_KEY": config["ALGOLIA_SEARCH_ACCESS_KEY"],
            "ALGOLIA_INDEX_NAME": config["ALGOLIA_INDEX_NAME"],
        })

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
    # Copy the static assets from the "static" directory to "BUILD_DIR/static".

    #print("static assets...")

    # Clear the output directory first. (copytree requires that the destination not exist)
    static_dir = os.path.join(BUILD_DIR, "static")
    if os.path.exists(static_dir):
        shutil.rmtree(static_dir)

    # "Copy" the assets. Actually just make hardlinks since we're not going to be
    # modifying the build output, and the source files are under version control anyway.
    shutil.copytree("static", static_dir, copy_function=make_link)

    # Extract the favicon assets.
    subprocess.check_call(["unzip", "-d", BUILD_DIR, "-u", "branding/favicons.zip"])

def get_report_url_path(report, ext):
    # Sanity check that report numbers won't cause invalid file paths.
    if not re.match(r"^[0-9A-Z-]+$", report["number"]):
        raise Exception("Report has a number {} that would cause problems for our URL structure.".format(repr(report["number"])))

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
    current_hash = dict_sha1(report, [__file__, "templates/master.html", "templates/report.html", "templates/report-diff.html"])
    if os.path.exists(os.path.join(BUILD_DIR, output_fn)):
        with open(os.path.join(BUILD_DIR, output_fn)) as f:
            existing_page = f.read()
            m = re.search(r'<meta name="source-content-hash" content="(.*?)" />', existing_page)
            if not m:
                raise Exception("Generated report file doesn't match pattern.")
            existing_hash = m.group(1)
            if existing_hash == current_hash:
                return

    # For debugging, skip this report if we didn't ask for it.
    # e.g. ONLY=R41360
    if os.environ.get("ONLY") and report["number"] != os.environ.get("ONLY"):
        return

    # Construct an HTML string with source information, listing each source
    # once and in chronological order, since a report can have versions from
    # multiple sources.
    seen_sources = set()
    sources = []
    for version in report["versions"]:
        if version["source"] in seen_sources: continue
        seen_sources.add(version["source"])
        if not version.get("sourceLink"):
            sources.append(html.escape(version["source"]))
        else:
            sources.append("<a href=\"{}\">{}</a>".format(html.escape(version["sourceLink"]), html.escape(version["source"])))
    sources = ", ".join(sources)

    # Find the most recent HTML file, the most recent PDF file,
    # and load diff info between pairs of sequential versions.
    most_recent_html = None
    most_recent_pdf_fn = None
    for version in reversed(report["versions"]):
        if 'PDF' in version['formats']:
            most_recent_pdf_fn = version['formats']['PDF']['filename']
        
        if 'HTML' in version['formats']:
            fn = version['formats']['HTML']['filename']

            if most_recent_html:
                if fn == most_recent_html[1]:
                    version["hide"] = True
                    continue
                else:
                    assert most_recent_html[1].startswith("files/")
                    assert fn.startswith("files/")
                    diff_fn_base = most_recent_html[1][6:].replace(".html", "") + "__" + fn[6:]
                    diff_fn = os.path.join(REPORTS_DIR, "diffs", diff_fn_base)
                    if os.path.exists(diff_fn):
                        diff_pct_fn = diff_fn.replace(".html", "-pctchg.txt")
                        with open(diff_pct_fn) as f:
                            pct_chg = float(f.read().strip())
                        version["percent_change"] = int(round(100*pct_chg))
                        version["diff_link"] = "/changes/" + diff_fn_base

                        # Generate the diff page.
                        with open(diff_fn) as f:
                            diff_text = f.read()
                        generate_static_page("report-diff.html", {
                            "report": report,
                            "html": diff_text,
                            "version1": most_recent_html[0],
                            "version2": version,
                        }, output_fn="changes/" + diff_fn_base)

            # Keep for next iteration & for displaying most recent text.
            most_recent_html = (version, fn)

    most_recent_text = None
    try:
        with open(os.path.join(REPORTS_DIR, most_recent_html[1])) as f:
            most_recent_text = f.read()
    except (FileNotFoundError, TypeError): # TypeError is for subscripting None
        print("Missing current HTML", report["number"])

    # Some reports have summaries that are just the whole report
    # in plain text. Hide those summaries.
    summary = (report["versions"][0].get("summary") or "").strip()
    show_summary = not most_recent_text \
        or (len(summary) > 10) and (len(summary) < .25*len(most_recent_text))

    # Is there an epub?
    epub_fn = os.path.join(REPORTS_DIR, "epubs", report["number"] + ".epub")
    has_epub = False
    if os.path.exists(epub_fn):
        make_link(
            epub_fn,
            os.path.join(BUILD_DIR, get_report_url_path(report, '.epub')))
        has_epub = True

    # Generate the report HTML page.
    generate_static_page("report.html", {
        "report": report,
        "sources": sources,
        "html": most_recent_text,
        "thumbnail_url": SITE_URL + "/" + get_report_url_path(report, '.png'),
        "show_summary": show_summary,
        "topics": [topicitem for topicitem in topic_areas.items()
            if topicitem[0] in report.get("topics", [])],
        "epub_url": "/" + get_report_url_path(report, '.epub') if has_epub else None,

        # cache some information
        "source_content_hash": current_hash,
    }, output_fn=output_fn)

    # Hard link the metadata file into place. Don't save the stuff we have in
    # memory because then we have to worry about avoiding changes in field
    # order when round-tripping, the digest would change, and also hard linking
    # is cheaper.
    make_link(
        os.path.join(REPORTS_DIR, "reports/%s.json" % report["number"]),
        os.path.join(BUILD_DIR, get_report_url_path(report, '.json')))

    # Hard link the thumbnail image of the most recent PDF, if it exists, as
    # the thumbnail for the report.
    thumbnail_source_fn = None # no thumbnail available
    thumbnail_fn = os.path.join(BUILD_DIR, get_report_url_path(report, '.png'))
    if most_recent_pdf_fn:
        thumbnail_source_fn = os.path.join(REPORTS_DIR, most_recent_pdf_fn.replace(".pdf", ".png"))
        if not os.path.exists(thumbnail_source_fn):
            thumbnail_source_fn = None
    make_link(thumbnail_source_fn, thumbnail_fn)


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
    feeditems = feeditems[0:25]

    # Create a feed.
    from feedgen.feed import FeedGenerator
    feed = FeedGenerator()
    feed.id(SITE_URL)
    feed.title(SITE_NAME + ' - ' + title)
    feed.link(href=SITE_URL, rel='alternate')
    feed.link(href=SITE_URL+"/rss.xml", rel='self')
    feed.language('en')
    feed.description(description="New Congressional Research Service reports tracked by " + SITE_NAME + ".")
    for _, report_index, version_index in feeditems:
        report = reports[report_index]
        version = report["versions"][version_index]
        fe = feed.add_entry()
        fe.id(SITE_URL + "/" + get_report_url_path(report, '.html') + "/" + version["date"].isoformat().replace(":", ""))
        fe.title(version["title"][:300])
        fe.description(description=(version["summary"] or "")[:600])
        fe.link(href=SITE_URL + "/" + get_report_url_path(report, '.html'))
        fe.pubDate(version["date"])
    feed.rss_file(os.path.join(BUILD_DIR, fn))

def create_sitemap(reports):
    import xml.etree.ElementTree as ET
    root = ET.Element(
        "urlset",
        {
            "xmlns": "http://www.sitemaps.org/schemas/sitemap/0.9"
        })
    root.text = "\n  " # pretty
    node = None
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
    if node is not None: node.tail = "\n" # change the pretty whitespace of the last child

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
        w.writerow(["number", "url", "sha1", "latestPubDate", "title", "latestPDF", "latestHTML"])
        for report in reports:
            w.writerow([
                report["number"],
                get_report_url_path(report, ".json"),
                report["_hash"],
                report["versions"][0]["date"].date().isoformat(),
                report["versions"][0]["title"],
                report["versions"][0]["formats"].get("PDF", {}).get("filename", ""),
                report["versions"][0]["formats"].get("HTML", {}).get("filename", ""),
            ])

    # Read back the top lines -- we'll show the excerpt on the
    # developer docs page.
    reports_csv_excerpt = ""
    for line in open(BUILD_DIR + "/reports.csv"):
        reports_csv_excerpt += line
        if len(reports_csv_excerpt) > 512: break
    return reports_csv_excerpt

def make_link(src, dst):
    # If the destination exists (possibly a broken symlink) then delete
    # it before creating the hard link, unless it's a hard link to the
    # source already. Use l* functions so this doesn't break with broken
    # symlinks (exists and stat error out on broken symlinks).
    if os.path.lexists(dst):
        if src and os.lstat(src).st_ino == os.lstat(dst).st_ino:
            return # files are already hardlinked
        if src and os.lstat(src).st_ino == os.lstat(os.path.realpath(dst)).st_ino:
            return # files are already symlinked
        os.unlink(dst) # destination exists and is not a hardlink
    if src:
       if os.lstat(src).st_dev == os.lstat(os.path.dirname(dst)).st_dev:
           os.link(src, dst) # hardlink
       else:
           # if crossing filesystem boundaries, use symlinks:
           os.symlink(os.path.abspath(src), dst)

# MAIN


if __name__ == "__main__":
    # Load all of the report metadata.
    reports = load_all_reports()

    # Ensure the build output directory and its reports subdirectory exists.
    os.makedirs(BUILD_DIR + "/reports", exist_ok=True)

    # Generate report listing file and an excerpt of the file for the documentation page.
    reports_csv_excerpt = generate_csv_listing()

    # Generate report pages.
    for report in tqdm.tqdm(reports, desc="report pages"):
        if report["id"] in ("RL34185", "RL31484"): continue # a hard crash occurs somewhere
        generate_report_page(report)

    # Delete any generated report files for reports we are no longer publishing.
    remove_orphaned_reports(reports)

    # Generate topic pages and topic RSS feeds.
    by_topic = index_by_topic(reports)
    for group in tqdm.tqdm(by_topic, desc="topic pages"):
        generate_static_page("topic.html", group, output_fn="topics/%s.html" % group["slug"])
        create_feed(group["reports"], "New Reports in " + group["topic"], "topics/%s-rss.xml" % group["slug"])

    # Generate main pages.
    print("Static pages...")
    generate_static_pages({
        "reports_count": len(reports),
        "topics": by_topic,
        "recent_reports": reports[0:6],
        "reports_csv_excerpt": reports_csv_excerpt,
        "all_reports": reports,
        "trending_reports": get_trending_reports(reports),
        "most_viewed_reports": get_most_viewed_reports(reports),
    })

    # Copy static assets (CSS etc.).
    copy_static_assets()

    # Sym-link the reports/files directory into the build directory since we can just
    # expose these paths directly.
    if not os.path.exists(BUILD_DIR + "/files"):
        print("Creating build/files.")
        os.symlink(os.path.abspath(REPORTS_DIR) + "/files", BUILD_DIR + "/files")

    # Create the main feed.
    print("Feed and sitemap...")
    create_feed(reports, "New Reports", "rss.xml")
    create_sitemap(reports)
