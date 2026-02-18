
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

