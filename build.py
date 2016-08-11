#!/usr/bin/python3
#
# Build the CRS Reports Archive website by generating its static content.
#
# Assumptions:
#
# * The CRS report metadata and document files are in the 'cache/documents' and 'cache/files' directories.
#
# Output:
#
# A static website in ./build.

import sys, os.path, glob, shutil

BUILD_DIR = "build"

# Generate the static pages.

def generate_static_page(fn):
	from jinja2 import Environment, FileSystemLoader

	env = Environment(loader=FileSystemLoader(["templates", "pages"]))

	try:
		templ = env.get_template(fn)
	except Exception as e:
		print("Error loading template", fn)
		print(e)
		sys.exit(1)

	try:
		html = templ.render()
	except Exception as e:
		print("Error rendering template", fn)
		print(e)
		sys.exit(1)

	os.makedirs(os.path.dirname(os.path.join(BUILD_DIR, fn)), exist_ok=True)
	with open(os.path.join(BUILD_DIR, fn), "w") as f:
		f.write(html)

for fn in glob.glob("pages/*.html"):
	generate_static_page(os.path.basename(fn))

# Copy the static assets.

static_dir = os.path.join(BUILD_DIR, "static")
if os.path.exists(static_dir):
	shutil.rmtree(static_dir)

# "Copy" the assets. Actually just make hardlinks.
shutil.copytree("static", static_dir, copy_function=os.link)
