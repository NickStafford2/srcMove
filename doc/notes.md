Will probably want to present at icfme

# Ideas
To do cross file move detection, i will need to keep references to the srcml nodes after ??? check out input_source_local.direcoty()

Must find a way to track the size of constructs, and which ones are subsets of others. 

Performance on large files is a concern.

may make a nested data format to label nested xml. 

Need a simple way to convert construct to source code. and possibly get line number

Should I do everything in a second post processing step. 
  Current move detector is done during normal differ operations. 
  Could I take only the diffs, and use that? 

Use terms to only check for moves on certain types on content

# What is a move
Moves are a type of refactor.
Should not change functionality or behavior.

# Constrained Approach
Keep move definitions quite restricted.
As tools are developed, developer behavior may change around it. 

git file renaming is limited. So developers often do atomic commits around renames.


# Move types
## Refactor Detection
Copy code into a new function that is then called in original section. 

## Trivial Moves
Large code block is moved
Same file.
Different file.
New file made for this new code.

# Code Order
alphabetize
reorder function specifiers.
reorder function arguments

# Formatting
- todo: list all things that prettier and similar formatters do. 

## String Literals
- String capitalization 
- Spelling fixes

## Whitespace changes
- Move to new line
- Break up function parameters to new lines.



# User Experience
Developer in the loop
Due to the subjectivity of move detection, the categorization of moves ultimately should be up to the developer. 
The program should provide sane defaults. Trivial moves should be automatic. Less obvious moves can be approved by the developer. 

The confidence threshold should be configurable to the developer. 

Maybe a commit can be designated as a refactor. in which a smaller threshold would be used. Can scan commit message and see

- Tool can ask for feedback from user. 
  - is this a move? 80% Confidence. y/n






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

Currently, I am using srcReader to read srcDiff files as inputs. I perform simple move detection with the information in the srcml_node.
Need to get all relevant move information from srcml_node and save it to some buffer. then compare inserts and deletes and add them to the move registry. use an unordered multimap. 
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


# Idea: Move Distance
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




## Questions
What exactly do we want on the output
Don't know what I don't know
  Tell me more about srcSAX
  Tell me more about dispatcher
What are some good github repos to test
You want to query this. What information do you want?
How to empirically measure memory usage
Do we consider comments inside moves

## Comments
srcDiff output for different file types are sometimes tough to interpret. 
  srcDiff already marks moves for very tags. (function specifiers)
1/10 the time as srcDiff
I have a filtering system. 
  What do we want to ignore.

## Problems
exact format of srcDiff files is difficult to understand.
blocks in nexted inside diff blocks also need checked.



## Only have access to info on srcDiff
do we want any access to the original srcML

## Output Notes
what annotations

## Examples 

# Notes
They use XPath for querying everything. 

