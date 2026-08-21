While srcMove is effective for identifying moves across large repositories with highly divergent code, I believe it is better utilized to identify sequential moves over the course of a repositories lifespan. 

Consider the following sequence: 

Commit 0: user writes function foo() in File A
Commit 1: user moves function foo() to File B
Commit 2: user changes function foo() significantly such that it is no longer detectable as a move. 

If srcMove was called between commits 0 and 2, srcMove would not detect a move at all. But in the true history, foo was moved and altered. For this reason, I developed the repository_analysis srcMove tool. 


## repository_analysis srcMove tool
This tool walks backward in time and identifies the moves that occur between each individual commit. The process works like this: 

High level overview: 

1) $ git clone <repository>
2) $ srcmove-history init
  - generates a .srcmove/ directory alongside .git/
2) $ srcmove-history run  
  - generates a .srcmove/ directory alongside .git/
2) checkout commit where you want analysis to start at.
  a) use git to generate two archives of repository state. before and after commit. (original, modified)
  b) generate srcDiff.xml based on original and modified. 
  c) run srcMove on srcDiff.xml
  d) record any moves for future analysis
3) walk forward a commit and repeat step 2
4) stop once yuouo 
