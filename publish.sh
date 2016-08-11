#!/bin/bash
source aws_credentials.txt
export AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
s3cmd sync --delete-removed -r -P build/ s3://crs-reports-website-dev-jt/

