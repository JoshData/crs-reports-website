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

	(cd static-site; python -m http.server)

and then visit http://localhost:8000/ in your web browser.


## Production Site Configuration

### Algolia search account

We use Algolia.com as a hosted facted search service index service.

* Create an index on Algolia. You'll put the name of the index into `credentials.txt` later.
* Get the client ID, admin API key (read-write access to the index), and search-only access key (read-only/public access to the index). You'll put these into `credentials.txt` later.

### Server Preparation

Install packages and make a virtual environment (based on Ubuntu 22.04):

	sudo apt install python3-virtualenv unzip pandoc
	virtualenv venv
	source venv/bin/activate
	pip install -r requirements.txt

Get the PDF redaction script, install its dependencies, and install QPDF:

	mkdir lib
	cd lib

	wget https://raw.githubusercontent.com/JoshData/pdf-redactor/master/pdf_redactor.py
	pip install $(curl https://raw.githubusercontent.com/JoshData/pdf-redactor/master/requirements.txt)

	wget https://github.com/qpdf/qpdf/releases/download/v11.9.1/qpdf-11.9.1-bin-linux-x86_64.zip
	unzip -d qpdf qpdf-11.9.1-bin-linux-x86_64.zip

	cd ..

Create a new file named `secrets/credentials.txt`. And add the Algolia account information.

	ALGOLIA_CLIENT_ID=...
	ALGOLIA_ADMIN_ACCESS_KEY=...
	ALGOLIA_SEARCH_ACCESS_KEY=...
	ALGOLIA_INDEX_NAME=...

Create a new file named `secrets/credentials.google_service_account.json` and place a Google API System Account's JSON credentials in the file. The credentials should have access to the EveryCRSReport.com Google Analytics view.

Create symlinks here for where the source report files are stored and where the static site will be built into:

	ln -s /mnt/volume_nyc1_01/source-reports/ .
	ln -s /mnt/volume_nyc1_02/processed-reports/ .
	ln -s /mnt/volume_nyc1_01/static-site/ .

Set up nginx & certbot:

	apt install nginx certbot python3-certbot-nginx
	rmdir /var/www/html # clear it out first
	ln -s /mnt/volume_nyc1_01/static-site/ /var/www/html
	chmod a+rx /home/user/
	certbot -d www.everycrsreport.com

### Running the site generator

To generate & update the website, run:

	./run.sh

Under the hood, this:

* Prepares the raw files for publication, creating new JSON and sanitizing the HTML and PDFs, saving the new files into `reports/`. This step is quite slow, but it will only process new files on each run. If our code changes and the sanitization process has been changed, delete the whole `reports/` directory so it re-processes everything from scratch. (`process_incoming.py`) 

* Queries Google Analytics for top-accessed reports in the last week.

* Generates the complete website in the `static-site/` directory. (`build.py`)


