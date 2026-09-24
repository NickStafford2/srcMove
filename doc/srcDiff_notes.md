
# srcDiff behavior notes

## Nested revision states

srcDiff stores both revisions in one well-formed XML document. Its diff
elements therefore act as revision-membership states rather than independent,
flat edit records:

| Nearest enclosing state | Content belongs to |
| --- | --- |
| no diff element | both revisions |
| `diff:common` | both revisions |
| `diff:delete` | original revision only |
| `diff:insert` | modified revision only |

The nearest state wins. A nested tag changes the state inherited from its
parent. There is no two-level format limit; elements may nest as deeply as the
structured comparison requires, subject to ordinary well-formed XML nesting.

Explicit `diff:common` is primarily needed when shared code is structurally
inside a larger inserted or deleted construct. For example, when an `if`
wrapper is removed but its body survives, srcDiff can encode the old `if` in an
outer deletion and the surviving body in nested common markup. Removing the
outer deleted form for the modified revision must promote the common
descendant rather than discard it.

Nested opposite-side elements similarly let one combined tree switch between
old and new structural forms. A `diff:insert` physically nested in a
`diff:delete` does not mean that new source was inserted into deleted source;
it means that the combined XML changed from describing the old form to the new
form. Same-side nesting does not change revision membership, although inner
boundaries or attributes may retain separate structural or move information.

This behavior comes from representing two overlapping srcML trees in one XML
tree. Understanding the shortest-edit-script implementation is not required to
consume the format. The edit algorithm helps choose correspondences; nested
markup serializes those correspondences while preserving both revisions.

For srcMove, clone similarity alone is insufficient: candidate construction
must first respect these revision states. The proposed handling and regression
requirements are maintained in the
[move-detection redesign](plans/move_detection_redesign.md).

## Historical investigation notes

# Stack
## Main
src/client/srcdiff.cpp main()
process command line option
process the options into an object
? get next_input_source from options
input_source is an object containing information about the files and options
  idk why it is different from options? 
input->consume()
  determines if inputs are directory or files and processes them. 
  file() consumes a file
input_source::file()
input_source_local::process_file()
  Everything important with diffing happens in here
  get the language 
  get the file paths
  unit_filename is the two paths together
  don't know what interpreter does

translator.hpp interpreter->translate()
  creates+runs two threads to create the srcml nodes 
  translates from input stream to output stream

src/client/input_source_local.cpp
src/client/input_source.cpp input_source::file()
src/client/input_source_local.cpp ::process_file()
src/translator/translator.hpp ::translate()

src/translator/differ.cpp ::output()
src/translator/move_detector.cpp ::mark_moves()

must learn the diffference between differ.cpp, and change_stream.cpp.
Must learn shortest edit scripts. 


# To Discuss

# Thread issue
src/translator/translate.hpp
translator::translate()
threads are created and ran in sequence instead of in parallel. 
  usually, joins are after both threads are created
Is this intentional?
if we can't do in parallel, we ought to remove the treads to reduce overhead and complexity. 

is_original and is_modified are never changed anywhere in the file as best i can tell. 

### srcml test
Increased throughput by 25%. 

### Linux Kernel Test
Run with Parrallel: 2:59 (179s).
Run with Sequential: 3:35 (215s).
Increased throughput by 20%


# Relevant code from Line 84 of translator.hpp. translator::translate()
## Original
int is_original = 0;
std::thread thread_original(std::ref(input_original), SES_DELETE, std::ref(output->nodes_original()), std::ref(is_original));
thread_original.join();
int is_modified = 0;
std::thread thread_modified(std::ref(input_modified), SES_INSERT, std::ref(output->nodes_modified()), std::ref(is_modified));
thread_modified.join();

## Modified
int is_original = 0;
std::thread thread_original(std::ref(input_original), SES_DELETE, std::ref(output->nodes_original()), std::ref(is_original));
int is_modified = 0;
std::thread thread_modified(std::ref(input_modified), SES_INSERT, std::ref(output->nodes_modified()), std::ref(is_modified));
thread_original.join();
thread_modified.join();




## other

can we change all angle brackets for local header includes to quotes. it is better for ide tools like clangd

created a move_registry.

I'm not stuck, but I don't exactly know what to do next. SrcDiff scans the file recursively and checks for moves. It detects deletes that are large, and then scans a subset of that nodes children and does the same thing. 
  So I need to develop a method of determining the correct delete. or maybe I simply compare everything with an unordered hash map, but I don't know about the scaling of that. 
I also believe i need a method to find construct locations based in postprocessing with the move_registry.

  maybe only register deleted and inserted lines? 

It would be nice to know the simplest way to convert a construct back to simple code. useful for debugging purposes. 
