# Keeper Secrets Manager -- Azure Function Middleware

An Azure Function App that acts as middleware between **Azure Logic Apps / Power Automate** and the **Keeper Secrets Manager (KSM)** SDK. Deploy it to your Azure subscription with a single click, then create a connection using the published [Keeper Secrets Manager connector](https://github.com/microsoft/PowerPlatformConnectors/tree/dev/certified-connectors/KeeperSecretsManager) <!-- TODO: update once certification PR is merged --> for zero-knowledge secrets management in your workflows.

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fmnaqvi-ks%2Fkeeper-connector-demo%2Fmain%2Fazuredeploy.json)

---

## What Gets Deployed

| Resource | Purpose |
|---|---|
| **Azure Function App** | Python 3.11, Linux Consumption plan, System Managed Identity |
| **App Service Plan** | Consumption (Y1) plan that hosts the Function App |
| **Azure Key Vault** | Stores your KSM config token as a secret (`KSM-CONFIG`) |
| **Storage Account** | Required by the Azure Functions runtime |
| **Key Vault Access Policy** | Grants the Function App `get` permission on Key Vault secrets via its managed identity |

All resources enforce **HTTPS only** and **TLS 1.2+**. The middleware code from [`keeperLogicAppMiddleware/`](./keeperLogicAppMiddleware) is built and deployed onto the Function App as part of the same one-click action.

---

## Prerequisites

1. **Azure subscription** with permission to create resources (Contributor role on a resource group).
2. **Keeper Enterprise** account (or Keeper Business) with Secrets Manager enabled.
3. **Keeper Secrets Manager Application** created in the Keeper Admin Console with at least one shared folder.
4. **One-Time Access Token** generated for the KSM application -- this is the Base64-encoded config string the deployment needs.

---

## Quick Start (One-Click Deploy)

### 1. Generate Your KSM Config Token

1. Sign in to the [Keeper Admin Console](https://keepersecurity.com/console).
2. Go to **Secrets Manager** > **Create Application** > give it a name.
3. Share one or more vault folders with the application.
4. Open the **Devices** tab > **Add Device** > select **Configuration File** > choose **Base64**.
5. Copy the Base64 value immediately -- this is your `KSM_CONFIG`. It can only be used once; if lost, add a new device to generate a fresh token.

> Treat this value like a password. It contains your application credentials in an encrypted, Base64-encoded format.

### 2. Click Deploy to Azure

Click the **Deploy to Azure** button at the top of this page, then fill in:

| Parameter | Description |
|---|---|
| **Resource Group** | Select an existing group or create a new one |
| **Function App Name** | A globally unique name (e.g., `keeper-middleware-acme`) |
| **Keeper Config** | Paste the Base64-encoded one-time token from step 1 |
| **Location** | Azure region (defaults to the resource group's region) |

Click **Review + create** and wait for deployment to complete (approximately 3-5 minutes). The ARM template provisions every resource listed above **and** automatically deploys the middleware code from this repo's [`keeperLogicAppMiddleware/`](./keeperLogicAppMiddleware) folder using the `PROJECT` app setting and Oryx remote build.

### 3. Get the Function Host Key

1. In the Azure portal, navigate to your new Function App.
2. Go to **App keys** (under the Functions section in the left menu).
3. Copy the **default** host key value -- you'll need it in step 4.

### 4. Create the Connector Connection

The **Keeper Secrets Manager** connector is already published in the Microsoft Power Platform / Azure Logic Apps connector gallery -- you do **not** need to import any swagger file.

1. In Azure Logic Apps or Power Automate, add a new action and search for **"Keeper Secrets Manager"** in the connectors list.
2. Pick any Keeper action (e.g. **List Secrets**) -- the first time you use it, you'll be prompted to create a connection.
3. Fill in the connection form:
    - **Connection name** -- any friendly label (e.g. `keeper-prod`)
    - **Function App hostname** -- `<your-function-app-name>.azurewebsites.net`
    - **API key** -- paste the host key you copied in step 3 (it's sent as the `x-functions-key` header)
4. Click **Create**.

You can now use **List Secrets**, **Get Secret**, **Create Secret**, **Update Secret**, and **List Folders** in any workflow.

---

## Manual Setup (Alternative)

If you prefer to provision resources by hand (for example, to fit into existing Bicep/Terraform pipelines, or because your environment restricts portal templates), follow these steps instead of clicking the Deploy to Azure button. Once the resources are in place and the code is deployed, **return to [Step 3](#3-get-the-function-host-key) above** to wire the connector up.

### 1. Create the Azure Resources

#### 1a. Resource Group

1. Azure portal > **Resource groups** > **Create**.
2. Pick a subscription, name (e.g. `rg-keeper-middleware`), and region.
3. **Review + create**.

#### 1b. Storage Account

1. **Storage accounts** > **Create**.
2. Select your resource group, give it a name (e.g. `stksmyourorg`).
3. **Redundancy**: LRS. Under **Advanced**, confirm **Secure transfer** is enabled and **Minimum TLS** is 1.2.
4. **Review + create**.

#### 1c. Key Vault + KSM Secret

1. **Key vaults** > **Create**. Select your resource group, name it (e.g. `kv-ksm-yourorg`), same region.
2. **Review + create**.
3. Once created, go to **Secrets** > **Generate/Import**.
4. **Name**: `KSM-CONFIG`, **Value**: paste the Base64 token from [Quick Start step 1](#1-generate-your-ksm-config-token).
5. **Create**.

#### 1d. Function App

1. **Function App** > **Create**.
2. Select your resource group. Set a globally unique name (e.g. `keeper-middleware-yourorg`).
3. **Runtime**: Python 3.11, **OS**: Linux, **Plan**: Consumption (Serverless).
4. **Storage**: select the account from 1b.
5. **Review + create**.

#### 1e. Enable Managed Identity

1. Open the Function App > **Identity** > set **System assigned** to **On** > **Save**.
2. Note the **Object (principal) ID**.

#### 1f. Grant Key Vault Access

1. Go to your Key Vault > **Access policies** > **Create**.
2. **Secret permissions**: check **Get**.
3. **Principal**: search for your Function App name or paste the Object ID.
4. **Create**.

#### 1g. Configure App Settings

Open Function App > **Environment variables** and add:

| Name | Value |
|---|---|
| `FUNCTIONS_WORKER_RUNTIME` | `python` |
| `FUNCTIONS_EXTENSION_VERSION` | `~4` |
| `KSM_CONFIG` | `@Microsoft.KeyVault(SecretUri=https://<your-keyvault>.vault.azure.net/secrets/KSM-CONFIG/)` |

Replace `<your-keyvault>` with your Key Vault name. Click **Save**.

### 2. Deploy the Middleware Code

```bash
git clone https://github.com/mnaqvi-ks/keeper-connector-demo.git
cd keeper-connector-demo/keeperLogicAppMiddleware
func azure functionapp publish <FUNCTION_APP_NAME> --python
```

Replace `<FUNCTION_APP_NAME>` with the name from step 1d. Wait for "Remote build succeeded!" (2-5 minutes).

> Requires [Azure Functions Core Tools](https://learn.microsoft.com/azure/azure-functions/functions-run-local) (v4) and Python 3.11+.

Once the code is published, continue with [Quick Start step 3](#3-get-the-function-host-key) to grab the host key and create the connector connection.

---

## API Reference

All endpoints require the `x-functions-key` header for authentication. The custom connector adds this header automatically using the API key you provided when creating the connection.

### Rate Limiting

The middleware enforces **best-effort** rate limiting per connection (per `x-functions-key`) to protect the backend from accidental overload.

- Limits are **in-memory per Function worker process**. They reset on cold start and do not enforce a strict global quota under scale-out.
- When the limit is exceeded, the API returns **429 Too Many Requests** with a `Retry-After` header.

### Health Check

```
GET /api/health
```

Returns `{"status": "ok"}` -- use this to verify the Function App is running.

### List All Secrets

```
GET /api/secrets
```

Returns an array of secret summaries:

```json
[
  {
    "uid": "xxxxxxxxxxxx",
    "title": "My Login",
    "type": "login",
    "folder_uid": "xxxxxxxxxxxx"
  }
]
```

### Get Secret Details

```
GET /api/secrets/{uid}
```

Returns the full record with all standard and custom fields:

```json
{
  "uid": "xxxxxxxxxxxx",
  "title": "My Login",
  "type": "login",
  "login": "admin",
  "password": "Secret123",
  "url": "https://example.com",
  "notes": "",
  "oneTimeCode": "",
  "passkey": [],
  "fileRef": [],
  "custom": [],
  "folder_uid": "xxxxxxxxxxxx",
  "is_editable": true
}
```

### Create Secret

```
POST /api/secrets
Content-Type: application/json

{
  "folder_uid": "xxxxxxxxxxxx",
  "title": "New Credential",
  "login": "user@example.com",
  "password": "StrongP@ss!",
  "url": "https://app.example.com",
  "notes": "Created by Logic App workflow"
}
```

### Update Secret

```
PUT /api/secrets/{uid}
Content-Type: application/json

{
  "password": "NewPassword!2025",
  "notes": "Rotated on 2025-04-09"
}
```

Supports updating: `title`, `login`, `password`, `url`, `notes`, `oneTimeCode`, and `custom` fields.

### List Folders

```
GET /api/folders
```

Returns all shared folders accessible to the KSM application:

```json
[
  {
    "uid": "xxxxxxxxxxxx",
    "name": "Production Credentials",
    "parent_uid": "",
    "total_records": 5
  }
]
```

---

## Local Development

### Prerequisites

- Python 3.11+
- [Azure Functions Core Tools v4](https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local)
- A Base64-encoded KSM configuration token (the same one-time access token used in production)

### Setup

```bash
cd keeperLogicAppMiddleware
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `local.settings.json` file (excluded from Git by `.gitignore`):

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "KSM_CONFIG": "<YOUR_BASE64_KSM_CONFIG>"
  }
}
```

Replace `<YOUR_BASE64_KSM_CONFIG>` with the raw Base64-encoded token from the Keeper Admin Console. In production this value comes via an Azure Key Vault reference, but locally you provide it directly.

> **Important**: Do not commit `local.settings.json` to source control -- it is already excluded by `.gitignore`.

### Run Locally

```bash
func start
```

The API will be available at `http://localhost:7071/api/`.

> **Note**: Function-level auth (`x-functions-key`) is not enforced when running locally with Azure Functions Core Tools. You can call the endpoints directly without an API key.

### Test the Endpoints

Verify the middleware is running and connected to your vault:

```bash
# Health check
curl http://localhost:7071/api/health

# List all secrets
curl http://localhost:7071/api/secrets

# Get a specific secret (replace <UID> with an actual secret UID)
curl http://localhost:7071/api/secrets/<UID>

# List all folders
curl http://localhost:7071/api/folders

# Create a secret (replace <FOLDER_UID> with a shared folder UID)
curl -X POST http://localhost:7071/api/secrets \
  -H "Content-Type: application/json" \
  -d '{"folder_uid":"<FOLDER_UID>","title":"Test Secret","login":"user@example.com","password":"TestP@ss","url":"https://example.com"}'

# Update a secret (replace <UID>)
curl -X PUT http://localhost:7071/api/secrets/<UID> \
  -H "Content-Type: application/json" \
  -d '{"password":"NewPassword!2025","notes":"Updated locally"}'
```

---

## Usage Examples

### Automated Password Rotation

```
Recurrence (every 30 days)
  -> Get secret (fetch current credential by UID)
  -> Compose (generate new password)
  -> Update secret (set new password + rotation timestamp in notes)
  -> Send email (notify the security team)
```

### Credential Injection for API Calls

```
When a new issue is opened (GitHub trigger)
  -> Get secret (fetch API key from Keeper by UID)
  -> HTTP action (call external API using the fetched credential)
  -> Update issue (post results back)
```

### Credential Provisioning

Use the **Create secret** action inside a loop to provision credentials for new employees or service accounts. Combine with email connectors to send onboarding notifications.

### Vault Auditing

Use **List secrets** and **List folders** to enumerate all accessible records and folders, then pipe the results into Azure Table Storage, SharePoint, or email for compliance reporting.

---

## Frequently Asked Questions

### Is my Keeper vault master password exposed through this middleware?

No. The middleware uses the Keeper Secrets Manager SDK, which operates on a zero-knowledge, zero-trust architecture. Your master password is never transmitted, stored, or accessible to the middleware or the connector. Authentication is handled entirely through the KSM one-time access token and derived encryption keys.

### Can I use this with Keeper's free or personal plans?

No. Keeper Secrets Manager is an add-on feature available exclusively with Keeper Enterprise subscriptions. Contact [Keeper Sales](https://www.keepersecurity.com/contact.html) for licensing information.

### How do I rotate the KSM access token?

1. Go to the [Keeper Admin Console](https://keepersecurity.com/console).
2. Navigate to **Secrets Manager** and select your application.
3. Generate a new one-time access token.
4. In the Azure portal, go to your Key Vault and update the **KSM-CONFIG** secret with the new Base64-encoded value. The Function App reads `KSM_CONFIG` via a Key Vault reference (`@Microsoft.KeyVault(SecretUri=https://<your-keyvault>.vault.azure.net/secrets/KSM-CONFIG/)`), so updating the Key Vault secret is all that's needed.
5. Restart the Function App to apply the change.

### Can multiple Logic Apps or Power Automate flows share the same connection?

Yes. Once a connection is created with a Function App URL and host key, any flow within the same environment can reuse that connection. Each connection points to a single KSM application, so the accessible secrets are determined by the folders shared with that application.

### What happens if I delete a secret in Keeper that a workflow references?

The **Get secret** and **Update secret** operations will return a 404 (Not Found) error. Design your workflows to handle this case using a Condition action or error handling (Configure Run After).

### How do I restrict which secrets the connector can access?

Access is controlled at the Keeper Secrets Manager application level. In the Admin Console, share only the specific folders that the connector should have access to. The connector cannot access secrets in folders that have not been explicitly shared with the KSM application.

---

## Security

- **Zero-Knowledge Architecture** -- The KSM config token is the only credential stored. Keeper's zero-knowledge SDK decrypts secrets locally inside the Function App; plaintext secrets never transit through Keeper's servers.
- **Key Vault Storage** -- The KSM config is stored in Azure Key Vault and accessed via a Managed Identity Key Vault reference. It never appears in plaintext in App Settings.
- **HTTPS Only** -- The Function App rejects all HTTP traffic.
- **TLS 1.2+** -- Minimum TLS version is enforced at the App Service level.
- **Function-Level Auth** -- Every API call requires the `x-functions-key` header, preventing unauthorized access.

---

## Architecture

```
                  +-----------------+
                  |   Logic Apps /  |
                  | Power Automate  |
                  +--------+--------+
                           |
                    x-functions-key
                           |
                  +--------v--------+
                  | Keeper Secrets  |
                  | Manager         |
                  | Connector       |
                  +--------+--------+
                           |
                  +--------v--------+        +----------------+
                  | Azure Function  | -----> | Azure Key Vault|
                  | (this repo)     |  MSI   | (KSM config)   |
                  +--------+--------+        +----------------+
                           |
                     KSM SDK
                           |
                  +--------v--------+
                  | Keeper Vault    |
                  | (your secrets)  |
                  +-----------------+
```

---

## License

Copyright (c) Keeper Security, Inc. All rights reserved.
