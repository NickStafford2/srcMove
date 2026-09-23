from __future__ import annotations

import unittest

from performance.startup_study import (
    _parse_ldd,
    _parse_loader_statistics,
    _parse_needed,
)


class StartupStudyParsingTests(unittest.TestCase):
    def test_parses_direct_needed_libraries(self) -> None:
        text = """
 0x0000000000000001 (NEEDED) Shared library: [libsrcreader.so]
 0x0000000000000001 (NEEDED) Shared library: [libxml2.so.2]
"""
        self.assertEqual(
            _parse_needed(text), ["libsrcreader.so", "libxml2.so.2"]
        )

    def test_parses_loaded_library_closure(self) -> None:
        text = """
linux-vdso.so.1 (0x00007fff)
libsrcml.so.1 => /workspace/srcML-install/lib/libsrcml.so.1 (0x001)
/lib64/ld-linux-x86-64.so.2 (0x002)
"""
        self.assertEqual(
            _parse_ldd(text), ["ld-linux-x86-64.so.2", "libsrcml.so.1"]
        )

    def test_parses_loader_statistics(self) -> None:
        text = """
  11: total startup time in dynamic loader: 6656188 cycles
  11: time needed for relocation: 396880 cycles (5.9%)
  11: number of relocations: 2806
  11: time needed to load objects: 6106102 cycles (91.7%)
"""
        self.assertEqual(
            _parse_loader_statistics(text),
            {
                "startup_cycles": 6656188,
                "relocation_cycles": 396880,
                "relocations": 2806,
                "load_object_cycles": 6106102,
            },
        )


if __name__ == "__main__":
    unittest.main()
