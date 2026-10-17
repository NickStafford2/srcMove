"""Build complete schema-3 fixtures from concise atomic test specifications.

This is test data construction, never a compatibility reader. Production
admission rejects schema 2; malformed fields deliberately stay malformed.
"""
from collections import Counter


def schema3_fixture(spec):
    moves = spec.get('moves', [])
    groups = []
    candidate_id = 0
    for index, move in enumerate(moves):
        endpoints = {}
        for old, side in [('from', 'original'), ('to', 'modified')]:
            texts = move.get(old + '_raw_texts', [])
            paths = move.get(old + '_xpaths', [f'/src:unit[1]/src:function[{index + 1}]'] * len(texts))
            endpoints[side] = []
            for xpath, text in zip(paths, texts):
                endpoints[side].append(dict(candidate_id=candidate_id, revision_file=None,
                                            xpath=xpath, construct='function', raw_text=text))
                candidate_id += 1
        pair = all(len(endpoints[side]) == 1 for side in endpoints)
        status = 'selected_pair' if pair else 'unresolved_partners'
        groups.append(dict(id=move.get('move_id', f'move-{index}'),
                           content_relationship=move.get('content_relationship', 'type1'),
                           correspondence=dict(status=status), name_evidence='not_assessed',
                           **endpoints,
                           location_evidence=(dict(scope='pair', classification='relocated', reason='different_file') if pair
                                              else dict(scope='group', status='group_relocation_evidence')),
                           selection=dict(matching_weight_milli=1000, utility=1, matched_units=1,
                                          reason='greedy_utility')))
    kinds = ('type1', 'type2c', 'type3')
    observed = Counter(group['content_relationship'] for group in groups)
    counts = spec.get('content_relationships', observed)
    items = [dict(id='item:' + group['id'] if isinstance(group['id'], str) else 'item:invalid', kind='atomic_move_group', member_group_ids=[group['id']]) for group in groups]
    return dict(results_schema_version=spec.get('results_schema_version', 3) if spec.get('results_schema_version') != 2 else 3,
                summary=dict(output_item_count=len(items), atomic_move_group_count=spec.get('move_count', len(groups)),
                             sequence_move_group_count=0,
                             pair_capacity=spec.get('move_pair_count', sum(min(len(g['original']), len(g['modified'])) for g in groups)),
                             endpoint_count=spec.get('annotated_region_count', candidate_id),
                             atomic_content_relationships={kind: counts.get(kind, 0) for kind in kinds},
                             output_content_relationships={kind: counts.get(kind, 0) for kind in kinds}),
                output_items=items, atomic_move_groups=groups,
                configuration=dict(min_granularity='statement', sequence_policy='ordered_adjacent_v1'),
                pipeline_statistics=dict(srcdiff_region_count=spec.get('regions_total', 0),
                                         grouped_candidate_entry_count=spec.get('candidates_total', candidate_id),
                                         processing_group_count=len(groups),
                                         processing_group_kinds={kind: (len(groups) if kind == 'move_1_to_1' else 0)
                                                                 for kind in ('move_1_to_1','moves_many','delete_only','insert_only','copy_or_repeat','ambiguous')}),
                xpath_context=dict(document='input_srcdiff', convention='srcreader_file_units_v1',
                                   namespaces={'src':'http://www.srcML.org/srcML/src','diff':'http://www.srcML.org/srcDiff'}))
