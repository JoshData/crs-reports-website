#!/usr/bin/env python3

# Query the Google Analytics API to get the top accessed
# reports by week.

from datetime import datetime, timedelta
import json
import os.path
import re

from google.oauth2 import service_account
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Metric, Dimension


KEY_FILE_LOCATION = 'secrets/credentials.google_service_account.json'
PROPERTY_ID = '383598924'


def get_top_reports(date_range_start, date_range_end, client):
  # Run query. Get top pageViews in the given date range (inclusive).
  request = RunReportRequest(
    property = f"properties/{PROPERTY_ID}",
    date_ranges = [DateRange(start_date=date_range_start.isoformat(), end_date=date_range_end.isoformat())],
    metrics = [Metric(name="eventCount")],
    dimensions = [Dimension(name='pagePath')],
  )
  response = client.run_report(request)

  # Return report ID, page view count tuples.
  for r in response.rows:
    pagePath = r.dimension_values[0].value
    eventCount = int(r.metric_values[0].value)

    # Extract report ID from pagePath.
    if m := re.match(r"/reports/(\w+)\.html", pagePath):
      yield (m.group(1), eventCount)

def main():
  # Create API client object.
  credentials = service_account.Credentials.from_service_account_file(KEY_FILE_LOCATION)
  client = BetaAnalyticsDataClient(credentials=credentials)

  # Write out trending reports - top reports in the last week.
  print("Fetching top reports from Google Analytics in the last week.")
  trending_reports = list(get_top_reports(datetime.now().date() - timedelta(days=6), datetime.now().date(), client))[0:20]
  with open("trending-reports.txt", "w") as f:
    for report_id, pageviews in trending_reports:
      f.write(report_id + "\n")

  # Get the most recent completed Sunday as a stable end point for
  # the week-by-week queries going back as far as we have had users.
  # If "top-reports-by-week.json" exists, just add new weeks to it
  # when needed.
  top_reports_by_week = { }
  if os.path.exists("top-reports-by-week.json"):
    with open("top-reports-by-week.json") as f:
      top_reports_by_week = json.load(f)
  now = datetime.now().date()
  date_range_end = now - timedelta(days=now.isoweekday())
  def strftime(t):
    return t.strftime("%A, %B %d, %Y").replace(" 0", " ")
  while date_range_end > datetime(2016, 11, 7).date():
    if date_range_end.isoformat() not in top_reports_by_week:
      print("Fetching top reports for week ending", strftime(date_range_end))
      date_range_start = date_range_end - timedelta(days=6)
      top_reports_by_week[date_range_end.isoformat()] = {
        "date_start": strftime(date_range_start),
        "date_end": strftime(date_range_end),
        "reports": list(get_top_reports(date_range_start, date_range_end, client))[0:20]
      }
    date_range_end -= timedelta(days=7)

  # Write out.
  with open("top-reports-by-week.json", "w") as f:
    json.dump(top_reports_by_week, f, sort_keys=True, indent=2)

if __name__ == '__main__':
  main()

