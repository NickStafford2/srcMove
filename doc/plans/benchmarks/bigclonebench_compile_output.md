I ran make bigclonebench-compile on 2026-08-21. on commit 6997fca
```

```
dev@58b83fafe8d6:/workspace/srcMove$ make bigclonebench-compile
BigCloneBench compile: full external pair frame
data_root=/workspace/srcMove/benchmark-data
✓ compile/export working in 08:06 — exported positive and known-false-positive rows
✓ compile/import 8648734/8648734 100% in 1:00:13 — 8,375,313 positive, 273,421 known false positive, 71,933 functions
✓ compile/fragments 73501/73501 100% in 06:45 — 60,850 unique fragments
✓ compile/pairs 8648734/8648734 100% in 15:13 — identities assigned
✓ compile/index 1/1 100% in 04:42 — read indexes built
✓ compile/finalize 1/1 100% in 1:19:44 — published and fully validated
dataset_id=bcb-dataset-sha256-bdee915912b126e9ec4f857560e01a7b70f30f988cd539a970cab029198dcc49
directory=/workspace/srcMove/benchmark-data/bigclonebench/compiled/bcb-dataset-sha256-bdee915912b126e9ec4f857560e01a7b70f30f988cd539a970cab029198dcc49
{
  "available_pairs": 8648734,
  "catalog_pair_rows": 8648734,
  "duplicate_source_rows": 0,
  "extracted_functions": 73501,
  "extraction_failures": 0,
  "function_materializations": 73501,
  "functions": 71933,
  "known_false_positive_source_rows": 273421,
  "positive_negative_label_conflicts": 242,
  "positive_source_rows": 8375313,
  "source_files": 53645,
  "unique_fragments": 60850,
  "unique_ordered_pairs": 6278280,
  "unique_unordered_pairs": 6011979
}
```
```
