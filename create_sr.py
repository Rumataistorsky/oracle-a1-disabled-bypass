#!/usr/bin/env python3
"""
File an Oracle Cloud Infrastructure (OCI) Service Request via the Support
Management (CIMS) API directly, bypassing the console/MOS self-service UI.

Background: https://github.com/<you>/oracle-a1-disabled-bypass (this repo's README)

Usage:
    pip install oci
    python3 create_sr.py            # dry run: prints the payload, sends nothing
    python3 create_sr.py --send     # actually files the ticket

Requires a working ~/.oci/config (the same one `oci` CLI uses).
"""
import json
import sys

import oci
from oci.cims import models as m

# ---------------------------------------------------------------------------
# EDIT EVERYTHING IN THIS SECTION
# ---------------------------------------------------------------------------

# Your tenancy's home region, as a 3-letter Oracle region code (NOT the
# "ca-toronto-1"-style identifier). Toronto = YYZ, Ashburn = IAD, Phoenix = PHX,
# Frankfurt = FRA, London = LHR, etc. Check your tenancy details page if unsure.
HOME_REGION_CODE = "YYZ"

TITLE = "Instance disabled after Always Free -> PAYG upgrade - please clear disable flag"

DESCRIPTION = """Tenancy: <your-tenancy-name> (<tenancy-ocid>)
Region: <your-region-identifier, e.g. ca-toronto-1>
Instance: <instance-display-name>
Instance OCID: <instance-ocid>
Shape: VM.Standard.A1.Flex, <OCPU>/<GB>, running since <date>

WHAT HAPPENED
On <date> Oracle system automation stopped this instance after the tenancy's
Always Free A1.Flex allocation was reduced. <Add audit-log event-grouping-ids
here if you have them, e.g. from `oci audit event list`.>

WHAT WE ALREADY DID
We upgraded the tenancy to Pay As You Go (Plan type: Pay As You Go, Account
type: Individual). Service limits are confirmed restored via
`oci limits value list --service-name compute` well above what this instance
needs.

THE REMAINING PROBLEM
Despite PAYG being active and limits restored, START (and RESET) on the
instance still fails with:

  ServiceError code=IncorrectState status=409 -
  "Instance <ocid> is disabled and will not accept any action requests.
   Please contact customer support to reenable."

WHY THIS IS FILED AS AN ACCOUNT REQUEST, NOT TECHNICAL
We cannot file a technical SR - the Console's "Create a support account"
button under Support Center does not fire a request (browser console shows
an "Unable to find action: undefined on
intent.cloudincidentmanagement.create-support-account.create" error), and
signing in at support.oracle.com with the commercial cloud account returns
"Tenancy not found."

WHAT WE NEED
1. Clear the account-level disable flag on instance <ocid> so START succeeds.
2. Provision/link a CSI and MOS support account for this tenancy so technical
   SRs are filable through normal channels going forward.

BUSINESS IMPACT
<Describe what's down / who's affected / how long.>
"""

CONTACT_NAME = "<Your Name>"
CONTACT_EMAIL = "<you@example.com>"
CONTACT_PHONE = "<+1XXXXXXXXXX>"

# These category/issue-type IDs are opaque Oracle taxonomy keys, not free text.
# The pair below (Account / "My Account and My Services Access") worked for
# an instance-disabled-after-upgrade case at the time this was written.
# Oracle can change these without notice - if create_incident rejects them,
# use the OCI Console's Ask Oracle / support chat category picker to find
# the current key for your situation, or open an issue in this repo.
CATEGORY_KEY = "b28b6f38"  # Account
ISSUE_TYPE_KEY = "9229c1cc"  # My Account and My Services Access

# ---------------------------------------------------------------------------
# Shouldn't need to touch anything below this line
# ---------------------------------------------------------------------------

cfg = oci.config.from_file(profile_name="DEFAULT")
client = oci.cims.IncidentClient(cfg)

item = m.CreateAccountItemDetails(
    type="account",
    category=m.CreateCategoryDetails(category_key=CATEGORY_KEY),
    issue_type=m.CreateIssueTypeDetails(issue_type_key=ISSUE_TYPE_KEY),
)

resource = m.CreateResourceDetails(item=item, region=HOME_REGION_CODE)

ticket = m.CreateTicketDetails(
    severity=m.CreateTicketDetails.SEVERITY_HIGH,  # Oracle may downgrade ACCOUNT
    resource_list=[resource],                       # requests to MEDIUM regardless
    title=TITLE,
    description=DESCRIPTION,
)

details = m.CreateIncident(
    compartment_id=cfg["tenancy"],
    ticket=ticket,
    problem_type="ACCOUNT",  # ACCOUNT and LIMIT don't require an MOS/CSI account.
    contacts=[
        m.Contact(
            contact_name=CONTACT_NAME,
            contact_email=CONTACT_EMAIL,
            email=CONTACT_EMAIL,
            contact_phone=CONTACT_PHONE,
            contact_type="PRIMARY",
        )
    ],
)

if "--send" not in sys.argv:
    print("DRY RUN - no request sent. Payload:")
    print(json.dumps(oci.util.to_dict(details), indent=2))
    print("\nRe-run with --send to actually file this ticket.")
    sys.exit(0)

response = client.create_incident(
    create_incident_details=details,
    ocid=cfg["user"],
    homeregion=cfg["region"],
)
data = oci.util.to_dict(response.data)

print("STATUS:", response.status)
print("SR KEY:", data.get("key"))
print(json.dumps({k: v for k, v in data.items() if not isinstance(v, (dict, list))}, indent=2))
