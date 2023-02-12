#!/usr/bin/env python

import difflib
import os
import re
import sys

from pyglossary.ui.tools.colors import *

wordRE = re.compile(r"(\W)", re.M)
xmlTagRE = re.compile(
	"</?[a-z][0-9a-z]* *[^<>]*>",
	re.I | re.M,
)


def plainWordSplit(text: str) -> "List[str]":
	return [
		word
		for word in wordRE.split(text)
		if word
	]


def xmlWordSplit(text: str) -> "List[str]":
	pos = 0
	words = []

	for m in xmlTagRE.finditer(text):
		start, end = m.span()
		match = m.group()
		if start > pos:
			words += plainWordSplit(text[pos:start])
		words.append(match)
		pos = end

	if pos < len(text):
		words += plainWordSplit(text[pos:])

	return words


def xmlDiff(text1, text2) -> "Iterator":
	words1 = xmlWordSplit(text1)
	words2 = xmlWordSplit(text2)
	return difflib.ndiff(words1, words2, linejunk=None, charjunk=None)


def formatDiff(diff) -> str:
	res = ""
	for part in diff:
		if part[0] == " ":
			res += part[2:]
			continue
		if part[0] == "-":
			res += red + part[2:] + reset
			continue
		if part[0] == "+":
			res += green + part[2:] + reset
			continue
	return res


def main_word_split():
	text = sys.argv[1]
	print(text)
	for word in xmlWordSplit(text):
		print(f"word: {word!r}")


def main():
	filename1 = sys.argv[1]
	filename2 = sys.argv[2]
	with open(filename1, mode="r", encoding="utf-8") as _file:
		text1 = _file.read()
	with open(filename2, mode="r", encoding="utf-8") as _file:
		text2 = _file.read()
	print(formatDiff(xmlDiff(text1, text2)))


if __name__ == "__main__":
	main()