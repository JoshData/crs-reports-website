#!/bin/bash
source aws_credentials.txt
export AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY

# Don't store Unix owner/mode/time on the remote file.
# Use reduced redundancy because it's cheaper.
# Follow symbolic links,
STORAGE_ARGS="--no-preserve --reduced-redundancy -F"

# Upload changed files to S3.
s3cmd sync --delete-removed -r --guess-mime-type $STORAGE_ARGS build/ s3://$AWS_WEBSITE_S3_BUCKET/

# MIME-type guessing on the CSS file is broken, so fix the MIME type.
s3cmd put -m text/css $STORAGE_ARGS static/main.css s3://$AWS_WEBSITE_S3_BUCKET/static/main.css
