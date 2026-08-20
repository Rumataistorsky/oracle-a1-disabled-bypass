#!/usr/bin/env python3
"""Print the category / issue-type keys you need to build a support request.

These keys are per-tenancy and per-region. Do not copy someone else's.

Usage:  python3 list_taxonomy.py [ACCOUNT|LIMIT|TECH] [profile]
"""
import sys

import oci

PROBLEM_TYPE = sys.argv[1] if len(sys.argv) > 1 else "ACCOUNT"
PROFILE = sys.argv[2] if len(sys.argv) > 2 else "DEFAULT"

cfg = oci.config.from_file(profile_name=PROFILE)
client = oci.cims.IncidentClient(cfg)

resp = client.list_incident_resource_types(
    problem_type=PROBLEM_TYPE,
    compartment_id=cfg["tenancy"],
    ocid=cfg["user"],
    homeregion=cfg["region"],
    limit=100,
)

for resource_type in oci.util.to_dict(resp.data):
    print("RESOURCE TYPE:", resource_type.get("label"),
          "| key:", resource_type.get("resource_type_key"))
    for category in resource_type.get("service_category_list") or []:
        print(f"  CAT   {category.get('key'):<10} {category.get('label')}")
        for issue in category.get("issue_type_list") or []:
            print(f"    ISSUE {issue.get('issue_type_key'):<10} {issue.get('label')}")
