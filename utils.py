import datetime
import os
import os.path

import pytz

us_eastern_tz = pytz.timezone('America/New_York')
utc_tz = pytz.timezone("UTC")

def make_link(src, dst):
    # Make a hard link dst to source if the paths are on the same filesystem,
    # or a symbolic link if they are not. If dst exists and isn't a link to
    # src, it is deleted first. If src is None and dst exists, dst is deleted.
    #
    # Use l* functions so this doesn't break with broken symlinks (exists()
    # and stat() raise exceptions on broken symlinks).
    if os.path.lexists(dst):
        if src and os.lstat(src).st_ino == os.lstat(dst).st_ino:
            return # files are already hardlinked
        if src and os.path.exists(os.path.realpath(dst)) and os.lstat(src).st_ino == os.lstat(os.path.realpath(dst)).st_ino:
            return # files are already symlinked
        # Destination exists and is not a link to src.
        #raise ValueError(f"Should {dst} be deleted? It's not a hard link to {src} and its symbolic target is {os.path.realpath(dst)}.")
        print(f"Deleting {dst}... ({os.path.realpath(dst)} != {src})")
        os.unlink(dst)
    if src:
       # Create a hard link if paths are on the same filesystem.
       if os.lstat(src).st_dev == os.lstat(os.path.dirname(dst)).st_dev:
           os.link(src, dst)
       # Otherwise when crossing filesystem boundaries, use a symlink.
       else:
           os.symlink(os.path.abspath(src), dst)

def parse_dt(s, hasmicro=False, utc=False):
    dt = datetime.datetime.strptime(s, "%Y-%m-%d" + ("T%H:%M:%S" if "T" in s else "") + (".%f" if hasmicro else ""))
    return (utc_tz if utc else us_eastern_tz).localize(dt)
