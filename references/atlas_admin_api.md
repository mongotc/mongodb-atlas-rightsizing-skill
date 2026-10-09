# MongoDB Atlas Administration API

OpenAPI file: https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2.json

Source: https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2


## Instance Sizes

```bash
Gen1 general:   M10, M20, M30, M40, M50, M60, M80, M140, M200, M250, M300, M400
Gen1 low-CPU:   R40, R50, R60, R80, R200, R300, R400, R600
Gen2 general:   M30_GEN_2, M40_GEN_2, M50_GEN_2, M60_GEN_2, M80_GEN_2,
                M140_GEN_2, M200_GEN_2, M300_GEN_2, M700_GEN_2
Gen2 low-CPU:   R40_GEN_2, R50_GEN_2, R60_GEN_2, R80_GEN_2,
                R200_GEN_2, R300_GEN_2, R400_GEN_2

```

## Description

This is version `2.0` of this API documentation. Last update on Oct 5, 2026.
The MongoDB Atlas Administration API allows developers to manage all components in MongoDB Atlas.

The Atlas Administration API supports OAuth2 Service Accounts and HTTP Digest-based API keys. Service accounts are the recommended authentication method and API keys are considered a legacy option.

To authenticate with a Service Account, first exchange its client ID and secret for an access token using the OAuth 2.0 Client Credentials flow. Atlas provides a token endpoint at `POST https://cloud.mongodb.com/api/oauth/token`, which returns a Bearer token that is reusable and valid for 1 hour (3600 seconds).

For example, to [return a list of your organizations](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorgs) with [cURL](https://en.wikipedia.org/wiki/CURL), first generate an access token and then use that token to call the same Atlas Administration API endpoint shown in the current example:

```
ACCESS_TOKEN=$(curl -fsS --request POST https://cloud.mongodb.com/api/oauth/token \
  --header "Authorization: Basic $(printf '%s' "${CLIENT_ID}:${CLIENT_SECRET}" | base64 | tr -d '\n')" \
  --header "Content-Type: application/x-www-form-urlencoded" \
  --header "Accept: application/json" \
  --data "grant_type=client_credentials" | jq -r '.access_token')

curl --header "Authorization: Bearer ${ACCESS_TOKEN}" \
  --header "Accept: application/vnd.atlas.2025-03-12+json" \
  -X GET "https://cloud.mongodb.com/api/atlas/v2/orgs?pretty=true"
```

If your organization requires an IP access list for the Atlas Administration API, the token can be created from any IP address, but the API call that uses the token must originate from an allowed IP.

To learn more, see [Get Started with the Atlas Administration API](https://www.mongodb.com/docs/atlas/configure-api-access/). For support, see [MongoDB Support](https://www.mongodb.com/support/get-started).

You can also explore the various endpoints available through the Atlas Administration API in MongoDB's [Postman workspace](https://www.postman.com/mongodb-devrel/workspace/mongodb-atlas-administration-apis/) (requires a Postman account).

## Servers

- https://cloud.mongodb.com: https://cloud.mongodb.com ()


## Topics

### [Authentication](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/authentication.md)

### [Rate Limiting](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/topic/topic-rate-limiting.md)


## Endpoints

### [Access Tracking](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-access-tracking.md)

- [Return Database Access History for One Cluster by Cluster Name](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupdbaccesshistorycluster.md)

- [Return Database Access History for One Cluster by Hostname](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupdbaccesshistoryprocess.md)


### [Activity Feed](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-activity-feed.md)

- [Return Pre-Filtered Activity Feed Link for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupactivityfeed.md)

- [Return Pre-Filtered Activity Feed Link for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgactivityfeed.md)


### [AI Model API Keys](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-ai-model-api-keys.md)

- [Return AI Model API Keys for One Group](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupaimodelapikeys.md)

- [Create New AI Model API Key](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupaimodelapikey.md)

- [Return Single AI Model API Key for One Group](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupaimodelapikey.md)

- [Delete Existing AI Model API Key](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupaimodelapikey.md)

- [Update Existing AI Model API Key](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupaimodelapikey.md)

- [Return AI Model API Keys for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorgaimodelapikeys.md)

- [Return Single AI Model API Key for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgaimodelapikey.md)


### [AI Model Rate Limits](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-ai-model-rate-limits.md)

- [Return Single AI Model Rate Limit for One Group](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupaimodelapicloudgeographymodelgroupnameratelimits.md)

- [Update AI Model Rate Limit](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupaimodelapicloudgeographymodelgroupnameratelimits.md)

- [Reset AI Model Rate Limit for One Model Group](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-resetgroupaimodelapicloudgeographymodelgroupnameratelimits.md)

- [Return AI Model Rate Limits for One Group](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupaimodelapiratelimits.md)

- [Reset AI Model Rate Limits for Group](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-resetgroupaimodelapiratelimits.md)

- [Return Single AI Model Rate Limit for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgaimodelapicloudgeographymodelgroupnameratelimits.md)

- [Return AI Model Rate Limits for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgaimodelapiratelimits.md)


### [Alert Configurations](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-alert-configurations.md)

- [Return All Alert Configuration Matchers Field Names](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listalertconfigmatcherfieldnames.md)

- [Return All Alert Configurations in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupalertconfigs.md)

- [Create One Alert Configuration in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupalertconfig.md)

- [Return One Alert Configuration from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupalertconfig.md)

- [Update One Alert Configuration in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupalertconfig.md)

- [Remove One Alert Configuration from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupalertconfig.md)

- [Toggle State of One Alert Configuration in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-togglegroupalertconfig.md)

- [Return All Alert Configurations Set for One Alert](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupalertalertconfigs.md)


### [Alerts](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-alerts.md)

- [Return All Open Alerts for One Alert Configuration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupalertconfigalerts.md)

- [Return All Alerts from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupalerts.md)

- [Return One Alert from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupalert.md)

- [Acknowledge One Alert from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-acknowledgegroupalert.md)


### [Atlas Search](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-atlas-search.md)

- [Create One Atlas Search Index](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupclusterftsindex.md)

- [Return All Atlas Search Indexes for One Collection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclusterftsindex.md)

- [Return One Atlas Search Index](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusterftsindex.md)

- [Remove One Atlas Search Index](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupclusterftsindex.md)

- [Update One Atlas Search Index](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupclusterftsindex.md)

- [Return All Search Nodes](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclustersearchdeployment.md)

- [Create Search Nodes](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupclustersearchdeployment.md)

- [Delete Search Nodes](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupclustersearchdeployment.md)

- [Update Search Nodes](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupclustersearchdeployment.md)

- [Return All Atlas Search Indexes for One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclustersearchindexes.md)

- [Create One Atlas Search Index](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupclustersearchindex.md)

- [Return All Atlas Search Indexes for One Collection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclustersearchindex.md)

- [Return One Atlas Search Index by Name](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclustersearchindexbyname.md)

- [Remove One Atlas Search Index by Name](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupclustersearchindexbyname.md)

- [Update One Atlas Search Index by Name](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupclustersearchindexbyname.md)

- [Return One Atlas Search Index by ID](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclustersearchindex.md)

- [Remove One Atlas Search Index by ID](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupclustersearchindex.md)

- [Update One Atlas Search Index by ID](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupclustersearchindex.md)


### [Auditing](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-auditing.md)

- [Return Auditing Configuration for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupauditlog.md)

- [Update Auditing Configuration for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupauditlog.md)


### [AWS Clusters DNS](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-aws-clusters-dns.md)

- [Return One Custom DNS Configuration for Atlas Clusters on AWS](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupawscustomdns.md)

- [Update State of One Custom DNS Configuration for Atlas Clusters on AWS](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-togglegroupawscustomdns.md)


### [Cloud Backups](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-cloud-backups.md)

- [Return All Snapshot Export Buckets](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupbackupexportbuckets.md)

- [Create One Snapshot Export Bucket](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupbackupexportbucket.md)

- [Return One Snapshot Export Bucket](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupbackupexportbucket.md)

- [Delete One Snapshot Export Bucket](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupbackupexportbucket.md)

- [Update One Export Bucket Private Networking Settings](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupbackupexportbucket.md)

- [Return Object Storage Private Endpoints for Cloud Backups for One Cloud Provider in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupbackupprivateendpoints.md)

- [Create One Object Storage Private Endpoint for Cloud Backups for One Cloud Provider in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupbackupprivateendpoint.md)

- [Return One Object Storage Private Endpoint for Cloud Backups for One Cloud Provider in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupbackupprivateendpoint.md)

- [Delete One Object Storage Private Endpoint for Cloud Backups for One Cloud Provider from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupbackupprivateendpoint.md)

- [Return Backup Compliance Policy Settings](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupbackupcompliancepolicy.md)

- [Update Backup Compliance Policy Settings](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupbackupcompliancepolicy.md)

- [Disable Backup Compliance Policy Settings](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-disablegroupbackupcompliancepolicy.md)

- [Return All Snapshot Export Jobs](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclusterbackupexports.md)

- [Create One Snapshot Export Job](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupclusterbackupexport.md)

- [Return One Snapshot Export Job](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusterbackupexport.md)

- [Return All Restore Jobs for One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclusterbackuprestorejobs.md)

- [Create One Restore Job of One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupclusterbackuprestorejob.md)

- [Return One Restore Job for One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusterbackuprestorejob.md)

- [Cancel One Restore Job for One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-cancelgroupclusterbackuprestorejob.md)

- [Return One Cloud Backup Schedule](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusterbackupschedule.md)

- [Remove All Cloud Backup Schedules](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupclusterbackupschedule.md)

- [Update Cloud Backup Schedule for One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupclusterbackupschedule.md)

- [Return All Replica Set Cloud Backups](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclusterbackupsnapshots.md)

- [Take One On-Demand Snapshot](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-takegroupclusterbackupsnapshots.md)

- [Return One Sharded Cluster Cloud Backup](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusterbackupsnapshotshardedcluster.md)

- [Remove One Sharded Cluster Cloud Backup](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupclusterbackupsnapshotshardedcluster.md)

- [Return All Sharded Cluster Cloud Backups](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclusterbackupsnapshotshardedclusters.md)

- [Return One Replica Set Cloud Backup](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusterbackupsnapshot.md)

- [Remove One Replica Set Cloud Backup](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupclusterbackupsnapshot.md)

- [Update Expiration Date for One Cloud Backup](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupclusterbackupsnapshot.md)

- [Return Databases in One Snapshot](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclusterbackupsnapshotdatabases.md)

- [Return One Database in One Snapshot](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusterbackupsnapshotdatabase.md)

- [Return Collections in One Database in One Snapshot](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclusterbackupsnapshotdatabasecollections.md)

- [Return One Collection in One Database in One Snapshot](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusterbackupsnapshotdatabasecollection.md)

- [Return All Collection Restore Jobs for One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclustercollectionrestorejobs.md)

- [Create One Collection Restore Job](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupclustercollectionrestorejob.md)

- [Return One Collection Restore Job for One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclustercollectionrestorejob.md)

- [Return All Collection States for One Collection Restore Job](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclustercollectionrestorejobcollections.md)

- [Return One Collection State for One Collection Restore Job](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclustercollectionrestorejobcollection.md)


### [Cloud Migration Service](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-cloud-migration-service.md)

- [Create One Migration for One Local Managed Cluster to MongoDB Atlas](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategrouplivemigration.md)

- [Validate One Migration Request](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-validategrouplivemigrations.md)

- [Return One Migration Validation Job](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgrouplivemigrationvalidatestatus.md)

- [Return One Migration Job](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgrouplivemigration.md)

- [Cut Over One Migrated Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-cutovergrouplivemigration.md)

- [Return All Projects Available for Migration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorglivemigrationavailableprojects.md)

- [Create One Link-Token](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createorglivemigrationlinktoken.md)

- [Remove One Link-Token](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deleteorglivemigrationlinktokens.md)


### [Cloud Provider Access](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-cloud-provider-access.md)

- [Return All Cloud Provider Access Roles](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupcloudprovideraccess.md)

- [Create One Cloud Provider Access Role](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupcloudprovideraccess.md)

- [Deauthorize One Cloud Provider Access Role](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deauthorizegroupcloudprovideraccessrole.md)

- [Return One Cloud Provider Access Role](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupcloudprovideraccess.md)

- [Authorize One Cloud Provider Access Role](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-authorizegroupcloudprovideraccessrole.md)


### [Cluster Outage Simulation](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-cluster-outage-simulation.md)

- [Return One Outage Simulation](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusteroutagesimulation.md)

- [Start One Outage Simulation](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-startgroupclusteroutagesimulation.md)

- [End One Outage Simulation](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-endgroupclusteroutagesimulation.md)


### [Clusters](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-clusters.md)

- [Return All Authorized Clusters in All Projects](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listclusterdetails.md)

- [Return All Clusters in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclusters.md)

- [Create One Cluster in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupcluster.md)

- [Return All Cloud Provider Regions](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclusterproviderregions.md)

- [Upgrade One Shared-Tier Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-upgradegroupclustertenantupgrade.md)

- [Upgrade One Shared-Tier Cluster to One Serverless Instance](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-upgradegroupclustertenantupgradetoserverless.md)

- [Return One Cluster from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupcluster.md)

- [Remove One Cluster from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupcluster.md)

- [Update One Cluster in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupcluster.md)

- [Return Adaptive Settings for One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusteradaptivesettings.md)

- [Update Adaptive Settings for One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupclusteradaptivesettings.md)

- [Return Auto Scaling Configuration for One Sharded Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-autogroupclusterscalingconfiguration.md)

- [Return Advanced Configuration Options for One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusterprocessargs.md)

- [Update Advanced Configuration Options for One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupclusterprocessargs.md)

- [Test Failover for One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-restartgroupclusterprimaries.md)

- [Return Status of All Cluster Operations](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusterstatus.md)

- [Grant MongoDB Employee Cluster Access for One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-grantgroupclustermongodbemployeeaccess.md)

- [Pin Feature Compatibility Version for One Cluster in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-pingroupclusterfeaturecompatibilityversion.md)

- [Revoke MongoDB Employee Cluster Access for One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-revokegroupclustermongodbemployeeaccess.md)

- [Unpin Feature Compatibility Version for One Cluster in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-unpingroupclusterfeaturecompatibilityversion.md)

- [Load Sample Dataset into One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-requestgroupsampledatasetload.md)

- [Return Status of Sample Dataset Load for One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupsampledatasetload.md)


### [Collection Level Metrics](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-collection-level-metrics.md)

- [Return Pinned Namespaces](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclustercollstatpinnednamespaces.md)

- [Pin Namespaces](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-pingroupclustercollstatpinnednamespaces.md)

- [Add Pinned Namespaces](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupclustercollstatpinnednamespaces.md)

- [Unpin Namespaces](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-unpingroupclustercollstatunpinnamespaces.md)

- [Return Ranked Namespaces from One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclustercollstatnamespaces.md)

- [Return Cluster-Level Query Latency](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclustercollstatmeasurements.md)

- [Return All Metric Names](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupcollstatmetrics.md)

- [Return Ranked Namespaces from One Host](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupprocesscollstatnamespaces.md)

- [Return Host-Level Query Latency](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupprocesscollstatmeasurements.md)


### [Custom Database Roles](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-custom-database-roles.md)

- [Return All Custom Roles in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupcustomdbroleroles.md)

- [Create One Custom Role](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupcustomdbrolerole.md)

- [Return One Custom Role in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupcustomdbrolerole.md)

- [Remove One Custom Role from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupcustomdbrolerole.md)

- [Update One Custom Role in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupcustomdbrolerole.md)


### [Data Federation](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-data-federation.md)

- [Return All Federated Database Instances in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupdatafederation.md)

- [Create One Federated Database Instance in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupdatafederation.md)

- [Return One Federated Database Instance in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupdatafederation.md)

- [Remove One Federated Database Instance from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupdatafederation.md)

- [Update One Federated Database Instance in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupdatafederation.md)

- [Return All Query Limits for One Federated Database Instance](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupdatafederationlimits.md)

- [Return One Federated Database Instance Query Limit for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupdatafederationlimit.md)

- [Delete One Query Limit for One Federated Database Instance](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupdatafederationlimit.md)

- [Configure One Query Limit for One Federated Database Instance](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-setgroupdatafederationlimit.md)

- [Download Query Logs for One Federated Database Instance](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-downloadgroupdatafederationquerylogs.md)

- [Return All Federated Database Instance and Online Archive Private Endpoints in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupprivatenetworksettingendpointids.md)

- [Create One Federated Database Instance and Online Archive Private Endpoint for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupprivatenetworksettingendpointid.md)

- [Return One Federated Database Instance and Online Archive Private Endpoint in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupprivatenetworksettingendpointid.md)

- [Remove One Federated Database Instance and Online Archive Private Endpoint from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupprivatenetworksettingendpointid.md)


### [Database Users](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-database-users.md)

- [Return All Database Users in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupdatabaseusers.md)

- [Create One Database User in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupdatabaseuser.md)

- [Return One Database User from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupdatabaseuser.md)

- [Remove One Database User from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupdatabaseuser.md)

- [Update One Database User in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupdatabaseuser.md)


### [Encryption at Rest using Customer Key Management](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-encryption-at-rest-using-customer-key-management.md)

- [Return One Configuration for Encryption at Rest Using Customer-Managed Keys for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupencryptionatrest.md)

- [Update Encryption at Rest Configuration in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupencryptionatrest.md)

- [Return Private Endpoints for Encryption at Rest Using Customer Key Management for One Cloud Provider in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupencryptionatrestprivateendpoints.md)

- [Create One Private Endpoint for Encryption at Rest Using Customer Key Management for One Cloud Provider in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupencryptionatrestprivateendpoint.md)

- [Return One Private Endpoint for Encryption at Rest Using Customer Key Management for One Cloud Provider in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupencryptionatrestprivateendpoint.md)

- [Delete One Private Endpoint for Encryption at Rest Using Customer Key Management for One Cloud Provider from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-requestgroupencryptionatrestprivateendpointdeletion.md)


### [Events](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-events.md)

- [Return All Event Types](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listeventtypes.md)

- [Return Events from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupevents.md)

- [Return One Event from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupevent.md)

- [Return Events from One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorgevents.md)

- [Return One Event from One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgevent.md)


### [Federated Authentication](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-federated-authentication.md)

- [Delete One Federation Settings Instance](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletefederationsetting.md)

- [Return All Organization Configurations from One Federation](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listfederationsettingconnectedorgconfigs.md)

- [Return One Organization Configuration from One Federation](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getfederationsettingconnectedorgconfig.md)

- [Remove One Organization Configuration from One Federation](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-removefederationsettingconnectedorgconfig.md)

- [Update One Organization Configuration in One Federation](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updatefederationsettingconnectedorgconfig.md)

- [Return All Role Mappings from One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listfederationsettingconnectedorgconfigrolemappings.md)

- [Create One Role Mapping in One Organization Configuration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createfederationsettingconnectedorgconfigrolemapping.md)

- [Return One Role Mapping from One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getfederationsettingconnectedorgconfigrolemapping.md)

- [Update One Role Mapping in One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updatefederationsettingconnectedorgconfigrolemapping.md)

- [Remove One Role Mapping from One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletefederationsettingconnectedorgconfigrolemapping.md)

- [Return All Identity Providers in One Federation](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listfederationsettingidentityproviders.md)

- [Create One Identity Provider](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createfederationsettingidentityprovider.md)

- [Return One Identity Provider by ID](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getfederationsettingidentityprovider.md)

- [Delete One Identity Provider](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletefederationsettingidentityprovider.md)

- [Update One Identity Provider](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updatefederationsettingidentityprovider.md)

- [Revoke JWKS from One OIDC Identity Provider](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-revokefederationsettingidentityproviderjwks.md)

- [Return Metadata of One Identity Provider](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getfederationsettingidentityprovidermetadata.md)

- [Return Federation Settings for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgfederationsettings.md)


### [Flex Clusters](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-flex-clusters.md)

- [Return All Flex Clusters from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupflexclusters.md)

- [Create One Flex Cluster in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupflexcluster.md)

- [Return One Flex Cluster from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupflexcluster.md)

- [Remove One Flex Cluster from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupflexcluster.md)

- [Update One Flex Cluster in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupflexcluster.md)

- [Upgrade One Flex Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-tenantgroupflexclusterupgrade.md)


### [Flex Restore Jobs](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-flex-restore-jobs.md)

- [Return All Restore Jobs for One Flex Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupflexclusterbackuprestorejobs.md)

- [Create One Restore Job for One Flex Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupflexclusterbackuprestorejob.md)

- [Return One Restore Job for One Flex Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupflexclusterbackuprestorejob.md)


### [Flex Snapshots](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-flex-snapshots.md)

- [Download One Flex Cluster Snapshot](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-downloadgroupflexclusterbackup.md)

- [Return All Snapshots for One Flex Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupflexclusterbackupsnapshots.md)

- [Return One Snapshot for One Flex Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupflexclusterbackupsnapshot.md)


### [Global Clusters](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-global-clusters.md)

- [Return One Managed Namespace in One Global Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusterglobalwrites.md)

- [Add One Custom Zone Mapping to One Global Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupclusterglobalwritecustomzonemapping.md)

- [Remove All Custom Zone Mappings from One Global Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupclusterglobalwritecustomzonemapping.md)

- [Create One Managed Namespace in One Global Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupclusterglobalwritemanagednamespace.md)

- [Remove One Managed Namespace from One Global Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupclusterglobalwritemanagednamespaces.md)


### [Invoices](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-invoices.md)

- [Return Associated Invoices](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgassociatedinvoices.md)

- [Create One Cost Explorer Query Process](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createorgbillingcostexplorerusageprocess.md)

- [Return Usage Details for One Cost Explorer Query](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgbillingcostexplorerusage.md)

- [Return All Invoices for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorginvoices.md)

- [Return All Pending Invoices for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorginvoicepending.md)

- [Return One Invoice for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorginvoice.md)

- [Return One Invoice as CSV for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorginvoicecsv.md)

- [Return All Line Items for One Invoice by Invoice ID](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-searchorginvoicelineitems.md)

- [Return All Invoice Reports for One Invoice](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorginvoicereports.md)

- [Create One Invoice Report](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createorginvoicereport.md)

- [Return One Invoice Report](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorginvoicereport.md)

- [Return All Stock Keeping Units](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listskus.md)

- [Return One Stock Keeping Unit](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getsku.md)


### [LDAP Configuration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-ldap-configuration.md)

- [Return LDAP or X.509 Configuration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupusersecurity.md)

- [Update LDAP or X.509 Configuration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupusersecurity.md)

- [Remove LDAP User to DN Mapping](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupusersecurityldapusertodnmapping.md)

- [Verify LDAP Configuration in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-verifygroupusersecurityldap.md)

- [Return Status of LDAP Configuration Verification in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupusersecurityldapverify.md)


### [Legacy Backup](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-legacy-backup.md)

- [Return All Legacy Backup Checkpoints](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclusterbackupcheckpoints.md)

- [Return One Legacy Backup Checkpoint](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusterbackupcheckpoint.md)

- [Return All Legacy Backup Restore Jobs](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclusterrestorejobs.md)

- [Create One Legacy Backup Restore Job](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupclusterrestorejob.md)

- [Return One Legacy Backup Restore Job](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusterrestorejob.md)

- [Return One Snapshot Schedule](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclustersnapshotschedule.md)

- [Update Snapshot Schedule for One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupclustersnapshotschedule.md)

- [Return All Legacy Backup Snapshots](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclustersnapshots.md)

- [Return One Legacy Backup Snapshot](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclustersnapshot.md)

- [Remove One Legacy Backup Snapshot](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupclustersnapshot.md)

- [Update Expiration Date for One Legacy Backup Snapshot](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupclustersnapshot.md)


### [Maintenance Windows](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-maintenance-windows.md)

- [Return One Maintenance Window for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupmaintenancewindow.md)

- [Reset One Maintenance Window for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-resetgroupmaintenancewindow.md)

- [Update One Maintenance Window for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupmaintenancewindow.md)

- [Toggle Automatic Deferral of Maintenance for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-togglegroupmaintenancewindowautodefer.md)

- [Defer One Maintenance Window for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-defergroupmaintenancewindow.md)


### [Metric Integrations](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-metric-integrations.md)

- [Return All Active Metric Integrations](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupmetricintegrations.md)

- [Create One Metric Integration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupmetricintegration.md)

- [Return One Metric Integration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupmetricintegration.md)

- [Update One Metric Integration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupmetricintegration.md)

- [Remove One Metric Integration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupmetricintegration.md)


### [MongoDB Cloud Users](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-mongodb-cloud-users.md)

- [Return All MongoDB Cloud Users in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupusers.md)

- [Add One MongoDB Cloud User to One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-addgroupusers.md)

- [Return One MongoDB Cloud User in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupuser.md)

- [Remove One MongoDB Cloud User from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-removegroupuser.md)

- [Add One Project Role to One MongoDB Cloud User](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-addgroupuserrole.md)

- [Remove One Project Role from One MongoDB Cloud User](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-removegroupuserrole.md)

- [Return All MongoDB Cloud Users Assigned to One Team](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorgteamusers.md)

- [Add One MongoDB Cloud User to One Team](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-addorgteamuser.md)

- [Remove One MongoDB Cloud User from One Team](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-removeorgteamuser.md)

- [Return All MongoDB Cloud Users in One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorgusers.md)

- [Add One MongoDB Cloud User to One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createorguser.md)

- [Return One MongoDB Cloud User in One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorguser.md)

- [Remove One MongoDB Cloud User from One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-removeorguser.md)

- [Update One MongoDB Cloud User in One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updateorguser.md)

- [Add One Organization Role to One MongoDB Cloud User](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-addorguserrole.md)

- [Remove One Organization Role from One MongoDB Cloud User](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-removeorguserrole.md)

- [Create One MongoDB Cloud User](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createuser.md)

- [Return One MongoDB Cloud User by Username](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getuserbyname.md)

- [Return One MongoDB Cloud User by ID](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getuser.md)


### [Monitoring and Logs](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-monitoring-and-logs.md)

- [Download Logs for One Cluster Host in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-downloadgroupclusterlog.md)

- [Return All Atlas Search Metric Types for One Process](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgrouphostftsmetrics.md)

- [Return All Atlas Search Index Metrics for One Namespace](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgrouphostftsmetricindexmeasurements.md)

- [Return Atlas Search Metrics for One Index in One Namespace](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgrouphostftsmetricindexmeasurements.md)

- [Return Atlas Search Hardware and Status Metrics](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgrouphostftsmetricmeasurements.md)

- [Return All MongoDB Processes in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupprocesses.md)

- [Return One MongoDB Process by ID](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupprocess.md)

- [Return Available Databases for One MongoDB Process](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupprocessdatabases.md)

- [Return One Database for One MongoDB Process](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupprocessdatabase.md)

- [Return Measurements for One Database in One MongoDB Process](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupprocessdatabasemeasurements.md)

- [Return Available Disks for One MongoDB Process](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupprocessdisks.md)

- [Return Measurements for One Disk](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupprocessdisk.md)

- [Return Measurements of One Disk for One MongoDB Process](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupprocessdiskmeasurements.md)

- [Return Measurements for One MongoDB Process](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupprocessmeasurements.md)


### [Network Peering](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-network-peering.md)

- [Return All Network Peering Containers in One Project for One Cloud Provider](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupcontainers.md)

- [Create One Network Peering Container](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupcontainer.md)

- [Return All Network Peering Containers in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupcontainerall.md)

- [Return One Network Peering Container](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupcontainer.md)

- [Remove One Network Peering Container](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupcontainer.md)

- [Update One Network Peering Container](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupcontainer.md)

- [Return All Network Peering Connections in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgrouppeers.md)

- [Create One Network Peering Connection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategrouppeer.md)

- [Return One Network Peering Connection in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgrouppeer.md)

- [Remove One Network Peering Connection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegrouppeer.md)

- [Update One Network Peering Connection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategrouppeer.md)

- [Verify Connect via Peering-Only Mode for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-verifygroupprivateipmode.md)

- [Disable Connect via Peering-Only Mode for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-disablegroupprivateipmodepeering.md)


### [Online Archive](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-online-archive.md)

- [Return All Online Archives for One Cluster](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclusteronlinearchives.md)

- [Create One Online Archive](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupclusteronlinearchive.md)

- [Download Online Archive Query Logs](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-downloadgroupclusteronlinearchivequerylogs.md)

- [Return One Online Archive](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusteronlinearchive.md)

- [Remove One Online Archive](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupclusteronlinearchive.md)

- [Update One Online Archive](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupclusteronlinearchive.md)


### [Organizations](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-organizations.md)

- [Return All Organizations](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorgs.md)

- [Create One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createorg.md)

- [Return One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorg.md)

- [Remove One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deleteorg.md)

- [Update One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updateorg.md)

- [Return Delegation Settings for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgdelegationsettings.md)

- [Update Delegation Settings for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updateorgdelegationsettings.md)

- [Return All Projects in One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorggroups.md)

- [Return All Invitations in One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorginvites.md)

- [Create Invitation for One MongoDB Cloud User in One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createorginvite.md)

- [Update One Invitation in One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updateorginvites.md)

- [Return One Invitation in One Organization by Invitation ID](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorginvite.md)

- [Remove One Invitation from One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deleteorginvite.md)

- [Update One Invitation in One Organization by Invitation ID](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updateorginvitebyid.md)

- [Return Maintenance Settings for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgmaintenancesettings.md)

- [Update Maintenance Settings for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updateorgmaintenancesettings.md)

- [Reset Maintenance Settings for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-resetorgmaintenancesettings.md)

- [Return Settings for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgsettings.md)

- [Update Settings for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updateorgsettings.md)

- [Update Organization Roles for One MongoDB Cloud User](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updateorguserroles.md)


### [Overload Protection Simulation](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-overload-protection-simulation.md)

- [Return All Overload Protection Simulations](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclusteroverloadsimulations.md)

- [Create One Overload Protection Simulation](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupclusteroverloadsimulation.md)

- [Return One Overload Protection Simulation](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusteroverloadsimulation.md)

- [Delete One Overload Protection Simulation](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupclusteroverloadsimulation.md)


### [Performance Advisor](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-performance-advisor.md)

- [Return All Suggested Indexes to Drop](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclusterperformanceadvisordropindexsuggestions.md)

- [Return Schema Advice](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclusterperformanceadvisorschemaadvice.md)

- [Return All Suggested Indexes](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclusterperformanceadvisorsuggestedindexes.md)

- [Return Managed Slow Operation Threshold Status](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupmanagedslowms.md)

- [Disable Managed Slow Operation Threshold](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-disablegroupmanagedslowms.md)

- [Enable Managed Slow Operation Threshold](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-enablegroupmanagedslowms.md)

- [Return All Namespaces for One Host](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupprocessperformanceadvisornamespaces.md)

- [Return Slow Queries](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupprocessperformanceadvisorslowquerylogs.md)

- [Return All Suggested Indexes](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupprocessperformanceadvisorsuggestedindexes.md)

- [Return Serverless Auto-Indexing Status](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupserverlessperformanceadvisorautoindexing.md)

- [Set Serverless Auto-Indexing Status](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-setgroupserverlessperformanceadvisorautoindexing.md)


### [Private Endpoint Services](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-private-endpoint-services.md)

- [Create One Private Endpoint Service for One Provider](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupprivateendpointendpointservice.md)

- [Update One Private Endpoint Service for One Provider](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupprivateendpointendpointservice.md)

- [Return Regionalized Private Endpoint Status](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupprivateendpointregionalmode.md)

- [Toggle Regionalized Private Endpoint Status](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-togglegroupprivateendpointregionalmode.md)

- [Return All Private Endpoint Services for One Provider](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupprivateendpointendpointservice.md)

- [Return One Private Endpoint Service for One Provider](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupprivateendpointendpointservice.md)

- [Remove One Private Endpoint Service for One Provider](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupprivateendpointendpointservice.md)

- [Create One Private Endpoint for One Provider](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupprivateendpointendpointserviceendpoint.md)

- [Return One Private Endpoint for One Provider](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupprivateendpointendpointserviceendpoint.md)

- [Remove One Private Endpoint for One Provider](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupprivateendpointendpointserviceendpoint.md)


### [Programmatic API Keys](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-programmatic-api-keys.md)

- [Return All Organization API Keys Assigned to One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupapikeys.md)

- [Create and Assign One Organization API Key to One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupapikey.md)

- [Assign One Organization API Key to One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-addgroupapikey.md)

- [Unassign One Organization API Key from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-removegroupapikey.md)

- [Update Organization API Key Roles for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupapikeyroles.md)

- [Return All Organization API Keys](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorgapikeys.md)

- [Create One Organization API Key](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createorgapikey.md)

- [Return One Organization API Key](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgapikey.md)

- [Remove One Organization API Key](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deleteorgapikey.md)

- [Update One Organization API Key](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updateorgapikey.md)

- [Return All Access List Entries for One Organization API Key](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorgapikeyaccesslistentries.md)

- [Create One Access List Entry for One Organization API Key](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createorgapikeyaccesslistentry.md)

- [Return One Access List Entry for One Organization API Key](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgapikeyaccesslistentry.md)

- [Remove One Access List Entry for One Organization API Key](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deleteorgapikeyaccesslistentry.md)


### [Project IP Access List](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-project-ip-access-list.md)

- [Return All Project IP Access List Entries](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupaccesslistentries.md)

- [Add Entries to Project IP Access List](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupaccesslistentry.md)

- [Return One Project IP Access List Entry](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupaccesslistentry.md)

- [Remove One Entry from One Project IP Access List](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupaccesslistentry.md)

- [Return Status of One Project IP Access List Entry](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupaccessliststatus.md)


### [Projects](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-projects.md)

- [Return All Projects](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroups.md)

- [Create One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroup.md)

- [Return One Project by Name](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupbyname.md)

- [Return One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroup.md)

- [Remove One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroup.md)

- [Update One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroup.md)

- [Add One MongoDB Cloud User to One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-addgroupaccessuser.md)

- [Return All Invitations in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupinvites.md)

- [Create Invitation for One MongoDB Cloud User in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupinvite.md)

- [Update One Invitation in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupinvites.md)

- [Return One Invitation in One Project by Invitation ID](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupinvite.md)

- [Remove One Invitation from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupinvite.md)

- [Update One Invitation in One Project by Invitation ID](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupinvitebyid.md)

- [Return All IP Addresses for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupipaddresses.md)

- [Return All Limits for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgrouplimits.md)

- [Return One Limit for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgrouplimit.md)

- [Remove One Project Limit](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegrouplimit.md)

- [Set One Project Limit](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-setgrouplimit.md)

- [Return All Available MongoDB LTS Versions for Clusters in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupmongodbversions.md)

- [Return Project Settings](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupsettings.md)

- [Update Project Settings](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupsettings.md)

- [Update Project Roles for One MongoDB Cloud User](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupuserroles.md)

- [Migrate One Project to Another Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-migrategroup.md)


### [Push-Based Log Export](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-push-based-log-export.md)

- [Return All Active Log Integrations](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgrouplogintegrations.md)

- [Create One Log Integration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategrouplogintegration.md)

- [Return One Log Integration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgrouplogintegration.md)

- [Update One Log Integration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategrouplogintegration.md)

- [Remove One Log Integration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegrouplogintegration.md)

- [Return One Push-Based Log Export Configuration in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgrouppushbasedlogexport.md)

- [Create One Push-Based Log Export Configuration in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategrouppushbasedlogexport.md)

- [Disable Push-Based Log Export for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegrouppushbasedlogexport.md)

- [Update One Push-Based Log Export Configuration in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategrouppushbasedlogexport.md)

- [Return All Organization Log Integrations](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorglogintegrations.md)

- [Create One Organization Log Integration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createorglogintegration.md)

- [Return One Organization Log Integration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorglogintegration.md)

- [Update One Organization Log Integration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updateorglogintegration.md)

- [Remove One Organization Log Integration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deleteorglogintegration.md)


### [Rate Limiting](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-rate-limiting.md)

- [Return All Rate Limits](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listratelimits.md)

- [Return One Rate Limit](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getratelimit.md)


### [Remote MCP Configurations](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-remote-mcp-configurations.md)

- [Return All MCP Configurations for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupmcpconfigs.md)

- [Create One MCP Configuration for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupmcpconfig.md)

- [Return One MCP Configuration for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupmcpconfig.md)

- [Delete One MCP Configuration for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupmcpconfig.md)

- [Update One MCP Configuration for One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupmcpconfig.md)

- [Return All Secrets for One Project MCP Configuration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupmcpconfigsecrets.md)

- [Create One Secret for One Project MCP Configuration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupmcpconfigsecret.md)

- [Return One Secret for One Project MCP Configuration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupmcpconfigsecret.md)

- [Delete One Secret for One Project MCP Configuration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupmcpconfigsecret.md)

- [Return All MCP Configurations for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorgmcpconfigs.md)

- [Create One MCP Configuration for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createorgmcpconfig.md)

- [Return One MCP Configuration for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgmcpconfig.md)

- [Delete One MCP Configuration for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deleteorgmcpconfig.md)

- [Update One MCP Configuration for One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updateorgmcpconfig.md)

- [Return All Secrets for One Organization MCP Configuration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorgmcpconfigsecrets.md)

- [Create One Secret for One Organization MCP Configuration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createorgmcpconfigsecret.md)

- [Return One Secret for One Organization MCP Configuration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgmcpconfigsecret.md)

- [Delete One Secret for One Organization MCP Configuration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deleteorgmcpconfigsecret.md)


### [Resource Policies](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-resource-policies.md)

- [Return All Non-Compliant Resources](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgnoncompliantresources.md)

- [Return All Atlas Resource Policies](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorgresourcepolicies.md)

- [Create One Atlas Resource Policy](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createorgresourcepolicy.md)

- [Return One Atlas Resource Policy](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgresourcepolicy.md)

- [Delete One Atlas Resource Policy](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deleteorgresourcepolicy.md)

- [Update One Atlas Resource Policy](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updateorgresourcepolicy.md)

- [Validate One Atlas Resource Policy](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-validateorgresourcepolicies.md)


### [Rolling Index](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-rolling-index.md)

- [Create One Rolling Index](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupclusterindexrollingindex.md)


### [Root](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-root.md)

- [Return the Status of This MongoDB Application](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getsystemstatus.md)

- [Return All Control Plane IP Addresses](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listcontrolplaneipaddresses.md)


### [Serverless Instances](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-serverless-instances.md)

- [Return All Serverless Instances in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupserverlessinstances.md)

- [Return One Serverless Instance from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupserverlessinstance.md)


### [Serverless Private Endpoints](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-serverless-private-endpoints.md)

- [Return All Private Endpoints for One Serverless Instance](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupprivateendpointserverlessinstanceendpoint.md)

- [Create One Private Endpoint for One Serverless Instance](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupprivateendpointserverlessinstanceendpoint.md)

- [Return One Private Endpoint for One Serverless Instance](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupprivateendpointserverlessinstanceendpoint.md)

- [Remove One Private Endpoint for One Serverless Instance](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupprivateendpointserverlessinstanceendpoint.md)

- [Update One Private Endpoint for One Serverless Instance](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupprivateendpointserverlessinstanceendpoint.md)


### [Service Accounts](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-service-accounts.md)

- [Return All Project Service Accounts](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupserviceaccounts.md)

- [Create One Project Service Account](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupserviceaccount.md)

- [Return One Project Service Account](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupserviceaccount.md)

- [Remove One Project Service Account](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupserviceaccount.md)

- [Update One Project Service Account](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupserviceaccount.md)

- [Return All Access List Entries for One Project Service Account](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupserviceaccountaccesslist.md)

- [Add Access List Entries for One Project Service Account](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupserviceaccountaccesslist.md)

- [Remove One Access List Entry from One Project Service Account](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupserviceaccountaccesslistentry.md)

- [Create One Project Service Account Secret](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupserviceaccountsecret.md)

- [Delete One Project Service Account Secret](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupserviceaccountsecret.md)

- [Assign One Service Account to One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-invitegroupserviceaccount.md)

- [Return All Organization Service Accounts](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorgserviceaccounts.md)

- [Create One Organization Service Account](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createorgserviceaccount.md)

- [Return One Organization Service Account](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgserviceaccount.md)

- [Delete One Organization Service Account](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deleteorgserviceaccount.md)

- [Update One Organization Service Account](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updateorgserviceaccount.md)

- [Return All Access List Entries for One Organization Service Account](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorgserviceaccountaccesslist.md)

- [Add Access List Entries for One Organization Service Account](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createorgserviceaccountaccesslist.md)

- [Remove One Access List Entry from One Organization Service Account](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deleteorgserviceaccountaccesslistentry.md)

- [Return All Service Account Project Assignments](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgserviceaccountgroups.md)

- [Create One Organization Service Account Secret](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createorgserviceaccountsecret.md)

- [Delete One Organization Service Account Secret](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deleteorgserviceaccountsecret.md)


### [Streams](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-streams.md)

- [Return All Stream Workspaces in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupstreamworkspaces.md)

- [Create One Stream Workspace](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupstreamworkspace.md)

- [Return Account ID and VPC ID for One Project and Region](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupstreamaccountdetails.md)

- [Return All Active Incoming VPC Peering Connections](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupstreamactivevpcpeeringconnections.md)

- [Return All Private Link Connections](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupstreamprivatelinkconnections.md)

- [Create One Private Link Connection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupstreamprivatelinkconnection.md)

- [Return One Private Link Connection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupstreamprivatelinkconnection.md)

- [Delete One Private Link Connection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupstreamprivatelinkconnection.md)

- [Update One Private Link Connection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupstreamprivatelinkconnection.md)

- [Return All VPC Peering Connections](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupstreamvpcpeeringconnections.md)

- [Delete One VPC Peering Connection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupstreamvpcpeeringconnection.md)

- [Accept One Incoming VPC Peering Connection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-acceptgroupstreamvpcpeeringconnection.md)

- [Reject One Incoming VPC Peering Connection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-rejectgroupstreamvpcpeeringconnection.md)

- [Return One Stream Workspace](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupstreamworkspace.md)

- [Delete One Stream Workspace](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupstreamworkspace.md)

- [Update One Stream Workspace](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupstreamworkspace.md)

- [Download Audit Logs for One Atlas Stream Processing Workspace](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-downloadgroupstreamauditlogs.md)

- [Return All Connections of the Stream Workspaces](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupstreamconnections.md)

- [Create One Stream Connection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupstreamconnection.md)

- [Return One Stream Connection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupstreamconnection.md)

- [Delete One Stream Connection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupstreamconnection.md)

- [Update One Stream Connection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupstreamconnection.md)

- [Return All Stream Failover Connections](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupstreamconnectionfailoverconnections.md)

- [Create One Failover Stream Connection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupstreamconnectionfailoverconnection.md)

- [Return One Stream Failover Connection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupstreamconnectionfailoverconnection.md)

- [Delete One Stream Failover Connection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupstreamconnectionfailoverconnection.md)

- [Update One Stream Failover Connection](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupstreamconnectionfailoverconnection.md)

- [Create One Stream Processor](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupstreamprocessor.md)

- [Return One Stream Processor](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupstreamprocessor.md)

- [Delete One Stream Processor](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupstreamprocessor.md)

- [Update One Stream Processor](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupstreamprocessor.md)

- [Start One Stream Processor](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-startgroupstreamprocessor.md)

- [Start One Stream Processor With Options](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-startgroupstreamprocessorwith.md)

- [Stop One Stream Processor](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-stopgroupstreamprocessor.md)

- [Return All Stream Processors in One Stream Workspace](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupstreamprocessors.md)

- [Download Operational Logs for One Atlas Stream Processing Workspace](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-downloadgroupstreamoperationallogs.md)

- [Create One Stream Workspace with Sample Connections](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-withgroupstreamsampleconnections.md)


### [Teams](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-teams.md)

- [Return All Teams in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupteams.md)

- [Add Multiple Teams to One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-addgroupteams.md)

- [Return One Team in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupteam.md)

- [Remove One Team from One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-removegroupteam.md)

- [Update Team Roles in One Project](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupteam.md)

- [Return All Teams in One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listorgteams.md)

- [Create One Team in One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-createorgteam.md)

- [Return One Team by Name](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgteambyname.md)

- [Return One Team by ID](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getorgteam.md)

- [Remove One Team from One Organization](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deleteorgteam.md)

- [Rename One Team](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-renameorgteam.md)

- [Assign MongoDB Cloud Users in One Organization to One Team](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-addorgteamusers.md)

- [Remove One MongoDB Cloud User from One Team](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-removeorgteamuserfromteam.md)


### [Third-Party Integrations](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-third-party-integrations.md)

- [Return All Active Third-Party Service Integrations](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupintegrations.md)

- [Return One Third-Party Service Integration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupintegration.md)

- [Update One Third-Party Service Integration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupintegration.md)

- [Create One Third-Party Service Integration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupintegration.md)

- [Remove One Third-Party Service Integration](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-deletegroupintegration.md)


### [X.509 Authentication](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-x-509-authentication.md)

- [Return All X.509 Certificates Assigned to One Database User](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupdatabaseusercerts.md)

- [Create One X.509 Certificate for One Database User](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-creategroupdatabaseusercert.md)

- [Disable Customer-Managed X.509](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-disablegroupusersecuritycustomerx509.md)


### [Query Shape Insights](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/group/endpoint-query-shape-insights.md)

- [Return Query Statistic Summaries](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclusterqueryshapeinsightsummaries.md)

- [Return Query Shape Details](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusterqueryshapeinsightdetails.md)

- [Return All Query Shapes](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-listgroupclusterqueryshapes.md)

- [Return One Query Shape](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-getgroupclusterqueryshape.md)

- [Update Query Shape Rejection Status](https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2/operation/operation-updategroupclusterqueryshape.md)




[Powered by Bump.sh](https://bump.sh)
