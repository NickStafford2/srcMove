One-page pipeline diagram 
Purpose: show end-to-end flow from srcDiff output to “moves annotated”.

Layout (left to right):

Input

* srcDiff output (XML / edit stream)
* optional metadata (file paths, directory distance)

Phase A: parse and index

* srcReader parses srcDiff into constructs
* normalize construct representation (your Type-1/Type-2 handling)
* compute fast fingerprints (SHA-1) and features
* create indices:

  * deleted_index: hash -> list of deleted constructs
  * inserted_index: hash -> list of inserted constructs
  * optional: size buckets, construct type buckets

Phase B: candidate generation (fast)

* for each inserted construct, lookup matching deleted candidates via unordered_multimap
* prune with cheap filters:

  * construct type match
  * size thresholds
  * max distance window (tree distance / file distance)
  * ignore noisy constructs (optional)

Phase C: scoring and probability

* compute move probability P(move | features)
* features you named:

  * hash match / near match (Type-1 vs Type-2)
  * tree distance / locality
  * size of construct
  * directory distance
  * developer-behavior heuristics (alphabetized includes, extracted function pattern)
* threshold decision:

  * if P >= T, mark as move
  * else leave as insert + delete

Output

* srcDiff with move annotations (move registry written back)
* optional: refactor labels (extract-method, include-reorder, etc.)

Put time complexity notes in the corner:

* O(N) parsing
* O(N) indexing
* O(K) candidate scoring where K is reduced by hashing + pruning

This diagram will immediately communicate “fast first, expensive later”, which is exactly what you want.

