@article{SAINI2018718,
title = {Code Clones: Detection and Management},
journal = {Procedia Computer Science},
volume = {132},
pages = {718-727},
year = {2018},
note = {International Conference on Computational Intelligence and Data Science},
issn = {1877-0509},
doi = {https://doi.org/10.1016/j.procs.2018.05.080},
url = {https://www.sciencedirect.com/science/article/pii/S1877050918308123},
author = {Neha Saini and Sukhdip Singh and  Suman},
keywords = {Clone Lifecycle, Clone Detection, Clone Management, Software Maintenance, Clone Refactoring, Bug Detection, Bad Smell},
abstract = {In a software system, similar or identical fragments of code are known as code clones. Instead of implementing a new code from scratch, most of the developers prefer copy–paste programming in which they use existing code fragments. So, the primary reason behind code cloning isboth developers and programming languages used by them. Reusing existing software for increasing software productivity is a key element of object oriented programming which makes clone detection and management a primary concern for current industry. As a software system grows, it becomes more complex which leads to difficulty in maintaining it. The main reason behind difficulty in software maintenance is code clones which do not lead to conclusion that code clones are only harmful for software development. Code clones can be both advantageous and disastrous for software development. Therefore, clones should be analysed before refactoring or removing them. For analysing the clones properly, there is a need to study all the clone detection techniques, various types of clones and techniques to manage them.The main purpose of this paper is to gain insight in to the research available in the area of clone detection and management and identify the research gaps to work upon. It will help the researchers to get started easily with clones as they can study the basic concepts, techniques, general steps for code clone detection and management and research gaps together at one place. Also, it will help in the selection of appropriate techniques for detecting and managing clones as comparative analysis of different techniques on the basis of various parameters is also given in the paper.}
}





# Types of Clones
## Type 1 or Exact clone 
Look like original code with variation of comments and blank spaces. 
Can be detected by use of text based, token based or any simple clone detection technique. 
Detect with: Algorithms like KMP, SDD can detect by string matching

## Type 2 or Renamed/Parameterized clone
Variations in name of literals, variables, keywords. 
The use of token or metric based techniques will be able to detect.
Detect with: CLAN, Columbus, MCD-finder.

## Type 3 or Near miss clone
They are created from base code by statement modification, addition or deletion. 
Detect with: ClonedDr, Clone Digger based on tree technique.
The AST sub tress is compared with each other in tree based techniques.

## Type 4 or Semantic clone 
The program coding or syntax is different but the behaviour or function of the clone remains same in semantic clones.
Detect with: Duplex, Scorpio based on graph technique.

