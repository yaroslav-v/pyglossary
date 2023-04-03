# DO NOT RUN THIS, IT REMOVES COMMENTS

import sys
from collections import OrderedDict
from os.path import abspath, dirname, join
from pathlib import Path

import toml

rootDir = dirname(dirname(abspath(__file__)))
sys.path.insert(0, rootDir)

from pyglossary.core import userPluginsDir
from pyglossary.glossary import Glossary

Glossary.init(
	# usePluginsJson=False,
)


userPluginsDirPath = Path(userPluginsDir)
plugins = [
	p
	for p in Glossary.plugins.values()
]

toolsDir = join(rootDir, "plugins-meta", "tools")


for p in plugins:
	toolsFile = join(toolsDir, f"{p.lname}.toml")
	try:
		with open(toolsFile, encoding="utf-8") as _file:
			tools_toml = toml.load(_file, _dict=OrderedDict)
	except FileNotFoundError:
		continue
	except Exception as e:
		print(f"\nFile: {toolsFile}")
		raise e
	with  open(toolsFile, mode="w", encoding="utf-8", newline="\n") as _file:
		toml.dump(tools_toml, _file)
