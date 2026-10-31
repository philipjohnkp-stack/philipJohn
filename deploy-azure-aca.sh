#!/usr/bin/env bash
# Budget deployment of Sage to Azure Container Apps (scale-to-zero, ACR Basic).
# Usage: az login && BUDGET_EMAIL=you@example.com ./deploy-azure-aca.sh
set -euo pipefail
cd "$(dirname "$0")"

RG=${RG:-SageRG}
LOCATION=${LOCATION:-canadacentral}
APP=${APP:-sage-ai}
ENV_NAME=${ENV_NAME:-sage-env}
LOGS=${LOGS:-sage-logs}
TAG=${TAG:-v$(date +%Y%m%d%H%M%S)}
ENV_FILE=${ENV_FILE:-.env.azure}
BUDGET_AMOUNT=${BUDGET_AMOUNT:-50}
BUDGET_EMAIL=${BUDGET_EMAIL:-}

command -v az >/dev/null || { echo "Azure CLI (az) not found. Install it and run 'az login'." >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "Missing $ENV_FILE. Copy .env.azure.example and fill it in." >&2; exit 1; }

SUB_ID=$(az account show --query id -o tsv)
ACR=${ACR:-sage$(printf '%s' "$SUB_ID" | tr -d '-' | cut -c1-12)}

echo "==> Providers and extension"
az extension add --name containerapp --upgrade --only-show-errors
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.OperationalInsights --wait
az provider register --namespace Microsoft.ContainerRegistry --wait

echo "==> Resource group $RG ($LOCATION)"
az group create --name "$RG" --location "$LOCATION" --only-show-errors -o none

echo "==> Container registry $ACR (Basic)"
az acr show --name "$ACR" -o none 2>/dev/null \
  || az acr create --resource-group "$RG" --name "$ACR" --sku Basic --admin-enabled false -o none

echo "==> Building image in ACR (no local Docker needed): $APP:$TAG"
az acr build --registry "$ACR" --image "$APP:$TAG" --file Dockerfile . --only-show-errors
IMAGE="$ACR.azurecr.io/$APP:$TAG"

echo "==> Log Analytics (30-day retention)"
az monitor log-analytics workspace show -g "$RG" -n "$LOGS" -o none 2>/dev/null \
  || az monitor log-analytics workspace create -g "$RG" -n "$LOGS" -l "$LOCATION" --retention-time 30 -o none
LOGS_ID=$(az monitor log-analytics workspace show -g "$RG" -n "$LOGS" --query customerId -o tsv)
LOGS_KEY=$(az monitor log-analytics workspace get-shared-keys -g "$RG" -n "$LOGS" --query primarySharedKey -o tsv)

echo "==> Container Apps environment (Consumption)"
az containerapp env show -g "$RG" -n "$ENV_NAME" -o none 2>/dev/null \
  || az containerapp env create -g "$RG" -n "$ENV_NAME" -l "$LOCATION" \
       --logs-workspace-id "$LOGS_ID" --logs-workspace-key "$LOGS_KEY" -o none

# Every non-empty setting becomes a Container App secret referenced by an env var.
secrets=()
env_vars=()
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  key=${line%%=*}
  value=${line#*=}
  value=${value%\"}; value=${value#\"}; value=${value%\'}; value=${value#\'}
  [ -n "$value" ] || continue
  name=$(printf '%s' "$key" | tr 'A-Z_' 'a-z-')
  secrets+=("$name=$value")
  env_vars+=("$key=secretref:$name")
done < "$ENV_FILE"

if az containerapp show -g "$RG" -n "$APP" -o none 2>/dev/null; then
  echo "==> Updating $APP"
  az containerapp secret set -g "$RG" -n "$APP" --secrets "${secrets[@]}" -o none
  az containerapp update -g "$RG" -n "$APP" --image "$IMAGE" --set-env-vars "${env_vars[@]}" -o none
else
  echo "==> Creating $APP (0.25 vCPU / 0.5 GiB, scale 0-1)"
  az containerapp create -g "$RG" -n "$APP" --environment "$ENV_NAME" \
    --image "$IMAGE" --registry-server "$ACR.azurecr.io" --registry-identity system \
    --target-port 8000 --ingress external \
    --cpu 0.25 --memory 0.5Gi --min-replicas 0 --max-replicas 1 \
    --secrets "${secrets[@]}" --env-vars "${env_vars[@]}" -o none
fi

if [ -n "$BUDGET_EMAIL" ]; then
  echo "==> Monthly budget \$$BUDGET_AMOUNT on $RG (alerts to $BUDGET_EMAIL)"
  start=$(date +%Y-%m-01)
  az rest --method put \
    --url "https://management.azure.com/subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.Consumption/budgets/sage-monthly?api-version=2023-05-01" \
    --body "{\"properties\":{\"category\":\"Cost\",\"amount\":$BUDGET_AMOUNT,\"timeGrain\":\"Monthly\",
      \"timePeriod\":{\"startDate\":\"${start}T00:00:00Z\"},
      \"notifications\":{
        \"actual80\":{\"enabled\":true,\"operator\":\"GreaterThan\",\"threshold\":80,\"thresholdType\":\"Actual\",\"contactEmails\":[\"$BUDGET_EMAIL\"]},
        \"forecast100\":{\"enabled\":true,\"operator\":\"GreaterThan\",\"threshold\":100,\"thresholdType\":\"Forecasted\",\"contactEmails\":[\"$BUDGET_EMAIL\"]}}}}" \
    -o none
else
  echo "==> Skipping budget alert (set BUDGET_EMAIL to enable)"
fi

FQDN=$(az containerapp show -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv)
echo "Deployed: https://$FQDN"
