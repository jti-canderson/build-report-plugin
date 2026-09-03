# Adversarial review

One critic agent, pointed at a finished rule, whose only job is to break it. Not a fan-out —
a second opinion earns its tokens, a committee does not.

## When it fires

Not "when the logic is complicated" — long and mechanical is usually safe. It fires when the
work **can be wrong in a way that looks right**. Three questions, in order:

1. **If this is wrong, does anything announce it?** A stack trace, a red banner, an obviously
   blank page. If yes, skip the critic — being wrong loudly is self-correcting.
2. **Can I verify it myself, right now, cheaply?** Compile against the live model, Execute
   with Rollback on, the probe trick, the data dictionary export, re-reading the page after a
   save. If yes, **do that instead.** A critic is what you reach for when real verification is
   not available; spending one where a check exists is the actual waste.
3. **Would a wrong answer look exactly as plausible as a right one?** If yes, and 1 and 2 were
   both no — run the critic.

By that test a 300-line loop over one collection is safe, and an eight-line money total is not.

## What to hand it

The `.groovy`, the contract it must satisfy, the field list the `.jrxml` declares, the user's
original request **in their own words**, and the specific claim to attack. Nothing else.

## The questions

### First — the task (always, and before any of the domain questions)

A rule with immaculate traversals that answers the wrong question is still garbage.

1. **Did this do what was actually asked?** Read the user's own words, not the restatement of
   them. Name anything added that was not requested, and anything requested that was quietly
   narrowed or dropped.
2. **Is the problem actually fixed?** Name the original symptom, then the specific mechanism
   that now prevents it. "The code looks right" is not an answer. If the mechanism cannot be
   named, it is not fixed.
3. **Where is this guessing?** Mark every load-bearing claim *seen working* or *assumed*. A
   comment in the corpus, a sibling report's field name, and "this is how it is usually done"
   are all assumptions.
4. **What one question would settle the biggest guess fastest?** Turn each assumption into a
   question for the user or a check that can be run now. This is where the tokens come back —
   one question asked now beats three speculative rounds.

### Then — the data (five, on any rule)

5. **Which traversals are invented rather than seen working?** For each, say what the user
   sees if it is wrong. The answer is almost always "column X is silently empty", never "it
   errors" — Jasper swallows NPE during expression evaluation and renders the literal `null`.
6. **Which key the `.jrxml` declares is not seeded on every row?** Including rows of a
   different `section`. An unseeded key is a missing key, and field values are cast, not
   converted.
7. **Who is missing from this row set?** What population does the query structurally never
   reach — e.g. a pay plan overdue while the obligation under it is not yet due.
8. **Where can one thing be counted twice?** Two active plans on a case can cover the same
   obligations.
9. **What comes back when an input is blank or null** — no rows, all rows, or a crash?
   `def x = _Param ?: ''` used as a filter, and a null date bound matching nothing, are the
   two documented ways this goes quiet.

### Conditional — only when they apply

- **Money** — which amount fields are integer cents and which are already dollars, and where
  are they mixed? Does the payment walk both allocation branches plus the assessment side?
  Reversed receipts and overpayments: in or out, and is that what was asked?
- **Merging two sources** — at what level does it deduplicate, and what does that level cost?
- **Parameters** — is a multi-select arriving as a single `String` normalized? Does each
  `<parameter name="X">` reach Groovy as `_X`, with the bare name in the registration row?
- **Null-safety** — where does `?.` guard the receiver but not the result
  (`r?.amountCents / 100` still throws), including inside a `logger.debug` that can kill the
  report on its own?

## What comes back

**Every answer is a data state, not an opinion.** "Case with two plans covering the same
restitution → total reads $148 high" is a finding. "Consider extracting this method" means the
critic was aimed at the wrong question — re-aim it or drop it.

Fold confirmed holes into the rule. Report both halves: what the critic broke, *and* what it
tried and could not break — the second half is what the user actually gets to rely on. Carry
any unresolved guess into **Needs your input** as the question the critic phrased.
