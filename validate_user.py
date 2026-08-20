#!/usr/bin/env python3
"""Check which OCI support request types you are allowed to file.

A My Oracle Support account is required only for TECH requests. If ACCOUNT or
LIMIT come back with is_valid_user=true, you can file that type right now --
even while the Console insists you have no support account.

Usage:  python3 validate_user.py [profile]
"""
import sys

import oci

PROFILE = sys.argv[1] if len(sys.argv) > 1 else "DEFAULT"

cfg = oci.config.from_file(profile_name=PROFILE)
client = oci.cims.IncidentClient(cfg)

print("profile: ", PROFILE)
print("tenancy: ", cfg["tenancy"])
print("region:  ", cfg["region"])
print("endpoint:", client.base_client.endpoint)
print()

for problem_type in ("TECH", "ACCOUNT", "LIMIT"):
    try:
        resp = client.validate_user(
            problem_type=problem_type,
            ocid=cfg["user"],
            homeregion=cfg["region"],
        )
        print(f"{problem_type:<8} -> {resp.status} {resp.data}")
    except Exception as exc:  # noqa: BLE001 - we want the message, whatever it is
        print(
            f"{problem_type:<8} -> ERROR {getattr(exc, 'status', '')} "
            f"{getattr(exc, 'code', '')} {getattr(exc, 'message', str(exc))[:200]}"
        )
