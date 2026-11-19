// Connects Blob Storage "submit.json created" events to the AuditOnSubmit function.
// Deployed by deploy.ps1 AFTER the code is published, because the function's blobs_extension
// key only exists once the host has loaded the Event Grid blob trigger. Building the webhook URL
// here (not on the command line) avoids Windows quoting problems with '&' in the URL.

param functionAppName string
param storageAccountName string
param topicName string

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource func 'Microsoft.Web/sites@2024-04-01' existing = {
  name: functionAppName
}

resource topic 'Microsoft.EventGrid/systemTopics@2022-06-15' = {
  name: topicName
  location: storage.location
  properties: {
    source: storage.id
    topicType: 'Microsoft.Storage.StorageAccounts'
  }
}

var blobsKey = listKeys('${func.id}/host/default', '2024-04-01').systemKeys.blobs_extension

resource subscription 'Microsoft.EventGrid/systemTopics/eventSubscriptions@2022-06-15' = {
  parent: topic
  name: 'audit-submit'
  properties: {
    destination: {
      endpointType: 'WebHook'
      properties: {
        endpointUrl: 'https://${func.properties.defaultHostName}/runtime/webhooks/blobs?functionName=Host.Functions.AuditOnSubmit&code=${blobsKey}'
      }
    }
    filter: {
      includedEventTypes: ['Microsoft.Storage.BlobCreated']
      subjectBeginsWith: '/blobServices/default/containers/audit-inputs/'
      subjectEndsWith: 'submit.json'
    }
    eventDeliverySchema: 'EventGridSchema'
    retryPolicy: { maxDeliveryAttempts: 30, eventTimeToLiveInMinutes: 1440 }
  }
}
