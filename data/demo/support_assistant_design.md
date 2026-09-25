# Helpdesk Copilot — illustrative design, not a real customer system

The assistant searches approved product articles and drafts replies for the
customer-support team. It cannot send email or issue refunds directly. A human
reviewer must approve replies and all account-changing actions. Unresolved cases
escalate to the support lead.

## Customer information
The request pipeline redacts email addresses and account numbers before calling
the model. Personal data is excluded from model logs. The retention policy deletes
request metadata after 30 days. Access to customer records is restricted by role.

## Known gaps
Prompt injection testing is planned. Retrieved external content is currently
concatenated with the user query; the trust boundary is not validated. We have no
adversarial evaluation report yet.

## Operations
An on-call engineer receives error-rate alerts. An incident runbook defines a
rollback to the previous model version. The model and dependency inventory records
supplier names and release versions. Supplier provenance checks are still planned.

## Unresolved design decisions
We have not documented output accuracy checks. Citation validation will be added
after the initial pilot. We have no rate limits or token budget in the pilot.
