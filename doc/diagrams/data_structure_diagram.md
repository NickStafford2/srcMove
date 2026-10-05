# srcMove data structures

This diagram shows the primary implemented types and the ownership boundary
between candidates, derived matching groups, annotation data, and JSON results.
It intentionally omits short-lived parsing stacks and profiling counters. See
[Architecture](../architecture.md) for behavior and selection semantics.

```mermaid
classDiagram
    direction LR

    class move_candidate {
        Kind insert_or_delete
        Role structural_role
        string filename
        string xpath
        source_span
        string raw_text
        string canonical_text
        string type2_canonical_text
        type3_sequences
        uint64 hash
        uint64 type2_hash
    }

    class candidate_registry {
        candidate_records
        file_to_candidate_ids
        exact_hash_buckets
    }

    class content_group {
        candidate_id_ranges
        group_kind cardinality
        match_kind matching_method
        confidence_milli
        selection_utility
        matched_units
        selection_reason
    }

    class content_groups {
        delete_candidate_ids
        insert_candidate_ids
        content_group_metadata
    }

    class group_selection {
        used_candidate_ids
        covered_source_spans
    }

    class move_tag {
        move_id
        content_relationship
        endpoint_xpath
        partner_xpaths
        ranking_evidence
    }

    class move_entry {
        move_id
        content_relationship
        source_xpaths_and_texts
        destination_xpaths_and_texts
        ranking_evidence
    }

    class summary {
        move_group_count
        move_pair_count
        annotated_region_count
        group_kind_counts
        content_relationship_counts
        move_entries
        optional_diagnostics
    }

    candidate_registry "1" *-- "many" move_candidate : owns
    content_groups "1" *-- "many" content_group : stores compactly
    content_group --> move_candidate : refers to by candidate id
    group_selection --> move_candidate : prevents reuse and overlap
    content_group --> group_selection : selected under
    move_tag --> content_group : copies evidence from
    move_tag --> move_candidate : identifies endpoint and partners
    move_entry --> move_tag : materialized from endpoint tags
    summary "1" *-- "many" move_entry : reports selected groups
```

`candidate_registry` is the authoritative owner of candidates. `content_groups`
is a derived snapshot containing candidate identifiers rather than candidate
copies. FNV-1a hashes index exact and Type-2c representations, but full canonical
text confirms equality. Type-3 candidates are shortlisted by construct kind and
sequence size before bounded-LCS comparison; there is no SHA-1 index,
probability model, or retained AST in the current implementation.
