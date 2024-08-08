#!/usr/bin/python3

import datetime
import json
import glob

from utils import parse_tz

# Get the first and last version date of each report.
reports = []
for fn in glob.glob("reports/reports/*.json"):
    with open(fn) as f:
        r = json.load(f)
    d1 = parse_dt(r["versions"][0]["date"])
    d2 = parse_dt(r["versions"][-1]["date"])
    reports.append((r["id"], d1, d2))

# Sort and output the longest duration reports.
reports.sort(key = lambda r : r[2]-r[1])
for r, d1, d2 in reports[0:10]:
     print(r, (d1-d2).days/365.25, "years", d2.isoformat(), d1.isoformat())

# Output a histogram of difference from first to last date.
factor = 365.25
from collections import defaultdict
histogram = defaultdict(lambda : 0)
for r, d1, d2 in reports:
    delta_days = (d1-d2).total_seconds() / (60*60*24)
    bin = int(delta_days/factor)
    histogram[bin] += 1
hist_max = max(histogram.values())
for delta_days, count in sorted(histogram.items()):
    print(str(delta_days).rjust(2), "#"*round(50*count/hist_max))
