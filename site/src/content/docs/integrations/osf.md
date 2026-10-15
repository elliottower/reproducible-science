---
title: OSF registration
description: prereg freeze --osf pushes a frozen plan to OSF as a draft registration, and prereg register submits it.
---

`prereg new` scaffolds a plan under the question titles of OSF's Preregistration form, verbatim,
so a frozen plan maps onto an OSF draft registration without editing. `prereg freeze --osf`
pushes the draft, and `prereg register` submits it. The [prereg](/tools/prereg/#osf-integration)
page covers every flag.

## Reads

- The frozen `PREREG.md` and its freeze record.
- An OSF token, saved to `.env` by `prereg setup`, or from the environment. The token is read
  only after any confirmation is given.
- OSF's registration schema, subjects, licenses and categories, through the OSF API.

## Writes

- `prereg freeze --osf`: an OSF draft registration, its Metadata page (`--subject`,
  `--description`, `--tag`, `--category`, `--copyright-holder`, `--license`, `--title-prefix`),
  and any file given with `--attach`, uploaded into the draft's storage.
- `prereg register`: a registration, `--embargo` until a date or `--immediate`.
- `prereg link`: a view-only link, `--anonymous` for blind review.
- `prereg status`: nothing, unless `--log` records the approval.
- Each step is an entry in `PREREG.log`. Nothing is written into the plan.

## Command

```bash
prereg freeze --osf --subject "Artificial Intelligence and Robotics" \
  --copyright-holder "A. Author" --title-prefix "EXPT01: "
prereg register --embargo 2027-06-01 --access "nothing run"
prereg status
```

## Refuses or never does

- Everything that can refuse runs before anything is frozen or sent: a plan whose
  multiple-choice headings do not name an OSF option, and a subject, license or category OSF
  does not have, are refused first.
- `register` and `link` ask for a typed phrase on `/dev/tty`, never on standard input. With no
  terminal, nothing is sent. `register --confirm DRAFT_ID` skips the phrase for one draft only
  with `PREREG_UNATTENDED_REGISTER=1` set, and the log says it was unattended; a batch and a link
  have no such path.
- `register` refuses a plan changed since its freeze, and a draft already registered.
- An attachment whose hash OSF reports differently is not logged as attached.
- A view-only link is logged without its key.
- `prereg` cannot approve a first registration. OSF's API has no request for it, and `register`
  prints how the email approval works.

## Does not claim

A registration is a copy of the plan, held by OSF, that the author cannot alter. It does not
show that no analysis was run before the freeze. The typed phrase raises the cost of an accidental
write; it is not a security boundary.

## The other project

[OSF Preregistration](https://osf.io/prereg/), and OSF's guide to
[creating a preregistration](https://help.osf.io/article/158-create-a-preregistration).

Not affiliated with or endorsed by OSF or the Center for Open Science.
