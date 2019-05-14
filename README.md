# Simple Uvicorn Based Web Server
## Overview
This simple HTTP 1.1 static web server is written in Python 3 utilizing the Uvicorn library for the HTTP server component.

This program requires CPython 3.5 or newer and uvicorn (e.g. `pip3 install uvicorn` if on Ubuntu). Only tested in Linux systems (including Microsoft WSL).

## Features
- Directory listing and file download.
- File download, with `Content-Length` header and CORS header (suitable for hosting static JSON files).
- File upload, utilizing `POST` method and `multipart/form-data` body format.
- Built-in `multipart/form-data` that works with chunked data streams.
- Streams both upload and download, suitable for transferring large files.
- More than 4GB file support.
- Simultaneous transfer in both directions.
- Path canonicalization.

## Known Issues
- File names with non ASCII unicode characters doesn't work.

Please note that this application is a very simple program, therefore no extensive performance and security testing has been performed. There isn't any guarantee of protection against security breach, denial of service attacks, etc.

## Usage
Simply run the `simplewebserver.py` from the `src` folder using Python 3 interpreter. Ensure that the other python files in the `src` folder from this repository accompany the main python program.

Another way to run this program is by renaming `simplewebserver.py` to `__main__.py`, zip archive the program with the other python files from the `src` folder, and then execute the zip file directly using the Python 3 interpreter (e.g. `python3 simplewebserver.zip`).

By default, the program will serve files and folders in the current working directory for all hosts at port 8080. Use the command line switch to change those parameters. For more info, run the program with `--help` argument.