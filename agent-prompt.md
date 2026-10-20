Set up a free Oracle Cloud "Always Free" ARM server for me. I already ran `uvx --from oci-cli oci setup bootstrap`, so `~/.oci/config` holds my login and home region. Stay inside the Always Free limits at every step. Ask me before you delete anything.

The fastest way is the script from https://free-oracle-vps.yarden-zamir.com. Read it first: https://free-oracle-vps.yarden-zamir.com/oracle-free-server.py
Then run `uv run https://free-oracle-vps.yarden-zamir.com/oracle-free-server.py --plan`, show me the plan, and run it without `--plan` after I agree. Its options are in `--help`.

If I ask you to do it by hand instead, follow these steps with the `oci` CLI (`uvx --from oci-cli oci ...`):

Goal: one VM.Standard.A1.Flex server, 4 OCPU, 24 GB RAM, 200 GB boot disk, latest Ubuntu LTS aarch64 image, reserved public IP, SSH with my key.

1. Read the tenancy OCID from `~/.oci/config`. Pass it as `-c` to every list call. `oci iam availability-domain list` without `-c` fails with NotAuthenticated.
2. A new API key can return 401 NotAuthenticated for a few minutes. Retry such calls every 10 seconds before you give up.
3. Ask me which SSH public key to use. Default to `~/.ssh/id_ed25519.pub`. Create the key if it does not exist.
4. Create a quota policy named `free-tier-only` (`oci limits quota create`) with these statements:
   zero compute-core quotas in tenancy
   zero compute-memory quotas in tenancy
   set compute-core quota standard-a1-core-count to 4 in tenancy
   set compute-core quota standard-a1-core-regional-count to 4 in tenancy
   set compute-memory quota standard-a1-memory-count to 24 in tenancy
   set compute-memory quota standard-a1-memory-regional-count to 24 in tenancy
   set compute-core quota standard-e2-micro-core-count to 2 in tenancy
   zero block-storage quotas in tenancy
   set block-storage quota total-storage-gb to 200 in tenancy
   set block-storage quota volume-count to 2 in tenancy
   set block-storage quota backup-count to 5 in tenancy
   zero database quotas in tenancy
   set database quota adb-free-count to 2 in tenancy
   zero load-balancer quotas in tenancy
   set load-balancer quota lb-flexible-count to 1 in tenancy
   set load-balancer quota lb-flexible-bandwidth-sum to 10 in tenancy
   Then check with `oci limits resource-availability get` that standard-a1-core-count has quota 4 and standard-e4-core-count has quota 0.
5. Create a 1 USD monthly budget named `free-tier-guard` for the tenancy, with an ACTUAL alert at 1 percent that emails me. The command path is `oci budgets budget budget create`, and `oci budgets budget alert-rule create` for the alert. Ask me for the email address.
6. Create a VCN (10.0.0.0/16), an internet gateway, a route rule 0.0.0.0/0 to the gateway in the default route table, and a public subnet (10.0.0.0/24). Keep the default security list. It allows SSH on port 22 only.
7. Find the newest "Canonical Ubuntu" 24.04 image for shape VM.Standard.A1.Flex (`oci compute image list --shape VM.Standard.A1.Flex --operating-system "Canonical Ubuntu" --operating-system-version 24.04 --sort-by TIMECREATED`).
8. Launch the server with `--shape-config '{"ocpus":4,"memoryInGBs":24}' --boot-volume-size-in-gbs 200 --assign-public-ip true --wait-for-state RUNNING`. If Oracle answers "Out of host capacity", try every availability domain, then retry every 60 seconds in the background. Stop on any other error and show it to me.
9. Replace the temporary public IP with a reserved one, named `<server-name>-ip`. Create the reserved IP first, delete the ephemeral IP of the primary private IP, then assign the reserved IP to that private IP. Tell me the new address.
10. Ask me which ports to open to the internet (for example TCP 80 and 443). `oci network security-list update` replaces the whole rule list. Read the current ingress rules, add the new ones, and convert the keys from kebab-case to camelCase before you send them. Keep the existing rules.
11. Oracle's Ubuntu images block all ports except 22 with iptables in `/etc/iptables/rules.v4`, not with ufw. Over SSH, insert ACCEPT rules for the same ports above the final REJECT rule, then run `sudo netfilter-persistent save`.
12. Add a `Host <server-name>` entry to `~/.ssh/config` with HostName, User ubuntu, IdentityFile and IdentitiesOnly yes. Back up the file first. Test `ssh <server-name> 'nproc; free -g; df -h /'`.
13. Report: server name, public IP, the SSH command, the quota check, the budget state and the open ports.

At the end, remind me to upgrade to Pay As You Go in the Oracle console: Billing & Cost Management, then Upgrade and Manage Payment, then Pay As You Go.
