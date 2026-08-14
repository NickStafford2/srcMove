cd benchmarks/repositories/notepadpp/work
➜ work git:(main) ll
total 36
drwxrwxr-x 5 nick nick 4096 Mar 6 08:40 ./
drwxr-xr-x 3 nick nick 4096 Mar 13 06:53 ../
-rw-rw-r-- 1 nick nick 169 Mar 6 08:40 diff_new.xml
-rw-rw-r-- 1 nick nick 334 Mar 6 08:40 diff.xml
drwxrwxr-x 7 nick nick 4096 Mar 6 08:40 modified/
drwxrwxr-x 7 nick nick 4096 Mar 6 08:40 original/
drwxrwxr-x 8 nick nick 4096 Mar 6 08:40 repo/
-rw-rw-r-- 1 nick nick 906 Mar 6 08:40 report.json
-rw-rw-r-- 1 nick nick 134 Mar 6 08:40 results.json
➜ work git:(main) srcml original -o original.srcml.xml
➜ work git:(main) srcdiff original modified -o notepadpp.diff.xml

- original|modified
- original/.gitignore|modified/.gitignore
- original/BUILD.md|modified/BUILD.md
- original/CONTRIBUTING.md|modified/CONTRIBUTING.md
- original/LICENSE|modified/LICENSE
- original/README.md|modified/README.md
- original/SUPPORTED_SYSTEM.md|modified/SUPPORTED_SYSTEM.md
- original/appveyor.yml|modified/appveyor.yml
- original/nppGpgPub.asc|modified/nppGpgPub.asc
  ... dozens of lines here
- original/PowerEditor/Test/xmlValidator/contextMenu.xsd|modified/PowerEditor/Test/xmlValidator/contextMenu.xsd
- original/PowerEditor/Test/xmlValidator/functionList.xsd|modified/PowerEditor/Test/xmlValidator/functionList.xsd
- original/PowerEditor/Test/xmlValidator/langs.xsd|modified/PowerEditor/Test/xmlValidator/langs.xsd
- original/PowerEditor/Test/xmlValidator/nativeLang.xsd|modified/PowerEditor/Test/xmlValidator/nativeLang.xsd
- original/PowerEditor/Test/xmlValidator/shortcuts.xsd|modified/PowerEditor/Test/xmlValidator/shortcuts.xsd
- original/PowerEditor/Test/xmlValidator/tabContext.xsd|modified/PowerEditor/Test/xmlValidator/tabContext.xsd
- original/PowerEditor/Test/xmlValidator/theme.xsd|modified/PowerEditor/Test/xmlValidator/theme.xsd
- original/PowerEditor/Test/xmlValidator/toolbarButtons.xsd|modified/PowerEditor/Test/xmlValidator/toolbarButtons.xsd
  1 original/PowerEditor/Test/xmlValidator/validator_xml.py|modified/PowerEditor/Test/xmlValidator/validator_xml.py
  Error: vector::\_M_range_check: \_\_n (which is 5032) >= this->size() (which is 5032)
