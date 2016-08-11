# CRS Reports Website Builder

This repository builds the CRS reports website. It's a totally static website. The scripts here generate the static HTML that get copied into a public URL.

## Preparation

On a new Linux machine (instructions here for an AWS Amazon Linux instance):

	sudi yum install python34-pip
	sudo pip install s3cmd
	sudo pip-3.4 install -r requirements.txt

Create a new file named `aws_credentials.txt` and put in it your AWS keys for access to the private CRS reports archive:

	AWS_ACCESS_KEY_ID=...
	AWS_SECRET_ACCESS_KEY=...

## Running the site generator

Fetch the latest CRS reports metadata and files from our private archive:

	./fetch_reports_files.sh

## Generating the website

Run:

	./build.py

This will generate the website in the `build` subdirectory. You then must upload it to the public space.
