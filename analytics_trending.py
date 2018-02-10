#!/usr/bin/env python3

# Query the Google Analytics API to get the top accessed
# reports by week.

from datetime import datetime, timedelta
import json
import os.path

from apiclient.discovery import build
from oauth2client.service_account import ServiceAccountCredentials


SCOPES = ['https://www.googleapis.com/auth/analytics.readonly']
KEY_FILE_LOCATION = 'credentials.google_service_account.json'
VIEW_ID = '130670929'


def get_top_reports(date_range_start, date_range_end, analytics):
  # Run query. Get top pageViews in the given date range (inclusive).
  # Only look at pages that have two 'levels' (i.e. /xxx/yyy),
  # since report pages always have two levels, and query for the values
  # of those two levels.
  response = analytics.reports().batchGet(
      body={
        'reportRequests': [
        {
          'viewId': VIEW_ID,
          'dateRanges': [{'startDate': date_range_start.isoformat(), 'endDate': date_range_end.isoformat()}],
          'metrics': [{'expression': 'ga:pageviews'}],
          'dimensions': [{'name': 'ga:pagePathLevel1'}, {'name': 'ga:pagePathLevel2' }],
          'orderBys': [{'fieldName': 'ga:pageViews', "sortOrder": "DESCENDING"}],
        }]
      }
    ).execute()

  # Go to the pageviews report.
  pageviews = response['reports'][0]['data']['rows']

  # Transform the list to tuples of report ID and pageviews
  # (still in descending order, per the query above).
  pageviews = [
    (
      r["dimensions"][1].lstrip("/").replace(".html", ""),
      int(r["metrics"][0]["values"][0])
    )
    for r in pageviews
    if r["dimensions"][0] == "/reports/"
  ]

  # Return the top 20.
  return pageviews[:20]


def main():
  # Load credentials and create API client.
  credentials = ServiceAccountCredentials.from_json_keyfile_name(
      KEY_FILE_LOCATION, SCOPES)
  analytics = build('analyticsreporting', 'v4', credentials=credentials)

  # Write out trending reports - top reports in the last week.
  print("Fetching top reports from Google Analytics in the last week.")
  trending_reports = get_top_reports(datetime.now().date() - timedelta(days=6), datetime.now().date(), analytics)
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
        "reports": get_top_reports(date_range_start, date_range_end, analytics)
      }
    date_range_end -= timedelta(days=7)

  # Write out.
  with open("top-reports-by-week.json", "w") as f:
    json.dump(top_reports_by_week, f, sort_keys=True, indent=2)

if __name__ == '__main__':
  main()

