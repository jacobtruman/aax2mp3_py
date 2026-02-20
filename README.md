# AAX2MP3_py


This is a rough rewrite of [KrumpetPirate AAXtoMP3](https://github.com/KrumpetPirate/AAXtoMP3) but in python. As with `AAXtoMP3` you will need to use a tool like [audible-activator](https://github.com/inAudible-NG/audible-activator) to get the authcode needed to decrypt the audio.

**Key advantages:**
- Uses [mp3splt](https://github.com/search?l=C&q=mp3splt&type=Repositories) for MP3 chapter splitting (much faster than ffmpeg)
- Supports multiple output formats: **MP3, AAC, M4A, M4B, FLAC, and Opus**
- Uses ffmpeg for efficient chapter splitting of non-MP3 formats
- Parallel processing support for batch conversions

## Installation

### Prerequisites

You'll need the following tools installed on your system:
- `ffmpeg`
- `ffprobe` (usually comes with ffmpeg)
- `mp3splt`

On macOS with Homebrew:
```bash
brew install ffmpeg mp3splt
```

On Ubuntu/Debian:
```bash
sudo apt-get install ffmpeg mp3splt
```

### Install with uv (Recommended)

The easiest way to install `aax2mp3` is using [uv](https://github.com/astral-sh/uv):

```bash
# Install from the repository
uv tool install git+https://github.com/ckuethe/aax2mp3_py.git

# Or install from a local clone
uv tool install .

# For development (editable install)
uv tool install --editable .
```

### Install with pip

Alternatively, you can install with pip:

```bash
pip install git+https://github.com/ckuethe/aax2mp3_py.git
```

### Manual Installation

You can also run the script directly:

```bash
python aax2mp3.py [options] input.aax
```

## Usage

```bash
# Basic usage
aax2mp3 -a YOUR_AUTHCODE input.aax

# Convert multiple files in parallel
aax2mp3 -a YOUR_AUTHCODE -p 4 *.aax

# Extract only cover art
aax2mp3 -a YOUR_AUTHCODE -i input.aax

# Convert to mono (smaller file size)
aax2mp3 -a YOUR_AUTHCODE -m input.aax

# Don't split into chapters (single file output)
aax2mp3 -a YOUR_AUTHCODE -s input.aax
```

### Command-line Options

```
usage: aax2mp3 [-h] [-a AUTH] [-f {mp3,aac,m4a,m4b,flac,opus}] [-o OUTDIR]
               [-p PROCESSES] [-c] [-i] [-m] [-s] [-k] [-t] [-v] [-x]
               input [input ...]

positional arguments:
  input                 AAX file(s) to convert

options:
  -h, --help            show this help message and exit
  -a, --authcode AUTH   Authorization Bytes
  -f, --format {mp3,aac,m4a,m4b,flac,opus}
                        output format. Default: mp3
  -o, --outputdir OUTDIR
                        output directory. Default: Audiobooks
  -p, --processes PROCESSES
                        number of parallel transcoder processes to run. Default: 1
  -c, --clobber         overwrite existing files
  -i, --coverimage      only extract cover image
  -m, --mono            downmix to mono
  -s, --single          don't split into chapters
  -k, --keep            keep intermediate transcoded file after splitting
  -t, --test            test input file(s)
  -v, --verbose         extra verbose output
  -x, --extract-metadata
                        only extract metadata
```

### Getting Your Authcode

You'll need your Audible activation bytes (authcode) to decrypt AAX files. Use [audible-activator](https://github.com/inAudible-NG/audible-activator) to obtain it.

You can provide the authcode in three ways:
1. Command line: `-a YOUR_AUTHCODE`
2. Environment variable: `export AUTHCODE=YOUR_AUTHCODE`
3. File: Create `.authcode` in the current directory or `~/.authcode` in your home directory

## Features

- ✅ Multiple output formats: MP3, AAC, M4A, M4B, FLAC, Opus
- ✅ Automatic chapter splitting
- ✅ Fast MP3 splitting with mp3splt
- ✅ Efficient non-MP3 splitting with ffmpeg
- ✅ Parallel processing for batch conversions
- ✅ Metadata preservation
- ✅ Cover art extraction
- ✅ Mono downmix option
- ✅ Progress bars for long conversions (optional, requires `tqdm`)
- ✅ Option to keep intermediate file (`-k`/`--keep`)

### Progress Bars (Optional)

For progress bars during transcoding and chapter splitting, install with the `progress` extra:

```bash
# With uv
uv tool install --editable ".[progress]"

# With pip
pip install ".[progress]"
```

This installs `tqdm` for progress bar support. Without it, the tool works normally but without visual progress indicators.

## License

WTFPL (Do What The Fork You Want To Public License)
