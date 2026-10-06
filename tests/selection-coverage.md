# Selection coverage map

This map explains the existing tests; it does not change their expectations or
propose a new framework. Selection asks **which eligible competing candidates
should be reported?** Identity and location determine eligibility first.

Read the overview first. The detailed inventory is reference material.

## What is tested

| Situation | Expected behavior | Existing evidence | Limit |
| --- | --- | --- | --- |
| A coherent parent competes with a nested child | Preserve the enclosing move | Component ranking check; catalog `nested_exact_parent_over_child` | Catalog checks the named parent and child, not the complete output or all competitor preconditions. |
| Strong independent children compete with a weak parent | Preserve the children | Bundle component checks; catalog `children_utility_over_weak_parent`, `independent_children_not_false_parent` | Sampled situations; not all policy boundaries. |
| Children nearly partition a coherent parent | Preserve the parent | Bundle partition check; catalog `coherent_type2_parent_over_partition` | The edited Type-3 parent example below has a different threshold condition. |
| Repeated children sit inside an identifiable parent | Preserve the parent rather than invent child pairs | Catalog `unique_parent_over_repeated_children` | Requires the supplied cross-file evidence; matching alone is insufficient. |
| Two proposals have equal ranking information | Break the tested tie consistently by minimum ID | Ranking component check | Other tie-break fields are not independently tested here. |
| Symmetric renamed endpoints have no justified pairing | Do not invent individual pairs | Catalog `equal_score_deterministic` | This tests correspondence eligibility, not ranking ties. |
| Two edges share one deletion endpoint | Prefer the exact edge over the weaker renamed alternative | Catalog `shared_delete_stronger_edge` | The mirrored shared-insertion winner is not in this catalog. |
| A relocated child is covered by a selected parent | Keep relocation classification but omit the separate child move | Type-2/Type-3 correspondence contracts | Classification and selection answer different questions. |
| Several edited-code edges compete | Retain the verified edges and their competition evidence | Type-3 competition contracts | Usually does not prescribe an independently justified winner. |
| Repeated text has unique neighbor evidence | Preserve resolved occurrences despite a partially matching wrapper | Exact-neighbor behavior checks | These are explicit XML scenarios, not arbitrary source-generated inputs. |

**A listed test is evidence for its stated condition, not proof of a general
rule such as “largest always wins.”** This map is based on inspected assertions,
not inferred coverage from names. It is not a complete map of the whole suite.

## Where to read the tests

- [Selection component](unit/selection_policy/test_selection_policy.cpp): seven
  assertions calling ranking/bundle policy functions directly. No detector run.
- [Selection catalog](fixtures/selection/catalog.json): 21 independently named
  XML cases. [Its executor](support/selection_catalog.py) runs the detector.
- [Type-2 checks](behavior/test_type2_contracts.py) and
  [expectations](fixtures/selection/type2_contracts.json): identity/location
  preconditions and parent coverage, alongside other correspondence behavior.
- [Type-3 checks](behavior/test_type3_contracts.py) and
  [expectations](fixtures/selection/type3_contracts.json): verified edges,
  competition, parent coverage, and consistency with emitted moves.
- [Historical Type-3 checks](behavior/test_type3_historical_contracts.py): reviewed
  source examples including a competing-edge subgraph. Bounded historical evidence.
- [Identity reservation](behavior/test_type2_adoption.py): both endpoint
  directions, with controls showing a Type-3 edge when reservation is absent.
- [Exact-neighbor checks](behavior/test_exact_neighbor_correspondence.py): partial
  wrappers cannot override resolved repeated occurrences; residual ambiguity remains.
- [Continuing identity](behavior/test_continuing_identity.py): a supported
  correspondence has greater utility than a tentative one. Not a complete ranking test.

## Seven component assertions, translated

| Setup | Expected decision |
| --- | --- |
| Larger structural coverage offsets lower utility | Larger proposal ranks first. |
| Otherwise identical keys, minimum IDs 5 and 6 | ID 5 ranks first. |
| Two strong children cover enough of a weak parent | Children replace the parent. |
| Children cover 20 of the parent's 44 units on each side | Children do not replace the parent. |
| Children cover 31 of 44 units on each side | Preserve the parent as a near-complete partition. |
| Raise parent confidence so the children's advantage is insufficient | Preserve the parent. |
| Increase child count from two to eight | Fragmentation penalty prevents replacement for these metrics. |

These metrics are constructed inputs. They do not prove that candidate generation
produces those metrics correctly from real code.

## Apparent contradictions

Independent review found **no confirmed same-input, same-stage contradictory
expectation** in the inspected files. This is a bounded manual review, not an
automated contradiction detector.

| Looks like a conflict | Distinguishing condition |
| --- | --- |
| Parent wins versus children win | Coherent/exact parent versus weak, incoherent, or below-threshold parent. |
| ID breaks ties versus equal candidates are rejected | Ranking eligible proposals versus establishing correspondence identity. |
| Child is relocated versus child is not reported | Location classification versus selecting its covering parent. |
| Similar content moves versus similar content does not move | Positive displacement evidence versus missing location context. |

Two case IDs are misleading; the rationale and expectations agree:

- `nested_near_miss_parent_over_exact_child` actually retains the exact child and
  rejects the below-threshold parent.
- `coherent_type3_parent_over_partition` actually rejects the below-threshold
  function and retains four independently strong descendants.

No expectation is declared incorrect here. Any suspected genuine conflict needs
its two inputs, conditions, and expectations compared before changing either test.

## Coverage gaps and limits

1. **Ranking branches:** this component does not separately test every tie-break
   field, identical keys, or reverse comparisons.
2. **Bundle boundaries:** no focused examples at both sides of the exact half-
   coverage, 70% partition, confidence-advantage, or utility-equality boundaries;
   one-child and zero-size guards also lack focused checks here.
3. **Complete output:** the selection catalog checks required and forbidden
   normalized text matches. It permits unspecified extra groups and does not
   enforce exact endpoint multiplicity. Other fixture families have stronger
   output oracles; do not assume that strength transfers to every selection case.
4. **Competitor exposure:** catalog cases generally do not assert that the losing
   candidate was generated and eligible. Some diagnostic contracts establish
   stronger preconditions, but not every parent/child example does.
5. **Competition winners:** Type-3 competing insertion/deletion and nontransitive
   examples mostly check edge exposure and output consistency, not a prescribed
   winning edge. A winner is checked where explicitly declared.
6. **Mirrored overlap:** this catalog has an exact-versus-renamed shared-deletion
   winner, but no matching shared-insertion winner case. This is a catalog gap;
   it is not a claim that the entire suite lacks insertion-side competition.

These describe what assertions do not establish. They are not reasons to remove
tests, relax expectations, or infer that the tested behavior is wrong.

## Detailed inventory of the 21 selection catalog cases

All inputs are explicit XML. The case ID also identifies the input under
`fixtures/selection/cases/<id>.xml`. Expectations live in the linked catalog.
Required/forbidden assertions are partial contracts, as explained above.

| Case ID | Situation and expected behavior |
| --- | --- |
| `nested_exact_parent_over_child` | Exact parent reported; its named exact child not separately reported. |
| `nested_near_miss_parent_over_exact_child` | Below-threshold parent rejected; exact child survives. |
| `common_content_is_not_a_move` | Common text and its named wrapper pair must not justify moves. |
| `adjacent_exact_replacement_is_stationary` | Exact replacement in one stable slot is not reported as a move. |
| `adjacent_type2_replacement_is_not_move` | Renaming in one stable slot is not a move. |
| `adjacent_restructure_is_not_move` | Named unchanged content in local restructuring is not a move. |
| `independent_children_not_false_parent` | Separate relocated children survive; incoherent parent alternative rejected. |
| `unique_parent_over_repeated_children` | Identifiable renamed parent survives; named repeated child pair suppressed. |
| `mixed_parent_rejected_inner_survives` | Eligible inner move survives mixed ownership; required output checked, no explicit forbidden-parent entry. |
| `deep_nesting_has_no_two_level_limit` | Enclosing move survives deep nesting; named leaf-only move suppressed. |
| `delete_common_transition` | Delete ownership resumes after common content; common statement is not a move. |
| `insert_common_transition` | Insert ownership resumes after common content; common statement is not a move. |
| `delete_insert_transition` | Nested insertion and restored deletion produce the required two pairs. |
| `insert_delete_transition` | Nested deletion and restored insertion produce the required two pairs. |
| `equal_score_deterministic` | Four unsupported symmetric renamed pairings are forbidden. |
| `cross_file_nonlocal_move` | Named cross-file function move survives intervening file distance. |
| `children_utility_over_weak_parent` | Two exact children survive; weak enclosing alternative rejected. |
| `shared_delete_stronger_edge` | Exact edge wins over the named renamed alternative sharing its source. |
| `coherent_type2_parent_over_partition` | Renamed function selected; named unchanged child alternative suppressed. |
| `coherent_type3_parent_over_partition` | Below-threshold function rejected; four strong descendants retained. |
| `type2_reorder_across_common_conditionals` | Reviewed renamed block crossing common conditionals remains a move. |

## Verification

On 2026-10-06, a focused Docker run passed all 21 selection catalog entries and
`components.selection_policy` (22 runner entries; the component contains seven
assertions). Related behavior families were inspected, not rerun for this map.
The ignored report is `build/selection-coverage-map/report.json` under the
workspace root. This is not a full-suite result.

## Small next step

The selection component now uses named fields and seven named scenario functions;
its input values and expectations are unchanged. A separate next slice can add
one independently justified missing boundary check. Review it before expanding
the migration. Keep the catalog expectations and existing genuine failures intact.
