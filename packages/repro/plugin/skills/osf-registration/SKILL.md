---
name: osf-registration
description: Register a frozen `prereg` plan on OSF. Write PREREG.md so it maps onto OSF's Preregistration form, dry-run the draft, push it with its metadata, check the draft against the plan, hand the irreversible step to a person, and log the approval. Use when a plan that will go on OSF is about to be frozen, when asked to put a preregistration on OSF, or when an OSF draft or registration needs checking. Requires the `prereg` CLI (`uv tool install prereg`).
---

# OSF registration

A frozen plan, pushed to OSF as a draft, checked against the file, and registered by a person.

## The rule that matters

**Shape the plan for OSF's form before the freeze, and leave the registration to a person.**

A frozen plan never changes, so a heading OSF refuses cannot be renamed after the freeze. And a
registration cannot be deleted, so `prereg register` asks for a typed phrase on the terminal.
Everything before that step can be prepared unattended; do not answer the phrase, and do not
call the OSF API to get around it.

## Write the plan so it maps onto the form

`prereg new <name>` scaffolds PREREG.md under the 27 question titles of OSF's Preregistration
form, verbatim and in order. Keep them that way.

- **Every `##` heading is one of OSF's question titles.** A heading OSF does not have is
  refused, because its section would be missing from the registration.
- **A question that does not apply is answered `N/A` with the reason, never deleted.** The four
  `- File upload` questions take files on OSF, so their `N/A` stays in the plan and is not sent.
- **Four questions are multiple choice**, and OSF accepts only its own options there. Under each,
  write option text only, one option per line, as the full text or as a prefix no other option
  shares. `N/A` leaves the question unanswered.

  | question | takes | a line that selects one option |
  |---|---|---|
  | Foreknowledge of data or evidence | one option | `Data exists but the authors have not observed it yet` |
  | Study type | one or more | `Descriptive study` |
  | Intention for causal interpretation | one or more | `No causal relationship inferred` |
  | Blinding of experimental treatments | one or more | `No blinding is involved` |

  Prose that explains a choice goes under "Explanation of foreknowledge and managing unintended
  influences" or "Context and additional information".
- **A "Maximum claim" paragraph goes inside "Context and additional information"**, as a bold
  run-in (`**Maximum claim under this registration.**`) followed by the paragraph. Under a
  heading of its own it would be refused like any other heading OSF does not have.
- **Files the plan relies on are not covered by the freeze.** The freeze hashes PREREG.md and
  nothing else. Attach a side file with `--attach`, which uploads it into the draft and logs its
  sha256, or log the hash by hand (step 4).

## Steps

1. **Dry run.** `build_draft` reads OSF's public form, maps the plan onto it and sends nothing.
   It needs the network and no token.

   ```bash
   uv run --with prereg python -c "
   import pathlib
   from prereg import osf
   body = osf.build_draft(pathlib.Path('PREREG.md').read_text())
   print(sorted(body['data']['attributes']['registration_responses']))
   "
   ```

   A `RuntimeError` names what cannot map. For a multiple-choice question it lists the valid
   options. Fix the plan and run it again until it passes.

2. **Commit the plan, then freeze and push.**

   ```bash
   prereg freeze --osf \
     --subject "<OSF subject, by its full name>" \
     --description "<one plain paragraph>" \
     --tag <tag> --category hypothesis \
     --copyright-holder "<name>" \
     --attach ../CONTEXT.md
   ```

   `--subject` is the flag that cannot be skipped: OSF refuses to register a draft with no
   subject. `--subject`, `--tag`, `--copyright-holder` and `--attach` repeat.
   `--copyright-holder` sets the license, CC-BY 4.0 unless `--license NAME` says otherwise.
   `--title-prefix` goes before the plan's title on OSF. A subject, license or category OSF does
   not have is refused before anything is frozen or sent.

   The token is read as `OSF_TOKEN` or `OSF_PAT`, from the environment or a `.env` in this
   directory or above. Never print it.

   A plan already frozen without a draft is pushed with `prereg freeze --osf --access <level>`,
   which leaves the freeze as it is.

3. **Check the draft against the plan, field by field.** Read the draft back and compare its
   `registration_responses` with the body the dry run built, key by key, after collapsing
   whitespace.

   ```bash
   curl -s -H "Authorization: Bearer $OSF_TOKEN" \
     https://api.osf.io/v2/draft_registrations/<draft id>/
   ```

   OSF cleans submitted text as HTML and stores `<` as `&lt;`, so unescape HTML entities before
   comparing. A threshold written `p < 0.05` that comes back as `p &lt; 0.05` is not a
   difference. Check the title, the subjects and the description as well.

4. **Commit the log.** The push wrote the draft id and each attached file's sha256 to
   `PREREG.log`. A side file that was not attached is logged by hand:

   ```bash
   shasum -a 256 analysis_plan_detail.md
   prereg log "side file analysis_plan_detail.md sha256 <hash>" --access "nothing run"
   ```

   Commit `.prereg/`, `.gitattributes`, the `.ots` proof and `PREREG.log`.

5. **A person registers.** Give them one command to run in their own terminal:

   ```bash
   prereg register --immediate --access "nothing run"    # or --embargo YYYY-MM-DD
   ```

   It shows the plan, its digest and the draft, and asks them to type `register <draft id>`.
   The four multiple-choice answers are the authors' own statements about what they have seen
   and what they intend, so ask the person to read them on the draft's page
   (`https://osf.io/registries/drafts/<draft id>/`) first. `register` writes the registration's
   id and address to the log.

6. **Approval.** A new registration is pending, not public. OSF emails every admin contributor
   and approves the registration by itself after 48 hours unless one of them cancels.

7. **Confirm the state and log it** (below), then commit the log.

## Approval after registering

The email is titled "Pending Registration - Admin Notification", or "Pending Embargo - Admin
Notification" for an embargoed registration. It carries two links. The first approves. The
second cancels: the pending registration goes back to a draft, at once, and that cannot be
undone.

**OSF's API has no route for this first approval.** The links go to OSF's website and carry a
token that exists only in the email, and the API's registration actions belong to moderators of
a moderated registry. So every admin contributor clicks the first link in their own email, or
nobody does and the registration becomes effective when the 48 hours pass. Never fetch either
link yourself.

Confirm with `GET /v2/registrations/<id>/` and read three attributes:

| attribute | while pending | approved, public | approved, embargoed |
|---|---|---|---|
| `pending_registration_approval` or `pending_embargo_approval` | `true` | `false` | `false` |
| `public` | `false` | `true` | `false` |
| `reviews_state` | `initial` | `accepted` | `embargo` |

Then record it:

```bash
prereg log "osf registration <id> approved, public" --access "nothing run"
```

Log the honest access level. If the analysis ran while the registration was pending, say so.

## Public at once, or under embargo

`register` has no default, because the choice decides whether the plan is published today.

- `--immediate`: public as soon as it is approved. Use this unless something requires
  otherwise.
- `--embargo YYYY-MM-DD`: private until that date, then public. By OSF's defaults the date is
  at least two days and at most four years ahead. Use it where the work will be judged
  double-blind, and share the plan with `prereg link --anonymous --access <level>`, which
  creates a view-only link that hides the contributors. `link` asks for a typed phrase too.

## Changes after registering

`prereg` does not change a registration. On OSF an update to an approved registration is a
schema response with a written justification, and it goes to the registration's admins for
approval. Unlike the first approval, an admin can give this one through the API:
`POST /v2/schema_responses/<id>/actions/` with the trigger `approve`.

Record the change locally as well: `prereg amend` for a change to the plan, `prereg log` for a
note.

## When to reach for this

- Before freezing a plan that will be registered on OSF, to shape it for the form
- When asked to put a frozen plan on OSF
- When an OSF draft has to be checked against the plan it came from
- After a registration, to confirm whether it is still pending

## What it will not do

It does not register for you, approve for you, or change a registration. It also cannot make
the multiple-choice answers true: they are statements by the authors, and OSF records whatever
option was written.

## Where this sits

`prereg freeze` fixes the plan locally, against a commit, a hash and an outside timestamp. An
OSF registration puts a copy with a third party, under a date the authors cannot alter. The
`prereg` skill covers freezing, the log, amendments and `prereg check`.
