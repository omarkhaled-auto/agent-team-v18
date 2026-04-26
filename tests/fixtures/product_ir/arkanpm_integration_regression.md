# Project: ArkanPM

## Technology Stack
| Layer | Technology |
|-------|------------|
| Storage | Azure Blob Storage |
| Notifications | Azure Notification Hubs |
| Cache | Redis |

## External Systems
- Arkan Handover webhook receiver (stubbed)

## Feature F-010: Integrations
POST /integrations/arkan/webhook
integration.arkan.handover_received
Notification providers may be configured later for email, SMS, and push.
The system handles payment approval and inbound webhook retries.
SMS is used for MFA verification when required.
PushToken stores device metadata for push notifications.
WorkOrderPart is updated during inventory integration checks.
An outbound webhook sends completion updates to downstream consumers.
