#!/bin/bash
# This script requires `mdspell`:
#
#    https://www.npmjs.com/package/markdown-spellcheck
#
# This script is intended to be run through tomte on the root folder.
# Usage:
#   tomte check-spelling
#

MDSPELL_PATH="$(which mdspell)"
if [ -z "${MDSPELL_PATH}" ]; then
  echo "Cannot find executable 'mdspell'. Please install it to run this script: npm i markdown-spellcheck -g"
  exit 127
else
  echo "Found 'mdspell' executable at ${MDSPELL_PATH}"
  mdspell -r -n -a --en-gb '**/*.md' '!docker-images/*.md' '!docs/api/**/*.md' '!third_party/**/*.md' '!go-ipfs/**/*.md' '!docs/package_list.md'
fi
