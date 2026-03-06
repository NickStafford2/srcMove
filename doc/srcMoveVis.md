high-level architecture
Make a new repo, e.g. srcMoveViz, that is just a “driver + renderer”.

Inputs:

* original.cpp
* modified.cpp

Pipeline:

1. run srcdiff (with --position) → diff_pos.xml
2. run srcmove on diff_pos.xml → diff_new.xml (adds move + xpath)
3. parse diff_new.xml to collect:

   * delete ranges (line/col in original)
   * insert ranges (line/col in modified)
   * move ranges (by move id; line/col in original and modified)
4. render original and modified side-by-side with highlights:

   * deletes: yellow (orig side)
   * inserts: blue (mod side)
   * moves: green (both sides, keyed by move id)
   * if a span is both “insert” and “move”, move (green) should win

repo setup steps

1. create the new repository layout

* src/

  * main.cpp
  * run_tools.cpp / run_tools.hpp        (process execution)
  * parse_diff.cpp / parse_diff.hpp      (XML parsing → ranges)
  * render.cpp / render.hpp              (side-by-side rendering + ANSI)
  * types.hpp                             (range structs, enums, etc.)
* CMakeLists.txt
* README.md

2. choose how to invoke srcdiff/srcmove
   Two sane options:

A) external executables (recommended for now)

* srcMoveViz shells out to:

  * srcdiff (from your srcDiff build)
  * srcMove (from your srcMove build)
    Pros: decoupled, fast to iterate, no link nightmares.
    Cons: need paths configured.

B) link libraries directly

* link srcreader + srcml and call the same APIs
  Pros: single process.
  Cons: you’ll fight build/link layout and ABI issues longer than you’ll like.

Do A first. You can always swap later.

3. implement “tool runner” layer
   Write a small wrapper to run commands and capture status/stdout/stderr.

Design:

* struct CommandResult { int exit_code; std::string out; std::string err; }
* CommandResult run(const std::vector[std::string](std::string)& argv)

Also decide how you locate executables:

* flags:

  * --srcdiff /path/to/srcdiff
  * --srcmove /path/to/srcMove
* or env vars:

  * SRCDIFF_BIN
  * SRCMOVE_BIN
* plus default guesses relative to the viz binary (nice UX)

4. define intermediate file locations
   Use a temp dir per run:

* /tmp/srcmoveviz-<pid>/

  * diff_pos.xml
  * diff_new.xml

Make “keep temp” an option:

* --keep-temp (for debugging)

5. generate the diff with positions
   Command:

* srcdiff --position original.cpp modified.cpp -o diff_pos.xml

You’ll also want to decide srcdiff view options later, but you only need XML.

6. run srcmove to annotate moves
   Command:

* srcMove diff_pos.xml diff_new.xml
  (Your main supports `<srcdiff.xml> [out.xml]` already.)

Important: ensure srcMove preserves the pos: namespace attrs. It should if srcWriter is writing nodes out and not stripping attrs. Your annotation_writer copies nodes and sets move/xpath; it should keep existing attrs.

7. parse diff_new.xml into highlight ranges
   This is the key step.

Goal output:

* for original side: vector<Span> spans_orig
* for modified side: vector<Span> spans_mod

Span:

* line_start, col_start, line_end, col_end (inclusive)
* kind: Delete / Insert / Move
* move_id optional
* priority (Move highest)

Parsing logic (streaming is fine):

* Stream nodes with srcml_reader (same style as your other tools)
* Maintain a stack of “are we inside diff:delete or diff:insert?”
* When you enter a diff region:

  * record kind (delete/insert)
  * check whether this diff region has move="N" (move id)
  * then find the first descendant element inside it that has pos:start and pos:end

    * in your sample, it’s the <expr> under diff:delete/insert
  * use that pos range as the range for the region
  * store it:

    * if kind == delete → spans_orig add Delete span
    * if kind == insert → spans_mod add Insert span
  * if move_id exists:

    * add Move span too (same range), on the same side
    * later, Move wins color/priority

Corner cases to handle:

* multi-line ranges (pos:start line != pos:end line)
* diff tags without position descendants (rare; skip with warning)
* nested diff tags (use a stack; only capture first pos range per diff frame)

8. normalize/merge spans for rendering
   Before rendering:

* group spans by line
* merge overlapping spans of the same priority
* resolve overlaps by priority:

  * Move > Delete/Insert
    Example rule:
* build a per-line “interval set”:

  * insert intervals in priority order (Delete/Insert first, then Move overwrites)

This makes rendering deterministic and fast.

9. build the side-by-side renderer (ANSI)
   Rendering behavior:

* left panel: original file lines
* right panel: modified file lines
* fixed width per panel:

  * compute max visible width based on terminal width or use a flag:

    * --width-left, --width-right
* print line numbers for each side:

  * e.g. “  12 | <code…>”
* align rows by line number (simplest v1)

  * row i displays original line i and modified line i
  * this won’t align inserted/deleted lines perfectly like a diff tool, but your highlights still work and it’s much simpler

Color plan (ANSI truecolor background):

* Delete: yellow background (orig only)
* Insert: blue background (mod only)
* Move: green background (both sides where move_id exists)

Optional: also print move id in a small gutter next to highlighted regions (super useful).

10. CLI for the viz tool
    v1 command line:

* srcmoveviz <original.cpp> <modified.cpp>
  options:
* --srcdiff <path>
* --srcmove <path>
* --keep-temp
* --no-color
* --tabstop N (used only if you decide to expand tabs for correct column visuals)
* --max-lines N (for huge files)
* --context N (only show lines around highlighted spans)

11. handle tabs (if you need accurate columns)
    pos columns are based on tabstop. If files contain tabs:

* either expand tabs to spaces before rendering (recommended)
* when expanding, also expand before applying column indices so highlights line up visually

You can implement:

* expand_tabs(line, tabstop) → expanded_line + mapping from “visual col” to “string index”
  But for most code formatted with spaces, you can skip initially.

12. build system
    CMake:

* find srcReader/srcML headers only if you parse diff_new.xml with srcml_reader

  * you can also parse XML with libxml2 directly, but since you already have srcml_reader, use it
* link:

  * srcreader
  * srcml
  * libxml2
    Same setup style you used in srcMove.

But again: you are NOT linking srcdiff or srcMove; you’re executing them.

13. development sequence (what to build first)
    Order that keeps you moving:

Step 1: skeleton CLI + run srcdiff + run srcMove

* just ensure diff_pos.xml and diff_new.xml exist

Step 2: parse diff_new.xml, print a debug list:

* “DEL 5:10-5:18 move=7”
* “INS …”
  Confirm positions match expectations.

Step 3: render one file with highlights (original only)

* verify yellow and green show up right

Step 4: render side-by-side, line-aligned

* verify both sides appear

Step 5: add overlap priority (Move overwrites)

* verify green wins

Step 6: add context mode (--context 3) to avoid huge output

* show only blocks around diffs

14. later improvements (after v1 works)

* smarter alignment (true diff alignment)

  * you can call srcdiff -u and parse its hunks, or implement LCS alignment yourself
* interactive TUI (scrolling, jumping between moves)

  * use ncurses or a small TUI lib
* click-to-open in editor

  * print commands like: nvim +{line} original.cpp
* show move id pairing:

  * left gutter: “m=7”
  * right gutter: “m=7”
  * maybe color each move id differently (fun but optional)
