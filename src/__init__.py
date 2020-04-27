#!/usr/bin/env python3
from troposphere import Ref
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
            Tags=[
                {
                    "Key": "Name",
                    "Value": f"{name_prefix} {index+1}({az_index})",
                }
            ],
        )
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

if __name__ == "__main__":
    pass
