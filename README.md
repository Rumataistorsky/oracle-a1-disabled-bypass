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

### What to ask for in the SR body

Two concrete asks work better than a vague "please help":

1. Clear the account-level disable flag on the specific instance OCID so `START`
   succeeds again.
2. Provision/link a CSI and MOS support account for the tenancy, so future technical
   SRs don't hit the same wall.

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
