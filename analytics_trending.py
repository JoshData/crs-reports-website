#!/usr/bin/env python3

from apiclient.discovery import build
from oauth2client.service_account import ServiceAccountCredentials


SCOPES = ['https://www.googleapis.com/auth/analytics.readonly']
KEY_FILE_LOCATION = 'credentials.google_service_account.json'
VIEW_ID = '130670929'


def get_report(analytics):
  """Queries the Analytics Reporting API V4.

  Args:
    analytics: An authorized Analytics Reporting API V4 service object.
  Returns:
    The Analytics Reporting API V4 response.
  """

def main():
  # Load credentials and create API client.
  credentials = ServiceAccountCredentials.from_json_keyfile_name(
      KEY_FILE_LOCATION, SCOPES)
  analytics = build('analyticsreporting', 'v4', credentials=credentials)

  # Run query. Get top pageViews in the last week for pages that
  # have two 'levels' (i.e. /xxx/yyy), and query for those two levels.
  response = analytics.reports().batchGet(
      body={
        'reportRequests': [
        {
          'viewId': VIEW_ID,
          'dateRanges': [{'startDate': '7daysAgo', 'endDate': 'today'}],
          'metrics': [{'expression': 'ga:pageviews'}],
          'dimensions': [{'name': 'ga:pagePathLevel1'}, {'name': 'ga:pagePathLevel2' }],
          'orderBys': [{'fieldName': 'ga:pageViews', "sortOrder": "DESCENDING"}],
        }]
      }
    ).execute()

  # Map report IDs to pageviews.
  data = { }
  for r in response['reports'][0]['data']['rows']:
    if r["dimensions"][0] == "/reports/":
      report_id = r["dimensions"][1].lstrip("/").replace(".html", "")
      pageviews = int(r["metrics"][0]["values"][0])
      data[report_id] = pageviews

  # Write out top 100.
  sorted_top_reports = sorted(data.items(), key = lambda kv : -kv[1])
  with open("trending-reports.txt", "w") as f:
    for report_id, pageviews in sorted_top_reports[:20]:
      f.write(report_id + "\n")

if __name__ == '__main__':
  main()

