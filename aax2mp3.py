#!/usr/bin/env python3
# vim: tabstop=4:softtabstop=4:shiftwidth=4:expandtab:
# -*- coding: utf-8 -*-

import os
from subprocess import check_output, Popen, PIPE, STDOUT
import re
import argparse
from json import loads
from json import dump as jdump
import time
from unicodedata import normalize

try:
    import multiprocessing
except ImportError:
    multiprocessing = None

try:
    from setproctitle import setproctitle
except ImportError:

    def setproctitle(x):
        pass

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    tqdm = None


args = None

codecs = {  # codec, ext, container
    "mp3": ["libmp3lame", "mp3", "mp3"],
    "aac": ["copy", "m4a", "m4a"],
    "m4a": ["copy", "m4a", "m4a"],
    "m4b": ["copy", "m4a", "m4b"],
    "flac": ["flac", "flac", "flac"],
    "opus": ["libopus", "opus", "opus"],
}


def parse_ffmpeg_time(time_str):
    """Parse ffmpeg time string (HH:MM:SS.ms) to seconds"""
    try:
        parts = time_str.split(':')
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
        elif len(parts) == 2:
            minutes, seconds = parts
            return float(minutes) * 60 + float(seconds)
        else:
            return float(time_str)
    except (ValueError, AttributeError):
        return 0


def run_ffmpeg_with_progress(cmd, total_duration, description="Processing", show_progress=True):
    """
    Run ffmpeg command with progress bar.

    Args:
        cmd: List of command arguments
        total_duration: Total duration in seconds for progress calculation
        description: Description to show in progress bar
        show_progress: Whether to show progress bar (requires tqdm)

    Returns:
        Return code from ffmpeg
    """
    if not show_progress or not HAS_TQDM or total_duration <= 0:
        # Fall back to simple execution
        cmd_str = " ".join([f'"{arg}"' if " " in str(arg) else str(arg) for arg in cmd])
        return os.system(cmd_str.encode("utf-8"))

    # Add progress output to ffmpeg command
    # Insert -progress pipe:1 after ffmpeg
    progress_cmd = cmd.copy()
    # Find where to insert progress args (after 'ffmpeg')
    if progress_cmd[0] == "ffmpeg":
        progress_cmd.insert(1, "-progress")
        progress_cmd.insert(2, "pipe:1")
        # Change loglevel to quiet to avoid mixing output
        for i, arg in enumerate(progress_cmd):
            if arg == "-loglevel":
                progress_cmd[i + 1] = "quiet"
                break

    try:
        process = Popen(progress_cmd, stdout=PIPE, stderr=STDOUT, universal_newlines=True)

        with tqdm(total=100, desc=description, unit="%", ncols=80,
                  bar_format='{desc}: {percentage:3.0f}%|{bar}| [{elapsed}<{remaining}]') as pbar:
            current_progress = 0

            for line in process.stdout:
                line = line.strip()
                if line.startswith("out_time="):
                    time_str = line.split("=")[1]
                    current_time = parse_ffmpeg_time(time_str)
                    new_progress = min(int((current_time / total_duration) * 100), 100)
                    if new_progress > current_progress:
                        pbar.update(new_progress - current_progress)
                        current_progress = new_progress
                elif line == "progress=end":
                    pbar.update(100 - current_progress)
                    break

            process.wait()

        return process.returncode
    except Exception as e:
        # Fall back to simple execution on error
        cmd_str = " ".join([f'"{arg}"' if " " in str(arg) else str(arg) for arg in cmd])
        return os.system(cmd_str.encode("utf-8"))


def check_missing_authcode(args):
    """ensure that an authcode is available"""
    if args.auth:
        return False

    tmp = os.environ.get("AUTHCODE", None)
    if tmp:
        args.auth = tmp
        return False

    for f in [".authcode", "~/.authcode"]:
        f = os.path.expanduser(f)
        if os.path.exists(f):
            with open(f) as fd:
                args.auth = fd.read().strip()
                return False
    print('authcode not found in ".authcode", "~/.authcode", "$AUTHCODE", or the command line')
    return True


def missing_required_programs(args):
    """ensure that various dependencies are available"""
    error = False
    required = ["ffmpeg", "ffprobe"]

    # mp3splt is only needed for MP3 format AND when actually converting (not just extracting metadata/cover)
    if args.container == "mp3" and not args.metadata and not args.coverimage:
        required.append("mp3splt")

    for p in required:
        try:
            check_output(["which", p])
        except Exception:
            error = True
            print(f"missing dependency - {p}")
    return error


def numfix(n):
    """convert the number of seconds into the format that mp3splt prefers"""
    n = float(n)
    m = int(n / 60)
    s = n - (m * 60)
    return f"{m}.{s:.2f}"


def get_splitpoints(container, md):
    """figure out where mp3splt should split the file"""
    splitpoints = [float(x["start_time"]) for x in md["chapters"]]
    if container == "mp3":
        splitpoints.append(
            md["chapters"][-1]["end_time"]
        )  # mp3splt needs to know the end of the split. it can't assume EOF
        splitpoints = [numfix(x) for x in splitpoints]

    return splitpoints


def probe_metadata(args, fn):
    """
    get file metadata, eg. chapters, titles, codecs. Recent version of ffprobe
    can emit json which is ever so helpful
    """
    if not os.path.exists(fn):
        print("Derp! Input file does not exist!")
        return None
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-activation_bytes",
        args.auth,
        "-i",
        fn,
        "-of",
        "json",
        "-show_chapters",
        "-show_programs",
        "-show_format",
    ]

    buf = check_output(cmd).decode("utf-8")

    buf = re.sub(r"\s*[(](Una|A)bridged[)]", "", buf)  # I don't care about abridged or not
    buf = re.sub(r"\s+", " ", buf)  # squish all whitespace runs

    ffprobe = loads(buf)
    return ffprobe


def split_with_ffmpeg(args, destdir, src, md, cover_file=None):
    """Split non-MP3 files using ffmpeg"""
    chapters = md["chapters"]
    t = md["format"]["tags"]
    ext = codecs[args.container][1]
    codec = codecs[args.container][0]
    num_chapters = len(chapters)

    if args.verbose:
        print(f"Splitting {src} into {num_chapters} chapters using ffmpeg")

    # Use tqdm for chapter progress if available and not in verbose mode
    use_chapter_progress = HAS_TQDM and not args.verbose and not args.test
    chapter_iter = chapters
    if use_chapter_progress:
        chapter_iter = tqdm(chapters, desc="Splitting chapters", unit="ch", ncols=80)

    # Check if we can embed cover art (supported in m4a/m4b/mp3, not in flac/opus via this method)
    embed_cover = cover_file and os.path.exists(cover_file) and args.container in ["m4a", "m4b", "aac"]

    success = True
    for i, chapter in enumerate(chapter_iter):
        chapter_num = i + 1
        chapter_title = chapter["tags"].get("title", f"Chapter {chapter_num}")
        start_time = float(chapter["start_time"])
        end_time = float(chapter["end_time"])
        duration = end_time - start_time

        # Sanitize chapter title for filename (replace underscores with spaces for readability)
        safe_title = sanitize(chapter_title).replace("_", " ")
        output_file = os.path.join(destdir, f"{chapter_num:02d} - {safe_title}.{ext}")

        # Build ffmpeg command
        # Note: -ss and -t must come BEFORE -i to apply as input options (faster seeking)
        # and to avoid affecting the cover image input
        cmd = [
            "ffmpeg",
            "-loglevel", "error",
            "-ss", str(start_time),
            "-t", str(duration),
            "-i", src,
        ]

        # Add cover art input if available (no seek options for cover)
        if embed_cover:
            cmd.extend(["-i", cover_file])

        # Map streams: audio from first input, cover from second if available
        if embed_cover:
            cmd.extend([
                "-map", "0:a",
                "-map", "1:v",
                "-c:v", "copy",
                "-disposition:v:0", "attached_pic",
            ])

        cmd.extend([
            "-c:a", codec,
            "-map_metadata", "-1",  # Clear existing metadata
            "-metadata", f'title={chapter_title}',
            "-metadata", f'artist={t.get("artist", "")}',
            "-metadata", f'album={t.get("title", "")}',
            "-metadata", f'album_artist={t.get("album_artist", "")}',
            "-metadata", f'date={t.get("date", "")}',
            "-metadata", f'genre={t.get("genre", "")}',
            "-metadata", f'track={chapter_num}/{num_chapters}',
            output_file
        ])

        if args.verbose or args.test:
            print(f"Chapter {chapter_num}: {chapter_title}")
            print(" ".join(cmd))
            if args.test:
                continue

        # Run ffmpeg quietly when using progress bar
        cmd_str = " ".join([f'"{arg}"' if " " in str(arg) else str(arg) for arg in cmd])
        rv = os.system(cmd_str.encode("utf-8"))
        if rv != 0:
            print(f"Error splitting chapter {chapter_num}")
            success = False

    if success and not args.test and not args.keep:
        os.unlink(src)
    elif success and args.keep and args.verbose:
        print(f"Keeping intermediate file: {src}")


def split_file(args, destdir, src, md, cover_file=None):
    """Split the file into chapters"""
    splitpoints = get_splitpoints(args.container, md)
    t = md["format"]["tags"]
    if args.container == "mp3":
        # Escape special characters in metadata for mp3splt
        artist = t.get("artist", "Unknown").replace('"', '\\"')
        title = t.get("title", "Unknown").replace('"', '\\"')
        date = t.get("date", "")

        cmd = [
            "mp3splt",
            "-T",
            "12",
            "-o",
            '"Chapter @n"',
            "-g",
            f'"r%[@N=1,@a={artist},@b={title},@y={date},@t=Chapter @n,@g=183]"',
            "-d",
            f'"{destdir}"',
            f'"{src}"',
            " ".join(splitpoints),
        ]
        if args.verbose or args.test:
            print(cmd)
            if args.test:
                return
        cmd = " ".join(cmd)
        rv = os.system(cmd.encode("utf-8"))
        if rv == 0 and not args.keep:
            os.unlink(src)
        elif rv == 0 and args.keep and args.verbose:
            print(f"Keeping intermediate file: {src}")
    else:
        # Use ffmpeg for non-MP3 formats (AAC, M4A, M4B, FLAC, Opus)
        split_with_ffmpeg(args, destdir, src, md, cover_file)


def extract_image(args, destdir, fn):
    output = os.path.join(destdir, "cover.jpg")
    cmd = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-stats",
        "-activation_bytes",
        args.auth,
        "-n",
        "-i",
        fn,
        "-an",
        "-codec:v",
        "copy",
        f"{output}",
    ]
    if os.path.exists(output) and args.overwrite:
        os.unlink(output)

    if args.test or args.verbose:
        print("extracting cover art")
        print(" ".join(cmd))
    if not args.test:
        check_output(cmd)


def sanitize(s):
    """replace any unsafe characters with underscores"""
    s = normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii", "ignore")
    s = s.replace("'", "").replace('"', "")
    s = re.sub("[^a-zA-Z0-9._/-]", "_", s)
    s = re.sub("_+", "_", s)
    return s


def convert_file(args, fn, md):
    destdir = None
    try:
        destdir = os.path.join(
            args.outdir, md["format"]["tags"]["artist"], md["format"]["tags"]["title"].replace("/", "-")
        )
    except KeyError:
        print(f"Metadata Error in {fn}")
        return
    destdir = sanitize(destdir)

    if not os.path.exists(destdir):
        os.makedirs(destdir)

    # XXX figure out how to hook up decrypt-only, eg:
    # XXX ffmpeg -activation_bytes $AUTHCODE -i input.aax -c:a copy -vn -f mp4 output.mp4
    with open(f"{destdir}/metadata.json", "w") as fd:
        jdump(md, fd, sort_keys=True, indent=4, separators=(",", ": "))

    if args.metadata:
        return

    # Extract cover image (will be embedded in chapter files if supported)
    cover_file = os.path.join(destdir, "cover.jpg")
    try:
        extract_image(args, destdir, fn)
    except Exception:
        cover_file = None

    if args.coverimage:
        return

    if "Chapter " in str(os.listdir(destdir)):
        if args.verbose:
            print(f"Already processed {fn}")
        return

    destfn = fn.replace(".aax", f".{codecs[args.container][1]}")
    output = os.path.join(destdir, destfn)
    if os.path.exists(output) and args.overwrite:
        print(f"removing transcoded file: {output}")
        os.unlink(output)

    ac = "2"
    ab = md["format"]["bit_rate"]
    if args.mono:
        ac = "1"
        ab = str(int(ab) / 2)

    # Build metadata arguments safely
    tags = md["format"]["tags"]
    metadata_args = []

    # Add metadata fields if they exist
    if "title" in tags:
        metadata_args.extend(["-metadata", f'title={tags["title"]}'])
    if "artist" in tags:
        metadata_args.extend(["-metadata", f'artist={tags["artist"]}'])
    if "album_artist" in tags:
        metadata_args.extend(["-metadata", f'album_artist={tags["album_artist"]}'])
    if "album" in tags:
        metadata_args.extend(["-metadata", f'album={tags["album"]}'])
    if "date" in tags:
        metadata_args.extend(["-metadata", f'date={tags["date"]}'])
    if "genre" in tags:
        metadata_args.extend(["-metadata", f'genre={tags["genre"]}'])
    if "copyright" in tags:
        metadata_args.extend(["-metadata", f'copyright={tags["copyright"]}'])

    metadata_args.extend(["-metadata", "track=1/1"])

    cmd = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-stats",
        "-activation_bytes",
        args.auth,
        "-n",
        "-i",
        fn,
        "-vn",
        "-codec:a",
        codecs[args.container][0],
        "-ab",
        ab,
        "-ac",
        ac,
        "-map_metadata",
        "-1",
    ] + metadata_args + [output]
    if args.test or args.verbose:
        print(" ".join([f'"{arg}"' if " " in str(arg) else str(arg) for arg in cmd]))
        print("splitpoints:", get_splitpoints(args.container, md))
        if args.test:
            return split_file(args, destdir, output, md, cover_file)

    t = time.time()
    # Get total duration for progress bar
    total_duration = float(md["format"].get("duration", 0))
    title = md["format"]["tags"].get("title", "audio")

    # Use progress bar for transcoding (especially useful for FLAC/Opus encoding)
    show_progress = HAS_TQDM and not args.verbose
    run_ffmpeg_with_progress(cmd, total_duration, f"Transcoding {title}", show_progress)

    t = time.time() - t
    if args.verbose:
        print(f"transcoding time: {t:0.2f}s")
    if args.single == True:
        return

    split_file(args, destdir, output, md, cover_file)


def process_wrapper(fn):
    global args
    setproctitle(f"transcode {fn}")
    md = None
    try:
        md = probe_metadata(args, fn)
    except Exception as e:
        print(f"Caught exception {e} while probing metadata")

    try:
        convert_file(args, fn, md)
    except Exception as e:
        print(f"Caught exception {e} while probing metadata")


def main():
    global args
    ap = argparse.ArgumentParser()
    # arbitrary parameters
    ap.add_argument("-a", "--authcode", default=None, dest="auth", help="Authorization Bytes")
    ap.add_argument(
        "-f",
        "--format",
        default="mp3",
        choices=codecs.keys(),
        dest="container",
        help="output format. Default: %(default)s",
    )
    ap.add_argument(
        "-o", "--outputdir", default="Audiobooks", dest="outdir", help="output directory. Default: %(default)s"
    )
    ap.add_argument(
        "-p",
        "--processes",
        default=1,
        type=int,
        dest="processes",
        help="number of parallel transcoder processes to run. Default: %(default)d",
    )
    # binary flags
    ap.add_argument(
        "-c", "--clobber", default=False, dest="overwrite", action="store_true", help="overwrite existing files"
    )
    ap.add_argument(
        "-i", "--coverimage", default=False, dest="coverimage", action="store_true", help="only extract cover image"
    )
    ap.add_argument("-m", "--mono", default=False, dest="mono", action="store_true", help="downmix to mono")
    ap.add_argument(
        "-s", "--single", default=False, dest="single", action="store_true", help="don't split into chapters"
    )
    ap.add_argument(
        "-k", "--keep", default=False, dest="keep", action="store_true",
        help="keep intermediate transcoded file after splitting into chapters"
    )
    ap.add_argument("-t", "--test", default=False, dest="test", action="store_true", help="test input file(s)")
    ap.add_argument("-v", "--verbose", default=False, dest="verbose", action="store_true", help="extra verbose output")
    ap.add_argument(
        "-x", "--extract-metadata", default=False, dest="metadata", action="store_true", help="only extract metadata"
    )

    ap.add_argument(nargs="+", dest="input")
    args = ap.parse_args()

    something_is_wrong = False
    if check_missing_authcode(args):
        something_is_wrong = True

    if missing_required_programs(args):
        something_is_wrong = True

    if something_is_wrong:
        exit(1)

    if args.mono:
        args.outdir += "-mono"

    if multiprocessing is None:
        args.processes = 1

    if args.processes < 2:
        for fn in args.input:
            process_wrapper(fn)
    else:
        proc_pool = multiprocessing.Pool(processes=args.processes, maxtasksperchild=1)
        setproctitle("transcode_dispatcher")
        proc_pool.map(process_wrapper, args.input, chunksize=1)

    os.system("stty echo")


if __name__ == "__main__":
    main()
