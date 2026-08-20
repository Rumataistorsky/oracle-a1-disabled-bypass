#!/usr/bin/env python3
"""List, comment on, and close OCI Service Requests through the API.

Useful because the Console's Support Center still returns 403 while your
tenancy has no My Oracle Support account -- the API does not.

    python3 manage_sr.py list
    python3 manage_sr.py note  12345678 "Please escalate, production is down"
    python3 manage_sr.py close 12345678 "Filed by mistake, please close"

Note: GetIncident is gated behind the same My Oracle Support check that
blocks TECH requests, so fetching one SR by number returns
403 SUPPORT_ACCOUNT_NOT_FOUND. ListIncidents is not gated, which is why
"list" below reads state by listing rather than getting. Notes and close
both work normally.

Watch the lifecycle_details field:
    PENDING_WITH_ORACLE    they have it
    PENDING_WITH_CUSTOMER  they asked you something -- you get no Console alert
    CLOSED                 done
"""
import sys

import oci
from oci.cims import models

PROFILE = "DEFAULT"
PROBLEM_TYPE = "ACCOUNT"

cfg = oci.config.from_file(profile_name=PROFILE)
client = oci.cims.IncidentClient(cfg)
common = dict(ocid=cfg["user"], homeregion=cfg["region"])


def cmd_list() -> None:
    resp = client.list_incidents(
        compartment_id=cfg["tenancy"], problem_type=PROBLEM_TYPE, limit=50, **common
    )
    if not resp.data:
        print("no service requests found")
        return
    for incident in resp.data:
        d = oci.util.to_dict(incident)
        t = d.get("ticket") or {}
        print(
            f"{d.get('key'):<12} {t.get('lifecycle_state'):<10} "
            f"{str(t.get('lifecycle_details')):<24} {str(t.get('severity')):<8} "
            f"{(t.get('title') or '')[:60]}"
        )


def _activity(key: str, activity_type: str, comment: str) -> None:
    details = models.UpdateIncident(
        ticket=models.UpdateTicketDetails(
            resource=models.UpdateResourceDetails(
                item=models.UpdateActivityItemDetails(
                    type="activity", activity_type=activity_type, comments=comment
                )
            )
        ),
        problem_type=PROBLEM_TYPE,
    )
    # compartment_id is a positional argument here even though the docs omit it
    resp = client.update_incident(
        incident_key=key,
        compartment_id=cfg["tenancy"],
        update_incident_details=details,
        **common,
    )
    print(f"{activity_type} on {key} -> HTTP {resp.status}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] == "list":
        cmd_list()
    elif sys.argv[1] == "note":
        _activity(sys.argv[2], "NOTES", sys.argv[3])
    elif sys.argv[1] == "close":
        _activity(sys.argv[2], "CLOSE", sys.argv[3])
    else:
        print(__doc__)
        sys.exit(1)
