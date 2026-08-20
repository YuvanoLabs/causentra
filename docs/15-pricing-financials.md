# Pricing and financial model

## Packaging principle

Keep instrumentation, local inspection, schema, core adapters, and basic self-hosting open. Charge for managed retention, collaboration, alerting, analytics, governance, scale, deployment options, and support.

## Proposed validation tiers

Prices are hypotheses for interviews and pilots, not launch commitments.

| Plan | Buyer | Included direction | Initial hypothesis |
|---|---|---|---:|
| Local | Individual/local team | Local runtime, SDKs, adapters | Free |
| Cloud Free | Evaluator | Small event/retention allowance | Free |
| Pro | Individual professional | More retention, projects, basic alerts | $29/month |
| Team | Small team | Seats, sharing, advanced alerts/analytics | $99–199/month base + usage |
| Business | Growing org | SSO-lite, longer retention, support | $499+ /month + usage |
| Managed | Regulated/large org | SCIM, audit, private deployment, SLA | $25K+ annual |

Pure per-seat pricing misaligns with infrastructure cost; pure event pricing is unpredictable. Validate a platform allowance plus transparent overage, with budget caps and sampling controls.

## Unit-economics model

Track monthly per tenant:

`gross margin = revenue - ingest compute - stream processing - hot storage - archive storage - query compute - egress - allocated support`

Model small, median, and high-volume cohorts. Target cloud gross margin above 75% at steady state and require plan changes if a cohort remains below 60% without strategic justification.

## Commercial validation

Interview at least 15 qualified teams using a concrete usage scenario. Ask for ranked value, procurement path, budget owner, expected volume/retention, and a signed pilot—not an abstract willingness-to-pay answer. Test price points rather than showing only one.

## Financial controls

- Per-project soft/hard quotas and customer-visible usage
- Spend anomaly alerts and ingestion circuit breakers
- Retention lifecycle policies and compression
- Monthly billing reconciliation against raw usage ledger
- Approval for discounts, free extensions, and custom support
- Quarterly review of CAC payback, expansion, churn, margin, and concentration

## Funding gates

Avoid scaling sales before retained use and pilot conversion exist. Add significant cloud capacity only after measured volume. Hire compliance and customer-success functions against qualified pipeline and control requirements, not the aspirational roadmap.
