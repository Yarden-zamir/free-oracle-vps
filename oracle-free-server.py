#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["oci>=2.189,<3"]
# ///
"""Create a free Oracle Cloud ARM server with cost guards.

Before you run it: sign up, turn on two-factor login, then log in with
`uvx --from oci-cli oci setup bootstrap`. Run it again at any time: it reuses what already exists.
Guide: https://free-oracle-vps.yarden-zamir.com
Source: https://github.com/Yarden-zamir/free-oracle-vps
"""

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import oci
from oci.core.models import (
    CreateInternetGatewayDetails,
    CreatePublicIpDetails,
    CreateSubnetDetails,
    CreateVcnDetails,
    CreateVnicDetails,
    GetPublicIpByPrivateIpIdDetails,
    IcmpOptions,
    IngressSecurityRule,
    InstanceSourceViaImageDetails,
    LaunchInstanceDetails,
    LaunchInstanceShapeConfigDetails,
    PortRange,
    RouteRule,
    TcpOptions,
    UdpOptions,
    UpdatePublicIpDetails,
    UpdateRouteTableDetails,
    UpdateSecurityListDetails,
)

SHAPE = "VM.Standard.A1.Flex"
FREE = {"ocpus": 4, "memory": 24, "disk": 200}  # Always Free ARM allowance
QUOTA_NAME, BUDGET_NAME = "free-tier-only", "free-tier-guard"
QUOTA_STATEMENTS = [
    "zero compute-core quotas in tenancy",
    "zero compute-memory quotas in tenancy",
    "set compute-core quota standard-a1-core-count to 4 in tenancy",
    "set compute-core quota standard-a1-core-regional-count to 4 in tenancy",
    "set compute-memory quota standard-a1-memory-count to 24 in tenancy",
    "set compute-memory quota standard-a1-memory-regional-count to 24 in tenancy",
    "set compute-core quota standard-e2-micro-core-count to 2 in tenancy",
    "zero block-storage quotas in tenancy",
    "set block-storage quota total-storage-gb to 200 in tenancy",
    "set block-storage quota volume-count to 2 in tenancy",
    "set block-storage quota backup-count to 5 in tenancy",
    "zero database quotas in tenancy",
    "set database quota adb-free-count to 2 in tenancy",
    "zero load-balancer quotas in tenancy",
    "set load-balancer quota lb-flexible-count to 1 in tenancy",
    "set load-balancer quota lb-flexible-bandwidth-sum to 10 in tenancy",
]


def step(title: str) -> None:
    print(f"\n\033[1m==> {title}\033[0m")


def ok(text: str) -> None:
    print(f"    \033[32m✓\033[0m {text}")


def plan(text: str) -> None:
    print(f"    \033[33m+\033[0m would {text}")


@dataclass
class Cloud:
    args: argparse.Namespace
    tenancy: str
    region: str
    identity: oci.identity.IdentityClient
    network: oci.core.VirtualNetworkClient
    network_ops: oci.core.VirtualNetworkClientCompositeOperations
    compute: oci.core.ComputeClient
    quotas: oci.limits.QuotasClient
    budgets: oci.budget.BudgetClient

    @classmethod
    def connect(cls, args: argparse.Namespace) -> "Cloud":
        config = oci.config.from_file(profile_name=args.profile)
        kw = {"retry_strategy": oci.retry.DEFAULT_RETRY_STRATEGY}
        network = oci.core.VirtualNetworkClient(config, **kw)
        cloud = cls(
            args,
            config["tenancy"],
            config["region"],
            oci.identity.IdentityClient(config, **kw),
            network,
            oci.core.VirtualNetworkClientCompositeOperations(network),
            oci.core.ComputeClient(config, **kw),
            oci.limits.QuotasClient(config, **kw),
            oci.budget.BudgetClient(config, **kw),
        )
        cloud.wait_for_login()
        return cloud

    def wait_for_login(self) -> None:
        """A new API key returns 401 for a few minutes after `oci setup bootstrap`."""
        for _ in range(12):
            try:
                self.identity.list_availability_domains(self.tenancy)
                return
            except oci.exceptions.ServiceError as e:
                if e.status != 401:
                    raise
                time.sleep(10)
        sys.exit("Oracle still rejects the login. Run `uvx --from oci-cli oci setup bootstrap` again.")

    def all(self, list_call, *args, **filters) -> list:
        return oci.pagination.list_call_get_all_results(list_call, *args, **filters).data


def first[T](items: list[T]) -> T | None:
    return items[0] if items else None


def quotas(c: Cloud) -> None:
    step("Quotas (block paid resources)")
    if first(c.all(c.quotas.list_quotas, c.tenancy, name=QUOTA_NAME)):
        return ok(f"quota policy {QUOTA_NAME} exists")
    if c.args.plan:
        return plan(f"create quota policy {QUOTA_NAME}")
    c.quotas.create_quota(
        oci.limits.models.CreateQuotaDetails(
            compartment_id=c.tenancy,
            name=QUOTA_NAME,
            statements=QUOTA_STATEMENTS,
            description="Block all resources beyond the Always Free allowance",
        )
    )
    ok(f"quota policy {QUOTA_NAME}")


def budget(c: Cloud) -> None:
    step("Budget alert")
    if first(c.all(c.budgets.list_budgets, c.tenancy, display_name=BUDGET_NAME)):
        return ok(f"budget {BUDGET_NAME} exists")
    if c.args.plan:
        return plan(f"create a {c.args.budget} USD monthly budget that emails {c.args.email}")
    models = oci.budget.models
    created = c.budgets.create_budget(
        models.CreateBudgetDetails(
            compartment_id=c.tenancy,
            display_name=BUDGET_NAME,
            amount=c.args.budget,
            reset_period="MONTHLY",
            target_type="COMPARTMENT",
            targets=[c.tenancy],
        )
    ).data
    c.budgets.create_alert_rule(
        created.id,
        models.CreateAlertRuleDetails(
            display_name="any-spend",
            type="ACTUAL",
            threshold=1,
            threshold_type="PERCENTAGE",
            recipients=c.args.email,
            message="Oracle Cloud charged money. The free tier is exceeded.",
        ),
    )
    ok(f"{c.args.budget} USD monthly budget {BUDGET_NAME}, alerts to {c.args.email}")


def ingress_rules(tcp: list[int], udp: list[int]) -> list[IngressSecurityRule]:
    def rule(source: str, protocol: str, **options) -> IngressSecurityRule:
        return IngressSecurityRule(source=source, protocol=protocol, is_stateless=False, **options)

    def port(p: int) -> PortRange:
        return PortRange(min=p, max=p)

    # The first three rules are the Oracle defaults for a new network. The update replaces the whole list.
    return [
        rule("0.0.0.0/0", "6", tcp_options=TcpOptions(destination_port_range=port(22))),
        rule("0.0.0.0/0", "1", icmp_options=IcmpOptions(type=3, code=4)),
        rule("10.0.0.0/16", "1", icmp_options=IcmpOptions(type=3)),
        *(rule("0.0.0.0/0", "6", tcp_options=TcpOptions(destination_port_range=port(p))) for p in tcp),
        *(rule("0.0.0.0/0", "17", udp_options=UdpOptions(destination_port_range=port(p))) for p in udp),
    ]


def open_ports(a: argparse.Namespace) -> str:
    udp = ", ".join(map(str, a.udp)) or "none"
    return f"TCP {', '.join(map(str, [22, *a.tcp]))}; UDP {udp}"


def network(c: Cloud) -> str | None:
    """Create the network and return the subnet id."""
    step("Network")
    name, available = c.args.name, ["AVAILABLE"]
    vcn = first(c.all(c.network.list_vcns, c.tenancy, display_name=f"{name}-vcn", lifecycle_state="AVAILABLE"))
    if not vcn and c.args.plan:
        plan(f"create network {name}-vcn, internet gateway, route and public subnet")
        plan(f"open {open_ports(c.args)} in the Oracle firewall")
        return None
    vcn = (
        vcn
        or c.network_ops.create_vcn_and_wait_for_state(
            CreateVcnDetails(
                compartment_id=c.tenancy, display_name=f"{name}-vcn", cidr_blocks=["10.0.0.0/16"], dns_label="vcn"
            ),
            available,
        ).data
    )
    ok(f"network {name}-vcn")

    gateway = first(c.all(c.network.list_internet_gateways, c.tenancy, vcn_id=vcn.id, display_name=f"{name}-igw"))
    if not gateway and c.args.plan:
        plan(f"create internet gateway {name}-igw")
    else:
        gateway = (
            gateway
            or c.network_ops.create_internet_gateway_and_wait_for_state(
                CreateInternetGatewayDetails(
                    compartment_id=c.tenancy, vcn_id=vcn.id, display_name=f"{name}-igw", is_enabled=True
                ),
                available,
            ).data
        )
        route = RouteRule(destination="0.0.0.0/0", destination_type="CIDR_BLOCK", network_entity_id=gateway.id)
        if c.args.plan:
            plan(f"set the default route to internet gateway {name}-igw")
        else:
            c.network.update_route_table(vcn.default_route_table_id, UpdateRouteTableDetails(route_rules=[route]))
            ok(f"internet gateway {name}-igw and route")

    rules = ingress_rules(c.args.tcp, c.args.udp)
    if c.args.plan:
        plan(f"open {open_ports(c.args)} in the Oracle firewall")
    else:
        c.network.update_security_list(
            vcn.default_security_list_id, UpdateSecurityListDetails(ingress_security_rules=rules)
        )
        ok(f"Oracle firewall: {open_ports(c.args)}")

    subnet = first(
        c.all(
            c.network.list_subnets, c.tenancy, vcn_id=vcn.id, display_name=f"{name}-subnet", lifecycle_state="AVAILABLE"
        )
    )
    if not subnet and c.args.plan:
        plan(f"create public subnet {name}-subnet")
        return None
    subnet = (
        subnet
        or c.network_ops.create_subnet_and_wait_for_state(
            CreateSubnetDetails(
                compartment_id=c.tenancy,
                vcn_id=vcn.id,
                display_name=f"{name}-subnet",
                cidr_block="10.0.0.0/24",
                dns_label="public",
                route_table_id=vcn.default_route_table_id,
                security_list_ids=[vcn.default_security_list_id],
            ),
            available,
        ).data
    )
    ok(f"public subnet {name}-subnet")
    return subnet.id


def is_capacity_error(e: oci.exceptions.ServiceError) -> bool:
    return e.status == 429 or (e.status == 500 and "capacity" in (e.message or "").lower())


def server(c: Cloud, subnet_id: str | None) -> str | None:
    """Create the server and return its id. Free ARM capacity is often sold out, so retry until Oracle has some."""
    step("Server")
    a = c.args
    existing = [
        i for i in c.all(c.compute.list_instances, c.tenancy, display_name=a.name) if i.lifecycle_state != "TERMINATED"
    ]
    if existing:
        ok(f"server {a.name} exists ({existing[0].lifecycle_state})")
        return existing[0].id

    images = c.all(
        c.compute.list_images,
        c.tenancy,
        operating_system="Canonical Ubuntu",
        operating_system_version=a.ubuntu,
        shape=SHAPE,
        sort_by="TIMECREATED",
        sort_order="DESC",
    )
    image = first(images) or sys.exit(f"No Ubuntu {a.ubuntu} ARM image in {c.region}.")
    domains = [d.name for d in c.identity.list_availability_domains(c.tenancy).data]
    spec = f"{a.ocpus} cores, {a.memory} GB RAM, {a.disk} GB disk, {image.display_name}"
    if a.plan or subnet_id is None:
        plan(f"create server {a.name}: {spec}")
        return None

    details = LaunchInstanceDetails(
        compartment_id=c.tenancy,
        display_name=a.name,
        shape=SHAPE,
        shape_config=LaunchInstanceShapeConfigDetails(ocpus=a.ocpus, memory_in_gbs=a.memory),
        source_details=InstanceSourceViaImageDetails(image_id=image.id, boot_volume_size_in_gbs=a.disk),
        create_vnic_details=CreateVnicDetails(subnet_id=subnet_id, assign_public_ip=True, hostname_label=a.name),
        metadata={"ssh_authorized_keys": a.ssh_key.read_text().strip()},
    )
    attempt = 0
    while True:
        attempt += 1
        for domain in domains:
            details.availability_domain = domain
            try:
                # Retry here, not in the SDK: the SDK retries 500 errors only a few times.
                launched = c.compute.launch_instance(details, retry_strategy=oci.retry.NoneRetryStrategy()).data
            except oci.exceptions.ServiceError as e:
                if not is_capacity_error(e):
                    raise
                continue
            oci.wait_until(c.compute, c.compute.get_instance(launched.id), "lifecycle_state", "RUNNING")
            ok(f"server {a.name} is running: {spec}")
            return launched.id
        print(
            f"    {time.strftime('%H:%M:%S')} attempt {attempt}: no free capacity, next try in "
            f"{a.retry} seconds (Ctrl+C to stop)"
        )
        time.sleep(a.retry)


def public_ip(c: Cloud, instance_id: str) -> str:
    """Give the server a reserved IP. It stays the same when the server is recreated."""
    step("Public IP")
    attachment = first(c.all(c.compute.list_vnic_attachments, c.tenancy, instance_id=instance_id))
    if attachment is None:
        sys.exit("The server has no network card yet. Run the script again in a minute.")
    private = first([p for p in c.all(c.network.list_private_ips, vnic_id=attachment.vnic_id) if p.is_primary])
    try:
        current = c.network.get_public_ip_by_private_ip_id(
            GetPublicIpByPrivateIpIdDetails(private_ip_id=private.id)
        ).data
    except oci.exceptions.ServiceError as e:
        if e.status != 404:
            raise
        current = None
    if c.args.no_reserved_ip or (current and current.lifetime == "RESERVED"):
        if current is None:
            sys.exit("The server has no public IP. Run without --no-reserved-ip.")
        ok(f"public IP {current.ip_address} ({current.lifetime.lower()})")
        return current.ip_address
    if c.args.plan:
        plan(f"replace the temporary IP {current.ip_address if current else ''} with a reserved IP {c.args.name}-ip")
        return current.ip_address if current else ""

    reserved = first(
        [
            p
            for p in c.all(c.network.list_public_ips, "REGION", c.tenancy, lifetime="RESERVED")
            if p.display_name == f"{c.args.name}-ip"
        ]
    )
    reserved = (
        reserved
        or c.network_ops.create_public_ip_and_wait_for_state(
            CreatePublicIpDetails(compartment_id=c.tenancy, lifetime="RESERVED", display_name=f"{c.args.name}-ip"),
            ["AVAILABLE"],
        ).data
    )
    if current:  # Oracle cannot convert a temporary IP, so SSH drops for a moment during the swap.
        c.network_ops.delete_public_ip_and_wait_for_state(current.id, ["TERMINATED"])
    c.network_ops.update_public_ip_and_wait_for_state(
        reserved.id, UpdatePublicIpDetails(private_ip_id=private.id), ["ASSIGNED"]
    )
    ok(f"reserved public IP {reserved.ip_address}")
    return reserved.ip_address


def ssh_setup(c: Cloud, ip: str) -> None:
    step("SSH")
    a = c.args
    config = Path.home() / ".ssh" / "config"
    config.parent.mkdir(mode=0o700, exist_ok=True)
    text = config.read_text() if config.exists() else ""
    if f"Host {a.name}\n" in text:
        print(f"    Host {a.name} is already in {config}. Check that its HostName is {ip}.")
    elif a.plan:
        plan(f"add Host {a.name} to {config}")
    else:
        if text:
            config.with_name(f"config.bak-{time.strftime('%Y%m%d-%H%M%S')}").write_text(text)
        identity = a.ssh_key.with_suffix("")
        config.write_text(
            f"{text}\nHost {a.name}\n\tHostName {ip}\n\tUser ubuntu\n\tIdentityFile {identity}\n\tIdentitiesOnly yes\n"
        )
        ok(f"added Host {a.name} to {config}")
    if a.plan:
        return

    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new", a.name]
    for _ in range(20):
        if subprocess.run([*ssh, "true"], capture_output=True).returncode == 0:
            break
        time.sleep(15)
    else:
        sys.exit(f"SSH to {a.name} does not answer. Try again later: ssh {a.name}")
    ok(f"ssh {a.name} works")

    ports = [("tcp", p) for p in a.tcp] + [("udp", p) for p in a.udp]
    if a.no_server_firewall or not ports:
        return
    # Oracle's Ubuntu images block every port except 22 with iptables. Insert the rules above the REJECT rule.
    rules = "\n".join(f"open {proto} {p}" for proto, p in ports)
    remote = f"""set -e
open() {{
  iptables -C INPUT -p "$1" --dport "$2" -j ACCEPT 2>/dev/null && return
  n=$(iptables -L INPUT --line-numbers | awk '$2 == "REJECT" {{ print $1; exit }}')
  if [ -n "$n" ]; then
    iptables -I INPUT "$n" -p "$1" --dport "$2" -j ACCEPT
  else
    iptables -A INPUT -p "$1" --dport "$2" -j ACCEPT
  fi
}}
{rules}
netfilter-persistent save >/dev/null 2>&1
"""
    subprocess.run([*ssh, "sudo", "bash", "-s"], input=remote, text=True, check=True)
    ok(f"server firewall: {', '.join(f'{proto.upper()} {p}' for proto, p in ports)} open")


def ports(text: str) -> list[int]:
    values = [int(p) for p in text.replace(",", " ").split()] if text.strip() not in ("", "none") else []
    if any(not 1 <= p <= 65535 for p in values):
        raise argparse.ArgumentTypeError("ports must be from 1 to 65535")
    return values


def within(limit: int):
    def check(text: str) -> int:
        value = int(text)
        if not 1 <= value <= limit:
            raise argparse.ArgumentTypeError(f"must be from 1 to {limit}, the Always Free limit")
        return value

    return check


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="oracle-free-server.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("name", nargs="?", default="oracle-vps", help="server name and SSH host name (default: oracle-vps)")
    p.add_argument("--email", help="email for the cost alert (asked if missing)")
    p.add_argument("--ssh-key", type=Path, default=Path.home() / ".ssh" / "id_ed25519.pub", help="SSH public key")
    p.add_argument("--tcp", type=ports, default=[80, 443], help="TCP ports to open besides 22 (default: 80,443)")
    p.add_argument("--udp", type=ports, default=[], help="UDP ports to open, for example 443 for HTTP/3")
    p.add_argument("--ocpus", type=within(FREE["ocpus"]), default=FREE["ocpus"], help="cores (default: 4)")
    p.add_argument("--memory", type=within(FREE["memory"]), default=FREE["memory"], help="RAM in GB (default: 24)")
    p.add_argument(
        "--disk", type=within(FREE["disk"]), default=FREE["disk"], help="disk in GB, at least 50 (default: 200)"
    )
    p.add_argument("--ubuntu", choices=["22.04", "24.04", "26.04"], default="24.04", help="Ubuntu version")
    p.add_argument("--budget", type=float, default=1.0, help="monthly budget in USD for the alert (default: 1)")
    p.add_argument("--retry", type=int, default=60, help="seconds between capacity retries (default: 60)")
    p.add_argument("--profile", default="DEFAULT", help="profile in ~/.oci/config")
    p.add_argument("--no-quotas", action="store_true", help="skip the quotas that block paid resources")
    p.add_argument("--no-budget", action="store_true", help="skip the budget alert")
    p.add_argument("--no-reserved-ip", action="store_true", help="keep the temporary public IP")
    p.add_argument("--no-server-firewall", action="store_true", help="do not open the ports inside the server")
    p.add_argument("--plan", action="store_true", help="show what the script would do, change nothing")
    a = p.parse_args()

    if (
        any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in a.name)
        or not a.name[:1].isalpha()
        or len(a.name) > 30
    ):
        p.error("the name must start with a letter and use only a-z, 0-9 and '-' (max 30)")
    if a.disk < 50:
        p.error("--disk must be at least 50, the smallest Oracle boot disk")
    a.ssh_key = a.ssh_key.expanduser()
    if not a.ssh_key.exists() and not a.plan:
        print(f"No key at {a.ssh_key}. Creating one.")
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-f", str(a.ssh_key.with_suffix("")), "-N", "", "-C", a.name], check=True
        )
    if not a.no_budget and not a.email:
        a.email = input("Email for the cost alert: ").strip()
    if not a.no_budget and "@" not in a.email:
        p.error("give a valid --email for the cost alert, or use --no-budget")
    return a


def main() -> None:
    args = parse_args()
    if not Path("~/.oci/config").expanduser().exists():
        sys.exit("Log in first: uvx --from oci-cli oci setup bootstrap")
    c = Cloud.connect(args)
    step(f"Oracle region {c.region}, server {args.name}{' (plan only, no changes)' if args.plan else ''}")
    if not args.no_quotas:
        quotas(c)
    if not args.no_budget:
        budget(c)
    instance_id = server(c, network(c))
    if instance_id is None:
        return step("Plan done. Run again without --plan to apply.")
    ip = public_ip(c, instance_id)
    ssh_setup(c, ip)
    step("Done" if not args.plan else "Plan done. Run again without --plan to apply.")
    print(f"    Connect: ssh {args.name}\n    IP:      {ip}")
    if not args.plan:
        print(
            "    Next: upgrade to Pay As You Go in the Oracle console:\n"
            "          Billing & Cost Management > Upgrade and Manage Payment > Pay As You Go"
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nStopped.")
    except oci.exceptions.ServiceError as e:
        sys.exit(f"\nOracle error {e.status} {e.code}: {e.message}")
