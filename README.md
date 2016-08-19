# CRS Reports Website Builder

This repository builds the CRS reports website. It's a totally static website. The scripts here generate the static HTML that get copied into a public URL.

## Preparation

On a new Linux machine (instructions here for an AWS Amazon Linux instance):

	sudo yum install python34-pip gcc libxml2-devel libxslt-devel python34-devel unzip poppler-utils
	sudo pip install s3cmd
	sudo pip-3.4 install -r requirements.txt

Create a new file named `aws_credentials.txt` and put in it your AWS keys that have access to 1) the private S3 bucket holding the CRS reports archive and 2) the public public S3 bucket holding the website content. Also set the name of the S3 buckets:

	AWS_ACCESS_KEY_ID=...
	AWS_SECRET_ACCESS_KEY=...
	AWS_INCOMING_S3_BUCKET=...
	AWS_WEBSITE_S3_BUCKET=...

## Running the site generator

To generate the website's static files, follow these steps.

Fetch the latest CRS reports metadata and files from our private archive (saves them into `incoming/`):

	./fetch_reports_files.sh

Then pre-process the files, which creates new JSON and sanitizes the HTML (saves the new files into `reports/`):

	./process_incoming.py

The HTML sanitization step in `process_incoming.py` is quite slow. But it will only process new files on each run. If our code changes and the sanitization process has been changed, delete the whole `reports/` directory so it re-processes everything from scratch.

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
