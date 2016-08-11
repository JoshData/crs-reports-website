#1/bin/sh
source aws_credentials.txt
s3cmd sync -s --no-preserve s3://crs-reports-201603/ cache/
