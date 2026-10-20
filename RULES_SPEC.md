# Rules spec

Every rule is one entry in `rules.yaml`. All rules must:
- change the correct action relative to what the agent would do without the rule (checked at Gate 2 with `no_rules`);
- be checkable from the action trace, with no judgment calls;
- read like real bank operations policy, not like a test, so no "IMPORTANT" or "always remember";
- use only real tools and enum values from `src/tau2/domains/banking_knowledge/tools.py`.

## Rule types (4 rules each)

| Type | What it tests | Pattern |
|---|---|---|
| `threshold` | conditional limits | "X is capped at $N for product P" |
| `prohibition` | doing nothing or escalating instead of the obvious action | "Never do Y when Z; transfer instead" |
| `exception` | a rule and its exception in **different** docs | base rule in doc A, override in doc B |
| `superseded` | the newest version wins | old doc says N, newer dated doc says M |
| `near_duplicate` | telling look-alike products apart | same rule for Gold vs Platinum with different values |
| `ordering` | procedure, i.e. step B requires step A first | "Before applying X, call Y" |

Spread rules across products and both categories (credit_cards, bank_accounts). Half the docs are `standalone`, half `buried`.

## Schema

```yaml
- id: R03
  type: exception
  placement: [buried, standalone]        # per doc in docs[]
  docs:
    - id: doc_credit_cards_silver_rewards_card_retention_012   # existing doc copy (buried)
      section: "Retention offers"
      text: |
        - Eligible customers who ask to close their account may be offered a 12‑month annual fee waiver.
    - id: doc_credit_cards_operational_update_903              # new doc (standalone)
      title: "Credit Card Retention Offers: Account Age Eligibility"
      text: |
        ## Eligibility
        - Retention offers, including annual fee waivers, are not available on accounts open fewer than 180 days.
        - For these accounts, proceed with the closure request if the customer confirms.
  trigger: "customer requests closure of a Silver Rewards card opened < 180 days ago"
  check:
    forbidden: [{tool: apply_credit_card_account_flag_6147, args: {flag_type: annual_fee_waived}}]
    required:  [{tool: close_credit_card_account_7834}]
  tasks:
    triggered: {base_task: task_0xx, user: <user_id>, account: <cc_id>, account_age_days: 45}
    control:   {base_task: task_0xx, user: <user_id>, account: <cc_id>, account_age_days: 400}
                                     # control: the waiver IS offered (flag applied with reason retention_offer)
```

`check` supports:
- `required`: tool plus a subset of args that must appear;
- `forbidden`: must not appear;
- `order`: [tool_a, tool_b], meaning a must precede b;
- `arg_equals`: exact values, e.g. an amount or a date.

Control tasks use the same `check` inverted, or their own `check_control`.

## Seed examples (one per type; Claude Code completes 4 per type)

**R01 threshold.** Late fee reversals on the Bronze Rewards Card are capped at $25 per request; for larger fees, apply $25.
- Check: `apply_statement_credit_8472` with `reason=late_fee_reversal`, `amount=25`.
- Control: a Gold Rewards customer with a $39 fee gets the full $39.

**R02 prohibition.** Do not close a credit card account that has a pending replacement card order. Transfer to a human agent instead, using the transfer reason the KB specifies.
- Check:
  - forbidden: `close_credit_card_account_7834`;
  - required: `transfer_to_human_agents`.
- Control: no pending order, so close normally.
- Note: the agent must call `get_pending_replacement_orders_5765` to notice the condition, which is a natural ordering trap as well.

**R03 exception.** The full spec is above. The plan "customer wants to close Silver card" does not mention account age, which is exactly the incomplete-plan case raised on Reddit.

**R04 superseded.**
- Doc A, dated 2026-03-01: credit limit increase requests on the Platinum card may be submitted for up to $5,000.
- Doc B, "effective 2026-09-01": the cap is $2,000.
- Customer asks for $4,000.
- Check: `submit_credit_limit_increase_request_7392` with `requested_increase_amount=2000`.
- Control: a request for $1,500 is submitted as asked.
- `get_current_time` returns a date after 2026-09-01, so check it in the env.

**R05 near_duplicate.** Promotional APR flags expire 12 months after application on the Gold Rewards Card and 6 months on the Platinum Rewards Card. Put the two statements in two separate look-alike docs.
- Check: `apply_credit_card_account_flag_6147` with `flag_type=promotional_apr` and `expiration_date` equal to today + 6 months, for a Platinum customer.
- Control: a Gold customer gets today + 12 months.

**R06 ordering.** Before applying a `dispute_resolution` statement credit, review the customer's dispute history.
- Check:
  - order: [`get_user_dispute_history_7291`, `apply_statement_credit_8472`];
  - `reason=dispute_resolution`.
- Control: a `goodwill_adjustment` credit, which has no prerequisite (check that the agent doesn't need it).

## Authoring checklist
- [ ] Trigger condition is observable to the agent: in DB data, the user's words, or tool output.
- [ ] Without the rule, the "obvious" action differs from the rule's action.
- [ ] Control differs from triggered by one fact only.
- [ ] Rule text doesn't contain the user's scenario words verbatim, so BM25 doesn't win on lexical overlap alone.
- [ ] For `exception` and `superseded` rules, the two docs don't link to each other explicitly.
- [ ] The user simulator script never states the rule. The customer doesn't know bank policy.
