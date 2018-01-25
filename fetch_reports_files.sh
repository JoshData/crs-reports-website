#!/bin/bash
source credentials.txt
export AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
s3cmd sync -s --no-preserve --no-check-md5 s3://$AWS_INCOMING_S3_BUCKET/ incoming/
  # we have one very large file and many other files,
  # and we're not worried about files being updated in place,
  # so don't check file hashes - just download if files are new
  # or size changed
