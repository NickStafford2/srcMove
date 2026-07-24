# srcdiff Encoding Repro

## Context

`test/e2e_bigclonebench/cases/bcb_t1_000004` exposed a text mismatch between
the generated Java source/metadata and the `srcdiff` XML consumed by `srcMove`.

The source text from IJaDataset displays as:

```java
System.out.println("��Ч��URL: " + urlString);
```

The generated `original.java` and `metadata.json` preserve that displayed form.
After running `srcdiff`, the XML contains:

```text
"ï¿½ï¿½Ð§ï¿½ï¿½URL: "
```

`srcMove` then reports the same mojibake form in `results.json`, so this does
not appear to originate in `srcMove`. It appears before `srcMove`, in the
`srcdiff` / srcML XML output.

## Minimal Source Shape

This is the smallest useful Java shape for a manual reproduction:

```java
public class EncodingRepro {
    private static String getDocumentAt(String urlString) {
        try {
            throw new java.net.MalformedURLException();
        } catch (java.net.MalformedURLException e) {
            System.out.println("��Ч��URL: " + urlString);
        }
        return "";
    }
}
```

Run it through `srcdiff --position` against an identical copy or a tiny moved-copy
case, then inspect the generated XML string literal.

Expected displayed source literal:

```text
"��Ч��URL: "
```

Observed XML literal in the BigCloneBench case:

```text
"ï¿½ï¿½Ð§ï¿½ï¿½URL: "
```

## Important Caveat

Typing `��Ч��` by hand may not reproduce the issue. The bug likely depends on
the exact bytes in the original IJaDataset file, not just the displayed Unicode
characters. For a strong srcdiff issue report, attach or derive the repro file
from:

```text
test/BigCloneEval/ijadataset/default/75138.java
```

The relevant BigCloneBench-generated case is:

```text
test/e2e_bigclonebench/cases/bcb_t1_000004/
```

## Issue Summary Draft

`srcdiff` / srcML appears to mojibake replacement-character-containing string
literals when serializing XML. The source file displays replacement characters
around a Cyrillic-looking character sequence, but the XML output contains a
Latin-1/UTF-8 mojibake form. This breaks downstream raw-text validation because
the generated Java source and metadata preserve one damaged representation while
the XML reports another.
