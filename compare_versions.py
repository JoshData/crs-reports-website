#!/usr/bin/env python3

import os.path
import glob
import json
import difflib

import lxml.etree
import html5lib
import tqdm

import xml_diff

REPORTS_DIR = "reports"

# Iterate through all of the HTML files for which a
# comparison could be generated, yielding the report,
# version, file record, and previous version file
# record.
def iter_files():
    for reportfn in glob.glob(os.path.join(REPORTS_DIR, "reports", "*.json")):
        with open(reportfn) as f:
            report = json.load(f)

        prev_version = None
        for version in reversed(report["versions"]):
            for file in version["formats"]:
                if file["format"] == "HTML":
                    if prev_version is not None and file["filename"] != prev_version["filename"]:
                        yield (
                            report,
                            version,
                            file,
                            prev_version,
                        )
                    prev_version = file


def create_diff(version1, version2, output_fn):
    # Generate a HTML diff of two HTML report versions.

    def load_html(fn):
        # Open file.
        with open(fn) as f:
            doc = f.read()

        # Parse DOM. It's a fragment so we need to use parseFragment,
        # which returns a list which we re-assemble into a node.
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fragment = html5lib.parseFragment(doc, treebuilder="lxml")

        dom = lxml.etree.Element("div")
        for node in fragment:
            dom.append(node)

        ## Remove comments - xml_diff can't handle that.
        ## They seem to already be stripped by the HTML
        ## sanitization.
        # for node in dom.xpath("//comment()"):
        #    node.getparent().remove(node)

        # Take everything out of the HTML namespace so
        # that when we serialize at the end there are no
        # namespaces and it's plain HTML.
        for node in dom.xpath("//*"):
            node.tag = node.tag.replace("{http://www.w3.org/1999/xhtml}", "")

        return (doc, dom)

    version1_text, version1_dom = load_html(version1)
    version2_text, version2_dom = load_html(version2)

    # Compute diff. Each DOM is updated in place with
    # <ins>/<del> tags.
    xml_diff.compare(version1_dom, version2_dom, merge=True)

    # Serialize. If we used tostring like normal, we'd get
    # the extra <div> that we wraped the fragement in. So
    # serialize what's inside of the div and concatenate.
    #diff_html = lxml.etree.tostring(version1, encoding=str)
    diff_html = "".join(
        lxml.etree.tostring(n, encoding=str, method="html")
        if isinstance(n, lxml.etree._Element)
        else str(n)
        for n in version1_dom.xpath("node()"))

    # Also compute a percent change.
    percent_change = 1.0 - difflib.SequenceMatcher(None,
        version1_text,
        version2_text).quick_ratio()

    # Save.
    with open(output_fn, "w") as f:
        f.write(diff_html)
    with open(output_fn.replace(".html", "-pctchg.txt"), "w") as f:
        f.write(str(percent_change))


# Make a comparisons.
for report, version, file, prev_version in tqdm.tqdm(list(iter_files()), desc="diffing versions"):
    fn = file["filename"]
    prev_fn = prev_version["filename"]

    assert fn.startswith("files/")
    assert prev_fn.startswith("files/")

    if not os.path.exists(os.path.join(REPORTS_DIR, fn)) or not os.path.exists(os.path.join(REPORTS_DIR, prev_fn)):
        continue

    diff_fn = os.path.join(REPORTS_DIR, "diffs", prev_fn[6:].replace(".html", "") + "__" + fn[6:])
    if not os.path.exists(diff_fn):
        create_diff(os.path.join(REPORTS_DIR, prev_fn), os.path.join(REPORTS_DIR, fn), diff_fn)

        
