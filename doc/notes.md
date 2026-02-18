Will probably want to present at icfme

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

# Ideas
To do cross file move detection, i will need to keep references to the srcml nodes after ??? check out input_source_local.direcoty()

Must find a way to track the size of constructs, and which ones are subsets of others. 
Cutoff should be one line. Do not care about moves smaller than one line. 

Performance on large files is a consern. 

may make a nested data format to label nested xml. 

Need a simple way to convert construct to source code. and possibly get line number

Should I do everything in a second post processing step. 
  Current move detector is done during normal differ operations. 
  Could I take only the diffs, and use that? 

Use terms to only check for moves on certain types on content


- Tool can ask for feedback from user. 
  - is this a move? 80% Confidence. y/n

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


# Present Notes

## Papers
Clone detection papers. 
Godfrey move analysis paper.
  Origin analysis to detect.
Ask Decker about the paper names. 
## Other
Create a separate program that take in srcdiff as inputs. 
# To Understand
SrcDispatch
  on top of SrcSAX is srcDispatch
Event Dispatcher.
  Would need to add ??
Look at name_collector.
  Name Collecter uses SrcX
Look at the diff namespace. And then diff ws.
Need a stack to track.
Learn about the attributer.




There is a bit of information that I think would be useful before we talk next. My Notes from the meeting are incomplete.
# Questions
You mentioned you already made a srcDiff reader?
If I added a move detector to the end of srcDiff, what code would you reccomend I check out.


## New Plan
Create either:
- A separate program that takes srcDiff as an input and outputs srcDiff with moves.
  - Multi passes.
  - Could use a text reader.
  - Could use SrcSAX.
    - Nice because all the tags are already known.
    - Creating Policies is very difficult.
    - May need to do meta programming.
  - Can use xml2.
- A move detecting step at the end of srcDiff.
  - After the translator, that detects moves.
- Create a plan for how I want to handle move detections. 

## Previous Plan
Break up existing srcDiff node traversal into two steps. Same work, but traversed twice.
1) Preprocessing
  - Create SES 
  - Edit Corrector
  - Save SES to buffer. (NEW)
  - Single block move detector
  - Save potential moves to a unordered_multimap in the move_registry
2) Move Detector 
  - Move all move detection here. mark_moves()
  - Good place for any future processing.
3) Output
  - Retrieve Corrected SES from buffer
  - Identical output as before.

### Performance Impact
Traversing twice. I don't think it would measureably increase speed.
The same exact operations would be done.
Buffer for SES would be small. 






# Move Distance
locality of behavior
Use several factors to measure the confidence that something is a move.
  assign points to each one. 
  can change values depending on user experience feedback. 
size of the move
  small lines of code are more likely to be rewritten. 
  giant functions moved across files are almost certainly moves
distance to move in the directory tree.
distance to move on page. rows/columns  --position
distance to move between blocks.
Similarity of the two code segments.
