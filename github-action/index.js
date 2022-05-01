// Copyright (c) 2022 CydrickT
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

// Github Workflow action that triggers a deploy check
// and waits for the answer.
// https://github.com/CydrickT/GithubDeployBot

const core = require('@actions/core');
const sleep = require('thread-sleep');
const { v4: uuidv4 } = require('uuid');
const axios = require('axios');

const DELAY_BETWEEN_ATTEMPTS_IN_SECONDS = 5;

async function verifyAuthorization(core) {

    try {
        // Getting the variables from the workflow.
        const authorizationServerUrl = core.getInput('authorization-server-url');
        const version = core.getInput('version');
        const requestor = core.getInput('requestor');
        const latestCommitHash = core.getInput('latest-commit-hash');
        const buildType = core.getInput('build-type');
        const deploymentEnvironments = JSON.parse(core.getInput('deployment-environments'));
        const whitelistedEnvironments = JSON.parse(core.getInput('whitelisted-environments'));
        const timeout = core.getInput('timeout');
        const timezone = core.getInput('timezone');
        const slackChannelId = core.getInput('slack-channel-id');
        const slackBotOAuthToken = core.getInput('slack-bot-oauth-token');
        core.setSecret(slackChannelId);
        core.setSecret(slackBotOAuthToken);

        //Generating a unique identifier for that deploy. It's very important to keep this identifier secret.
        const buildUuid = uuidv4();
        core.setSecret(buildUuid);

        // Sending to the Lambda function the authorization request.
        const submitted_date = new Date().toLocaleString("en-CA", {timeZone: timezone});
        const authorizationRequestBody = {
            "id": buildUuid,
            "submitted_date": submitted_date,
            "requestor": requestor,
            "version": version,
            "commit_hash": latestCommitHash,
            "deployment_environments": deploymentEnvironments,
            "whitelisted_environments": whitelistedEnvironments,
            "build_type": buildType,
            "slack_channel_id": slackChannelId,
            "slack_bot_oauth_token": slackBotOAuthToken,
        };
        await axios.post(authorizationServerUrl + "?type=build_deploy_requested", authorizationRequestBody);
        
        //Building the necessary variables for the preiodic request to verify if the user responded.
        const verificationBody = {
            "id": buildUuid
        };
        const verificationUrl = authorizationServerUrl + "?type=verify_authorization";
        const numberOfRuns = (timeout * 60) / DELAY_BETWEEN_ATTEMPTS_IN_SECONDS;
        let runIndex = 1;
        let answerProvided = false;
        let response = {};

        while(answerProvided == false && numberOfRuns >= runIndex){
            //Looping until either the user provides a response or we reached the timeout
            console.log("Checking authorization attempt " + runIndex + " of " + numberOfRuns + "...");
            sleep(DELAY_BETWEEN_ATTEMPTS_IN_SECONDS * 1000);
            await axios.post(verificationUrl, verificationBody).then(r => 
                {
                    response = r.data;
                    if (response.actioned){
                        // The user provided a response. Exiting out of the while loop.
                        answerProvided = true;
                    }
                });
            runIndex++;
        }

        if (answerProvided == true){
            if (response.authorized){
                // The user provided a response and it is authorized. Continuing with the deploy.
                console.log("The deploy is authorized to continue.");
            }else{
                // The user provided a response and it is not authorized. Failing the deploy.
                core.setFailed("The deploy has been denied.");
            }
        }
        else{
            //The user did not provide a response. Failing the deploy.
            core.setFailed("No answer provided to authorize the deploy after " + timeout + " minutes. This deploy is not authorized to continue...");
        }

    } catch (error) {
        core.setFailed(error.message);
    }

};

verifyAuthorization(core);