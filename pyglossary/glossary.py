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

from time import time as now
from typing import Any, Dict, Optional

from .core import log
from .glossary_v2 import Glossary as GlossaryV2
from .sort_keys import lookupSortKey


class Glossary(GlossaryV2):
	def read(
		self,
		filename: str,
		format: str = "",
		direct: bool = False,
		**kwargs,  # noqa: ANN
	) -> bool:
		"""
		filename (str):	name/path of input file
		format (str):	name of input format,
						or "" to detect from file extension
		direct (bool):	enable direct mode
		progressbar (bool): enable progressbar

		read-options can be passed as additional keyword arguments
		"""
		if type(filename) is not str:
			raise TypeError("filename must be str")
		if format is not None and type(format) is not str:
			raise TypeError("format must be str")

		# don't allow direct=False when there are readers
		# (read is called before with direct=True)
		if self._readers and not direct:
			raise ValueError(
				f"there are already {len(self._readers)} readers"
				f", you can not read with direct=False mode",
			)

		self._setTmpDataDir(filename)

		ok = self._read(
			filename=filename,
			format=format,
			direct=direct,
			**kwargs,
		)
		if not ok:
			return False

		self.detectLangsFromName()
		return True

	def sortWords(
		self,
		sortKeyName: "str" = "headword_lower",
		sortEncoding: "str" = "utf-8",
		writeOptions: "Optional[Dict[str, Any]]" = None,
	) -> None:
		"""
			sortKeyName: see doc/sort-key.md
		"""
		if self._readers:
			raise NotImplementedError(
				"can not use sortWords in direct mode",
			)

		if self._sqlite:
			raise NotImplementedError(
				"can not use sortWords in SQLite mode",
			)

		namedSortKey = lookupSortKey(sortKeyName)
		if namedSortKey is None:
			log.critical(f"invalid {sortKeyName = }")
			return

		if not sortEncoding:
			sortEncoding = "utf-8"
		if writeOptions is None:
			writeOptions = {}

		t0 = now()
		self._data.setSortKey(
			namedSortKey=namedSortKey,
			sortEncoding=sortEncoding,
			writeOptions=writeOptions,
		)
		self._data.sort()
		log.info(f"Sorting took {now() - t0:.1f} seconds")

		self._sort = True
		self._updateIter()
