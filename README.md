# OCI Always Free A1.Flex "Instance is disabled" — root cause and a working bypass

**TL;DR:** In mid-2026 Oracle silently halved the Always Free Ampere A1.Flex allocation
(4 OCPU/24GB → 2 OCPU/12GB), then auto-stopped and *account-disabled* every instance
that no longer fit, starting with an enforcement wave around **2026-08-18**. Upgrading
to Pay As You Go restores your resource limits but **does not** clear the disable flag
on the instance. Filing a normal technical Service Request to get it cleared is
blocked by at least three independent Oracle Console/MOS bugs. There is a working
bypass: the Support Management API accepts `problemType=ACCOUNT` (or `LIMIT`) Service
Requests **without a My Oracle Support (MOS) account**, because Oracle's own
`validate_user` check only requires an MOS account for `problemType=TECH`. This repo
documents the whole chain and ships a ready-to-adapt script to file the SR yourself.

If you're here because your instance says *"is disabled and will not accept any
action requests. Please contact customer support to reenable"* — jump to
[The bypass](#the-bypass).

## What's in this repo

| File | Purpose |
|---|---|
| [`validate_user.py`](./validate_user.py) | check which SR problem types Oracle will accept from your tenancy |
| [`list_taxonomy.py`](./list_taxonomy.py) | print the category / issue-type keys valid for your tenancy |
| [`create_sr.py`](./create_sr.py) | file the ACCOUNT-type Service Request (dry run by default) |
| [`manage_sr.py`](./manage_sr.py) | list, comment on, and close SRs — the console can't |

## What actually happened

1. Oracle reduced the tenancy-wide Always Free Ampere A1 allocation from
   **4 OCPU / 24 GB** (3,000 OCPU-hours + 18,000 GB-hours/month) to
   **2 OCPU / 12 GB** (1,500 OCPU-hours + 9,000 GB-hours/month), with no public
   changelog entry — the docs were edited quietly. See:
   - https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/
   - https://www.heise.de/en/news/Oracle-halves-free-cloud-resources-11334516.html
2. Existing Always Free A1.Flex instances provisioned at the old 4/24 ceiling now
   exceed the new tenancy limit.
3. Starting around **2026-08-18**, Oracle's own `SYSTEM`-attributed automation began
   stopping and *disabling* the offending instances tenancy-wide (visible as two
   `SYSTEM-*`-prefixed stop events in the tenancy Audit log, with no user identity
   attached — you did not do this).
4. `START` (and `RESET`) on the instance afterwards returns:

   ```text
   ServiceError:
   {
     "code": "IncorrectState",
     "status": 409,
     "message": "Instance <ocid> is disabled and will not accept any action
                  requests. Please contact customer support to reenable."
   }
   ```

5. Adding a payment method and upgrading the tenancy to Pay As You Go **does not
   clear this**. It does restore your `standard-a1-core-count` /
   `standard-a1-memory-count` service limits (verify with
   `oci limits value list --service-name compute`), but the instance stays disabled —
   this is a **separate, account-level flag**, not a resource-limit gate. Several
   Oracle Cloud Customer Connect threads from the same week confirm this is common,
   not a one-off:
   - https://community.oracle.com/customerconnect/discussion/974424/
   - https://community.oracle.com/customerconnect/discussion/974476/ (disabled even
     though the instance was resized to fit the new 2/12 limit)
   - https://community.oracle.com/customerconnect/discussion/966208/
   - https://community.oracle.com/customerconnect/discussion/974045/

## The three broken self-service paths (as of 2026-08)

You'd normally clear this by filing a technical Service Request. All three obvious
ways to do that were broken at the time of writing:

1. **Console → Support Center → "Create a support account"** — the button fires no
   network request at all. Browser console shows:
   ```
   Unable to find action: "undefined" on
   "intent.cloudincidentmanagement.create-support-account.create" child of
   "intent.cloudincidentmanagement.tech_support_request_list.list"
   ```
   This is a broken action-mapping in the console's own config — a genuine Oracle
   front-end bug, not something you're doing wrong.
2. **support.oracle.com → "Sign in with your commercial cloud account"** (tenancy
   SSO) — fails with `Login Failed: Tenancy not found, please sign in with a
   different tenancy or use your Oracle account.` Root cause: a fresh
   Always-Free-to-PAYG tenancy usually has no **CSI (Customer Support Identifier)**
   linked yet, and MOS tenancy-SSO needs one.
3. **Phone support (1.800.223.1711)** — the IVR requires an existing SR number to
   proceed and offers no path to open a new one by phone; it explicitly tells you to
   use the website, which is the thing that's broken.

## The bypass

Oracle's Customer Incident Management System (CIMS) — the backend behind Service
Requests — validates users differently **per problem type**. Call
`validate_user` (or just try creating an incident) with each `problemType` and you'll
see:

| `problemType` | Requires MOS/CSI? | Result without one |
|---|---|---|
| `TECH`    | Yes | `403 SUPPORT_ACCOUNT_NOT_FOUND` |
| `ACCOUNT` | No  | `isValidUser: true` |
| `LIMIT`   | No  | `isValidUser: true` |

In other words: **you can file an `ACCOUNT` or `LIMIT` type Service Request through
the API right now, with zero MOS account and zero CSI**, using nothing but your
normal OCI API key. This is exactly the situation you're in — "please clear a
disable flag on my account" is legitimately an account request, not a technical one.

### Prerequisites

- The [OCI CLI](https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm)
  configured (`~/.oci/config`) — you already need this to have found this error in
  the first place.
- The OCI Python SDK: `pip install oci`
- Your tenancy's **home region's 3-letter code** (not the `ca-toronto-1`-style region
  identifier used elsewhere in OCI). Toronto is `YYZ`. If you're not sure, check your
  tenancy details page in the console, or ask Oracle chat support.

### Step 0 — verify this applies to you, on your own tenancy

Don't take the table above on faith, and don't reuse our taxonomy IDs. Two small
scripts in this repo check both against your own account:

```bash
python3 validate_user.py     # which problem types will Oracle accept from you?
python3 list_taxonomy.py     # the category / issue-type keys valid for YOUR tenancy
```

`validate_user.py` output on the affected tenancy looked like this:

```
TECH    -> ERROR 403 SUPPORT_ACCOUNT_NOT_FOUND  MOS validation failure. Support account does not exists.
ACCOUNT -> 200 { "is_valid_user": true }
LIMIT   -> 200 { "is_valid_user": true }
```

If `ACCOUNT` comes back `403` for you too, this bypass is closed on your tenancy and
nothing below will help — say so in an issue, it's a useful data point.

`list_taxonomy.py` prints the keys live, which matters because the IDs hard-coded in
`create_sr.py` are a snapshot Oracle can change without notice. Ours printed:

```
CAT   b28b6f38   Account
  ISSUE 9229c1cc   My Account and My Services Access      <- what we used
  ISSUE ab27f7d5   Order Re-Provisioning
  ISSUE d8f38038   Order Provisioning and Account Creation
CAT   239f7536   Billing
CAT   52b975c0   Administration
CAT   b379dbdf   Governance
```

### Filing the SR

Edit [`create_sr.py`](./create_sr.py) — fill in your tenancy details, the instance
OCID, a description of what happened, your contact info, and your home region code —
then:

```bash
python3 create_sr.py            # dry run — prints the payload, sends nothing
python3 create_sr.py --send     # actually files the SR
```

On success you get back an SR number you can track and comment on through the same
API, entirely independent of the broken console/MOS UI.

Notes from filing our own SR this way:

- Oracle's API **forces `problemType=ACCOUNT` requests to `SEVERITY_MEDIUM`** even if
  you request `HIGH` — it silently downgrades rather than rejecting. If severity
  matters, say so explicitly in the description and consider a follow-up comment.
- The `region` field on `CreateResourceDetails` wants the 3-letter home-region code
  (`YYZ`), not `ca-toronto-1` — using the wrong format returns a `400` with a
  not-very-obvious message.
- `category_key` / `issue_type_key` are opaque IDs from Oracle's own taxonomy, not
  free text. The values in the script (`b28b6f38` for the Account category,
  `9229c1cc` for "My Account and My Services Access") worked for exactly this
  scenario at the time of writing — Oracle can change these without notice, so treat
  them as a starting point, not a permanent contract.

### Errors you will hit, and what they actually mean

Every one of these came back with a message that points nowhere near the real cause.

| What you see | Real cause | Fix |
|---|---|---|
| `400 Unable to process JSON` | `region` on `CreateResourceDetails` is the region *name* | use the 3-letter code — `YYZ`, not `ca-toronto-1` |
| `TypeError: Field ticket.resource_list[*] ... expected CreateResourceDetails but was CreateAccountItemDetails` | the item has to be wrapped | `CreateResourceDetails(item=CreateAccountItemDetails(...), region=...)` |
| `400 INVALID_SR_TICKET_TITLE — Ticket Title is too long` | undocumented title length cap | keep the title under ~80 characters, put the detail in the description |
| `update_incident() missing 1 required positional argument: 'compartment_id'` | signature differs from the published docs | pass `compartment_id` explicitly |
| endless spinner on `support.oracle.com/?page=home` or `?page=dashboard` | your MOS account belongs to no user group | not fixable from your side; ignore the portal and use the API |

Region codes: `YYZ` Toronto, `YUL` Montreal, `IAD` Ashburn, `PHX` Phoenix, `FRA`
Frankfurt, `LHR` London, `NRT` Tokyo, `SYD` Sydney, `BOM` Mumbai, `GRU` Sao Paulo.
[Full list](https://docs.oracle.com/en-us/iaas/Content/General/Concepts/regions.htm).

> **Use the dry run, seriously.** While probing which payload shape the API would
> accept, the first variant that validated went straight through and created a live
> Service Request. There is no draft state and no confirmation step. Don't loop over
> `create_incident` while experimenting — if you do file a stray SR, close it with
> `manage_sr.py close <number> "filed in error"` and explain, rather than leaving it
> in the queue.

### Tracking the SR afterwards

The console still returns `403` for the SR list, so the API is also how you read and
update the request you just filed:

One caveat: `GetIncident` is gated behind the same MOS check that blocks `TECH`, so
fetching a single SR by number returns `403 SUPPORT_ACCOUNT_NOT_FOUND`. `ListIncidents`
is not gated, so listing works and is how `manage_sr.py list` reads state. Updates
(notes, close) work fine.

```bash
python3 manage_sr.py list                      # your ACCOUNT SRs and their state
python3 manage_sr.py note  <number> "text"     # add a comment / ask for escalation
python3 manage_sr.py close <number> "text"     # close one filed by mistake
```

Watch the `lifecycle_details` field:

- `PENDING_WITH_ORACLE` — with them
- `PENDING_WITH_CUSTOMER` — **they asked you something.** You get no console
  notification and no reliable email, so poll for this
- `CLOSED` — done

Because of the forced `MEDIUM` severity, adding a `NOTES` activity that states your
impact and that you are reachable at any time is worth doing right after filing.

A cron job every 30 minutes that checks `lifecycle_details` and retries
`oci compute instance action --action START` costs nothing. Put a hard `timeout` on
every call — `START` against a disabled instance and SSH to a host that is down can
both hang for a very long time.

### What to ask for in the SR body

Two concrete asks work better than a vague "please help":

1. Clear the account-level disable flag on the specific instance OCID so `START`
   succeeds again.
2. Provision/link a CSI and MOS support account for the tenancy, so future technical
   SRs don't hit the same wall.

## Where an ACCOUNT SR actually lands (read this before you celebrate)

Filing the SR works. Where it goes next is the part nobody warns you about.

Within minutes of filing, both our requests were auto-acknowledged by
**Oracle Canada Collections** (`collections_ca@oracle.com`) — the billing, invoicing and
payment-chasing queue:

```
Thank you for contacting us! ... will be addressed within the next 2 working days.
Also, in order to facilitate a prompt response to your request, please make sure you
provide the following information in the email subject: customer name / invoice number
```

A team that asks for an invoice number is not a team that clears an instance-level
disable flag. `problemType=ACCOUNT` appears to route to the regional collections desk,
at least for a Canadian tenancy. Your region's queue may differ — if you try this, please
open an issue saying which queue acknowledged you, because that mapping is the single
most useful thing missing from this writeup.

So treat the bypass accurately: **it gets your request in front of a human at Oracle. It
does not guarantee that human is the right one.** That is still a large step up from
"there is no button that works", but it is not the finish line.

Two things worth doing immediately after filing:

1. **Add a routing note to the SR** (`manage_sr.py note <number> "..."`) stating plainly
   that this is not a billing or invoice matter, that the account is in good standing
   with no outstanding invoice, and asking for the request to be routed to Cloud
   Operations or Compute support.
2. **Reply to the acknowledgement email.** It comes from a monitored human queue and
   creates a second, parallel record. Lead with "this is not a billing enquiry" in the
   very first line — before any technical detail — and put the customer name in the
   subject, since that is what their intake process asks for.

## Status / disclaimer

This documents one real case, filed and accepted by Oracle's API (visible as a real,
trackable SR number) at the time of writing. It is **not** a confirmation that Oracle
will resolve every case this way, that these category/issue-type IDs are stable, or
that this bypass will keep working — Oracle could tighten the `validate_user` check
at any time. If you hit a wall this doesn't get you past, the community threads
linked above are actively being updated as more people hit the same August 2026
enforcement wave — check there for the latest.

If this helped you get unstuck (or if Oracle closes this bypass and you found another
way), please open an issue or PR — the goal is to keep this useful for the next
person who searches the exact error string and lands here.
