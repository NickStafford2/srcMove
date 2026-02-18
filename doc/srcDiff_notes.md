
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



