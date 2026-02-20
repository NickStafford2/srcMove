# srcMove
Source code move detection algorithm. Takes srcDiff inputs and applies moves to them. Master's Thesis of Nicholas Stafford

Takes srcDiff as input
Outputs new srcDiff

# Dependencies
srcReader


# Implementation Steps
  Pass 1
    Creating objects that store information about moves and surrounding context
  Analyze all potential moves
    Good place for future tools to analyze 
  Pass 2 
    mark all moves and add attributes

  I think I can do it with two passes. Maybe three if I need information on surrounding node context
    Type 1 and Type 2 moves


# Psychological Considerations
I think it is valueable to strongly consider developer psychological information. 
  Developer expectation is important. 
  Do not want false positives. 
  Was reading some papers on clone detection. 
    What counts as a clone is highly subjective and debated by experts.
    Think about how developers expect moves to work with regard to **changelog and impact tracing**
      Debating if we should care about if moves affect behavior.
        Devs may think about moves as more akin to refactoring operations.
      Do devs care about if 
        code changes location, or 
        if code changes behavior. 
        or who 

## Ideomatic operations
We should identify ideomatic operations people perform and check if each move fullfills those criteria. 
  Move of full construct to new file
  Move of full construct to a different location in file
  alphabetize a bunch of lines
  Single line move 
  Moving comment location
  Whitespace changes
    Formatting
    Move function parameters to new line.
  to/from syntactic categories must be correct. 
    function, class, ect.

## Attributes 
Could add attribues marking the type of idiomatic move/refactor. Useful for changelog and impact tracing.
add srcMove prefix for all attirbutes.
### operation_details
type1 move
type2 move
formatting_change
move_id
hunk_to_new_file
### Need some id 
whereto
not where from
delete move_to
to mark location, use xml id, xpath,
filepath_filename_xpath_tag_index_
don't need position row/col
class should have its name

Josh sent me the attribute tag that he used for eye tracking.

'''
//src:unit[@filename='_data/EL_A_CS_NI/edge_ratio_2.py']/src:function[@pos:start='14:1' and @pos:end='75:0']/src:block[@pos:start='14:66' and @pos:end='75:0']/src:block_content[@pos:start='14:67' and @pos:end='75:0']/src:expr_stmt[@pos:start='15:5' and @pos:end='29:7']/src:expr[@pos:start='15:5' and @pos:end='29:7']/src:literal[@pos:start='15:5' and @pos:end='29:7']
  todo: whk
'''

'''
         QString syntactic_context = "",
                xpath = "/";
        for(auto element : element_list) {
            if(element.namespaceURI() == "") {
                xpath += "/src:"+element.tagName();
            }
            else {
                xpath += "/" + element.tagName();
            }
            if(element.tagName() == "unit") {
                xpath += "[@filename=\"" + element.attributeNode("filename").value()+"\"]";
            }
            QDomAttr start = element.attributeNode("pos:start"),
                     end = element.attributeNode("pos:end");
            if(!start.isNull() && !end.isNull()) {
                xpath += "[@pos:start=\""+start.value()+"\" and ";
                xpath += "@pos:end=\""+end.value()+"\"]";
            }
            if(syntactic_context != "") {
                syntactic_context += "->"+element.tagName();
            }
            else {
                syntactic_context = element.tagName();
            }
            QApplication::processEvents();
        } 
'''

# Questions:
SrcDiff has nested diff and delete tags. 
why does diff have so many <diff:ws>  </diff:ws> everywhere






