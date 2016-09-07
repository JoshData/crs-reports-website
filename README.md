# CRS Reports Website Builder

This repository builds the CRS reports website. It's a totally static website. The scripts here generate the static HTML that get copied into a public URL.

## AWS Account Configuration

### Resources

The website is driven by several resources in Amazon Web Services.

1) The AWS S3 bucket which holds the private archive of CRS reports.

2) A cheap server running in EC2 which fetches the reports from the private archive, generates the static pages of the website, and uploads the website to (3). Nothing permanent is kept on this server.

3) A second AWS S3 bucket which holds the public, static files of the website. Although an S3 bucket _can_ serve the website directly, it cannot do so with HTTPS, so we don't use that. The bucket itself is therefore not public.

4) An AWS CloudFront "distribution", whose "origin" is configured to be the AWS S3 bucket (3). The CloudFront "distribution" makes the website available to the world on the web. The distribution is set with the following options: a) 'Restrict Bucket Access', b) a custom cache policy and a default TTL of about 14400 (4 hours) so that the site updates eventually after new files are published, and c) Amazon Certificate Manager (ACM) is used to provision a SSL certificate for the HTTPS site.

5) An IAM (Identity and Access Management) account which has read-only access to (1) and read/write access to (3). The IAM account's credentials are stored on the server (2). We use an IAM account and not a master AWS account's credentials so that we only work with the permissions we need.

The DNS for the website's domain name is configured with a CNAME that points to the CloudFront distribution. The non-"www." domain name is parked somewhere with a redirect to the "www." domain name.

### Security Configuration

Create the IAM account. It has an access key, a secret access key, and a user ARN.

Grant the IAM account read-only access to the private reports archive by adding the following bucket policy to the private reports archive S3 bucket, under Properties > Permissions > Add bucket policy. Replace `BUCKET_NAME_HERE` with the _private CRS reports archive bucket name_ and `IAM_USER_ARN_HERE` with the IAM user ARN in the four places they appear:

	{
		"Id": "Policy1471614193686",
		"Version": "2012-10-17",
		"Statement": [
			{
				"Sid": "Stmt1471614186000",
				"Action": [
					"s3:ListBucket"
				],
				"Effect": "Allow",
				"Resource": "arn:aws:s3:::BUCKET_NAME_HERE",
				"Principal": {
					"AWS": [
						"IAM_USER_ARN_HERE"
					]
				}
			},
			{
				"Sid": "Stmt1471614186000",
				"Action": [
					"s3:GetObject"
				],
				"Effect": "Allow",
				"Resource": "arn:aws:s3:::BUCKET_NAME_HERE/*",
				"Principal": {
					"AWS": [
						"IAM_USER_ARN_HERE"
					]
				}
			}
		]
	}

Grant the IAM account full access to the public website bucket in Properties > Permissions > Add bucket policy. Replace `BUCKET_NAME_HERE` with the _public website bucket name_ and `IAM_USER_ARN_HERE` with the IAM user ARN in the four places they appear. **If you already created the CloudFront distribution, this bucket will already have an access policy granting CloudFront access. You will have to merge the policies.**

	{
	  "Id": "Policy1471615487213",
	  "Version": "2012-10-17",
	  "Statement": [
	    {
	      "Sid": "Stmt1471615480136",
	      "Action": [
	        "s3:ListBucket"
	      ],
	      "Effect": "Allow",
	      "Resource": "arn:aws:s3:::BUCKET_NAME_HERE",
	      "Principal": {
	        "AWS": [
	          "IAM_USER_ARN_HERE"
	        ]
	      }
	    },
	    {
	      "Sid": "Stmt1471615480136",
	      "Action": [
	        "s3:DeleteObject",
	        "s3:GetObject",
	        "s3:PutObject"
	      ],
	      "Effect": "Allow",
	      "Resource": "arn:aws:s3:::BUCKET_NAME_HERE/*",
	      "Principal": {
	        "AWS": [
	          "IAM_USER_ARN_HERE"
	        ]
	      }
	    }
	  ]
	}

## Server Preparation

This section prepares a Linux machine that is ready to fetch the CRS reports from the private location and turn them into the public website. The machine need not be running all the time, but without it the website will not be updated.

On a new Linux machine (instructions here for an AWS Amazon Linux instance):

	sudo yum install python34-pip gcc libxml2-devel libxslt-devel python34-devel unzip poppler-utils
	sudo pip install s3cmd
	sudo pip-3.4 install -r requirements.txt

Get the PDF sanitization script and install QPDF, which on Amazon Linux must unfortunately be compiled from source:

	wget https://raw.githubusercontent.com/JoshData/contact_removal/master/contact_remover.py

	sudo yum install gcc-c++ pcre-devel
	wget http://downloads.sourceforge.net/project/qpdf/qpdf/6.0.0/qpdf-6.0.0.tar.gz
	tar -zxf qpdf-6.0.0.tar.gz
	(cd qpdf-6.0.0/ && ./configure && make && sudo make install)


Create a new file named `aws_credentials.txt` and put in it the AWS IAM user's access keys that have access to 1) the private S3 bucket holding the CRS reports archive and 2) the public S3 bucket holding the website content. Also set the names of the S3 buckets:

	AWS_ACCESS_KEY_ID=...
	AWS_SECRET_ACCESS_KEY=...
	AWS_INCOMING_S3_BUCKET=...
	AWS_WEBSITE_S3_BUCKET=...

## Running the site generator

To generate the website's static files, follow these steps.

Fetch the latest CRS reports metadata and files from our private archive (saves them into `incoming/`):

	./fetch_reports_files.sh

Then pre-process the files, which creates new JSON and sanitizes the HTML and PDFs (saves the new files into `reports/`):

	./process_incoming.py

The sanitization step in `process_incoming.py` is quite slow. But it will only process new files on each run. If our code changes and the sanitization process has been changed, delete the whole `reports/` directory so it re-processes everything from scratch.

The above steps are the only steps that require access to our private archive. If you don't have access to our private archive, you can grab some of our public files and put them into the `reports/` directory (TODO: say more about this).

Generate the complete website in the `build` subdirectory:

	./build.py

The build step is also quite slow because it is checking for changes between report versions and generating thumbnail images from PDFs. It also will only process changed reports.

For testing, if you want to speed up this step and just build the output for one report, and force it to re-process that report, you can give it a report number in the `ONLY` environment variable:

	ONLY=RS20444 ./build.py

If the templates or the build process change and all of the report pages need to be re-built, delete the `cache/` directory. (If only the home page, about page, etc. have changed, there is no need to re-process the reports.)

For testing, to view the unpublished website from these generated files, you can run:

	(cd build; python -m SimpleHTTPServer)

and then visit http://localhost:8000/ in your web browser.

You must then upload the built site to the public space:

	./publish.sh

which will copy the built website to the Amazon S3 bucket where the site is served from.
