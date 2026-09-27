# SQLite source review

The machine-readable source of truth is [sqlite.json](sqlite.json). Labels were
written without opening detector outputs. The canonical prior audit was read;
its already-known shell example occurs at ordinary revision 22 and is explicitly
flagged. This window must not be described as entirely held out.

## Frozen source findings

- Thirty latest first-parent comparisons at the recorded anchor were inspected.
  All changed C/C++ hunks were reviewed. No confirmed strict independent Type-1
  or Type-2 move was labeled in that ordinary extension-filtered window.
- Nine additional source diffs were inspected after purposive commit-subject
  search. Six revisions provide eleven Type-1 targets: six complete functions
  and five independently reordered statements or field declarations.
- No strict Type-2 positive was confirmed. The moved-and-renamed Walker callbacks
  also lose `static`; their complete definitions are structurally edited. Their
  unchanged bodies are carried with the parent, not additional independent moves.
- The unchanged `version-info.c` file rename contributes its two functions to the
  function stratum, not a third file-level positive.
- Five exact statements hoisted outside existing conditionals are retained as
  movement-versus-restructuring challenges with endpoints. They are excluded from
  the strict recall oracle until the taxonomy is adjudicated, and are not negative
  cases. Four are repeated JNI counters, whose enclosing function disambiguates
  the intended continuing role.

The ordinary HEAD extraction changes a function signature and body and is outside
strict Type-1/Type-2 whole-function matching. The `f17a2ee0` helper extraction
consolidates repeated origins, so unique pair identity remains unresolved.
`.in` templates, including shell source, are listed as exclusions rather than
silently treated as absent movement. The broader Table refactor candidate was
only partly inspected and was not labeled or included in scoring.

## Reuse and limits

Use each full `parent` and `commit` identifier, never current checkout HEAD.
Endpoint line bounds are inclusive and one-based. `text_sha256` hashes the raw
bytes obtained from `git show REV:PATH`, split with `bytes.splitlines(keepends=True)`
and sliced to the declared lines; line-ending bytes and trailing comments remain
in the hash. File hashes provide an additional check. All eleven strict targets
have equal old/new raw text hashes. A function endpoint excludes its preceding
comment and includes its full declaration and body. Field endpoints include the
complete declaration line, not surrounding preprocessor directives.

This is a single AI source review, not an independently adjudicated gold standard.
The manifest records scope, exclusions, uncertain observations, and search choices
so a second reviewer can check labels without redoing revision discovery. No
accuracy percentage follows from these labels until the detector outputs are
separately run and adjudicated. Keep negative-history observations, strict
positives, restructuring challenges, and partial reviews separate.
