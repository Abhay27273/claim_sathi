# Corpus

Two real source documents, extracted with `pypdfium2` from the actual PDFs
(not paraphrased, not hand-typed):

- `irdai_master_circular_health_2024.txt` -- IRDAI Master Circular on Health
  Insurance Business, 29 May 2024 (17 pages).
- `insurance_ombudsman_rules_2017.txt` -- Insurance Ombudsman Rules 2017, as
  amended till 18.05.2021 (13 pages).

This resolved something the code previously couldn't know: the Master
Circular defines "PMC" as the Product Management Committee, with CRC (Claims
Review Committee) as its three-member sub-group for claim repudiation
decisions. `draft.py` had been instructed to never guess that expansion --
now it doesn't have to guess, it's grounded in the primary source.

Starter set, not exhaustive -- no Ombudsman award precedents yet (the plan's
"searchable library of past ombudsman awards" from section 4 future-releases),
and no insurer-specific playbooks. Add more `.txt` files here and re-run
`python -m rag.ingest.ingest` to pick them up.
