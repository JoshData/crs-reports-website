# CRS Reports Website Builder

This repository builds the CRS reports website. It's a totally static website. The scripts here generate the static HTML that get copied into a public URL.

## Preparation

On a new Linux machine (instructions here for an AWS Amazon Linux instance):

	sudi yum install python34-pip gcc libxml2-devel libxslt-devel python34-devel
	sudo pip install s3cmd
	sudo pip-3.4 install -r requirements.txt

Create a new file named `aws_credentials.txt` and put in it your AWS keys for access to the private CRS reports archive:

	AWS_ACCESS_KEY_ID=...
	AWS_SECRET_ACCESS_KEY=...

## Running the site generator

Fetch the latest CRS reports metadata and files from our private archive and then pre-process them:

	./fetch_reports_files.sh # pulls the files into 'incoming'
	./process_incoming.py # cleans HTML and transforms JSON to our public format, writing to 'reports'

The HTML sanitization step in `process_incoming.py` is slow, which is one reason why we do this step separately. It will skip files it's already done.

The above steps are the only steps that require access to our private archive. If you don't have access to our private archive, you can grab some of our public files and put them into the `reports` directory (TODO: say more about this).

Generate the complete website in the `build` subdirectory:

	./build.py

For testing, if you want to speed up this step and just build the output for one report, you can give it a report number:

	ONLY=RS20444 ./build.py

For testing, to view the unpublished website, you can run:

	(cd build; python -m SimpleHTTPServer)

and then visit http://localhost:8000/ in your web browser.

You must then upload the built site to the public space:

	./publish.sh

which will copy the built website to the Amazon S3 bucket where the site is served from.
