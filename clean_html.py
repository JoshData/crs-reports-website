#!/usr/bin/python3

import glob
import os
import os.path

from multiprocessing import Pool

import bleach
import html5lib

def clean_up(content):
    # Extract the report itself from the whole page.
    import html5lib
    content = html5lib.parse(content)
    content = content.find(".//*[@class='Report']")

    # Kill mailto: links, which have author emails, which we want to scrub.
    for tag in content.findall(".//a"):
        if 'href' in tag.attrs and tag['href'].lower().startswith("mailto:"):
            tag.name = "span"
            del tag['href']
            tag.string = "[scrubbed]"

    for tag in [content] + content.findall(".//*"):
        if isinstance(tag.tag, str):
            tag.tag = tag.tag.replace("{http://www.w3.org/1999/xhtml}", "")

        # Demote h#s.
        if tag.tag in ("h1", "h2", "h3", "h4", "h5"):
            tag.tag = "h" + str(int(tag.tag[1:])+1)

    import xml.etree
    content = xml.etree.ElementTree.tostring(content, encoding="unicode", method="html")

    # Guard against unsafe content.
    import bleach
    def link_filter(name, value):
        if name == "name": # link targets
            return True
        if name == "href" and (value.startswith("http:") or value.startswith("https:") or value.startswith("#")):
            return True
        return False
    def image_filter(name, value):
        if name == "src" and (value.startswith("http:") or value.startswith("https:")):
            return True
        return False
    content = bleach.clean(
        content,
        tags=["a", "img", "b", "strong", "i", "em", "u", "sup", "sub", "span", "div", "p", "br", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td", "hr", "h2", "h3", "h4", "h5", "h6"],
        attributes={
            "*": "title",
            "a": link_filter,
            "img": image_filter,
        }
    )

    return content


def process_file(fn, out_fn):
    print(out_fn, "...")
    with open(fn) as f1:
        content = clean_up(f1.read())
    with open(out_fn, "w") as f2:
        f2.write(content)


# MAIN

if __name__ == "__main__":
    # Ensure output directory exists.
    if not os.path.exists("sanitized-html"):
        os.mkdir("sanitized-html")

    # This is all very slow, so...
    pool = Pool()

    # For every HTML file, if we haven't yet processed it, then process it.
    for fn in sorted(glob.glob("cache/files/*.html")):
        out_fn = "sanitized-html/" + fn[12:]
        if not os.path.exists(out_fn):
            #process_file(fn, out_fn)
            # Queue up the job.
            pool.apply_async(process_file, [fn, out_fn])

    # Wait for the last processes to be done.
    pool.close()
    pool.join()
