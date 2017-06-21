#!/bin/bash
./fetch_reports_files.sh
./process_incoming.py
./assign_topics.py
./build.py
./publish.sh
./update_search_index.py
