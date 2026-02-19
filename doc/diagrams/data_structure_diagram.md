Data structure diagram 
Purpose: justify speed and scaling.


Construct record
* id
* kind (include, function, block, stmt, etc.)
* file path + position range
* size metrics (tokens/nodes/span)
* canonical form (for Type-2 normalization)
* hash (sha1 raw, sha1 normalized)
* context features (parent kind, surrounding scope)

Indices
* unordered_multimap sha1 -> construct ids
* unordered_multimap normalized_sha1 -> construct ids
* optional: bucket maps by size range, by kind

Move registry

* move_id
* deleted_construct_id
* inserted_construct_id
* probability score
* reason codes (hash_match, include_sort, extract_method, etc.)

This diagram reassures them you’re not doing quadratic matching.

