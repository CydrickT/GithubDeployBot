# Copyright (c) 2022 CydrickT
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

# AWS Lambda function for GitHub Deploy Bot
# https://github.com/CydrickT/GithubDeployBot

import os
import json
import urllib3
import boto3
import time
import datetime
import urllib.parse
import uuid

client = boto3.client('dynamodb')

TABLE_NAME = 'BuildDeployRequests'

#############################
# Entry Point
#############################
def lambda_handler(event, context):
    client = boto3.client('dynamodb')
    if event is not None and event["queryStringParameters"] is not None and event["queryStringParameters"]["type"] is not None:
        type = event["queryStringParameters"]["type"]
        body = event['body']
        if type == "build_deploy_requested":
            # Step 1: This is a deploy request from the GitHub action. We need to send a message to the Slack channel for approval.
            return send_slack_authorization_request(body)
        elif type == "user_response_received":
            # Step 2: This is a deploy response from Slack. The user provided a response. Need to update the Slack message and store the response.
            return parse_user_response(body)
        elif type == "verify_authorization":
            # Step 3: This is a periodic check from GitHub action to verify if the user approved it or not.
            return verify_authorization(body)
        else:
            return {"statusCode": 404}
            
#############################
# Step 1: Request from GitHub Actions
#############################

def send_slack_authorization_request(body):
    # Parsing GitHub Action's request's body
    github_parsed_request = json.loads(body)
    github_deploy_id = github_parsed_request['id']
    github_submitted_date = github_parsed_request['submitted_date']
    github_requestor = github_parsed_request['requestor']
    github_version = github_parsed_request['version']
    github_deployment_environments = github_parsed_request['deployment_environments']
    github_whitelisted_environments = github_parsed_request['whitelisted_environments']
    github_build_type = github_parsed_request['build_type']
    github_slack_channel_id = github_parsed_request['slack_channel_id']
    github_slack_bot_oauth_token = github_parsed_request['slack_bot_oauth_token']
    
    # Verifying if the request ID is already in the database.
    if get_request(github_deploy_id) is not None:
        return {"statusCode": 400, 'body': json.dumps({'reason': 'Request already exists'})}
    
    # Inserting the request's data in the database
    client.put_item(
        TableName=TABLE_NAME,
        Item={
            'id':{'S': github_deploy_id}, 
            'request_date':{'S': github_submitted_date}, 
            'requestor': {'S': github_requestor},
            'version':{'S': github_version},
            'deployment_environments': {'SS': github_deployment_environments},
            'build_type': {'S': github_build_type},
            'slack_channel_id': {'S': github_slack_channel_id},
            'slack_bot_oauth_token': {'S': github_slack_bot_oauth_token},
            'approval_date': {'NULL': True},
            'approver': {'NULL': True},
            'approval_response': {'NULL': True},
        }
    )
    
    if (is_deploy_whitelisted(github_whitelisted_environments, github_deployment_environments)):
        client.update_item(
            TableName=TABLE_NAME,
            Key={'id': {'S': github_deploy_id}},
            UpdateExpression="set approval_date = :ad, approver = :a, approval_response = :ar",
            ExpressionAttributeValues={
                ':ad': {'S': github_submitted_date},
                ':a': {'S': 'Auto-approved due to whitelisted environments'},
                ':ar': {'BOOL':True},
            },
            ReturnValues="UPDATED_NEW"
        )
    else:
        # Posting the request to the Slack channel
        slack_mesage = build_authorization_slack_message_for_request(
            submitted_date = github_submitted_date, 
            requestor = github_requestor, 
            version = github_version, 
            environments = github_deployment_environments, 
            build_type = github_build_type, 
            id = github_deploy_id,
            channel = github_slack_channel_id)
        post_to_slack("https://slack.com/api/chat.postMessage", github_slack_bot_oauth_token, slack_mesage)
    
    return {"statusCode": 200}

def is_deploy_whitelisted(whitelisted_environments, deployment_environments):
    '''
    Checks if the deployment_environments only contains entries from the whitelisted_environments
    '''
    lowercased_deployment_environments = set(list(map(str.lower,deployment_environments)))
    lowercased_whitelisted_environments = set(list(map(str.lower,whitelisted_environments)))
    return lowercased_deployment_environments.issubset(lowercased_whitelisted_environments)
    
def build_authorization_slack_message_for_request(id, channel, submitted_date, requestor, version, environments, build_type):
    msg = build_authorization_slack_message(id = id, channel = channel, submitted_date = submitted_date, requestor = requestor, version = version, environments = environments, build_type = build_type)
    # Approval not given yet, we present the buttons.
    msg["blocks"].append({
    	"type": "actions",
    	"elements": [
    		{
    			"type": "button",
    			"text": {
    				"type": "plain_text",
    				"text": "Cancel Deploy",
    			},
    			"value": "cancel",
    			"style": "danger"
    		},
    		{
    			"type": "button",
    			"text": {
    				"type": "plain_text",
    				"text": "Approve Deploy"
    			},
    			"value": "approve",
    			"style": "primary"
    		}
    	]
    })
    
    return msg

#############################
# Step 2: Response from Slack 
#############################

def parse_user_response(body):
    # Parsing the Slack's response's body. Need to remove "payload=", then convert it to dictionary.
    slack_payload = json.loads(urllib.parse.unquote(body[8:]))
    slack_deploy_id = slack_payload['message']['metadata']['event_payload']['id']
    slack_approval_date = datetime.datetime.fromtimestamp(float(slack_payload['actions'][0]['action_ts']))
    slack_approver_id = slack_payload['user']['id']
    slack_approval_response = slack_payload['actions'][0]['value'] == 'approve'
    slack_message_timestamp = slack_payload['container']['message_ts']
    
    # Getting back the request from the response. Verifying that it already exists and that it has not been approved/denied yet.
    original_request = get_request(slack_deploy_id) 
    if original_request is None:
        # Trying to authorize a request that does not exist.
        return {"statusCode": 400, 'body': json.dumps({'reason': 'Request not found.'})}
    elif 'NULL' not in original_request['approver']:
        # Trying to authorize a request that has already been actioned upon
        return{"statusCode": 400, 'body': json.dumps({'reason': 'Request has already been actioned upon.'})}
    
    # Inserting the response in the database.
    slack_bot_oauth_token = original_request['slack_bot_oauth_token']['S']
    approver_full_name = get_slack_user_name(slack_approver_id, slack_bot_oauth_token)
    client.update_item(
        TableName=TABLE_NAME,
        Key={'id': {'S': slack_deploy_id}},
        UpdateExpression="set approval_date = :ad, approver = :a, approval_response = :ar",
        ExpressionAttributeValues={
            ':ad': {'S': slack_approval_date.isoformat()},
            ':a': {'S': approver_full_name},
            ':ar': {'BOOL':slack_approval_response},
        },
        ReturnValues="UPDATED_NEW"
    )
    
    # Retrieving the original parameters from the database because we essentially need to reconstruct the original message.
    original_request_submitted_date = original_request['request_date']['S']
    original_request_requestor = original_request['requestor']['S']
    original_request_version = original_request['version']['S']
    original_request_deployment_environments = original_request['deployment_environments']['SS']
    original_request_build_type = original_request['build_type']['S']
    original_request_slack_channel_id = original_request['slack_channel_id']['S']
    
    # Sending the response to the Slack channel, but with removing the buttons and replacing them by the name of the approver.
    slack_response = build_authorization_slack_message_for_response(
        id = slack_deploy_id,
        channel = original_request_slack_channel_id,
        submitted_date = original_request_submitted_date, 
        requestor = original_request_requestor, 
        version = original_request_version, 
        environments = original_request_deployment_environments, 
        build_type = original_request_build_type, 
        approver = approver_full_name, 
        approved = slack_approval_response,
        original_message_timestamp = slack_message_timestamp)
    post_to_slack("https://slack.com/api/chat.update", slack_bot_oauth_token, slack_response)

    return {"statusCode": 200}
    
def get_slack_user_name(user_id, bot_token):
    response = get_to_slack("https://slack.com/api/users.info?user=" + user_id, bot_token, {})
    return response['user']['real_name']
    
def build_authorization_slack_message_for_response(id, channel, submitted_date, requestor, version, environments, build_type, approver, approved, original_message_timestamp):
    msg = build_authorization_slack_message(id = id, channel = channel, submitted_date = submitted_date, requestor = requestor, version = version, environments = environments, build_type = build_type)
    #Approver given, we display the message that the approver approved it.
    approval_as_text = "cancelled"
    if approved:
        approval_as_text = "approved"
        
    msg["blocks"].append({
    	"type": "section",
    	"text": {
    		"type": "mrkdwn",
    		"text": approver + " *" + approval_as_text + "* the deploy."
    	}
    })
    
    msg["ts"] = original_message_timestamp
    return msg
    
#############################
# Step 3: Verify for authorization from Github Actions 
#############################
            
def verify_authorization(body):
    # Parses the body from the GitHub Actions.
    parsed_request = json.loads(body)
    id = parsed_request['id']
    
    # Checking the status of the original request.
    request = get_request(id)
    if request is None:
        # Trying to verify the authorization status of a request that does not exist.
        return {"statusCode": 400, 'body': json.dumps({'reason': 'Request not found.'})}
    elif 'NULL' in request['approval_response']:
        # We did not get the response to the request yet. Returning actioned=false
        return {"statusCode": 200, 'body': json.dumps({'actioned': False})}
    else:
        # We got the response from the request. Returning actioned=true and whatever response was given by the user.
        approval_response = request['approval_response']['BOOL']
        return {"statusCode": 200, 'body': json.dumps({'actioned': True, 'authorized' : approval_response})}

#############################
# Tools
#############################

def get_to_slack(url, bot_token, message_json):
    return http_request_to_slack('GET', url, bot_token, message_json)

def post_to_slack(url, bot_token, message_json):
    return http_request_to_slack('POST', url, bot_token, message_json)
    
def http_request_to_slack(method, url, bot_token, message_json):
    '''
    Does an HTTP request tailored to Slack. Returns the response given by the Slack bot.
    '''
    headers = {
        "Authorization": "Bearer " + bot_token,
        "charset":"utf-8",
        "Content-type" : "application/json"
    }
    http = urllib3.PoolManager()
    response = http.request(method, url, body = json.dumps(message_json), headers=headers)
    parsed_response = json.loads(response.data.decode('utf-8'))
    return parsed_response
   
def get_request(id):
    '''
    Gets the request from the DynamoDB database by its ID. Can return None if it does not exist.
    '''
    data = client.get_item(
        TableName=TABLE_NAME,
        Key={
            'id': {'S': id}
        }
    )
    return data['Item'] if 'Item' in data else None
    
def build_authorization_slack_message( id, channel, submitted_date, requestor, version, environments, build_type):
    '''
    Builds an approbation slack message.
    
    submitted_date: The date that the request was submitted, as string
    requestor: The person requesting the deploy
    version: An identifier for the version being deployed. Should be the branch / tag name.
    build_type: An additional key to identify the build
    id: A unique token for every build. Is sent as part of message metadata.
    '''
    
    formatted_environments = ''
    for environment in environments:
        formatted_environments += ("\n- " + environment)
    
    msg = {
        "channel": channel,
        "metadata": {
            "event_type": "deploy_review_requested",
            "event_payload": {
                "id": id,
            }
        },
        "text": "⚠️New deploy request received⚠️",
    	"blocks": [
    		{
    			"type": "header",
    			"text": {
    				"type": "plain_text",
    				"text": "Build Deploy Request"
    			}
    		},
    		{
    			"type": "divider"
    		},
    		{
    			"type": "section",
    			"text": {
    				"type": "mrkdwn",
    				"text": "A build deploy on production environments has been submitted and is pending approval."
    			}
    		},
    		{
    			"type": "section",
    			"fields": [
    				{
    					"type": "mrkdwn",
    					"text": "*Date Submitted:*\n{submitted_date}".format(submitted_date = submitted_date)
    				},
    				{
    					"type": "mrkdwn",
    					"text": "*Requestor:*\n{requestor}".format(requestor = requestor)
    				},
    				{
    					"type": "mrkdwn",
    					"text": "*Version / Branch:*\n{version}".format(version = version)
    				},
    				{
    					"type": "mrkdwn",
    					"text": "*Type:*\n{build_type}".format(build_type = build_type)
    				}
    			]
    		},
    		{
    			"type": "section",
    			"text": {
    				"type": "mrkdwn",
    				"text": "*Environments:*{environments}".format(environments = formatted_environments)
    			}
    		}
    	]
    }
        
    return msg