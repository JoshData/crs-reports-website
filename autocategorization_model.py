#!/usr/bin/python3
#
# Automatic category classification of CRS Reports.

import os
import glob
import json
import random
import re

import lxml.etree
import tqdm

REPORTS_DIR = "reports"

def sample(x):
    import random
    return random.sample(x, 1000)

# Load the categories.
topics = { }
term_topics = { }
for line in open("author_specializations.txt"):
    terms = line.strip().split("|")
    if terms == [""]: continue
    topics[terms[0]] = set(terms)
    for term in terms: term_topics[term] = terms[0]

# Create a categorization model.
train = []
for fn in tqdm.tqdm(sample(glob.glob(os.path.join(REPORTS_DIR, "reports/*.json"))), desc="loading training data"):
    # Parse the JSON.
    with open(fn) as f:
        report = json.load(f)

    # Load the report as plain text by converting from the HTML content of most recent
    # version of the report.
    text = None
    for format in report["versions"][0]["formats"]:
        if format["format"] != "HTML": continue
        text_fn = os.path.join(REPORTS_DIR, format["filename"])
        if not os.path.exists(text_fn): continue # conversion issue in process_incoming.py
        with open(text_fn) as f:
            text = f.read()
    if text is None: continue # no data

    for term in term_topics:
        if term in text:
            train.append([text, term_topics[term]])
            break

print(len(train), "training documents")
print(len(set(x[1] for x in train)), "categories")

print("Creating the model...")
from textblob.classifiers import NaiveBayesClassifier as Classifier
for row in train:
    bag_of_words = re.split(r"\W+", row[0])
    if len(bag_of_words) > 5000: bag_of_words = random.sample(bag_of_words, 5000)
    row[0] = " ".join(bag_of_words)
cl = Classifier(train)

print("Saving model...")
import pickle
pickle.dump(cl, open("autocategorization.model", "wb" ))
