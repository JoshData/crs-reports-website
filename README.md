# EveryCRSReport.com

This repository builds the website at [EveryCRSReport.com](https://www.everycrsreport.com).

It's a totally static website. The scripts here generate the static HTML that gets copied into a public URL.

## Local Development

The website build process is written in Python 3. Prepare your development environment:

	pip3 install -r requirements.txt

Although the full website build requires access to a private source archive of CRS reports, which you probably don't have access to, you can run the core website build process on the public reports. Download some of the reports using the bulk download example script:

	python3 bulk-download.py
	(CTRL+C at any time once you have as much as you want)

Run the build process:

	./build.py

which generates the static files of the website into the `build` directory. To view the generated website, you can run:

	(cd build; python -m SimpleHTTPServer)

and then visit http://localhost:8000/ in your web browser.


## Production Site Configuration

### AWS Resources

The website is driven by several resources in Amazon Web Services.

1) The AWS S3 bucket which holds the private archive of CRS reports.

2) A cheap server running in EC2 which fetches the reports from the private archive, generates the static pages of the website, and uploads the website to (3). Nothing permanent is kept on this server.

3) A second AWS S3 bucket which holds the public, static files of the website. Although an S3 bucket _can_ serve the website directly, it cannot do so with HTTPS, so we don't use that. The bucket itself is therefore not public.

4) An AWS CloudFront "distribution", whose "origin" is configured to be the AWS S3 bucket (3). The CloudFront "distribution" makes the website available to the world on the web. The distribution is set with the following options: a) 'Restrict Bucket Access', b) a custom cache policy and a default TTL of about 14400 (4 hours) so that the site updates eventually after new files are published, and c) Amazon Certificate Manager (ACM) is used to provision a SSL certificate for the HTTPS site.

5) An IAM (Identity and Access Management) account which has read-only access to (1) and read/write access to (3). The IAM account's credentials are stored on the server (2). We use an IAM account and not a master AWS account's credentials so that we only work with the permissions we need.

The DNS for the website's domain name is configured with a CNAME that points to the CloudFront distribution. The non-"www." domain name is parked somewhere with a redirect to the "www." domain name.

### Security Configuration

The IAM account is given read-only access to the private reports archive by adding the following bucket policy to the private reports archive S3 bucket, under Properties > Permissions > Add bucket policy. Replace `BUCKET_NAME_HERE` with the _private CRS reports archive bucket name_ and `IAM_USER_ARN_HERE` with the IAM user ARN in the four places they appear:

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

The IAM account is given full access to the public website bucket in Properties > Permissions > Add bucket policy. Replace `BUCKET_NAME_HERE` with the _public website bucket name_ and `IAM_USER_ARN_HERE` with the IAM user ARN in the four places they appear. **If you already created the CloudFront distribution, this bucket will already have an access policy granting CloudFront access. You will have to merge the policies.**

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

### Algolia search account

We use Algolia.com as a hosted facted search service index service.

* Create an index on Algolia. You'll put the name of the index into `credentials.txt` later.
* Get the client ID, admin API key (read-write access to the index), and search-only access key (read-only/public access to the index). You'll put these into `credentials.txt` later.

### Server Preparation

This section prepares a Linux machine that is ready to fetch the CRS reports from the private location and turn them into the public website. The machine need not be running all the time, but without it the website will not be updated.

On a new Linux machine (instructions here for an AWS Amazon Linux instance):

	sudo yum install python34-pip gcc libxml2-devel libxslt-devel python34-devel unzip poppler-utils
	sudo pip install s3cmd
	sudo pip-3.4 install -r requirements.txt

Get the PDF redaction script, install its dependencies, and install QPDF, which on Amazon Linux must unfortunately be compiled from source:

	wget https://raw.githubusercontent.com/JoshData/pdf-redactor/master/pdf_redactor.py
	pip3 install $(curl https://raw.githubusercontent.com/JoshData/pdf-redactor/master/requirements.txt)

	sudo yum install gcc-c++ pcre-devel
	wget http://downloads.sourceforge.net/project/qpdf/qpdf/6.0.0/qpdf-6.0.0.tar.gz
	tar -zxf qpdf-6.0.0.tar.gz
	(cd qpdf-6.0.0/ && ./configure && make && sudo make install)

Create a new file named `credentials.txt` and put in it the AWS IAM user's access keys that have access to 1) the private S3 bucket holding the CRS reports archive and 2) the public S3 bucket holding the website content. Also set the names of the S3 buckets. And add the Algolia account information.

	AWS_ACCESS_KEY_ID=...
	AWS_SECRET_ACCESS_KEY=...
	AWS_INCOMING_S3_BUCKET=...
	AWS_WEBSITE_S3_BUCKET=...
	ALGOLIA_CLIENT_ID=...
	ALGOLIA_ADMIN_ACCESS_KEY=...
	ALGOLIA_SEARCH_ACCESS_KEY=...
	ALGOLIA_INDEX_NAME=...

### Running the site generator

To generate & update the website, run:

	./run.sh

Under the hood, this:

* Fetches the latest CRS reports metadata and files from our private archive, saving them into `incoming/`. (`fetch_reports_files.sh`)

* Prepares the raw files for publication, creating new JSON and sanitizing the HTML and PDFs, saving the new files into `reports/`. This step is quite slow, but it will only process new files on each run. If our code changes and the sanitization process has been changed, delete the whole `reports/` directory so it re-processes everything from scratch. (`process_incoming.py`) 

* Generates the complete website in the `build/` directory. (`build.py`)

* Uploads the built site to the public S3 bucket (which is served by the CloudFront distribution). (`publish.sh`)

