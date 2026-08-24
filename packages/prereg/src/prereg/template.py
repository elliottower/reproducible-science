"""The plan, under OSF's question titles.

Using OSF's headings verbatim costs nothing and means the document maps onto a registration
without being rewritten. Two of them do the real work:

    Foreknowledge of data or evidence   forces you to say what you have already seen
    Inference criteria                  forces the decision rule to be a commitment

A heading that does not apply is answered N/A with a reason, never deleted. A deleted heading
and an inapplicable one look identical in a file and very different to a reader.
"""
from __future__ import annotations

# Verbatim from the OSF Preregistration schema, in order.
QUESTIONS = [
    ("Research questions or hypotheses", "What is being asked, and what would count as an answer."),
    ("Foreknowledge of data or evidence",
     "What have you already seen? Pilot runs, exploratory results, anything from a related "
     "study. If nothing, say so."),
    ("Explanation of foreknowledge and managing unintended influences",
     "How the answer above does or does not constrain the predictions below."),
    ("Study type", "Experimental, observational, meta-analytic."),
    ("Intention for causal interpretation", "Or N/A if no causal claim is intended."),
    ("Blinding of experimental treatments", ""),
    ("Additional blinding during research or analysis", ""),
    ("Study design", ""),
    ("Randomization", ""),
    ("Data collection procedures", ""),
    ("Data collection procedures - File upload", ""),
    ("Sample size", "And what it can and cannot detect."),
    ("Sample size rationale", ""),
    ("Starting and stopping rules", ""),
    ("Manipulated variables", ""),
    ("Measured variables", ""),
    ("Measured variables - File upload", ""),
    ("Indices", ""),
    ("Indices - File upload", ""),
    ("Statistical models", ""),
    ("Statistical models - File upload", ""),
    ("Transformations", ""),
    ("Inference criteria",
     "The decision rule, as a commitment, before the number exists. A threshold, not a hope."),
    ("Data inclusion and exclusion", ""),
    ("Missing data", ""),
    ("Other planned analysis", "Anything beyond the above is exploratory and labelled so."),
    ("Context and additional information", ""),
]

HEADER = """\
# {title}

**Status:** DRAFT — not frozen.

Sections use the [OSF Preregistration](https://osf.io/prereg/) question titles verbatim, so
this maps onto a registration without being rewritten. A question that does not apply is
answered **N/A** with the reason, never deleted.
"""

LOG = """\

---

## Log

Append only. Never edit above the line.

The last column is what distinguishes an amendment from a deviation, so you do not have to
decide which word to use: `nothing run`, `no results seen`, `results not opened`, `results seen`.

```
{date}  created                              nothing run
```
"""


def render(title: str, date: str) -> str:
    parts = [HEADER.format(title=title)]
    for q, hint in QUESTIONS:
        parts.append(f"\n## {q}\n")
        parts.append(f"_{hint}_\n" if hint else "N/A — \n")
    parts.append(LOG.format(date=date))
    return "".join(parts)
