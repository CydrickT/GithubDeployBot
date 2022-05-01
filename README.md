# GitHub Deploy Bot

This is an integration between a GitHub action and a Slack Bot. It allows to let users of a Slack channel to authorize or not a deploy. Informations such as the environment to deploy to and the user are presented to the user of the Slack channel.

![Message Preview](docs/Message-Preview.png)

## Table of contents

* [Use Cases](#use-cases)
* [Prerequisites](#prerequisites)
* [Installation & Configuration](#installation--configuration)
    * [AWS](#aws)
        * [Installing the Lambda function](#installing-the-lambda-function)
        * [Creating the API Gateway](#creating-an-api-gateway)
        * [Creating a DynamoDB database](#creating-a-dynamodb-database)
        * [Setting permissions with IAM](#setting-permissions-with-iam)
    * [Slack Bot](#slack-bot)
    * [Github](#github)
        * [Configuring the GitHub Workflow](#configuring-the-github-workflow)
        * [Adding GitHub Secrets (Optional)](#adding-github-secrets-optional)
    * [TODOs](#todos)

## Use Cases

Here are the use cases of the bot:

1. Serve as a double validation to prevent accidental or misconfigured deployments
2. Allow only certain users to approve the deployments
3. Serve as auditing purposes to know who deployed and who authorized the deploys

![Sequence Diagram](docs/Diagram-Overview.drawio.png)

## Prerequisites

This necessitates an AWS account in order to work. The following AWS services are involved:
- Lambda
- DynamoDB
- API Gateway
- IAM

You also need a Slack channel with admin rights.

## Installation & Configuration

### AWS

#### Installing the Lambda function

The first step is to deploy the AWS Lambda function

1. Go to the AWS Lambda dashboard, and click on `Create Function`
2. Fill in the following details:
    * `Author from scratch`
    * Function Name: `GitHub-Deploy-Bot`
    * Runtime: `Python 3.9`
    * Architecture: `x86_64`
    * Execution Role: `Create a new role with basic Lambda permissions`
3. Copy-paste the content of `aws-lambda-function/lambda-function.py` into the Code source and click `Deploy`

#### Creating an API Gateway 

The second step is to create an AWS API Gateway to contact the Lambda function

1. On the `GitHub-Deploy-Bot` Lambda function, click on `Add trigger` on the left and select the trigger `API Gateway`
2. Fill the following details:
    * `Create an API`
    * API Type: `Rest API`
    * Security: `Open`
3. Back on the AWS Lambda function, click on `Configuration`. Under `Triggers`, note the URL next to `API endpoint`. This will be used later in the [Slack Bot](#slack-bot) and [Configuring the GitHub Workflow](#configuring-the-github-workflow) sections as the Authorization Server URL.

#### Creating a DynamoDB database

The third step is to create an AWS DynamoDB database to store the deploy requests and responses.

1. Open the DynamoDB dashboard and click on `Create table`
2. Fill the following details:
    * Table Name: `BuildDeployRequests`
    * Partition Key: `id`, `String`
    * Sort Key: Left Blank
    * Read / Write capacity settings: `On-demand`

#### Setting permissions with IAM

Permissions for the AWS Lambda to add items to the DynamoDB database must be given.

1. Open the IAM Dashboard and click on `Policies > Create Policy`
2. Fill the following details:
    * Service: `DynamoDB`
    * In `JSON`, enter the following:
```
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "VisualEditor0",
            "Effect": "Allow",
            "Action": [
                "dynamodb:BatchGetItem",
                "dynamodb:PutItem",
                "dynamodb:GetItem",
                "dynamodb:Query",
                "dynamodb:UpdateItem"
            ],
            "Resource": "*"
        }
    ]
}
```
3. Click on `Next` twice
4. Under `Name`, Write `GitHub_Deploy_Bot_Read_Write_Table`, then click on `Create Policy`
5. Under `Roles`, select `Github-Deploy-Bot-role-<ID>`, `Add permissions` and `Attach Policy`
6. Select `GitHub_Deploy_Bot_Read_Write_Table`, then `Attach Policies`

### Slack Bot

Once you have acquired the URL from the API Gateway, you can follow these steps to configure the Slack Bot

1. Make a copy of `slack-bot-manifest/slack_bot_manifest.yml` and edit the `request_url` to match the Authorization Server URL, with `?type=user_response_received` at the end. For instance, it should look like `https://abcdef1234.execute-api.us-east-1.amazonaws.com/default/Github-Deploy-Bot?type=user_response_received`
2. Go to the [Slack Apps page](https://api.slack.com/apps), 
3. Click on `Create New App > From an app manifest`, select your workspace, copy-paste the updated manifest text into the Yaml section and click on `Create`
4. Click on `OAuth & Permissions > Install to Workspace`
5. Keep a note of then `Bot User OAuth Token`. This will be used later in the [Configuring the GitHub Workflow](#configuring-the-github-workflow) section as the Slack Bot OAuth Token.
6. In the Slack App, pick a channel where you want the message to be sent. Go to the Add User panel, then click on `Integrations > Add an App > GitHub Deploy Bot`
7. Right-Click on the channel's name on the left side, then click on `Copy Link` and paste it somewhere. The URL should look like this: `https://<WORKSPACE_NAME>.slack.com/archives/<SLACK_CHANNEL_ID>`. Keep a note of the `SLACK_CHANNEL_ID`. This will be used later in the [Configuring the GitHub Workflow](#configuring-the-github-workflow) section as the Slack Channel ID.

### GitHub

#### Configuring the GitHub Workflow

You can use this GitHub Action at any point in the workflow. Here's an example:
```
name: Deploying Build
on: push
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy Authorization Check
        id: deploy-authorization-check
        uses: CydrickT/GithubDeployBot@v1.0.0
        with:
          authorization-server-url: 'https://CHANGE_THIS.amazonaws.com/CHANGE_THIS?type=user_response_received'
          slack-bot-oauth-token: 'xoxb-XXXXXXXXXXXX-TTTTTTTTTTTTTT'
          slack-channel-id: 'A785C9271BD'
          version: ${{ github.ref }}
          requestor: ${{ github.actor }}
          build-type: 'Enterprise Platform'
          deployment-environments: ${{ needs.setup.outputs.deployment_servers}}
          whitelisted-environments: '["Development", "Staging"]'
          timezone: 'America/New_York'
          timeout: 5

      - name: Deploying
        id: deploy
        needs: [deploy-authorization-check]
        ...
```

#### Adding GitHub Secrets (Optional)

This step is optional and is only useful for hardening the deploy.

Once you have accomplished the previous steps, you can put the following as GitHub Secrets:
- Authorization Server URL (From the API Gateway)
- Slack Bot OAuth Token (From Slack Bot)
- Slack Channel ID (from Slack)

Here are the steps to follow:

1. In your repository, go to `Settings > Secrets > Actions`
2. Create the following secrets:
    * `AUTHORIZATION_SERVER_URL` : The value is the API Gateway URL
    * `SLACK_BOT_OAUTH_TOKEN`: The Slack Bot User OAuth Token from step 5 of `Slack Bot`
    * `SLACK_CHANNEL_ID`: The ID of the Slack channel to send the message to

Then, set the following GitHub Workflow action to be as this:

```
authorization-server-url: ${{ secrets.AUTHORIZATION_SERVER_URL }}
slack-bot-oauth-token: ${{ secrets.SLACK_BOT_OAUTH_TOKEN }}
slack-channel-id: ${{ secrets.SLACK_CHANNEL_ID }}
```

## TODOs

Here is a list of possible feature improvements:
- Simplify installation of the various AWS components by providing CLI commands or a script instead of UI-based steps. Note that it would be interesting to tighten the `resource` of the IAM policy `GitHub_Deploy_Bot_Read_Write_Table` at the same time.
- Have a fully customizable message. Will have to find a solution to handle displaying the current date & time
-  Be able to send information messages to another Slack channel once the deploy is approved. Essentially the same message without the buttons at the bottom.
-  Once the timeout is reached, make the buttons disappear on the Slack message and say that the deploy timed out.

PRs are welcome!
