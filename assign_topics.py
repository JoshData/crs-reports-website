#!/usr/bin/env python3
#
# Assign topic areas to CRS reports. The topic areas that come from the CRS.gov
# raw data aren't very good, so we make our own using simple text matching.
# CRS reports start with author information, and under each author is usually
# their area of expertise. Those areas make for good topics.
#
# We've manually collected those text strings into topic_areas.txt. Each line
# is a topic area, defined by a pipe-delimited list of strings to do text
# matching on. The first string is used as the topic name for display.
# Asterisks at the start of a string indicates we should only search the
# title and summary of the report and not its full text.
#
# Assumptions:
#
# * The CRS report metadata and document files are in the 'reports/reports'
#   and 'reports/files' directories.
# * topic_areas.txt has our pre-set topic areas.
#
# Output:
#
# * The CRS report metadata JSON files are updated in-place.

from collections import OrderedDict
import glob
import json
import os.path

import tqdm

def load_topic_areas():
    # Load topic areas as a mapping from the display name to
    # the text matching terms.
    topic_areas = { }
    for line in open("topic_areas.txt"):
        if line.startswith("#") or line.strip() == "": continue # comment or empty line
        terms = line.strip().split("|")
        name = terms[0]
        if name.startswith("*"): name = name[1:] # strip asterisk from topic name if in first term
        topic_areas[name] = terms
    return topic_areas

def assign_topics(topic_areas):
    for reportfn in tqdm.tqdm(glob.glob("reports/reports/*.json"), "assigning topics"):
        assign_topics_to(reportfn, topic_areas)

def assign_topics_to(reportfn, topic_areas):
    # Load the report JSON data.
    with open(reportfn) as f:
        report = json.load(f, object_pairs_hook=OrderedDict)

    # Find the most recent HTML text that we'll perform text matching on.
    most_recent_text_fn = None
    most_recent_text = None
    for version in reversed(report["versions"]):
        for versionformat in version["formats"]:
            if versionformat["format"] == "HTML":
                most_recent_text_fn = os.path.join("reports", versionformat['filename'])
    if most_recent_text_fn:
        try:
            with open(most_recent_text_fn) as f:
                most_recent_text = f.read()
        except FileNotFoundError:
            print("Missing HTML", report["number"], version["date"])

    # Assign topic areas.
    topics = []
    for topic, terms in topic_areas.items():
        # For each string term to search for...
        for term in terms:
            if term.startswith("*"):
                # search title only
                term = term[1:] # strip asterisk
                if term.lower() in report["versions"][0]["title"].lower() or term.lower() in (report["versions"][0].get("summary") or "").lower():
                    topics.append(topic)
                    break # only add topic once
            elif most_recent_text and term in most_recent_text:
                topics.append(topic)
                break # only add topic once
            elif term in report["versions"][0]["title"] or term in (report["versions"][0].get("summary") or ""):
                # if no text is available, fall back to title and summary
                topics.append(topic)
                break # only add topic once
        
    # Add the special crs-insights topic to insights documents.
    if report["typeId"] == "INSIGHTS":
        topics.append("CRS Insights")

    # Set.
    topics.sort()

    # Save.
    if report.get("topics") != topics:
        report["topics"] = topics
        with open(reportfn, "w") as f:
            f.write(json.dumps(report, indent=2))

if __name__ == "__main__":
    topic_areas = load_topic_areas()
    assign_topics(topic_areas)
