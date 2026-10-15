**A `set_aside` entry may say who set its passage aside and when, as `reviewed: {who, when}`.** It is the shape an inferred assertion's review takes, and the pull-request bot writes it. An entry without it dumps, and so hashes, as before.

A `claims-cli` up to 0.6.1 rejects a manifest carrying `reviewed` on a `set_aside` entry, as it rejects any key it does not know. `scripts/versions.py` refuses a further 0.6 release, so the next is 0.7.0, whose sibling ranges exclude those versions.
