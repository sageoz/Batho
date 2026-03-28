# Sample Markdown Document

This is a sample Markdown file for testing language detection and parsing.

## Table of Contents

1. [Headers](#headers)
2. [Lists](#lists)
3. [Code Blocks](#code-blocks)
4. [Links and Images](#links-and-images)
5. [Tables](#tables)
6. [Blockquotes](#blockquotes)

## Headers

# Level 1 Header
## Level 2 Header
### Level 3 Header
#### Level 4 Header
##### Level 5 Header
###### Level 6 Header

## Lists

### Unordered Lists

- Item 1
- Item 2
  - Nested item 2.1
  - Nested item 2.2
- Item 3

### Ordered Lists

1. First item
2. Second item
   1. Nested item 2.1
   2. Nested item 2.2
3. Third item

### Task Lists

- [x] Completed task
- [ ] Incomplete task
- [ ] Another incomplete task

## Code Blocks

### Inline Code

Here is some `inline code` in a sentence.

### Fenced Code Blocks

```python
def hello_world():
    print("Hello, World!")
    return True

if __name__ == "__main__":
    hello_world()
```

```javascript
function greet(name) {
    console.log(`Hello, ${name}!`);
}

greet("World");
```

### Indented Code Blocks

    // This is an indented code block
    function example() {
        return "indented";
    }
```

## Links and Images

### Links

[Link text](https://example.com)
[Link with title](https://example.com "Example Website")

### Reference Links

[Reference link][ref1]
[Another reference][ref2]

[ref1]: https://example.com/reference1
[ref2]: https://example.com/reference2 "Reference Title"

### Images

![Alt text](https://example.com/image.png)
![Alt text with title](https://example.com/image.png "Image Title")

## Tables

| Column 1 | Column 2 | Column 3 |
|----------|----------|----------|
| Row 1    | Data 1   | Data 2   |
| Row 2    | Data 3   | Data 4   |
| Row 3    | Data 5   | Data 6   |

| Left-aligned | Center-aligned | Right-aligned |
|:-------------|:--------------:|--------------:|
| Content      |    Content     |        Content |
| More content |   More data    |     More data |

## Blockquotes

> This is a blockquote.
> 
> It can span multiple lines.
> 
> > This is a nested blockquote.
> > 
> > It can contain other elements.

## Emphasis and Formatting

*Italic text* and _italic text_

**Bold text** and __bold text__

***Bold and italic*** and ___bold and italic___

~~Strikethrough text~~

## Horizontal Rules

---

***

---

## Raw HTML

<div style="color: red;">
  This is <strong>raw HTML</strong> in Markdown.
</div>

## Escaping

\*This is not italic\*
\`This is not code\`
\[This is not a link\](https://example.com)

## Footnotes

Here's a statement with a footnote[^1].

[^1]: This is the footnote content.

## Definition Lists

Term 1
: Definition 1
: Definition 2

Term 2
: Definition 3

## Math (if supported)

Inline math: $E = mc^2$

Block math:
$$
\sum_{i=1}^{n} i = \frac{n(n+1)}{2}
$$

## Front Matter (for static site generators)

---
title: "Sample Markdown Document"
author: "Test Author"
date: "2023-01-01"
tags: ["markdown", "sample", "testing"]
---

This content appears after the front matter.
