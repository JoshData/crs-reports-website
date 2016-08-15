#!/bin/bash
source aws_credentials.txt
export AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY

# Upload to S3.
s3cmd sync --delete-removed -r -P --guess-mime-type -F --reduced-redundancy build/ s3://$AWS_WEBSITE_S3_BUCKET/

# MIME-type guessing on the CSS file is broken, so fix the MIME type.
s3cmd modify s3://$AWS_WEBSITE_S3_BUCKET/static/main.css -m text/css

# Send an invalidation request to CloudFront so that it pulls new content from S3.
aws configure set preview.cloudfront true
aws cloudfront create-invalidation --distribution-id $AWS_DISTRIBUTION_ID --paths "/*"

