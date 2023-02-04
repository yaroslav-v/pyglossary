#!/usr/bin/env python

import difflib
import os
import re
import sys
from typing import Iterator, List

from pyglossary.langs.writing_system import (
	getAllWritingSystemsFromText,
)
from pyglossary.ui.tools.colors import green, red, reset

# wordRE = re.compile(r"(\W)", re.M)
# \W also includes ZWNJ which is bad for us
wordRE = re.compile(r"([\s!\"#$%&'()*+,-./:;=?@\[\\\]^_`{|}~])", re.M)

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


def xmlDiff(text1: str, text2: str) -> "Iterator[str]":
	words1 = xmlWordSplit(text1)
	words2 = xmlWordSplit(text2)
	return difflib.ndiff(words1, words2, linejunk=None, charjunk=None)


def formatDiff(diff: "Iterator[str]") -> str:
	res = ""
	for part in diff:
		if part[0] == " ":
			res += part[2:]
			continue
		if part[0] == "?":
			continue
		color: str
		if part[0] == "-":
			color = red
		elif part[0] == "+":
			color = green
		else:
			raise ValueError(f"invalid diff part: {part!r}")
		text = part[2:]
		colored = color + text + reset

		if os.getenv("BAD_BIDI_SUPPORT"):
			wsSet = getAllWritingSystemsFromText(text)
			if "Arabic" in wsSet:
				colored = "\n" + colored + "\n"

		res += colored
	return res


def main_word_split() -> None:
	text = sys.argv[1]
	print(text)
	for word in xmlWordSplit(text):
		print(f"word: {word!r}")


def main() -> None:
	filename1 = sys.argv[1]
	filename2 = sys.argv[2]
	with open(filename1, mode="r", encoding="utf-8") as _file:
		text1 = _file.read()
	with open(filename2, mode="r", encoding="utf-8") as _file:
		text2 = _file.read()
	print(formatDiff(xmlDiff(text1, text2)))


if __name__ == "__main__":
	main()
