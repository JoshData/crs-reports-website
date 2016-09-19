#!/bin/bash
./fetch_reports_files.sh
./process_incoming.py
./build.py
./publish.sh

