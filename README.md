# Azure Logic Apps Connector -- Function Middleware

An Azure Function App that acts as middleware between **Azure Logic Apps / Power Automate** and the **Keeper Secrets Manager (KSM)** SDK. Deploy it to your Azure subscription with a single click, then create a connection using the certified **Keeper Secrets Manager** connector available in the Microsoft Power Platform / Azure Logic Apps connector gallery.

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fmnaqvi-ks%2Fkeeper-connector-demo%2Fmain%2Fazuredeploy.json)

---

## What Gets Deployed

| Resource | Purpose |
|---|---|
| **Azure Function App** | Python 3.11, Linux Consumption plan, hosts the middleware code |
| **Azure Key Vault** | Stores your KSM config token as a secret (`KSM-CONFIG`) |
| **Storage Account** | Required by the Azure Functions runtime |

Plus supporting resources: an App Service Plan, a Key Vault access policy for the Function App's managed identity, and a temporary User-Assigned Managed Identity + Role Assignment + Deployment Script that pushes the middleware code into the Function App during provisioning (auto-cleaned on success).

All resources enforce **HTTPS only** and **TLS 1.2+**.

---

## Prerequisites

1. **Azure subscription** -- **Owner** on a resource group for the one-click deploy (it creates a role assignment). **Contributor** alone works for the [Manual Setup](#manual-setup-alternative) path.
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

Click **Review + create** and wait ~5-7 minutes. The template provisions all resources and deploys the middleware code automatically -- no `func publish` step needed.

> Requires **Owner** on the resource group. With Contributor only, use the [Manual Setup](#manual-setup-alternative) path.

### 3. Get the Function Host Key

1. In the Azure portal, navigate to your new Function App.
2. Go to **App keys** (under the Functions section in the left menu).
3. Copy the **default** host key value -- you'll need it in step 4.

### 4. Create the Connector Connection

The **Keeper Secrets Manager** connector is published as a certified connector in the Microsoft Power Platform and Azure Logic Apps connector gallery. There is nothing to import -- just create a connection.

1. In Azure Logic Apps or Power Automate, add a new action and search for **"Keeper Secrets Manager"** in the connectors list.
2. Pick any Keeper action (e.g. **List Secrets**) -- the first time you use it, you'll be prompted to create a connection.
3. Fill in the connection form:
    - **Connection name** -- any friendly label (e.g. `keeper-prod`)
    - **Function App hostname** -- `<your-function-app-name>.azurewebsites.net`
    - **API key** -- paste the host key you copied in step 3 (it's sent as the `x-functions-key` header)
4. Click **Create**.

You can now use **List Secrets**, **Get Secret**, **Create Secret**, **Update Secret**, and **List Folders** in any workflow.

---

## Sample Workflow Templates

Three ready-to-deploy Consumption Logic Apps live under [`workflowTemplates/`](workflowTemplates) so you can validate the connector end-to-end without building a workflow by hand:

- **`get-secret`** -- HTTP-triggered. POST `{ "uid": "<secret-uid>" }` to its callback URL and the response body is the full secret JSON.
- **`create-secret`** -- HTTP-triggered. POST a secret payload (`folder_uid`, `title`, `login`, `password`, `url`, `notes`) and the response body is the newly created secret JSON (including its UID).
- **`update-secret`** -- Recurrence-triggered. Stamps `Updated at <utcNow()>` into the `notes` field of a single secret on a schedule -- a tiny smoke test for the connector + middleware.

### Deploy

Click any of the buttons below (or use the equivalent CLI line) after the middleware Function App from the Quick Start is up:

| Workflow | Deploy |
|---|---|
| Get secret (HTTP) | [![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fmnaqvi-ks%2Fkeeper-connector-demo%2Fmain%2FworkflowTemplates%2Fget-secret%2Fazuredeploy.json) |
| Create secret (HTTP) | [![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fmnaqvi-ks%2Fkeeper-connector-demo%2Fmain%2FworkflowTemplates%2Fcreate-secret%2Fazuredeploy.json) |
| Update secret (recurrence) | [![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fmnaqvi-ks%2Fkeeper-connector-demo%2Fmain%2FworkflowTemplates%2Fupdate-secret%2Fazuredeploy.json) |

Or from a terminal, using the sibling parameters file (one per workflow):

```bash
az deployment group create \
  --resource-group <your-rg> \
  --template-file workflowTemplates/get-secret/azuredeploy.json \
  --parameters @workflowTemplates/get-secret/azuredeploy.parameters.json
```

### Required inputs

Edit the placeholders in each workflow's [`azuredeploy.parameters.json`](workflowTemplates) before deploying. The fields are:

- **`functionAppHostname`** -- e.g. `keeper-middleware-acme.azurewebsites.net` (your Quick Start Function App).
- **`functionHostKey`** -- the default host key from **App keys** (same value used by the connector).
- **`secretUid`** -- *(update-secret only)* UID of the Keeper secret the recurrence run will stamp.
- **`keeperApiIdOverride`** -- leave `""` once the certified connector ships; otherwise set to your custom-connector resource ID (see below).

`connectionName` and `logicAppName` aren't in the parameters file -- they fall back to template defaults (`keeper-secrets-manager` and `la-keeper-<workflow>-sample`). Add them to the parameters file only if you want to override.

### Reusing one connection across workflows

`Microsoft.Web/connections` is idempotent in a resource group. Pass the **same `connectionName`** when deploying all three templates and ARM updates the existing connection in place rather than creating three separate ones -- you end up with one shared `keeper-secrets-manager` connection wired to every workflow.

### Pre-cert testing against a custom connector

Until the certified **Keeper Secrets Manager** connector is published, the templates' default `managedApis/keeper-secrets-manager` reference will not resolve. To test against your own custom connector, set `keeperApiIdOverride` in the parameters file to the resource ID of your `Microsoft.Web/customApis/<name>`. Find it with:

```bash
az resource list --resource-type Microsoft.Web/customApis --query "[].id" -o tsv
```

Then update the workflow's `azuredeploy.parameters.json`:

```json
"keeperApiIdOverride": {
  "value": "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Web/customApis/<your-connector>"
}
```

Deploy into the **same subscription as your custom connector** (`Microsoft.Web/connections` cannot reference a `customApis` resource in a different subscription). Once the certified connector ships, set `keeperApiIdOverride` back to `""` and the default just works.

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

## Troubleshooting

### "Operation cannot be completed without additional quota" (Dynamic VMs)

Linux Consumption Function Apps need **Dynamic VM** quota in the chosen region. Some new subscriptions have **0 quota** in certain regions. Either redeploy in another region (e.g. `East US`, `West Europe`), or request a quota increase under **Subscriptions > Usage + quotas**.

### "The operation 'List' is not enabled in this Key Vault's access policy"

The template grants the Function App's managed identity access to the secret -- not your user account (Azure separates control-plane and data-plane permissions on Key Vault). To view or edit the secret yourself, open the Key Vault > **Access policies** > **Create**, and grant your user **Get / List / Set / Delete** on secrets. The Function App keeps working either way.

### `deployFunctionCode` step shows "Running" for several minutes

Normal -- typically 3-7 minutes end to end. If it exceeds 15 minutes, the script times out; re-running the deployment usually resolves it.

### Function App shows no functions after deployment

Wait 30-60 seconds and refresh -- the runtime needs a moment to discover the deployed code. If still missing, check **Deployment Center > Logs** in the Function App for build errors.

---

## API Reference

All endpoints require the `x-functions-key` header for authentication. The custom connector adds this header automatically using the API key you provided when creating the connection.

### Rate Limiting

Best-effort rate limiting is enforced per `x-functions-key` (in-memory per worker, resets on cold start). When exceeded, returns **429 Too Many Requests** with a `Retry-After` header.

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

```bash
curl http://localhost:7071/api/health
curl http://localhost:7071/api/secrets
```

See [API Reference](#api-reference) for the full set of endpoints and request bodies.

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
                           v
                  +-----------------+
                  | Keeper Secrets  |
                  | Manager         |
                  | Connector       |
                  +--------+--------+
                           |
              Function App URL +
              Host Key (x-functions-key)
                           |
                           v
                  +-----------------+        +----------------+
                  | Azure Function  | -----> | Azure Key Vault|
                  | (this repo)     |  MSI   | (KSM config)   |
                  +--------+--------+        +----------------+
                           |
                       KSM SDK
                           v
                  +-----------------+
                  | Keeper Vault    |
                  | (your secrets)  |
                  +-----------------+
```

The connector is created with the **Function App URL** and **Function App Host Key** (collected in [Quick Start step 3](#3-get-the-function-host-key)). On every call, the connector adds the host key as the `x-functions-key` header.

---

## License

Copyright (c) Keeper Security, Inc. All rights reserved.
