# Operating Procedure — Processing Payments and Reconciliation Exceptions

FICTIONAL EXERCISE — ASPIRE INTERNAL BRAIN DEMO

This offline test procedure is not an actual Aspire policy.

Document owner: Payment Operations  
Procedure reference: PAY-OPS-DEMO-04  
Revision: 1.0  
Classification: Demo internal  
Applies to: Supplier payments in the controlled demonstration dataset

## Purpose

Provide a consistent process for investigating payments that remain processing,
appear inconsistent across systems or require manual review.

## Initial checks

1. Confirm the payment identifier, customer identifier, amount, currency and
   instruction timestamp.
2. Check whether the payment has received all required approvals.
3. Compare the internal payment status with the latest available partner status
   and reconciliation record.
4. Record the time at which each source was checked. An old status observation
   must not be presented as current.

## Processing payments

Escalate a payment to Payment Operations when it has remained processing for
more than 30 minutes after partner acknowledgement.

The 30-minute value is an internal triage threshold for this exercise. It is not
a settlement guarantee.

An uncertain status must not trigger a replacement payment. Before considering
resubmission, establish the outcome of the original instruction and obtain the
required operational approval.

## Beneficiary-detail changes

A change to beneficiary bank details requires independent verification through
an established contact route.

Approval of an invoice does not, by itself, verify subsequently changed
beneficiary details.

Customer-supplied replacement details must remain pending until the verification
outcome is recorded.

## Reconciliation exceptions

Compare payment amount, currency and transaction references separately.

Do not close an exception merely because two records have the same amount.
Similar amounts can belong to different transactions.

Record whether a difference is explained by a fee, a timing difference, a
status-update delay or an unresolved mismatch.

## Escalation and closure

Escalate suspected processing defects to Engineering with transaction references
and timestamps. Avoid copying unnecessary customer details into broadly
accessible channels.

Close an exception only after the final outcome, supporting evidence and
reviewing operator are recorded.

If the outcome remains uncertain, retain the exception as open and record the
next-review time.
