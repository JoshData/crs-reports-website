#!/bin/bash
source venv/bin/activate
./scrape_crs_website.py
./process_incoming.py
./assign_topics.py
./compare_versions.py
./make_epubs.py
./analytics_trending.py
./build.py
./update_search_index.py
