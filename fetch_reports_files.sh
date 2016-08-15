#1/bin/sh
source aws_credentials.txt
export AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
s3cmd sync -s --no-preserve s3://$AWS_INCOMING_S3_BUCKET/ incoming/
