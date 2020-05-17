#!/usr/bin/env python3
import json
from troposphere import Ref, Join, Region, AccountId
from troposphere import apigatewayv2 as t_apigw2
from pawslib.var import alphanum


class HttpApi:
    def __init__(self, name: str, description: str = None):
        self.name = name
        self.clean_name = alphanum(name)
        self.description = description
        self.resources = dict()
        self.t_api = t_apigw2.Api(
            title=f"{self.clean_name}HTTPApi", ProtocolType="HTTP", Name=self.name,
        )
        if description is not None:
            self.t_api.Description = description
        self.resources[self.t_api.title] = self.t_api

    def add_stage(self, name: str, auto_deploy: bool = False, log_format: str = "none"):
        if log_format.lower() in ["none", "clf", "json", "xml", "csv"]:
            pass
        elif "$context.requestId" in log_format:
            pass
        else:
            raise ValueError(f"{log_format} is not a valid log format")
        # Create Troposphere resource
        api_stage = t_apigw2.Stage(
            title=f"{alphanum(name)}Stage", ApiId=Ref(self.t_api), StageName=name
        )
        # Set logging
        if log_format.lower() != "none":
            api_stage_log = t_apigw2.AccessLogSettings(
                DestinationArn=Join(
                    ":",
                    [
                        "arn",
                        "aws",
                        "logs",
                        Region,
                        AccountId,
                        f"{self.clean_name}HttpApi",
                        alphanum(name),
                    ],
                )
            )
            if log_format.lower() == "clf":
                api_stage_log.Format = '$context.identity.sourceIp - - [$context.requestTime] "$context.httpMethod $context.routeKey $context.protocol" $context.status $context.responseLength $context.requestId'  # noqa: E501
            elif log_format.lower() == "json":
                api_stage_log.Format = json.dumps(
                    {
                        "requestId": "$context.requestId",
                        "ip": "$context.identity.sourceIp",
                        "requestTime": "$context.requestTime",
                        "httpMethod": "$context.httpMethod",
                        "routeKey": "$context.routeKey",
                        "status": "$context.status",
                        "protocol": "$context.protocol",
                        "responseLength": "$context.responseLength",
                    }
                )
            elif log_format.lower() == "xml":
                api_stage_log.Format = '<request id="$context.requestId"> <ip>$context.identity.sourceIp</ip> <requestTime>$context.requestTime</requestTime> <httpMethod>$context.httpMethod</httpMethod> <routeKey>$context.routeKey</routeKey> <status>$context.status</status> <protocol>$context.protocol</protocol> <responseLength>$context.responseLength</responseLength> </request>'  # noqa: E501
            elif log_format.lower() == "csv":
                api_stage_log.Format = "$context.identity.sourceIp,$context.requestTime,$context.httpMethod,$context.routeKey,$context.protocol,$context.status,$context.responseLength,$context.requestId"  # noqa: E501

        api_stage.AutoDeploy = auto_deploy

    def add_route(
        self,
        path: str,
        target: str,
        http_method: str = "ANY",
        timeout: int = 10000,
        description: str = None,
    ):
        # TODO:
        #   - Configure CORS?
        #   - CredentialsArn should be null?
        #   - generate $default?
        if http_method.upper() not in [
            "ANY",
            "GET",
            "POST",
            "PUT",
            "PATCH",
            "HEAD",
            "DELETE",
            "OPTIONS",
        ]:
            raise ValueError(f"{http_method} is not a valid HTTP METHOD")
        # Define HTTP API Integration
        api_integration = t_apigw2.Integration(
            title=f"{alphanum(path)}Integration", ApiId=Ref(self.t_api),
        )
        if description is not None:
            api_integration.Description = description
        api_integration.IntegrationMethod = http_method
        api_integration.IntegrationUri = target
        if target.lower()[:5] == "http:" or target.lower()[:6] == "https:":
            api_integration.IntegrationType = "HTTP_PROXY"
            api_integration.PayloadFormatVersion = "1.0"
        else:
            api_integration.IntegrationType = "AWS_PROXY"
            api_integration.PayloadFormatVersion = "2.0"
        api_integration.TimeoutInMillis = timeout
        # Define HTTP API route
        api_route = t_apigw2.Route(
            title=f"{alphanum(path)}Route", ApiId=Ref(self.t_api),
        )
        if description is not None:
            api_route.OperationName = description
        api_route.RouteKey = f"{http_method} /{path}"
        api_route.Target = Join("/", ["integrations", Ref(api_integration)])
        self.resources[api_integration.title] = api_integration
        self.resources[api_route] = api_route


if __name__ == "__main__":
    pass
