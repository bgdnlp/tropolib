#!/usr/bin/env python3
from troposphere import Template, Ref, GetAtt, Export, Output, Sub
from troposphere import ec2 as t_ec2
from pawslib.ec2 import split_net_across_zones
from pawslib.var import alphanum


def multiaz_subnets(
    name_prefix: str,
    cidr_block: str,
    region: str,
    vpc: object = None,
    vpc_id: str = None,
    no_of_subnets: int = 4,
    network_acl: object = None,
    network_acl_id: str = None,
    route_table: object = None,
    route_table_id: str = None,
) -> list:
    """Split given CIDR block into subnets over multiple AZs

    Either `vpc` or both `vpc_id` and `region`  are required.

    If a network ACL or route table are passed as parameters, they
    will be associated with the subnets.

    `vpc`, `network_acl` and `route_table` are expected to be
    Troposphere resource objects which can be passed to Ref and GetAtt
    functions. As an alternative, `vpc_id`, `region`, `network_acl_id`
    `route_table_id` can be passed directly. If both resource and *_id
    are specified, the *_id will take precedence.

    Returns a list of Troposphere resources that describes the subnets
    and can be attached to a Template object.

    Returned subnet objects have the following keys set in their
    Metadata attribute:
        az: full availability zone name ("eu-west-1a")
        az_index: uppercase AZ, without the region part ("A")
        suffix: the suffix that was added to the name to form a unique
            resource title. Probably a single digit.

    Args:
        name_prefix (str): Prefix each resource with this string. Use to
            assure unique name for the resource in the calling Template
        cidr_block (str): IP range to split into subnets
        region (str): AWS region
        vpc (object, optional): VPC Troposphere resource. One of vpc or
            vpc_id is required. Defaults to None.
        vpc_id (str, optional): VPC ID. One of vpc or vpc_id is
            required. Defaults to None.
        no_of_subnets (int, optional): Create this many subnets. must
            be a power of 2. Defaults to 4.
        network_acl (object, optional): Network ACL Troposphere
            resource. Defaults to None.
        network_acl_id (str, optional): Network ACL ID. Defaults to
            None.
        route_table (object, optional): Route table resource.
            Defaults to None.
        route_table_id (str, optional): Route table ID. Defaults to
            None.

    Raises:
        ValueError: If neither vpc nor vpc_id were specified.

    Returns:
        list: Troposphere resources to be added to Template.

    """
    if vpc is None and vpc_id is None:
        raise ValueError("One of vpc or vpc_id must be specified")
    if vpc_id is None:
        vpc_id = Ref(vpc)
    # Resource names only accept alphanumeric
    prefix = alphanum(name_prefix).lower().capitalize()
    net_split = split_net_across_zones(cidr_block, region, no_of_subnets)
    resources = list()
    for index, net_segment in enumerate(net_split):
        # set subnet
        az_index = net_segment["az"][-1:].upper()
        subnet = t_ec2.Subnet(
            title=f"{prefix}{index+1}",
            AvailabilityZone=net_segment["az"],
            CidrBlock=net_segment["cidr"],
            VpcId=vpc_id,
            Tags=[{"Key": "Name", "Value": f"{name_prefix} {az_index}"}],
        )
        subnet.Metadata = {}
        subnet.Metadata["az"] = net_segment["az"].lower()
        subnet.Metadata["az_index"] = az_index
        subnet.Metadata["suffix"] = index + 1
        resources.append(subnet)
        # associate network ACL with subnet
        if network_acl_id is None and network_acl is not None:
            network_acl_id = Ref(network_acl)
        if network_acl_id is not None:
            resources.append(
                t_ec2.SubnetNetworkAclAssociation(
                    title=f"{subnet.title}NaclAssociation",
                    SubnetId=Ref(subnet),
                    NetworkAclId=network_acl_id,
                )
            )
        if route_table_id is None and route_table is not None:
            route_table_id = Ref(route_table)
        if route_table_id is not None:
            resources.append(
                t_ec2.SubnetRouteTableAssociation(
                    title=f"{subnet.title}RouteAssociation",
                    SubnetId=Ref(subnet),
                    RouteTableId=route_table_id,
                )
            )
    return resources


class VpcTemplate:
    """Generate a CloudFormation Template that creates a VPC

    It can create the VPC, connect it to the internet via an internet
    gateway, set up NAT gateways and public and private subnets with the
    corresponding route tables and network ACLs.

    Exports:
        - VPC ID: stackname-vpc-id
    """

    def __init__(
        self,
        region: str,
        cidr_block: str,
        name: str = "VPC",
        internet_access_enabled: bool = True,
        internal_networks: list = [],
    ):
        """Create VPC, internet gateway, route tables and network ACLs

        Args:
            region (str): Region to use when setting up the VPC. The
                maximum number of subnets set up depends on the number
                of availability zones present in the region.
            cidr_block (str): IP range used by the VPC
            name (str, optional): VPC name. Defaults to "VPC".
            internet_access_enabled (bool, optional): If False, internet
                gateway will not be set up. Public network ACLs and
                route tables will still be created.
                Defaults to True.
            internal_networks (list, optional): IP ranges for private
                networks that this VPC will be connected to. They will
                be added to network ACLs. Defaults to [].
        """
        self.name = name
        self.region = region
        self.cidr_block = cidr_block
        self.internal_networks = internal_networks
        self.internet_access_enabled = internet_access_enabled
        self.nat_gateways = []
        self.natted_route_tables = []
        self._t = Template()  # Template
        self._r = dict()  # Resources
        self._o = dict()  # Outputs
        self._r["Vpc"] = t_ec2.VPC(
            title=f"{self.name}Vpc",
            CidrBlock=self.cidr_block,
            EnableDnsHostnames=True,
            EnableDnsSupport=True,
            Tags=[{"Key": "Name", "Value": self.name}],
        )
        self.vpc = self._r["Vpc"]
        self._o["VpcId"] = Output(
            title="VpcId",
            Value=Ref(self.vpc),
            Export=Export(Sub("${AWS::StackName}-vpc-id")),
        )
        if internet_access_enabled:
            # Create Internet Gateway
            title = "Igw"
            self._r[title] = t_ec2.InternetGateway(
                title=title,
                Tags=[{"Key": "Name", "Value": f"{self.name}-igw"}],
            )
            self._r["igw_attachment"] = t_ec2.VPCGatewayAttachment(
                title="IgwAttachment",
                VpcId=Ref(self.vpc),
                InternetGatewayId=Ref(self._r["Igw"]),
            )
        # Public routing table
        self._r["PubRouteTable"] = t_ec2.RouteTable(
            title="PubRouteTable",
            VpcId=Ref(self.vpc),
            Tags=[{"Key": "Name", "Value": "Public"}],
        )
        self.public_route_table = self._r["PubRouteTable"]
        if internet_access_enabled:
            self._r["pub_rtt_rt_pub"] = t_ec2.Route(
                title="PubRoute",
                RouteTableId=Ref(self._r["PubRouteTable"]),
                DestinationCidrBlock="0.0.0.0/0",
                GatewayId=Ref(self._r["Igw"]),
            )
        # Network ACL for public subnets
        self._r["PubNacl"] = t_ec2.NetworkAcl(
            title="PubNacl",
            VpcId=Ref(self.vpc),
            Tags=[{"Key": "Name", "Value": "Public"}],
        )
        self.public_nacl = self._r["PubNacl"]
        self._r["pub_nacl_out_all"] = t_ec2.NetworkAclEntry(
            title="PubNaclOutAll",
            NetworkAclId=Ref(self.public_nacl),
            Egress=True,
            RuleNumber=500,
            CidrBlock="0.0.0.0/0",
            Protocol=-1,
            RuleAction="allow",
        )
        self._r["pub_nacl_in_icmp"] = t_ec2.NetworkAclEntry(
            title="PubNaclInIcmp",
            NetworkAclId=Ref(self.public_nacl),
            Egress=False,
            RuleNumber=99,
            CidrBlock="0.0.0.0/0",
            Protocol=1,
            Icmp=t_ec2.ICMP(Code=-1, Type=-1),
            RuleAction="allow",
        )
        self._r["pub_nacl_in_vpc"] = t_ec2.NetworkAclEntry(
            title="PubNaclInVpc",
            NetworkAclId=Ref(self.public_nacl),
            Egress=False,
            RuleNumber=100,
            CidrBlock=GetAtt(self.vpc, "CidrBlock"),
            Protocol=-1,
            RuleAction="allow",
        )
        for index, cidr_block in enumerate(self.internal_networks):
            self._r[f"pub_nacl_in_internal_{index}"] = t_ec2.NetworkAclEntry(
                title=f"PubNaclInInternal{index}",
                NetworkAclId=Ref(self.public_nacl),
                Egress=False,
                RuleNumber=101 + index,
                CidrBlock=cidr_block,
                Protocol=-1,
                RuleAction="allow",
            )
        self._r["pub_nacl_in_ssh"] = t_ec2.NetworkAclEntry(
            title="PubNaclInSsh",
            NetworkAclId=Ref(self.public_nacl),
            Egress=False,
            RuleNumber=210,
            CidrBlock="0.0.0.0/0",
            Protocol=6,
            PortRange=t_ec2.PortRange(From=22, To=22),
            RuleAction="allow",
        )
        self._r["pub_nacl_in_http"] = t_ec2.NetworkAclEntry(
            title="PubNaclInHttp",
            NetworkAclId=Ref(self.public_nacl),
            Egress=False,
            RuleNumber=220,
            CidrBlock="0.0.0.0/0",
            Protocol=6,
            PortRange=t_ec2.PortRange(From=80, To=80),
            RuleAction="allow",
        )
        self._r["pub_nacl_in_https"] = t_ec2.NetworkAclEntry(
            title="PubNaclInHttps",
            NetworkAclId=Ref(self.public_nacl),
            Egress=False,
            RuleNumber=221,
            CidrBlock="0.0.0.0/0",
            Protocol=6,
            PortRange=t_ec2.PortRange(From=443, To=443),
            RuleAction="allow",
        )
        self._r["pub_nacl_in_nat_tcp"] = t_ec2.NetworkAclEntry(
            title="PubNaclInNatTcp",
            NetworkAclId=Ref(self.public_nacl),
            Egress=False,
            RuleNumber=500,
            CidrBlock="0.0.0.0/0",
            Protocol=6,
            PortRange=t_ec2.PortRange(From=1024, To=65535),
            RuleAction="allow",
        )
        self._r["pub_nacl_in_nat_udp"] = t_ec2.NetworkAclEntry(
            title="PubNaclInNatUdp",
            NetworkAclId=Ref(self.public_nacl),
            Egress=False,
            RuleNumber=501,
            CidrBlock="0.0.0.0/0",
            Protocol=17,
            PortRange=t_ec2.PortRange(From=1024, To=65535),
            RuleAction="allow",
        )
        # Network ACL for private subnets
        self._r["InternalNacl"] = t_ec2.NetworkAcl(
            title="InternalNacl",
            VpcId=Ref(self.vpc),
            Tags=[{"Key": "Name", "Value": "Private"}],
        )
        self.internal_nacl = self._r["InternalNacl"]
        self._r["internal_nacl_out_all"] = t_ec2.NetworkAclEntry(
            title="InternalNaclOutAll",
            NetworkAclId=Ref(self.internal_nacl),
            Egress=True,
            RuleNumber=500,
            CidrBlock="0.0.0.0/0",
            Protocol=-1,
            RuleAction="allow",
        )
        self._r["internal_nacl_in_icmp"] = t_ec2.NetworkAclEntry(
            title="InternalNaclInIcmp",
            NetworkAclId=Ref(self.internal_nacl),
            Egress=False,
            RuleNumber=99,
            CidrBlock="0.0.0.0/0",
            Protocol=1,
            Icmp=t_ec2.ICMP(Code=-1, Type=-1),
            RuleAction="allow",
        )
        self._r["internal_nacl_in_vpc"] = t_ec2.NetworkAclEntry(
            title="InternalNaclInVpc",
            NetworkAclId=Ref(self.internal_nacl),
            Egress=False,
            RuleNumber=100,
            CidrBlock=GetAtt(self.vpc, "CidrBlock"),
            Protocol=-1,
            RuleAction="allow",
        )
        for index, cidr_block in enumerate(self.internal_networks):
            self._r[f"internal_nacl_in_internal_{index}"] = t_ec2.NetworkAclEntry(
                title=f"InternalNaclInInternal{index}",
                NetworkAclId=Ref(self.internal_nacl),
                Egress=False,
                RuleNumber=101 + index,
                CidrBlock=cidr_block,
                Protocol=-1,
                RuleAction="allow",
            )
        self._r["internal_nacl_in_nat_tcp"] = t_ec2.NetworkAclEntry(
            title="InternalNaclInNatTcp",
            NetworkAclId=Ref(self.internal_nacl),
            Egress=False,
            RuleNumber=500,
            CidrBlock="0.0.0.0/0",
            Protocol=6,
            PortRange=t_ec2.PortRange(From=1024, To=65535),
            RuleAction="allow",
        )
        self._r["internal_nacl_in_nat_udp"] = t_ec2.NetworkAclEntry(
            title="InternalNaclInNatUdp",
            NetworkAclId=Ref(self.internal_nacl),
            Egress=False,
            RuleNumber=501,
            CidrBlock="0.0.0.0/0",
            Protocol=17,
            PortRange=t_ec2.PortRange(From=1024, To=65535),
            RuleAction="allow",
        )

    def add_public_subnet_group(
        self,
        name_prefix: str,
        cidr_block: str,
        no_of_subnets: int = 4,
        create_nat_gateways: bool = False,
    ):
        """Create public subnets and, optionally, NAT Gateways

        Args:
            name_prefix (str): Subnet name. AZ will be added at the end.
            cidr_block (str): Range of IP addresses to be split over
                availability zones.
            no_of_subnets (int, optional): How many subnets to set up.
                Defaults to 4.
            create_nat_gateways (bool, optional): If True, it will
                create one NAT gateway in each subnet and a private
                route table for each. Defaults to False.
        """
        for res in multiaz_subnets(
            name_prefix=name_prefix,
            cidr_block=cidr_block,
            region=self.region,
            no_of_subnets=no_of_subnets,
            vpc=self.vpc,
            network_acl=self.public_nacl,
            route_table=self.public_route_table,
        ):
            self._r[res.title] = res
            if create_nat_gateways and res.resource["Type"] == "AWS::EC2::Subnet":
                subnet = res
                az = subnet.Metadata["az"]
                az_index = subnet.Metadata["az_index"]
                suffix = subnet.Metadata["suffix"]
                # Elastic IP for NAT Gateway
                eip = t_ec2.EIP(title=f"EipNatGw{suffix}", Domain="vpc")
                self._r[eip.title] = eip
                # NAT Gateway
                nat_gw = t_ec2.NatGateway(
                    title=f"NatGw{suffix}",
                    AllocationId=GetAtt(eip, "AllocationId"),
                    SubnetId=Ref(subnet),
                    Tags=[{"Key": "Name", "Value": f"Nat Gw {az_index}"}],
                    Metadata={"az": az, "az_index": az_index, "suffix": suffix},
                )
                self._r[nat_gw.title] = nat_gw
                self.nat_gateways.append(nat_gw)
                # Natted route table
                route_table = t_ec2.RouteTable(
                    title=f"PrivRouteTable{suffix}",
                    VpcId=Ref(self.vpc),
                    Tags=[{"Key": "Name", "Value": f"Private {az_index}"}],
                    Metadata={"az": az, "az_index": az_index, "suffix": suffix},
                )
                self.natted_route_tables.append(route_table)
                # NAT route
                self._r[route_table.title] = route_table
                route = t_ec2.Route(
                    title=f"NatRoute{az_index.upper()}",
                    RouteTableId=Ref(route_table),
                    DestinationCidrBlock="0.0.0.0/0",
                    NatGatewayId=Ref(nat_gw),
                )
                self._r[route.title] = route

    def add_natted_subnet_group(
        self, cidr_block: str, name_prefix: str, no_of_subnets: int = 4
    ):
        """Create private subnets behind NAT gateways

        Creates a group of subnets, attaches the private network ACL and
        the corresponding private route table depending on AZ

        Args:
            cidr_block (str): Will be split across AZs
            name_prefix (str): Subnet name. AZ will be added at the end.
            no_of_subnets (int, optional): How many subnets to set up.
                Must be a power of 2. Defaults to 4.

        Raises:
            NotImplementedError: [description]
        """
        for res in multiaz_subnets(
            name_prefix=name_prefix,
            cidr_block=cidr_block,
            region=self.region,
            vpc=self.vpc,
            network_acl=self.internal_nacl,
        ):
            self._r[res.title] = res
            if res.resource["Type"] == "AWS::EC2::Subnet":
                subnet = res
                route_found = False
                for route_table in self.natted_route_tables:
                    if route_table.Metadata["az"] == subnet.Metadata["az"]:
                        self._r[
                            f"{subnet.title}RouteAssociation"
                        ] = t_ec2.SubnetRouteTableAssociation(
                            title=f"{subnet.title}RouteAssociation",
                            SubnetId=Ref(subnet),
                            RouteTableId=Ref(route_table),
                        )
                        route_found = True
                        break
                if not route_found:
                    raise NotImplementedError(
                        f"Can't find NAT gateway in {subnet.Metadata['az']}"
                    )

    def add_subnet_group(
        self,
        name_prefix: str,
        cidr_block: str,
        vpc: object = None,
        no_of_subnets: int = 4,
        network_acl: object = None,
        route_table: object = None,
    ):
        for res in multiaz_subnets(
            name_prefix=name_prefix,
            cidr_block=cidr_block,
            region=self.region,
            vpc=self.vpc,
            network_acl=network_acl,
            route_table=route_table,
        ):
            self._r[res.title] = res

    def peer_with_another_vpc(
        self,
        peer_vpc_id: str,
        peer_vpc_name: str,
        peer_role_arn: str = None,
        peer_owner_id: str = None,
        peer_region: str = None,
        peer_cidrs: list = [],
        add_route_to_private_tables: bool = True,
        add_route_to_public_table: bool = True,
    ):
        """Set VPC Peering

        Args:
            peer_vpc_id (str): The ID of the VPC with which you are
                creating the VPC peering connection
            peer_vpc_name (str): A name for the peer VPC, used in
                the Name tag for the peering connection
            peer_role_arn (str, optional): VPC peer role for the
                peering connection in another AWS account.
                Required if peering with a different AWS account.
                Defaults to None.
            peer_owner_id (str, optional): Owner of the other AWS
                account, if any.
                Defaults to None.
            peer_region (str, optional): The Region code for the
                accepter VPC. Defaults to the same region as requester
                VPC.
            peer_cidrs: (list, optional): List of CIDR blocks used
                by the peer VPC. If non-empty and any add_route_*
                argument is set to true, a route entry will be added
                to the respective table pointing that CIDR block to
                the peered connection.
                Defaults to an empty list.
            add_route_to_private_tables (bool,optional): If True,
                add the peered VPC to the private routing tables.
                Defaults to True.
            add_route_to_public_tables (bool,optional): If True,
                add the peered VPC to the public routing table.
                Defaults to True.

        Notes:
          - For the peered VPC to be added to the routing tables,
            they must already exist when this method is called. That
            means subnets should be created before setting up
            VPC Connection Peering.
          - As of Jan 2022 CloudFormation can't enable DNS resolution
        """
        res = t_ec2.VPCPeeringConnection(
            title=alphanum(
                f"Peer{peer_vpc_name.capitalize()}With{self.name.capitalize()}"
            ),
            VpcId=Ref(self.vpc),
            PeerVpcId=peer_vpc_id,
            Tags=[{"Key": "Name", "Value": f"{peer_vpc_name} - {self.name}"}],
        )
        if peer_region is not None:
            res.PeerRegion = peer_region
        if peer_owner_id is not None:
            res.PeerOwnerId = peer_owner_id
        if peer_role_arn is not None:
            res.PeerRoleArn = peer_role_arn
        self._r[res.title] = res
        if add_route_to_private_tables:
            for cidr in peer_cidrs:
                for route_table in self.natted_route_tables:
                    route_title = f"{route_table.title}Peer{alphanum(cidr)}Route"
                    self._r[route_title] = t_ec2.Route(
                        title=route_title,
                        RouteTableId=Ref(route_table),
                        DestinationCidrBlock=cidr,
                        VpcPeeringConnectionId=Ref(res),
                    )
        if add_route_to_public_table:
            for cidr in peer_cidrs:
                route_title = (
                    f"{self.public_route_table.title}Peer{alphanum(cidr)}Route"
                )
                self._r[route_title] = t_ec2.Route(
                    title=route_title,
                    RouteTableId=Ref(self.public_route_table),
                    DestinationCidrBlock=cidr,
                    VpcPeeringConnectionId=Ref(res),
                )

    def set_s3_endpoint(self):
        """Set an S3 endpoint with full access and add it to private routes"""
        res = t_ec2.VPCEndpoint(
            title=alphanum(f"{self.name}S3EndpointGateway"),
            VpcId=Ref(self.vpc),
            ServiceName=f"com.amazonaws.{self.region}.s3",
            RouteTableIds=[
                Ref(route_table) for route_table in self.natted_route_tables
            ],
        )

    def generate(self):
        for key, resource in self._r.items():
            self._t.add_resource(resource)
        for key, output in self._o.items():
            self._t.add_output(output)
        return self._t.to_yaml()


if __name__ == "__main__":
    pass
