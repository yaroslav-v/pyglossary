# -*- coding: utf-8 -*-
# glossary.py
#
# Copyright © 2008-2022 Saeed Rasooli <saeed.gnu@gmail.com> (ilius)
# This file is part of PyGlossary project, https://github.com/ilius/pyglossary
#
# This program is a free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program. Or on Debian systems, from /usr/share/common-licenses/GPL
# If not, see <http://www.gnu.org/licenses/gpl.txt>.

import logging
import os
import os.path
from collections import OrderedDict as odict
from contextlib import suppress
from dataclasses import dataclass
from os.path import (
	isdir,
	isfile,
	join,
	relpath,
)
from time import time as now
from typing import (
	TYPE_CHECKING,
	Any,
	Callable,
	Dict,
	Iterator,
	Optional,
	Tuple,
	Type,
)

from . import core
from .core import (
	cacheDir,
)
from .entry import DataEntry, Entry
from .entry_filters import (
	EntryFilterType,
	PreventDuplicateWords,
	RemoveHtmlTagsAll,
	ShowMaxMemoryUsage,
	ShowProgressBar,
	StripFullHtml,
	entryFiltersRules,
)
from .entry_list import EntryList
from .flags import (
	ALWAYS,
	DEFAULT_YES,
	NEVER,
)
from .glossary_info import GlossaryInfo
from .glossary_progress import GlossaryProgress
from .glossary_type import EntryType, GlossaryExtendedType
from .glossary_utils import splitFilenameExt
from .info import c_name
from .os_utils import rmtree, showMemoryUsage
from .plugin_manager import PluginManager
from .sort_keys import defaultSortKeyName, lookupSortKey

if TYPE_CHECKING:
	# from .flags import StrWithDesc
	from .plugin_prop import PluginProp
	from .sort_keys import NamedSortKey
	from .ui_type import UIType


log = logging.getLogger("pyglossary")


"""
sortKeyType = Callable[
	[[list[str]],
	Any,
]
"""


@dataclass(frozen=True)
class ConvertArgs:
	inputFilename: str
	inputFormat: str = ""
	direct: "Optional[bool]" = None
	outputFilename: str = ""
	outputFormat: str = ""
	sort: "Optional[bool]" = None
	sortKeyName: "Optional[str]" = None
	sortEncoding: "Optional[str]" = None
	readOptions: "Optional[Dict[str, Any]]" = None
	writeOptions: "Optional[Dict[str, Any]]" = None
	sqlite: "Optional[bool]" = None
	infoOverride: "Optional[Dict[str, str]]" = None


class Glossary(GlossaryInfo, GlossaryProgress, PluginManager, GlossaryExtendedType):
	GLOSSARY_API_VERSION = "2.0"

	"""
	The signature of 'convert' method is different in glossary_v2.py
		See help(Glossary.convert)

	addEntryObj is renamed to addEntry in glossary_v2.py

	These methods do not exist in glossary_v2.py (but still exist in glossary.py)

		- read(): you can use directRead() then iterate over glossary

		- sortWords(): you have to sort entries yourself (when adding or after directRead)

		- updateIter(): no longer needed, and doens't do anything in glossary.py

	"""

	def _closeReaders(self) -> None:
		for reader in self._readers:
			try:
				reader.close()
			except Exception:
				log.exception("")

	def clear(self) -> None:
		GlossaryProgress.clear(self)
		self._info = odict()

		self._data.clear()

		readers = getattr(self, "_readers", [])
		for reader in readers:
			try:
				reader.close()
			except Exception:
				log.exception("")
		self._readers: "list[Any]" = []
		self._defiHasWordTitle = False

		self._iter: "Optional[Iterator[EntryType]]" = None
		self._entryFilters: "list[EntryFilterType]" = []
		self._entryFiltersName: "set[str]" = set()
		self._sort = False

		self._filename = ""
		self._defaultDefiFormat = "m"
		self._tmpDataDir = ""

	def __init__(
		self,
		info: "Optional[Dict[str, str]]" = None,
		ui: "Optional[UIType]" = None,  # noqa: F821
	) -> None:
		"""
		info:	OrderedDict or dict instance, or None
				no need to copy OrderedDict instance before passing here
				we will not reference to it
		"""
		GlossaryInfo.__init__(self)
		GlossaryProgress.__init__(self, ui=ui)
		self._config: "Dict[str, Any]" = {}
		self._data = EntryList(self)
		self._sqlite = False
		self._rawEntryCompress = False
		self._cleanupPathList: "set[str]" = set()
		self.clear()
		if info:
			if not isinstance(info, (dict, odict)):
				raise TypeError(
					"Glossary: `info` has invalid type"
					", dict or OrderedDict expected",
				)
			for key, value in info.items():
				self.setInfo(key, value)

	def cleanup(self) -> None:
		if not self._cleanupPathList:
			return
		if not self._config.get("cleanup", True):
			log.info("Not cleaning up files:")
			log.info("\n".join(self._cleanupPathList))
			return
		for cleanupPath in self._cleanupPathList:
			if isfile(cleanupPath):
				log.debug(f"Removing file {cleanupPath}")
				try:
					os.remove(cleanupPath)
				except Exception:
					log.exception(f"error removing {cleanupPath}")
			elif isdir(cleanupPath):
				log.debug(f"Removing directory {cleanupPath}")
				rmtree(cleanupPath)
			else:
				log.error(f"no such file or directory: {cleanupPath}")
		self._cleanupPathList = set()

	@property
	def rawEntryCompress(self) -> bool:
		return self._rawEntryCompress

	def setRawEntryCompress(self, enable: bool) -> None:
		self._rawEntryCompress = enable

	def updateEntryFilters(self) -> None:
		entryFilters = []
		config = self._config

		for configParam, default, filterClass in entryFiltersRules:
			args = []
			if configParam is None:
				value = default
			else:
				value = config.get(configParam, default)
			if not value:
				continue
			if not isinstance(default, bool):
				args = [value]
			entryFilters.append(filterClass(self, *tuple(args)))

		if self.progressbar:
			entryFilters.append(ShowProgressBar(self))

		if log.level <= core.TRACE:
			try:
				import psutil  # noqa: F401
			except ModuleNotFoundError:
				pass
			else:
				entryFilters.append(ShowMaxMemoryUsage(self))

		self._entryFilters = entryFilters

		self._entryFiltersName = {
			entryFilter.name
			for entryFilter in entryFilters
		}

	def prepareEntryFilters(self) -> None:
		"""
			call .prepare() method on all _entryFilters
			run this after glossary info is set and ready
			for most entry filters, it won't do anything
		"""
		for entryFilter in self._entryFilters:
			entryFilter.prepare()

	def _addExtraEntryFilter(self, cls: "Type[EntryFilterType]") -> None:
		if cls.name in self._entryFiltersName:
			return
		self._entryFilters.append(cls(self))
		self._entryFiltersName.add(cls.name)

	def removeHtmlTagsAll(self) -> None:
		"""
		Remove all HTML tags from definition

		This should only be called from a plugin's Writer.__init__ method.
		Does not apply on entries added with glos.addEntry
		"""
		self._addExtraEntryFilter(RemoveHtmlTagsAll)

	def stripFullHtml(
		self,
		errorHandler: "Optional[Callable[[EntryType, str], None]]" = None,
	):
		"""
		Adds entry filter "strip_full_html"
		to replace a full HTML document with it's body in entry definition
		"""
		name = StripFullHtml.name
		if name in self._entryFiltersName:
			return
		self._entryFilters.append(StripFullHtml(
			self,
			errorHandler=errorHandler,
		))
		self._entryFiltersName.add(name)

	def preventDuplicateWords(self) -> None:
		"""
		Adds entry filter to prevent duplicate `entry.s_word`

		This should only be called from a plugin's Writer.__init__ method.
		Does not apply on entries added with glos.addEntry

		Note: there may be still duplicate headwords or alternate words
			but we only care about making the whole `entry.s_word`
			(aka entry key) unique
		"""
		self._addExtraEntryFilter(PreventDuplicateWords)

	def __str__(self) -> str:
		return (
			"Glossary{"
			f"filename: {self._filename!r}"
			f", name: {self._info.get('name')!r}"
			"}"
		)

	def _loadedEntryGen(self) -> "Iterator[EntryType]":
		if not self.progressbar:
			yield from self._data
			return

		pbFilter = ShowProgressBar(self)
		self.progressInit("Writing")
		for entry in self._data:
			pbFilter.run(entry)
			yield entry
		self.progressEnd()

	def _readersEntryGen(self) -> "Iterator[EntryType]":
		for reader in self._readers:
			self.progressInit("Converting")
			try:
				yield from self._applyEntryFiltersGen(reader)
			finally:
				reader.close()
			self.progressEnd()

	# This iterator/generator does not give None entries.
	# And Entry is not falsable, so bool(entry) is always True.
	# Since ProgressBar is already handled with an EntryFilter, there is
	# no point of returning None entries anymore.
	def _applyEntryFiltersGen(
		self,
		gen: "Iterator[EntryType]",
	) -> "Iterator[EntryType]":
		entry: "Optional[EntryType]"
		for entry in gen:
			if entry is None:
				continue
			for entryFilter in self._entryFilters:
				entry = entryFilter.run(entry)
				if entry is None:
					break
			else:
				yield entry

	def __iter__(self) -> "Iterator[EntryType]":
		if self._iter is not None:
			return self._iter

		if not self._readers:
			return self._loadedEntryGen()

		log.error("Glossary: iterator is not set in direct mode")
		return iter([])

	# TODO: switch to @property defaultDefiFormat
	def setDefaultDefiFormat(self, defiFormat: str) -> None:
		"""
		defiFormat must be empty or one of these:
			"m": plain text
			"h": html
			"x": xdxf
		"""
		self._defaultDefiFormat = defiFormat

	def getDefaultDefiFormat(self) -> str:
		return self._defaultDefiFormat

	def collectDefiFormat(
		self,
		maxCount: int,
	) -> "Optional[Dict[str, float]]":
		"""
			example return value:
				[("h", 0.91), ("m", 0.09)]
		"""
		from collections import Counter
		readers = self._readers
		if readers:
			log.error("collectDefiFormat: not supported in direct mode")
			return None

		counter: "Dict[str, int]" = Counter()
		count = 0
		for entry in self:
			if entry.isData():
				continue
			entry.detectDefiFormat()
			counter[entry.defiFormat] += 1
			count += 1
			if count >= maxCount:
				break

		result = {
			defiFormat: itemCount / count
			for defiFormat, itemCount in counter.items()
		}
		for defiFormat in ("h", "m", "x"):
			if defiFormat not in result:
				result[defiFormat] = 0

		self._iter = self._loadedEntryGen()

		return result

	def __len__(self) -> int:
		return len(self._data) + sum(
			len(reader) for reader in self._readers
		)

	@property
	def config(self) -> "Dict[str, Any]":
		raise NotImplementedError

	@config.setter
	def config(self, config: "Dict[str, Any]") -> None:
		if self._config:
			log.error("glos.config is set more than once")
			return
		self._config = config
		if "optimize_memory" in config:
			self._rawEntryCompress = config["optimize_memory"]

	@property
	def alts(self) -> bool:
		return self._config.get("enable_alts", True)

	@property
	def filename(self) -> str:
		return self._filename

	@property
	def tmpDataDir(self) -> str:
		if not self._tmpDataDir:
			self._setTmpDataDir(self._filename)
		return self._tmpDataDir

	def wordTitleStr(
		self,
		word: str,
		sample: str = "",
		_class: str = "",
	) -> str:
		"""
		notes:
			- `word` needs to be escaped before passing
			- `word` can contain html code (multiple words, colors, etc)
			- if input format (reader) indicates that words are already included
				in definition (as title), this method will return empty string
			- depending on glossary's `sourceLang` or writing system of `word`,
				(or sample if given) either '<b>' or '<big>' will be used
		"""
		if self._defiHasWordTitle:
			return ""
		if not word:
			return ""
		if not sample:
			sample = word
		tag = self._getTitleTag(sample)
		if _class:
			return f'<{tag} class="{_class}">{word}</{tag}><br>'
		return f'<{tag}>{word}</{tag}><br>'

	def getConfig(self, name: str, default: "Optional[str]") -> "Optional[str]":
		return self._config.get(name, default)

	def addEntry(self, entry: "EntryType") -> None:
		self._data.append(entry)

	def newEntry(
		self,
		word: str,
		defi: str,
		defiFormat: str = "",
		byteProgress: "Optional[Tuple[int, int]]" = None,
	) -> "Entry":
		"""
		create and return a new entry object

		defiFormat must be empty or one of these:
			"m": plain text
			"h": html
			"x": xdxf
		"""
		if not defiFormat:
			defiFormat = self._defaultDefiFormat

		return Entry(
			word, defi,
			defiFormat=defiFormat,
			byteProgress=byteProgress,
		)

	def newDataEntry(self, fname: str, data: bytes) -> "DataEntry":
		import uuid

		if self._readers:
			return DataEntry(fname, data)

		if self._tmpDataDir:
			return DataEntry(
				fname,
				data,
				tmpPath=join(self._tmpDataDir, fname.replace("/", "_")),
			)

		tmpDir = join(cacheDir, "tmp")
		os.makedirs(tmpDir, mode=0o700, exist_ok=True)
		self._cleanupPathList.add(tmpDir)
		return DataEntry(
			fname,
			data,
			tmpPath=join(tmpDir, uuid.uuid1().hex),
		)

	# ________________________________________________________________________#

	# def _hasWriteAccessToDir(self, dirPath: str) -> None:
	# 	if isdir(dirPath):
	# 		return os.access(dirPath, os.W_OK)
	# 	return os.access(os.path.dirname(dirPath), os.W_OK)

	def _createReader(self, format: str, options: "Dict[str, Any]") -> "Any":
		readerClass = self.plugins[format].readerClass
		if readerClass is None:
			log.critical("_createReader: readerClass is None")
			return None
		reader = readerClass(self)
		for name, value in options.items():
			setattr(reader, f"_{name}", value)
		return reader

	def _setTmpDataDir(self, filename: str) -> None:
		import uuid
		# good thing about cacheDir is that we don't have to clean it up after
		# conversion is finished.
		# specially since dataEntry.save(...) will move the file from cacheDir
		# to the new directory (associated with output glossary path)
		# And we don't have to check for write access to cacheDir because it's
		# inside user's home dir. But input glossary might be in a directory
		# that we don't have write access to.
		# still maybe add a config key to decide if we should always use cacheDir
		# if self._hasWriteAccessToDir(f"{filename}_res", os.W_OK):
		# 	self._tmpDataDir = f"{filename}_res"
		# else:
		if not filename:
			filename = uuid.uuid1().hex
		self._tmpDataDir = join(cacheDir, os.path.basename(filename) + "_res")
		log.debug(f"tmpDataDir = {self._tmpDataDir}")
		os.makedirs(self._tmpDataDir, mode=0o700, exist_ok=True)
		self._cleanupPathList.add(self._tmpDataDir)

	def _validateReadoptions(
		self,
		format: str,
		options: "Dict[str, Any]",
	) -> None:
		validOptionKeys = set(self.formatsReadOptions[format].keys())
		for key in list(options.keys()):
			if key not in validOptionKeys:
				log.error(
					f"Invalid read option {key!r} "
					f"given for {format} format",
				)
				del options[key]

	def _openReader(self, reader: "Any", filename: str) -> bool:
		# reader.open returns "Optional[Iterator[Tuple[int, int]]]"
		progressbar: bool = self.progressbar
		try:
			openResult = reader.open(filename)
			if openResult is not None:
				self.progressInit("Reading metadata")
				lastPos = -100_000
				for pos, total in openResult:
					if progressbar and pos - lastPos > 100_000:
						self.progress(pos, total, unit="bytes")
						lastPos = pos
				self.progressEnd()
		except (FileNotFoundError, LookupError) as e:
			log.critical(str(e))
			return False
		except Exception:
			log.exception("")
			return False

		hasTitleStr = self._info.get("definition_has_headwords", "")
		if hasTitleStr:
			if hasTitleStr.lower() == "true":
				self._defiHasWordTitle = True
			else:
				log.error(f"bad info value: definition_has_headwords={hasTitleStr!r}")
		return True

	def directRead(
		self,
		filename: str,
		format: str = "",
		**options,  # noqa: ANN
	) -> bool:
		self._setTmpDataDir(filename)
		return self._read(
			filename=filename,
			format=format,
			direct=True,
			**options,
		)

	def _read(
		self,
		filename: str,
		format: str = "",
		direct: bool = False,
		**options,  # noqa: ANN
	) -> bool:
		filename = os.path.abspath(filename)
		###
		inputArgs = self.detectInputFormat(filename, format=format)
		if inputArgs is None:
			return False
		origFilename = filename
		filename, format, compression = inputArgs

		if compression:
			from pyglossary.compression import uncompress
			uncompress(origFilename, filename, compression)

		self._validateReadoptions(format, options)

		filenameNoExt, ext = os.path.splitext(filename)
		if ext.lower() not in self.plugins[format].extensions:
			filenameNoExt = filename

		self._filename = filenameNoExt
		if not self._info.get(c_name):
			self._info[c_name] = os.path.split(filename)[1]

		self.updateEntryFilters()

		reader = self._createReader(format, options)
		if not self._openReader(reader, filename):
			return False

		self.prepareEntryFilters()

		if not direct:
			self.loadReader(reader)
			self._iter = self._loadedEntryGen()
			return True

		self._readers.append(reader)
		self._iter = self._readersEntryGen()

		return True

	def loadReader(self, reader: "Any") -> None:
		"""
		iterates over `reader` object and loads the whole data into self._data
		must call `reader.open(filename)` before calling this function
		"""
		showMemoryUsage()

		self.progressInit("Reading")
		try:
			for entry in self._applyEntryFiltersGen(reader):
				self.addEntry(entry)
		finally:
			reader.close()

		self.progressEnd()

		log.trace(f"Loaded {len(self._data)} entries")
		showMemoryUsage()

	def _createWriter(
		self,
		format: str,
		options: "Dict[str, Any]",
	) -> "Any":
		validOptions = self.formatsWriteOptions.get(format)
		if validOptions is None:
			log.critical(f"No write support for {format!r} format")
			return None
		validOptionKeys = list(validOptions.keys())
		for key in list(options.keys()):
			if key not in validOptionKeys:
				log.error(
					f"Invalid write option {key!r}"
					f" given for {format} format",
				)
				del options[key]

		writerClass = self.plugins[format].writerClass
		if writerClass is None:
			log.critical("_createWriter: writerClass is None")
			return None
		writer = writerClass(self)
		for name, value in options.items():
			setattr(writer, f"_{name}", value)
		return writer

	def write(
		self,
		filename: str,
		format: str,
		**kwargs,  # noqa: ANN
	) -> "Optional[str]":
		"""
		filename (str): file name or path to write

		format (str): format name

		sort (bool):
			True (enable sorting),
			False (disable sorting),
			None (auto, get from UI)

		sortKeyName (str or None):
			key function name for sorting

		sortEncoding (str or None):
			encoding for sorting, default utf-8

		You can pass write-options (of given format) as keyword arguments

		returns absolute path of output file, or None if failed
		"""
		if type(filename) is not str:
			raise TypeError("filename must be str")
		if format is not None and type(format) is not str:
			raise TypeError("format must be str")

		return self._write(
			filename=filename,
			format=format,
			**kwargs,
		)

	def _writeEntries(
		self,
		writerList: "list[Any]",
		filename: str,
	) -> None:
		writer = writerList[0]
		genList = []
		gen = writer.write()
		if gen is None:
			log.error(f"{format} write function is not a generator")
		else:
			genList.append(gen)

		if self._config.get("save_info_json", False):
			infoWriter = self._createWriter("Info", {})
			filenameNoExt, _, _, _ = splitFilenameExt(filename)
			infoWriter.open(f"{filenameNoExt}.info")
			genList.append(infoWriter.write())
			writerList.append(infoWriter)

		for gen in genList:
			gen.send(None)
		for entry in self:
			for gen in genList:
				gen.send(entry)
		# suppress() on the whole for-loop does not work
		for gen in genList:
			with suppress(StopIteration):
				gen.send(None)

	def _openWriter(
		self,
		writer: "Any",
		filename: str,
	) -> bool:
		try:
			writer.open(filename)
		except (FileNotFoundError, LookupError) as e:
			log.critical(str(e))
			return False
		except Exception:
			log.exception("")
			return False
		return True

	def _write(
		self,
		filename: str,
		format: str,
		sort: bool = False,
		**options,  # noqa: ANN
	) -> "Optional[str]":
		filename = os.path.abspath(filename)

		if format not in self.plugins or not self.plugins[format].canWrite:
			log.critical(f"No Writer class found for plugin {format}")
			return None

		if self._readers and sort:
			log.warning(
				"Full sort enabled, falling back to indirect mode",
			)
			for reader in self._readers:
				self.loadReader(reader)
			self._readers = []

		log.info(f"Writing to {format} file {filename!r}")

		writer = self._createWriter(format, options)

		self._sort = sort

		if sort:
			t0 = now()
			self._data.sort()
			log.info(f"Sorting took {now() - t0:.1f} seconds")

		if self._readers:
			self._iter = self._readersEntryGen()
		else:
			self._iter = self._loadedEntryGen()
		if not self._openWriter(writer, filename):
			return None

		showMemoryUsage()

		writerList = [writer]
		try:
			self._writeEntries(writerList, filename)
		except (FileNotFoundError, LookupError) as e:
			log.critical(str(e))
			return None
		except Exception:
			log.exception("Exception while calling plugin\'s write function")
			return None
		finally:
			showMemoryUsage()
			log.debug("Running writer.finish()")
			for writer in writerList:
				writer.finish()
			self.clear()

		showMemoryUsage()

		return filename

	def _compressOutput(self, filename: str, compression: str) -> str:
		from pyglossary.compression import compress
		return compress(self, filename, compression)

	def _switchToSQLite(
		self,
		inputFilename: str,
		outputFormat: str,
	) -> None:
		from pyglossary.sq_entry_list import SqEntryList

		sq_fpath = join(cacheDir, f"{os.path.basename(inputFilename)}.db")
		if isfile(sq_fpath):
			log.info(f"Removing and re-creating {sq_fpath!r}")
			os.remove(sq_fpath)

		self._data = SqEntryList(
			self,
			sq_fpath,
			create=True,
			persist=True,
		)
		self._rawEntryCompress = False
		self._cleanupPathList.add(sq_fpath)

		if not self.alts:
			log.warning(
				"SQLite mode only works with enable_alts=True"
				", force-enabling it.",
			)
		self._config["enable_alts"] = True
		self._sqlite = True

	def _checkSortFlag(
		self,
		plugin: "PluginProp",
		sort: "Optional[bool]",
	) -> "Optional[bool]":
		sortOnWrite = plugin.sortOnWrite
		if sortOnWrite == ALWAYS:
			if sort is False:
				log.warning(
					f"Writing {plugin.name} requires sorting"
					f", ignoring user sort=False option",
				)
			return True

		if sortOnWrite == NEVER:
			if sort:
				log.warning(
					"Plugin prevents sorting before write"
					", ignoring user sort=True option",
				)
			return False

		if sortOnWrite == DEFAULT_YES:
			return sort or sort is None

		# if sortOnWrite == DEFAULT_NO:
		return bool(sort)

	def _resolveSortParams(
		self,
		args: ConvertArgs,
		plugin: "PluginProp",
	) -> "Optional[Tuple[bool, bool]]":
		"""
			sortKeyName: see doc/sort-key.md

			returns (sort, direct) or None if fails
		"""
		if args.direct and args.sqlite:
			raise ValueError(
				f"Conflictng arguments: direct={args.direct}, "
				f"sqlite={args.sqlite}",
			)

		sort = self._checkSortFlag(plugin, args.sort)

		if not sort:
			if args.direct is None:
				return True, False
			return args.direct, False

		# from this point we can assume sort == True and direct == False

		sqlite = args.sqlite
		if sqlite is None:
			sqlite = self._config.get("auto_sqlite", True)
			if sqlite:
				log.info(
					"Automatically switching to SQLite mode"
					f" for writing {plugin.name}",
				)

		sortKeyTuple = self._checkSortKey(
			plugin,
			args.sortKeyName,
			args.sortEncoding,
		)
		if sortKeyTuple is None:
			return None
		namedSortKey, sortEncoding = sortKeyTuple

		if sqlite:
			self._switchToSQLite(
				inputFilename=args.inputFilename,
				outputFormat=plugin.name,
			)

		self._data.setSortKey(
			namedSortKey=namedSortKey,
			sortEncoding=sortEncoding,
			writeOptions=args.writeOptions or {},
		)

		return False, True

	def _checkSortKey(
		self,
		plugin: "PluginProp",
		sortKeyName: "Optional[str]",
		sortEncoding: "Optional[str]",
	) -> "Optional[Tuple[NamedSortKey, str]]":
		"""
			checks sortKeyName, sortEncoding and (output) plugin's params
			returns (namedSortKey, sortEncoding) or None
		"""
		writerSortKeyName = plugin.sortKeyName
		writerSortEncoding = getattr(plugin, "sortEncoding", None)
		if plugin.sortOnWrite == ALWAYS:
			if not writerSortKeyName:
				log.critical("No sortKeyName was found in plugin")
				return None

			if sortKeyName and sortKeyName != writerSortKeyName:
				log.warning(
					f"Ignoring user-defined sort order {sortKeyName!r}"
					f", and using sortKey function from {plugin.name} plugin",
				)
			sortKeyName = writerSortKeyName

			if writerSortEncoding:
				sortEncoding = writerSortEncoding
		elif not sortKeyName:
			if writerSortKeyName:
				sortKeyName = writerSortKeyName
			else:
				sortKeyName = defaultSortKeyName

		namedSortKey = lookupSortKey(sortKeyName)
		if namedSortKey is None:
			log.critical(f"invalid {sortKeyName = }")
			return None

		log.info(f"Using sortKeyName = {namedSortKey.name!r}")

		if not sortEncoding:
			sortEncoding = "utf-8"

		return namedSortKey, sortEncoding

	def _convertValidateStrings(self, args: ConvertArgs):
		if type(args.inputFilename) is not str:
			raise TypeError("inputFilename must be str")
		if type(args.outputFilename) is not str:
			raise TypeError("outputFilename must be str")

		if args.inputFormat is not None and type(args.inputFormat) is not str:
			raise TypeError("inputFormat must be str")
		if args.outputFormat is not None and type(args.outputFormat) is not str:
			raise TypeError("outputFormat must be str")

	def _convertPrepare(
		self,
		args: ConvertArgs,
		outputFilename: str = "",
		outputFormat: str = "",
	) -> "Optional[bool]":
		if isdir(outputFilename) and os.listdir(outputFilename):
			log.critical(
				f"Directory already exists and not empty: {relpath(outputFilename)}",
			)
			return None

		outputPlugin = self.plugins[outputFormat]

		sortParams = self._resolveSortParams(
			args=args,
			plugin=outputPlugin,
		)
		if sortParams is None:
			return None
		direct, sort = sortParams

		showMemoryUsage()

		self._setTmpDataDir(args.inputFilename)

		readOptions = args.readOptions or {}

		if not self._read(
			args.inputFilename,
			format=args.inputFormat,
			direct=direct,
			**readOptions,
		):
			log.critical(f"Reading file {relpath(args.inputFilename)!r} failed.")
			self.cleanup()
			return None

		self.detectLangsFromName()

		return sort

	def convert(self, args: ConvertArgs) -> "Optional[str]":
		"""
		returns absolute path of output file, or None if failed

		sortKeyName:
			name of sort key/algorithm
			defaults to `defaultSortKeyName` in sort_keys.py
			see doc/sort-key.md or sort_keys.py for other possible values
			This can also include sort locale after a colon sign, for example:
				sortKeyName=":fa_IR.UTF-8"
				sortKeyName="headword:fa_IR.UTF-8"

		sortEncoding:
			encoding/charset for sorting, default to utf-8
		"""
		self._convertValidateStrings(args)
		if args.outputFilename == args.inputFilename:
			log.critical("Input and output files are the same")
			return None

		tm0 = now()

		outputArgs = self.detectOutputFormat(
			filename=args.outputFilename,
			format=args.outputFormat,
			inputFilename=args.inputFilename,
		)
		if not outputArgs:
			log.critical(f"Writing file {relpath(args.outputFilename)!r} failed.")
			return None
		outputFilename, outputFormat, compression = outputArgs

		sort = self._convertPrepare(
			args=args,
			outputFilename=outputFilename,
			outputFormat=outputFormat,
		)
		if sort is None:
			return None

		if args.infoOverride:
			for key, value in args.infoOverride.items():
				self.setInfo(key, value)

		if compression and not self.plugins[outputFormat].singleFile:
			os.makedirs(outputFilename, mode=0o700, exist_ok=True)

		writeOptions = args.writeOptions or {}

		finalOutputFile = self._write(
			outputFilename,
			outputFormat,
			sort=sort,
			**writeOptions,
		)
		if not finalOutputFile:
			log.critical(f"Writing file {relpath(outputFilename)!r} failed.")
			self._closeReaders()
			self.cleanup()
			return None

		if compression:
			finalOutputFile = self._compressOutput(finalOutputFile, compression)

		log.info(f"Writing file {finalOutputFile!r} done.")
		log.info(f"Running time of convert: {now()-tm0:.1f} seconds")
		showMemoryUsage()
		self.cleanup()

		return finalOutputFile

	# ________________________________________________________________________#

	"""
	init method is inherited from PluginManager
	arguments:
		usePluginsJson: bool = True
		skipDisabledPlugins: bool = True

	init() must be called only once, so make sure you put it in the
	right place. Probably in the top of your program's main function or module.
	"""